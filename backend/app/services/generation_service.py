import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.compiler.engine import validate_latex_syntax, _fix_common_latex_issues, _find_begin_document as _find_real_begin_document
from app.core.llm.chains import (
    analyze_document,
    plan_outline,
    generate_chapter,
    generate_chapter_stream,
    integrate_content,
    generate_latex_stream,
)
from app.core.compiler.error_parser import parse_xelatex_log
from app.core.llm.fix_agent import fix_latex_content
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


def _get_structured_template_rules(template_id: str) -> str:
    """Extract structured formatting rules from template for LLM prompts.

    Instead of dumping the raw preamble, this extracts only the key formatting
    information that the LLM needs to generate consistent content.
    """
    import re

    meta = get_template(template_id)
    if not meta:
        return ""

    rules_parts = []

    # 1. Template description
    if meta.get("description"):
        rules_parts.append(f"模板：{meta['name']}（{meta['description']}）")

    # 2. Parse preamble for key settings
    tex_content = get_template_content(template_id)
    if not tex_content:
        return "\n".join(rules_parts)

    bd_pos = _find_real_begin_document(tex_content)
    dc_match = re.search(r'\\documentclass', tex_content) if bd_pos is not None else None

    if dc_match and bd_pos is not None:
        preamble = tex_content[dc_match.start():bd_pos]
        # Strip Jinja2 delimiters
        preamble_clean = re.sub(r'<<\s*.*?\s*>>', '', preamble)
        preamble_clean = re.sub(r'<%.*?%>', '', preamble_clean)
        preamble_clean = re.sub(r'<#.*?#>', '', preamble_clean)

        # Document class + options
        dc = re.search(r'\\documentclass\[([^\]]*)\]\{([^}]+)\}', preamble_clean)
        if dc:
            rules_parts.append(f"文档类型：{dc.group(2)}，选项：{dc.group(1)}")
        else:
            dc = re.search(r'\\documentclass\{([^}]+)\}', preamble_clean)
            if dc:
                rules_parts.append(f"文档类型：{dc.group(1)}")

        # Key packages
        pkgs = re.findall(r'\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}', preamble_clean)
        key_pkgs = [p.strip() for pkg_group in pkgs for p in pkg_group.split(',')]
        if key_pkgs:
            rules_parts.append(f"已加载宏包：{', '.join(key_pkgs[:20])}")

        # Geometry
        geo = re.search(r'\\geometry\{([^}]+)\}', preamble_clean)
        if geo:
            rules_parts.append(f"页面版式：{geo.group(1)}")

        # Line spacing
        if r'\onehalfspacing' in preamble_clean:
            rules_parts.append("行距：1.5 倍")
        elif r'\doublespacing' in preamble_clean:
            rules_parts.append("行距：2 倍")
        spacing = re.search(r'\\setstretch\{([^}]+)\}', preamble_clean)
        if spacing:
            rules_parts.append(f"行距：{spacing.group(1)} 倍")

        # Font hints
        if 'ctex' in preamble_clean.lower() or 'fontset' in preamble_clean.lower():
            rules_parts.append("字体：中文使用 ctex 预定义命令（\\songti、\\heiti 等），不要自定义字体")

    # 3. Section hierarchy examples (from body)
    doc_class = meta.get("doc_class_type") or _detect_document_class(template_id)
    section_cmds = _get_section_commands(doc_class)
    rules_parts.append(
        f"章节层级：{section_cmds['top']}{{}} → {section_cmds['second']}{{}} → "
        f"{section_cmds['third']}{{}} → {section_cmds['fourth']}{{}}"
    )

    return "\n".join(rules_parts)


