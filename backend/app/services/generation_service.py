import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.compiler.engine import validate_latex_syntax
from app.core.llm.chains import (
    analyze_document,
    plan_outline,
    generate_chapter,
    generate_chapter_stream,
    integrate_content,
    generate_latex_stream,
    fix_chapter_latex_errors,
)
from app.core.llm.output_parsers import extract_latex
from app.core.templates.registry import get_template, get_template_content, get_template_support_dirs
from app.services.document_service import list_documents, get_document

logger = logging.getLogger(__name__)


def _detect_document_class(template_id: str) -> str:
    """Detect the document class from a template (e.g. 'report', 'article').

    Supports meta.json ``doc_class_type`` override, and handles path-prefixed
    class names like ``Style/ucasthesis`` by stripping the directory part.
    """
    import re

    # Check meta.json override first
    meta = get_template(template_id)
    if meta and meta.get("doc_class_type"):
        return meta["doc_class_type"]

    tex_content = get_template_content(template_id)
    if tex_content:
        # Match \documentclass[...]{...} or \documentclass{...}
        # Strip optional path prefix (e.g. Style/ucasthesis -> ucasthesis)
        m = re.search(r'\\documentclass\[.*?\]\{(?:[\w/]*/)?([\w]+)\}', tex_content)
        if not m:
            m = re.search(r'\\documentclass\{(?:[\w/]*/)?([\w]+)\}', tex_content)
        if m:
            return m.group(1)
    return "article"


def _get_section_commands(doc_class: str) -> dict:
    """Return the correct sectioning commands based on document class."""
    if doc_class in ("report", "book", "ctexrep", "ctexbook", "ucasthesis"):
        return {
            "top": r"\chapter",
            "second": r"\section",
            "third": r"\subsection",
            "fourth": r"\subsubsection",
        }
    else:  # article, etc.
        return {
            "top": r"\section",
            "second": r"\subsection",
            "third": r"\subsubsection",
            "fourth": r"\paragraph",
        }


def _get_template_rules(template_id: str) -> str:
    """Extract formatting rules from template metadata for use in prompts."""
    meta = get_template(template_id)
    if not meta:
        return ""

    rules_parts = []
    if meta.get("description"):
        rules_parts.append(f"模板类型：{meta['name']} — {meta['description']}")

    variables = meta.get("variables", {})
    if variables:
        # Extract any formatting hints from variable descriptions
        for var_name, var_info in variables.items():
            if isinstance(var_info, dict) and var_info.get("description"):
                rules_parts.append(f"- {var_name}: {var_info['description']}")

    # Also include the template .tex.j2 content as reference for LaTeX structure
    tex_content = get_template_content(template_id)
    if tex_content:
        # Extract preamble (documentclass to begin{document}) as formatting reference
        import re
        preamble_match = re.search(
            r'(\\documentclass.*?)(\\begin\{document\})',
            tex_content, re.DOTALL
        )
        if preamble_match:
            preamble = preamble_match.group(1).strip()
            rules_parts.append(f"\n参考模板的 LaTeX 导言区设置（请保持一致的格式风格）：\n{preamble}")

        # Extract example body content for section hierarchy reference
        body_match = re.search(
            r'\\begin\{document\}(.*?)\\end\{document\}',
            tex_content, re.DOTALL
        )
        if body_match:
            body = body_match.group(1).strip()
            # Extract section hierarchy examples (first few)
            section_examples = []
            for m in re.finditer(r'(\\(?:chapter|section|subsection|subsubsection|paragraph|subparagraph)\{[^}]+\})', body):
                section_examples.append(m.group(1))
                if len(section_examples) >= 8:
                    break
            if section_examples:
                rules_parts.append(f"\n模板的章节层级示例（请保持一致的层级结构）：\n" + "\n".join(section_examples))

    return "\n".join(rules_parts) if rules_parts else ""


