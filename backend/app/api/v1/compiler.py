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
from app.core.compiler.latex2docx import convert_latex_to_docx
from app.core.llm.fix_agent import run_fix_agent_loop
from app.core.templates.registry import get_template_support_dirs
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


@router.get("/projects/{project_id}/word")
async def download_word(project: Project = Depends(get_project)):
    """Convert LaTeX to Word (.docx).

    Semantic-first flow:
    1) Compile LaTeX to refresh ``document.tex`` / ``document.aux``.
    2) Convert with the direct LaTeX→DOCX engine.
    """
    build_dir = (settings.storage_path / project.id / "output" / "build").resolve()
    tex_path = (build_dir / "document.tex").resolve()
    if not str(build_dir).startswith(str(settings.storage_path.resolve())):
        raise HTTPException(status_code=403, detail="Access denied.")

    latex_content = (project.latex_content or "").strip()
    if not latex_content and tex_path.exists():
        latex_content = tex_path.read_text(encoding="utf-8")
    if not latex_content:
        raise HTTPException(status_code=404, detail="No LaTeX content. Generate or edit LaTeX first.")

    support_dirs = get_template_support_dirs(project.template_id) if project.template_id else []
    compile_result = await compile_latex(
        latex_content,
        build_dir,
        support_dirs=support_dirs or None,
    )
    if not compile_result.success:
        err = (compile_result.errors[0] if compile_result.errors else "LaTeX compilation failed")[:500]
        raise HTTPException(status_code=400, detail=f"LaTeX 编译失败，无法导出一致的 Word: {err}")
    if not tex_path.exists():
        raise HTTPException(status_code=500, detail="编译完成但未生成 document.tex")

    # Use compiled source to stay aligned with PDF generation path.
    latex_content = tex_path.read_text(encoding="utf-8")
    template_id = project.template_id or ""

    # Metadata extraction only; keep source unchanged for semantic conversion.
    _, metadata = preprocess_latex_for_word(latex_content, template_id)

    docx_path = tex_path.with_suffix(".docx")

    try:
        build_frontmatter = _should_rebuild_frontmatter(latex_content, metadata)
        convert_latex_to_docx(
            latex_content=latex_content,
            output_path=docx_path,
            metadata=metadata,
            template_id=template_id,
            image_base_dir=tex_path.parent,
            build_frontmatter=build_frontmatter,
            strip_numbering_part=False,
        )
    except Exception as e:
        logger.exception("Direct LaTeX→DOCX conversion failed")
        raise HTTPException(status_code=500, detail=f"Word 转换失败: {e}")

    if not docx_path.exists():
        raise HTTPException(status_code=500, detail="Word 文件生成失败")

    filename = f"{project.name or 'document'}.docx"
    return FileResponse(
        path=str(docx_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


def _should_rebuild_frontmatter(latex_content: str, _metadata) -> bool:
    """Build front-matter only for command-driven LaTeX front-matter."""
    return bool(
        re.search(
            r"\\(?:maketitle|MAKETITLE|makedeclaration|frontmatter)\b",
            latex_content,
        )
    )


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