def _get_template_structure_info(template_id: str) -> dict:
    """Extract template structure info for outline planning.

    Returns a dict with: name, description, doc_class_type, section_commands,
    fixed_sections (auto-generated content like cover/toc), suggested_chapter_range.
    """
    import re

    meta = get_template(template_id)
    if not meta:
        return {}

    doc_class = meta.get("doc_class_type") or _detect_document_class(template_id)
    section_cmds = _get_section_commands(doc_class)

    # Scan template body for fixed content (maketitle, tableofcontents, etc.)
    fixed_sections = []
    tex_content = get_template_content(template_id)
    if tex_content:
        bd_pos = _find_real_begin_document(tex_content)
        if bd_pos is not None:
            body = tex_content[bd_pos:]
            fixed_patterns = [
                (r'\\maketitle', '封面/标题页'),
                (r'\\tableofcontents', '目录'),
                (r'\\listoffigures', '图片列表'),
                (r'\\listoftables', '表格列表'),
                (r'\\makedeclaration', '声明页'),
                (r'\\MAKETITLE', '英文封面'),
                (r'\\begin\{abstract\}', '摘要'),
                (r'\\frontmatter', '前置部分'),
                (r'\\mainmatter', '正文部分'),
                (r'\\backmatter', '后置部分'),
                (r'\\bibliography', '参考文献'),
            ]
            for pattern, label in fixed_patterns:
                if re.search(pattern, body):
                    fixed_sections.append(label)

    # Suggested chapter range based on document class
    if doc_class in ("book", "ctexbook"):
        suggested_range = "4-8"
    elif doc_class in ("report", "ctexrep", "ucasthesis"):
        suggested_range = "3-7"
    else:
        suggested_range = "3-6"

    return {
        "name": meta.get("name", template_id),
        "description": meta.get("description", ""),
        "doc_class_type": doc_class,
        "section_commands": section_cmds,
        "fixed_sections": fixed_sections,
        "suggested_chapter_range": suggested_range,
    }


def _build_outline_summary(chapters: list[dict]) -> str:
    """Build a full-document outline summary for cross-chapter context.

    Returns a string listing all chapters with their subsections.
    The current chapter marker is added by _mark_current_chapter().
    """
    lines = []
    for i, ch in enumerate(chapters):
        title = ch.get("title", f"章节 {i + 1}")
        desc = ch.get("description", "")
        lines.append(f"第 {i + 1} 章：{title}")
        if desc:
            lines.append(f"  内容：{desc}")
        for sub in ch.get("subsections", []):
            lines.append(f"  - {sub.get('title', '')}")
    return "\n".join(lines)


def _mark_current_chapter(outline_summary: str, current_index: int) -> str:
    """Mark the current chapter in the outline summary."""
    lines = outline_summary.split("\n")
    result = []
    for line in lines:
        if line.startswith(f"第 {current_index + 1} 章："):
            result.append(f">>> {line} <<< [当前章节]")
        else:
            result.append(line)
    return "\n".join(result)


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

    doc_begin_pos = _find_real_begin_document(tex_content)
    if doc_begin_pos is None:
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
    # Inject CJK font variables for cross-platform support
    from app.core.fonts import get_cjk_fonts
    cjk = get_cjk_fonts()
    variables.setdefault("cjk_songti", cjk.songti)
    variables.setdefault("cjk_heiti", cjk.heiti)
    variables.setdefault("cjk_kaiti", cjk.kaiti)
    variables.setdefault("cjk_fangsong", cjk.fangsong)

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


_CHAPTER_START_MARKER = "% <<<CHAPTER_CONTENT_START>>>"
_CHAPTER_END_MARKER = "% <<<CHAPTER_CONTENT_END>>>"


def _strip_preamble_commands(content: str) -> tuple[str, bool]:
    """Remove preamble-only commands that LLM sometimes puts in chapter content.

    Returns (cleaned_content, was_modified).
    """
    import re as _re

    lines = content.split('\n')
    filtered = []
    modified = False
    for line in lines:
        stripped = line.strip()
        if _re.match(r'\\documentclass[\[\{]', stripped):
            modified = True
            continue
        if _re.match(r'\\usepackage[\[\{]', stripped):
            modified = True
            continue
        if stripped in (r'\begin{document}', r'\end{document}', r'\maketitle'):
            modified = True
            continue
        if _re.match(r'\\(title|author|date)\{', stripped):
            modified = True
            continue
        filtered.append(line)
    return '\n'.join(filtered), modified