def _build_preamble_from_template(outline: dict, template_id: str) -> str:
    """Build LaTeX preamble + front matter from template content.

    Uses Jinja2 rendering to properly handle all template variables (with
    defaults), then extracts everything before the first content \\chapter/\\section.
    """
    import re
    from app.core.templates.engine import render_string

    tex_content = get_template_content(template_id)

    if not tex_content:
        return _build_default_preamble(outline)

    doc_begin_match = re.search(r'\\begin\{document\}', tex_content)
    if not doc_begin_match:
        return _build_default_preamble(outline)

    # Render the full template with Jinja2 using outline variables as context.
    # Only include non-empty values so that Jinja2 default() filters work
    # correctly (default() only triggers on undefined, not on empty string).
    variables = {}
    key_map = {
        "title": "title",
        "author": "author",
        "institute": "institute",
        "institution": "institute",  # alias
        "report_date": "report_date",
        "abstract": "abstract",
    }
    for outline_key, var_name in key_map.items():
        val = outline.get(outline_key, "")
        if val and var_name not in variables:
            variables[var_name] = val
    if "title" not in variables:
        variables["title"] = "综合文档"
    # Pass through any extra outline keys (only non-empty)
    for k, v in outline.items():
        if k not in variables and v:
            variables[k] = v

    try:
        rendered = render_string(tex_content, variables)
    except Exception as e:
        logger.warning("Jinja2 rendering failed, falling back to regex: %s", e)
        rendered = re.sub(r'<<.*?>>', '', tex_content)
        rendered = re.sub(r'<%.*?%>', '', rendered)
        rendered = re.sub(r'<#.*?#>', '', rendered)

    # Take everything up to (but not including) \end{document}.
    # This gives us preamble + front matter (cover, revision records, toc, etc.)
    # Chapters will be appended after this, followed by a new \end{document}.
    end_doc = re.search(r'\\end\{document\}', rendered)
    if end_doc:
        result = rendered[:end_doc.start()].rstrip()
    else:
        result = rendered.rstrip()

    # Ensure \begin{document} is present
    if r'\begin{document}' not in result:
        return _build_default_preamble(outline)

    return result + "\n"


def _build_default_preamble(outline: dict) -> str:
    """Build a default LaTeX preamble when no template is available."""
    title = outline.get("title", "综合文档")
    author = outline.get("author", "")
    abstract = outline.get("abstract", "")

    preamble = (
        "\\documentclass[12pt, a4paper]{article}\n"
        "\\usepackage[UTF8]{ctex}\n"
        "\\usepackage{geometry}\n"
        "\\usepackage{amsmath, amssymb}\n"
        "\\usepackage{graphicx}\n"
        "\\usepackage{hyperref}\n"
        "\\usepackage{booktabs}\n"
        "\\usepackage{setspace}\n"
        "\\usepackage{enumitem}\n"
        "\\usepackage{longtable}\n"
        "\n"
        "\\geometry{left=2.5cm, right=2.5cm, top=2.5cm, bottom=2.5cm}\n"
        "\\onehalfspacing\n"
        "\n"
        f"\\title{{{title}}}\n"
        f"\\author{{{author}}}\n"
        "\\date{\\today}\n"
        "\n"
        "\\begin{document}\n"
        "\n"
        "\\maketitle\n"
        "\n"
    )

    if abstract:
        preamble += (
            "\\begin{abstract}\n"
            f"{abstract}\n"
            "\\end{abstract}\n"
            "\n"
        )

    preamble += "\\tableofcontents\n\\newpage\n"

    return preamble


async def _validate_and_fix_chapter(
    preamble: str,
    chapter_content: str,
    chapter_index: int,
    max_fix_attempts: int = 1,
    support_dirs: list[Path] | None = None,
) -> tuple[str, bool]:
    """Validate a chapter's LaTeX syntax and auto-fix if errors are found.

    Wraps preamble + chapter + \\end{document}, runs xelatex -draftmode,
    and if errors occur, calls LLM to fix the chapter content.

    Returns (content, was_fixed).
    """
    # Build a complete document for validation
    full_doc = preamble + "\n\n" + chapter_content + "\n\n\\end{document}\n"

    result = await validate_latex_syntax(full_doc, support_dirs=support_dirs)

    if result.success:
        return chapter_content, False

    # Validation failed — try to fix
    error_summary = "\n".join(result.errors[:10])  # Limit to 10 errors
    logger.warning(
        "Chapter %d syntax validation failed (%d errors): %s",
        chapter_index,
        len(result.errors),
        error_summary[:200],
    )

    for attempt in range(max_fix_attempts):
        try:
            fixed_content = await fix_chapter_latex_errors(
                chapter_content, error_summary
            )
            if not fixed_content or fixed_content == chapter_content:
                logger.warning(
                    "Chapter %d fix attempt %d returned unchanged content",
                    chapter_index,
                    attempt + 1,
                )
                break

            # Re-validate the fixed content
            fixed_doc = preamble + "\n\n" + fixed_content + "\n\n\\end{document}\n"
            re_result = await validate_latex_syntax(fixed_doc, support_dirs=support_dirs)

            if re_result.success:
                logger.info("Chapter %d fixed successfully on attempt %d", chapter_index, attempt + 1)
                return fixed_content, True

            # Still has errors — update for next attempt
            chapter_content = fixed_content
            error_summary = "\n".join(re_result.errors[:10])
            logger.warning(
                "Chapter %d still has errors after fix attempt %d",
                chapter_index,
                attempt + 1,
            )
        except Exception as e:
            logger.warning("Chapter %d fix attempt %d failed: %s", chapter_index, attempt + 1, e)
            break

    # Return best effort (possibly partially fixed)
    return chapter_content, False


