import json
import logging
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse

from app.api.schemas.schemas import TemplateGenerateRequest, TemplateResponse
from app.core.llm.chains import generate_template_stream, extract_format_requirements
from app.core.parsers.registry import ParserRegistry
from app.core.templates.registry import discover_templates, get_template, get_template_content, save_custom_template, delete_custom_template

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateResponse])
async def list_templates():
    templates = discover_templates()
    return [
        TemplateResponse(
            id=t["id"],
            name=t["name"],
            description=t["description"],
            variables=t.get("variables", {}),
            preview=t.get("preview", ""),
            is_builtin=t.get("is_builtin", False),
        )
        for t in templates
    ]


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template_detail(template_id: str):
    t = get_template(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return TemplateResponse(
        id=t["id"],
        name=t["name"],
        description=t["description"],
        variables=t.get("variables", {}),
        preview=t.get("preview", ""),
        is_builtin=t.get("is_builtin", False),
    )


@router.get("/{template_id}/content")
async def get_template_source(template_id: str):
    """Get the .tex.j2 source content of a template."""
    content = get_template_content(template_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"content": content}


@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: str):
    """Delete a custom template. Built-in templates cannot be deleted."""
    t = get_template(template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    if t.get("is_builtin", False):
        raise HTTPException(status_code=403, detail="Cannot delete built-in templates")
    deleted = delete_custom_template(template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")


def _parse_template_output(full_text: str) -> tuple[dict, str]:
    """Parse LLM output to extract meta.json and template.tex.j2 content."""
    meta_match = re.search(
        r"META_JSON_START\s*\n(.*?)META_JSON_END", full_text, re.DOTALL
    )
    tex_match = re.search(
        r"TEMPLATE_TEX_START\s*\n(.*?)TEMPLATE_TEX_END", full_text, re.DOTALL
    )

    if not meta_match or not tex_match:
        raise ValueError("LLM output does not contain expected markers")

    meta_text = meta_match.group(1).strip()
    # Remove possible code block markers
    meta_text = re.sub(r"^```(?:json)?\s*\n?", "", meta_text)
    meta_text = re.sub(r"\n?```\s*$", "", meta_text)

    tex_text = tex_match.group(1).strip()
    tex_text = re.sub(r"^```(?:latex|tex)?\s*\n?", "", tex_text)
    tex_text = re.sub(r"\n?```\s*$", "", tex_text)

    meta = json.loads(meta_text)
    return meta, tex_text


@router.post("/generate")
async def generate_template(req: TemplateGenerateRequest):
    """SSE endpoint: generate a LaTeX template from description."""

    async def event_stream():
        full_text = ""
        try:
            async for chunk in generate_template_stream(req.description):
                full_text += chunk
                yield f"event: chunk\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

            # Parse the complete output
            meta, tex_content = _parse_template_output(full_text)
            template_id = meta.get("id", "custom_template")

            # Save to custom directory
            save_custom_template(template_id, meta, tex_content)

            yield f"event: done\ndata: {json.dumps({'template_id': template_id, 'meta': meta}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("Template generation failed")
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


MAX_TEMPLATE_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("/generate-from-file")
async def generate_template_from_file(file: UploadFile = File(...)):
    """Upload a document (docx/pdf/md/txt), extract formatting requirements, then generate a LaTeX template."""
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    parser = ParserRegistry.get_parser(ext)
    if not parser:
        supported = ParserRegistry.supported_extensions()
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {supported}",
        )

    content = await file.read()
    if len(content) > MAX_TEMPLATE_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Max 50MB.")

    # Save to temp file for parsing
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        parsed = await parser.parse(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    # Build description from parsed content + formatting metadata
    formatting = parsed.metadata.get("formatting", {})
    doc_text = parsed.text[:8000]  # Limit text length

    async def event_stream():
        full_text = ""
        try:
            # Step 1: Extract formatting requirements from document
            yield f"event: status\ndata: {json.dumps({'message': '正在分析文档格式要求...'}, ensure_ascii=False)}\n\n"

            format_desc = await extract_format_requirements(doc_text, formatting)

            yield f"event: format\ndata: {json.dumps({'description': format_desc}, ensure_ascii=False)}\n\n"

            # Step 2: Generate template from extracted requirements
            # Prepend source filename so LLM names the template accordingly
            doc_base_name = filename.rsplit(".", 1)[0] if "." in filename else filename
            full_desc = f"源文档名称：{doc_base_name}\n请以此文档名称作为模板命名参考。\n\n{format_desc}"

            yield f"event: status\ndata: {json.dumps({'message': '正在生成 LaTeX 模板...'}, ensure_ascii=False)}\n\n"

            async for chunk in generate_template_stream(full_desc):
                full_text += chunk
                yield f"event: chunk\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"

            # Parse and save template
            meta, tex_content = _parse_template_output(full_text)
            template_id = meta.get("id", "custom_template")
            save_custom_template(template_id, meta, tex_content)

            yield f"event: done\ndata: {json.dumps({'template_id': template_id, 'meta': meta}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("Template generation from file failed")
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
