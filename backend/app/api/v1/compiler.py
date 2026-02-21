import asyncio
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.schemas.schemas import CompileRequest, CompileResponse
from app.config import settings
from app.core.compiler.engine import compile_latex
from app.core.compiler.sandbox import create_sandbox, cleanup_sandbox
from app.core.compiler.error_parser import parse_xelatex_log
from app.core.compiler.word_preprocessor import preprocess_latex_for_word
from app.core.compiler.word_postprocessor import postprocess_word
from app.core.compiler.latex2docx import convert_latex_to_docx
from app.core.llm.fix_agent import run_fix_agent_loop
from app.core.templates.registry import get_template, get_template_support_dirs
from app.dependencies import get_db, get_project
from app.models.models import Project
from app.services import project_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["compiler"])


@router.post("/projects/{project_id}/compile", response_model=CompileResponse)
async def compile_project(
    data: CompileRequest | None = None,
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    latex_content = (data and data.latex_content) or project.latex_content
    if not latex_content:
        raise HTTPException(status_code=400, detail="No LaTeX content to compile")

    output_dir = settings.storage_path / project.id / "output"
    sandbox = create_sandbox(output_dir)
    support_dirs = get_template_support_dirs(project.template_id) if project.template_id else []

    result = await compile_latex(latex_content, sandbox, support_dirs=support_dirs or None)
    cleanup_sandbox(sandbox)

    pdf_url = ""
    if result.success:
        pdf_url = f"/api/v1/projects/{project.id}/pdf"

    return CompileResponse(
        success=result.success,
        pdf_url=pdf_url,
        log=result.log,
        errors=result.errors,
    )


@router.post("/projects/{project_id}/compile-and-fix")
async def compile_and_fix(
    data: CompileRequest | None = None,
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    """Compile LaTeX, auto-fix errors with agent + tools, retry up to 3 times. Returns SSE events."""
    latex_content = (data and data.latex_content) or project.latex_content
    if not latex_content:
        raise HTTPException(status_code=400, detail="No LaTeX content to compile")

    max_retries = 2
    support_dirs = get_template_support_dirs(project.template_id) if project.template_id else []

    async def event_stream():
        current_latex = latex_content
        for attempt in range(1, max_retries + 1):
            yield {
                "event": "status",
                "data": json.dumps({
                    "attempt": attempt,
                    "message": f"第 {attempt} 次编译中...",
                }),
            }

            output_dir = settings.storage_path / project.id / "output"
            sandbox = create_sandbox(output_dir)
            result = await compile_latex(current_latex, sandbox, support_dirs=support_dirs or None)
            cleanup_sandbox(sandbox)

            if result.success:
                # Save fixed LaTeX back to project if it was modified
                if current_latex != latex_content:
                    await project_service.update_project(
                        db, project, latex_content=current_latex
                    )
                pdf_url = f"/api/v1/projects/{project.id}/pdf"
                yield {
                    "event": "done",
                    "data": json.dumps({
                        "success": True,
                        "pdf_url": pdf_url,
                        "latex_content": current_latex,
                        "attempts": attempt,
                        "message": f"编译成功（第 {attempt} 次）",
                    }),
                }
                return

            # Compile failed — parse structured errors from log
            parsed_errors = parse_xelatex_log(result.log)

            if attempt >= max_retries:
                yield {
                    "event": "done",
                    "data": json.dumps({
                        "success": False,
                        "latex_content": current_latex,
                        "attempts": attempt,
                        "errors": result.errors,
                        "message": f"编译失败，已重试 {max_retries} 次",
                    }),
                }
                return

            # Run fix agent
            yield {
                "event": "status",
                "data": json.dumps({
                    "attempt": attempt,
                    "message": "编译失败，AI 正在分析编译错误...",
                }),
            }

            try:
                agent_fixed = False
                async for event in run_fix_agent_loop(current_latex, parsed_errors):
                    sse_event = _map_fix_agent_event(event, attempt)
                    if sse_event is not None:
                        yield sse_event

                    # Capture the fixed latex from the agent
                    if event.type == "latex":
                        current_latex = event.data
                        agent_fixed = True

                    # Agent declared unfixable — stop retrying
                    if event.type == "unfixable":
                        yield {
                            "event": "done",
                            "data": json.dumps({
                                "success": False,
                                "latex_content": current_latex,
                                "attempts": attempt,
                                "errors": result.errors,
                                "message": f"无法自动修复: {event.data}",
                            }),
                        }
                        return

                    # Agent errored out
                    if event.type == "error":
                        yield {
                            "event": "done",
                            "data": json.dumps({
                                "success": False,
                                "latex_content": current_latex,
                                "attempts": attempt,
                                "errors": result.errors,
                                "message": f"AI 修正出错: {event.data}",
                            }),
                        }
                        return

                if not agent_fixed:
                    yield {
                        "event": "done",
                        "data": json.dumps({
                            "success": False,
                            "latex_content": current_latex,
                            "attempts": attempt,
                            "errors": result.errors,
                            "message": "AI 未能修正任何错误",
                        }),
                    }
                    return

            except Exception as e:
                logger.exception("Fix agent error")
                yield {
                    "event": "done",
                    "data": json.dumps({
                        "success": False,
                        "latex_content": current_latex,
                        "attempts": attempt,
                        "errors": result.errors,
                        "message": f"AI 修正出错: {str(e)}",
                    }),
                }
                return

    return EventSourceResponse(event_stream())


def _map_fix_agent_event(event, attempt: int) -> dict | None:
    """Map a fix agent AgentEvent to an SSE event dict, or None to skip."""
    if event.type == "thinking":
        return {
            "event": "status",
            "data": json.dumps({"attempt": attempt, "message": event.data}),
        }
    elif event.type == "tool_call":
        return {
            "event": "status",
            "data": json.dumps({"attempt": attempt, "message": f"AI 正在操作: {event.data}"}),
        }
    elif event.type == "latex":
        return {
            "event": "fix",
            "data": json.dumps({
                "attempt": attempt,
                "latex_content": event.data,
                "message": "AI 已修正，重新编译...",
            }),
        }
    # tool_result, done, content — consumed internally, not forwarded as SSE
    return None


def _detect_top_level_division(project: Project, latex_content: str = "") -> str:
    """Determine whether Pandoc should use 'chapter' or 'section' as top-level.

    Checks template meta.json ``doc_class_type`` first, then falls back to
    inspecting the LaTeX ``\\documentclass`` line.
    """
    # 1. Check template metadata
    if project.template_id:
        tmpl = get_template(project.template_id)
        if tmpl:
            dct = tmpl.get("doc_class_type", "")
            if dct in ("book", "report"):
                return "chapter"
            if dct == "article":
                return "section"

    # 2. Inspect LaTeX content
    if latex_content:
        m = re.search(r"\\documentclass(?:\[[^\]]*\])?\{(\w+)\}", latex_content)
        if m:
            doc_class = m.group(1).lower()
            if doc_class in ("ctexrep", "ctexbook", "report", "book"):
                return "chapter"

    return "section"


def _find_reference_docx(project: Project) -> str | None:
    """Find the best reference.docx for Pandoc Word export.

    Priority: template-specific > generic fallback.
    """
    templates_dir = Path(__file__).resolve().parent.parent.parent / "core" / "templates"

    # 1. Try template-specific reference.docx
    template_id = project.template_id
    if template_id:
        for subdir in ("builtin", "custom"):
            ref = templates_dir / subdir / template_id / "reference.docx"
            if ref.exists():
                return str(ref)

    # 2. Generic fallback
    generic = templates_dir / "reference.docx"
    if generic.exists():
        return str(generic)

    return None


@router.get("/projects/{project_id}/word")
async def download_word(project: Project = Depends(get_project)):
    """Convert LaTeX to Word (.docx).

    Uses the direct LaTeX→DOCX converter (no Pandoc). Falls back to the
    legacy Pandoc pipeline if the direct conversion fails.
    """
    tex_path = (settings.storage_path / project.id / "output" / "build" / "document.tex").resolve()
    if not str(tex_path).startswith(str(settings.storage_path.resolve())):
        raise HTTPException(status_code=403, detail="Access denied.")

    # Fallback: use project's latex_content if .tex file doesn't exist
    if not tex_path.exists():
        if not project.latex_content:
            raise HTTPException(status_code=404, detail="No LaTeX content. Compile first.")
        tex_path.parent.mkdir(parents=True, exist_ok=True)
        tex_path.write_text(project.latex_content, encoding="utf-8")

    latex_content = tex_path.read_text(encoding="utf-8")
    template_id = project.template_id or ""

    # Extract metadata (shared by both paths)
    _, metadata = preprocess_latex_for_word(latex_content, template_id)

    docx_path = tex_path.with_suffix(".docx")

    # ── Try direct LaTeX→DOCX conversion ────────────────────────────────
    try:
        convert_latex_to_docx(
            latex_content=latex_content,
            output_path=docx_path,
            metadata=metadata,
            template_id=template_id,
            image_base_dir=tex_path.parent,
        )
    except Exception as e:
        logger.warning("Direct LaTeX→DOCX conversion failed, falling back to Pandoc: %s", e)
        # ── Pandoc fallback ─────────────────────────────────────────────
        await _pandoc_word_fallback(tex_path, latex_content, metadata, docx_path, project)

    if not docx_path.exists():
        raise HTTPException(status_code=500, detail="Word 文件生成失败")

    filename = f"{project.name or 'document'}.docx"
    return FileResponse(
        path=str(docx_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


async def _pandoc_word_fallback(
    tex_path: Path,
    latex_content: str,
    metadata,
    docx_path: Path,
    project: Project,
):
    """Legacy Pandoc-based Word export (fallback)."""
    cleaned_content, metadata = preprocess_latex_for_word(
        latex_content, project.template_id or ""
    )

    word_tex_path = tex_path.parent / "document_for_word.tex"
    word_tex_path.write_text(cleaned_content, encoding="utf-8")

    cmd = [
        "pandoc", str(word_tex_path),
        "-f", "latex",
        "-t", "docx",
        "-o", str(docx_path),
        "--resource-path", str(tex_path.parent),
        "--number-sections",
    ]

    top_div = _detect_top_level_division(project, latex_content)
    cmd.extend(["--top-level-division", top_div])

    ref_docx = _find_reference_docx(project)
    if ref_docx:
        cmd.extend(["--reference-doc", ref_docx])

    lua_filter = (
        Path(__file__).resolve().parent.parent.parent
        / "core" / "compiler" / "pandoc_filters" / "smart_latex.lua"
    )
    if lua_filter.exists():
        cmd.extend(["--lua-filter", str(lua_filter)])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            detail = stderr.decode(errors="replace")[:500] if stderr else "pandoc conversion failed"
            raise HTTPException(status_code=500, detail=f"Word 转换失败: {detail}")
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Word 转换超时")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="pandoc 未安装，无法导出 Word")

    try:
        postprocess_word(str(docx_path), metadata, project.template_id or "")
    except Exception as e:
        logger.warning("Word post-processing failed (returning Pandoc output): %s", e)


@router.get("/projects/{project_id}/pdf")
async def download_pdf(project: Project = Depends(get_project)):
    pdf_path = (settings.storage_path / project.id / "output" / "build" / "document.pdf").resolve()
    # Defence in depth: ensure path is within storage directory
    if not str(pdf_path).startswith(str(settings.storage_path.resolve())):
        raise HTTPException(status_code=403, detail="Access denied.")
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found. Compile first.")
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
    )