async def generate_latex_from_documents(
    db: AsyncSession,
    project_id: str,
    template_id: str,
    document_ids: list[str],
) -> AsyncGenerator[str, None]:
    """Orchestrate LaTeX generation. Always uses pipeline mode to avoid truncation."""
    documents = await _gather_documents(db, project_id, document_ids)

    if not documents:
        yield "% No documents found. Please upload documents first.\n"
        return

    # Always use pipeline mode — simple mode (one-shot) causes truncation with long docs
    async for chunk in _pipeline_generate(documents, template_id):
        yield chunk


async def generate_latex_pipeline(
    db: AsyncSession,
    project_id: str,
    template_id: str,
    document_ids: list[str],
) -> AsyncGenerator[dict, None]:
    """Pipeline generation with structured SSE events for frontend progress tracking."""
    documents = await _gather_documents(db, project_id, document_ids)

    if not documents:
        yield {"event": "error", "message": "没有找到文档，请先上传文档"}
        return

    total_docs = len(documents)
    template_rules = _get_template_rules(template_id)
    doc_class = _detect_document_class(template_id)
    section_commands = _get_section_commands(doc_class)
    support_dirs = get_template_support_dirs(template_id)

    # Add project images directory for compilation validation
    images_dir = settings.storage_path / project_id / "images"
    if images_dir.is_dir():
        support_dirs.append(images_dir)

    # ===== Stage 1: Analyze each document =====
    yield {
        "event": "stage",
        "stage": "analyze",
        "message": f"阶段 1/3：分析 {total_docs} 篇文档...",
        "progress": 0,
    }

    analyses = []
    # Process in batches of 5 for concurrency control
    batch_size = 10
    for batch_start in range(0, total_docs, batch_size):
        batch_end = min(batch_start + batch_size, total_docs)
        batch = documents[batch_start:batch_end]

        tasks = [
            analyze_document(
                doc["filename"],
                doc["content"],
                batch_start + i + 1,
                total_docs,
            )
            for i, doc in enumerate(batch)
        ]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(batch_results):
            doc_idx = batch_start + i
            if isinstance(result, Exception):
                logger.warning(f"Failed to analyze doc {doc_idx + 1}: {result}")
                # Fallback analysis
                analyses.append({
                    "title": documents[doc_idx]["filename"],
                    "authors": [],
                    "type": "其他",
                    "key_topics": [],
                    "sections": [{"heading": "全文", "summary": documents[doc_idx]["content"][:500], "key_points": []}],
                    "abstract": documents[doc_idx]["content"][:300],
                    "references": [],
                    "importance": "中",
                })
            else:
                analyses.append(result)

            progress = int((doc_idx + 1) / total_docs * 100)
            yield {
                "event": "stage",
                "stage": "analyze",
                "message": f"已分析 {doc_idx + 1}/{total_docs} 篇文档",
                "progress": progress,
                "detail": f"完成：{documents[doc_idx]['filename']}",
            }

    # ===== Stage 2: Plan outline =====
    yield {
        "event": "stage",
        "stage": "outline",
        "message": "阶段 2/3：规划文档大纲...",
        "progress": 0,
    }

    outline = await plan_outline(analyses, template_id)

    yield {
        "event": "outline",
        "stage": "outline",
        "message": "大纲规划完成",
        "progress": 100,
        "outline": outline,
    }

    # ===== Stage 3: Generate chapters (parallel) =====
    chapters = outline.get("chapters", [])
    total_chapters = len(chapters)

    yield {
        "event": "stage",
        "stage": "generate",
        "message": f"阶段 3/3：并行生成 {total_chapters} 个章节...",
        "progress": 0,
    }

    # Build document preamble from template
    preamble = _build_preamble_from_template(outline, template_id)
    full_latex = preamble

    yield {"event": "chunk", "content": preamble}

    # Prepare source docs for each chapter
    chapter_sources = []
    for chapter in chapters:
        source_doc_indices = chapter.get("source_docs", [])
        source_docs = []
        for idx in source_doc_indices:
            if 1 <= idx <= total_docs:
                doc = documents[idx - 1]
                source_docs.append({
                    "filename": doc["filename"],
                    "content": doc["content"],
                    "analysis": analyses[idx - 1],
                })
        chapter_sources.append(source_docs)

    # Generate chapters in parallel batches of 3
    chapter_batch_size = 8
    chapter_results = [""] * total_chapters
    completed_count = 0

    for batch_start in range(0, total_chapters, chapter_batch_size):
        batch_end = min(batch_start + chapter_batch_size, total_chapters)

        batch_titles = [chapters[i].get("title", "") for i in range(batch_start, batch_end)]
        yield {
            "event": "stage",
            "stage": "generate",
            "message": f"并行生成第 {batch_start + 1}-{batch_end}/{total_chapters} 章：{', '.join(batch_titles)}",
            "progress": int(batch_start / total_chapters * 100),
        }

        tasks = [
            generate_chapter(
                doc_title=outline.get("title", ""),
                chapter=chapters[ch_idx],
                chapter_index=ch_idx + 1,
                total_chapters=total_chapters,
                source_documents=chapter_sources[ch_idx],
                template_rules=template_rules,
                section_commands=section_commands,
            )
            for ch_idx in range(batch_start, batch_end)
        ]

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(batch_results):
            ch_idx = batch_start + i
            if isinstance(result, Exception):
                logger.warning(f"Failed to generate chapter {ch_idx + 1}: {result}")
                top_cmd = section_commands["top"]
                chapter_results[ch_idx] = f"\n\n{top_cmd}{{{chapters[ch_idx].get('title', '章节')}}}\n% 生成失败: {result}\n"
            else:
                chapter_results[ch_idx] = extract_latex(result)

        # Validate and fix chapters in parallel
        validate_tasks = []
        validate_indices = []
        for i in range(batch_start, batch_end):
            if not chapter_results[i].startswith("\n\n"):  # skip failed chapters
                validate_tasks.append(
                    _validate_and_fix_chapter(
                        preamble, chapter_results[i], i + 1,
                        support_dirs=support_dirs or None,
                    )
                )
                validate_indices.append(i)

        if validate_tasks:
            yield {
                "event": "stage",
                "stage": "generate",
                "message": f"验证第 {batch_start + 1}-{batch_end} 章语法...",
                "progress": int(batch_start / total_chapters * 100),
            }
            val_results = await asyncio.gather(*validate_tasks, return_exceptions=True)
            for ch_idx, val_result in zip(validate_indices, val_results):
                if isinstance(val_result, Exception):
                    logger.warning(f"Validation failed for chapter {ch_idx + 1}: {val_result}")
                else:
                    fixed_content, was_fixed = val_result
                    chapter_results[ch_idx] = fixed_content
                    if was_fixed:
                        logger.info(f"Chapter {ch_idx + 1} was auto-fixed")

        # Yield completed chapters in order
        for ch_idx in range(batch_start, batch_end):
            completed_count += 1
            content = chapter_results[ch_idx]
            full_latex += "\n\n" + content
            yield {"event": "chunk", "content": "\n\n" + content}
            yield {
                "event": "stage",
                "stage": "generate",
                "message": f"第 {completed_count}/{total_chapters} 章完成：{chapters[ch_idx].get('title', '')}",
                "progress": int(completed_count / total_chapters * 100),
            }

    # Add appendices if any
    appendices = outline.get("appendices", [])
    if appendices:
        appendix_latex = "\n\n\\appendix\n"
        for app in appendices:
            appendix_latex += f"\\section{{{app.get('title', '附录')}}}\n"
            appendix_latex += f"{app.get('description', '')}\n\n"
        full_latex += appendix_latex
        yield {"event": "chunk", "content": appendix_latex}

    # Add document ending
    ending = "\n\n\\end{document}\n"
    full_latex += ending
    yield {"event": "chunk", "content": ending}

    # Clean the full output
    cleaned = extract_latex(full_latex)

    yield {
        "event": "done",
        "content": cleaned,
        "message": f"生成完成：{total_chapters} 章，基于 {total_docs} 篇文档（并行生成）",
    }