async def _validate_and_fix_chapter(
    preamble: str,
    chapter_content: str,
    chapter_index: int,
    support_dirs: list[Path] | None = None,
) -> tuple[str, bool]:
    """Validate a chapter's LaTeX syntax and auto-fix if errors are found.

    Uses a two-phase approach:
    1. Regex pre-clean: strip preamble commands (\\usepackage etc.) from chapter body
    2. If still failing, run the fix agent (ReAct with tools) for targeted repairs

    Returns (content, was_fixed).
    """
    # Phase 1: Regex pre-clean common LLM mistakes
    cleaned, was_stripped = _strip_preamble_commands(chapter_content)
    if was_stripped:
        logger.info("Chapter %d: stripped preamble commands from chapter body", chapter_index)
        chapter_content = cleaned

    # Validate
    full_doc = preamble + "\n\n" + chapter_content + "\n\n\\end{document}\n"
    result = await validate_latex_syntax(full_doc, support_dirs=support_dirs)

    if result.success:
        return chapter_content, was_stripped

    # Parse structured errors from the log
    parsed_errors = parse_xelatex_log(result.log)
    if not parsed_errors:
        logger.warning(
            "Chapter %d: validation failed but no extractable errors; "
            "skipping fix (likely environment issue). Log tail: %s",
            chapter_index,
            result.log[-500:] if result.log else "(empty)",
        )
        return chapter_content, was_stripped

    logger.warning(
        "Chapter %d: %d errors, running fix agent",
        chapter_index, len(parsed_errors),
    )

    # Phase 2: Fix agent with markers for chapter extraction
    # Apply _fix_common_latex_issues so the agent's document matches the
    # line numbers in the xelatex error log (validate_latex_syntax applies
    # this transform internally before compiling).
    marked_doc = _fix_common_latex_issues(
        preamble + "\n"
        + _CHAPTER_START_MARKER + "\n"
        + chapter_content + "\n"
        + _CHAPTER_END_MARKER + "\n"
        + "\\end{document}\n"
    )

    try:
        fixed_doc = await fix_latex_content(marked_doc, parsed_errors, max_turns=5)
    except Exception as e:
        logger.warning("Chapter %d: fix agent failed: %s", chapter_index, e)
        return chapter_content, was_stripped

    if not fixed_doc:
        logger.warning("Chapter %d: fix agent returned no changes or unfixable", chapter_index)
        return chapter_content, was_stripped

    # Extract chapter content from markers
    start_idx = fixed_doc.find(_CHAPTER_START_MARKER)
    end_idx = fixed_doc.find(_CHAPTER_END_MARKER)
    if start_idx == -1 or end_idx == -1:
        logger.warning("Chapter %d: markers lost after agent fix", chapter_index)
        return chapter_content, was_stripped

    fixed_chapter = fixed_doc[start_idx + len(_CHAPTER_START_MARKER):end_idx].strip()

    # Re-validate the fixed content
    verify_doc = preamble + "\n\n" + fixed_chapter + "\n\n\\end{document}\n"
    verify_result = await validate_latex_syntax(verify_doc, support_dirs=support_dirs)

    if verify_result.success:
        logger.info("Chapter %d: fixed by agent", chapter_index)
        return fixed_chapter, True

    logger.warning("Chapter %d: still has errors after agent fix", chapter_index)
    return fixed_chapter, True  # return partially fixed content


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
    documents: list[dict],
    template_id: str,
    project_images_dir: Path | None = None,
) -> AsyncGenerator[dict, None]:
    """Pipeline generation with structured SSE events.

    Pure function — no DB dependency.  DB operations are handled by the API layer.
    """
    if not documents:
        yield {"event": "error", "message": "没有找到文档，请先上传文档"}
        return

    total_docs = len(documents)
    template_rules = _get_structured_template_rules(template_id)
    doc_class = _detect_document_class(template_id)
    section_commands = _get_section_commands(doc_class)
    support_dirs = get_template_support_dirs(template_id)

    if project_images_dir and project_images_dir.is_dir():
        support_dirs.append(project_images_dir)

    total_stages = 4  # analyze, outline, generate, review

    # ===== Stage 1: Analyze each document =====
    yield {
        "event": "stage",
        "stage": "analyze",
        "message": f"阶段 1/{total_stages}：分析 {total_docs} 篇文档...",
        "progress": 0,
    }

    analyses = []
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
        "message": f"阶段 2/{total_stages}：规划文档大纲...",
        "progress": 0,
    }

    template_structure = _get_template_structure_info(template_id)
    outline = await plan_outline(analyses, template_id, template_structure=template_structure)

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
        "message": f"阶段 3/{total_stages}：并行生成 {total_chapters} 个章节...",
        "progress": 0,
    }

    preamble = _build_preamble_from_template(outline, template_id)
    full_latex = preamble

    yield {"event": "chunk", "content": preamble}

    # Prepare source docs for each chapter (no analysis — only raw content)
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
                })
        chapter_sources.append(source_docs)

    # Build outline summary for cross-chapter context
    outline_summary_base = _build_outline_summary(chapters)

    chapter_batch_size = 8
    chapter_results: list[str | None] = [None] * total_chapters
    failed_chapters: dict[int, str] = {}
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
                outline_summary=_mark_current_chapter(outline_summary_base, ch_idx),
            )
            for ch_idx in range(batch_start, batch_end)
        ]

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(batch_results):
            ch_idx = batch_start + i
            if isinstance(result, Exception):
                logger.warning(f"Failed to generate chapter {ch_idx + 1}: {result}")
                top_cmd = section_commands["top"]
                failed_chapters[ch_idx] = f"\n\n{top_cmd}{{{chapters[ch_idx].get('title', '章节')}}}\n% 生成失败: {result}\n"
                chapter_results[ch_idx] = None
            else:
                chapter_results[ch_idx] = extract_latex(result)

        # Validate and fix chapters in parallel
        validate_tasks = []
        validate_indices = []
        for i in range(batch_start, batch_end):
            if chapter_results[i] is not None:
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
            content = chapter_results[ch_idx] if chapter_results[ch_idx] is not None else failed_chapters.get(ch_idx, "")
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

    # ===== Stage 4: Review & Revise =====
    yield {
        "event": "stage",
        "stage": "review",
        "message": f"阶段 4/{total_stages}：审查与修订...",
        "progress": 0,
    }

    try:
        from app.core.llm.review_agent import review_and_revise
        revised, summary = await review_and_revise(cleaned)
        if revised and revised != cleaned:
            cleaned = revised
            logger.info("Review agent revised the document: %s", summary)
            yield {
                "event": "stage",
                "stage": "review",
                "message": f"审查完成：{summary}",
                "progress": 100,
            }
        else:
            yield {
                "event": "stage",
                "stage": "review",
                "message": "审查完成，无需修订",
                "progress": 100,
            }
    except Exception as e:
        logger.warning("Review agent failed, using unreviewed version: %s", e)
        yield {
            "event": "stage",
            "stage": "review",
            "message": f"审查跳过（{e}）",
            "progress": 100,
        }

    yield {
        "event": "done",
        "content": cleaned,
        "message": f"生成完成：{total_chapters} 章，基于 {total_docs} 篇文档",
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
    async for event in generate_latex_pipeline(documents, template_id):
        if event.get("event") == "chunk":
            yield event["content"]