async def _gather_documents(
    db: AsyncSession, project_id: str, document_ids: list[str]
) -> list[dict]:
    """Gather document contents from DB."""
    if document_ids:
        documents = []
        for doc_id in document_ids:
            doc = await get_document(db, doc_id)
            if doc:
                documents.append({
                    "filename": doc.original_name,
                    "content": doc.parsed_content,
                })
    else:
        all_docs = await list_documents(db, project_id)
        documents = [
            {"filename": d.original_name, "content": d.parsed_content}
            for d in all_docs
        ]
    return documents


async def _pipeline_generate(
    documents: list[dict], template_id: str
) -> AsyncGenerator[str, None]:
    """Pipeline generation as plain text stream (backward compatible)."""
    async for event in generate_latex_pipeline_internal(documents, template_id):
        if event.get("event") == "chunk":
            yield event["content"]


async def generate_latex_pipeline_internal(
    documents: list[dict], template_id: str
) -> AsyncGenerator[dict, None]:
    """Internal pipeline without DB dependency."""
    total_docs = len(documents)
    template_rules = _get_template_rules(template_id)
    doc_class = _detect_document_class(template_id)
    section_commands = _get_section_commands(doc_class)
    support_dirs = get_template_support_dirs(template_id)

    # Stage 1: Analyze
    analyses = []
    batch_size = 10
    for batch_start in range(0, total_docs, batch_size):
        batch_end = min(batch_start + batch_size, total_docs)
        batch = documents[batch_start:batch_end]
        tasks = [
            analyze_document(doc["filename"], doc["content"], batch_start + i + 1, total_docs)
            for i, doc in enumerate(batch)
        ]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                analyses.append({
                    "title": documents[batch_start + i]["filename"],
                    "authors": [], "type": "其他", "key_topics": [],
                    "sections": [{"heading": "全文", "summary": documents[batch_start + i]["content"][:500], "key_points": []}],
                    "abstract": documents[batch_start + i]["content"][:300],
                    "references": [], "importance": "中",
                })
            else:
                analyses.append(result)

    # Stage 2: Outline
    outline = await plan_outline(analyses, template_id)

    # Stage 3: Generate (parallel)
    chapters = outline.get("chapters", [])
    total_chapters = len(chapters)
    preamble = _build_preamble_from_template(outline, template_id)
    yield {"event": "chunk", "content": preamble}

    # Prepare sources
    chapter_sources = []
    for chapter in chapters:
        source_docs = []
        for idx in chapter.get("source_docs", []):
            if 1 <= idx <= total_docs:
                source_docs.append({
                    "filename": documents[idx - 1]["filename"],
                    "content": documents[idx - 1]["content"],
                    "analysis": analyses[idx - 1],
                })
        chapter_sources.append(source_docs)

    # Parallel batch generation
    chapter_batch_size = 8
    for batch_start in range(0, total_chapters, chapter_batch_size):
        batch_end = min(batch_start + chapter_batch_size, total_chapters)
        tasks = [
            generate_chapter(
                doc_title=outline.get("title", ""),
                chapter=chapters[ch_idx],
                chapter_index=ch_idx + 1,
                total_chapters=total_chapters,
                source_documents=chapter_sources[ch_idx],
                template_rules=template_rules,
                section_commands=section_commands,
            )
            for ch_idx in range(batch_start, batch_end)
        ]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Extract content, then validate and fix in parallel
        chapter_contents = []
        for i, result in enumerate(batch_results):
            ch_idx = batch_start + i
            if isinstance(result, Exception):
                chapter_contents.append(None)
            else:
                chapter_contents.append(extract_latex(result))

        validate_tasks = []
        validate_indices = []
        for i, content in enumerate(chapter_contents):
            if content is not None:
                ch_idx = batch_start + i
                validate_tasks.append(
                    _validate_and_fix_chapter(
                        preamble, content, ch_idx + 1,
                        support_dirs=support_dirs or None,
                    )
                )
                validate_indices.append(i)

        if validate_tasks:
            val_results = await asyncio.gather(*validate_tasks, return_exceptions=True)
            for local_i, val_result in zip(validate_indices, val_results):
                if not isinstance(val_result, Exception):
                    fixed_content, was_fixed = val_result
                    chapter_contents[local_i] = fixed_content

        for i, content in enumerate(chapter_contents):
            if content is None:
                yield {"event": "chunk", "content": f"\n\n% Chapter generation failed: {batch_results[i]}\n"}
            else:
                yield {"event": "chunk", "content": "\n\n" + content}

    yield {"event": "chunk", "content": "\n\n\\end{document}\n"}
