import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.core.llm.client import doubao_client
from app.core.llm.output_parsers import extract_json, extract_latex

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
_prompt_env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=False)


def _render_prompt(template_name: str, **kwargs) -> str:
    template = _prompt_env.get_template(template_name)
    return template.render(**kwargs)


async def integrate_content(documents: list[dict], template_id: str) -> dict:
    """Use LLM to integrate multiple document contents into structured JSON."""
    prompt = _render_prompt(
        "content_integration.j2",
        documents=documents,
        template_id=template_id,
    )
    messages = [{"role": "user", "content": prompt}]
    response = await doubao_client.chat(messages, temperature=0.3)
    return extract_json(response)


async def generate_latex(structured_content: dict, template_content: str) -> str:
    """Use LLM to generate LaTeX from structured content and a template."""
    prompt = _render_prompt(
        "latex_generation.j2",
        structured_content=json.dumps(structured_content, ensure_ascii=False, indent=2),
        template_content=template_content,
    )
    messages = [{"role": "user", "content": prompt}]
    response = await doubao_client.chat(messages, temperature=0.3)
    return extract_latex(response)


async def generate_latex_stream(
    structured_content: dict, template_content: str
) -> AsyncGenerator[str, None]:
    """Stream generate LaTeX from structured content."""
    prompt = _render_prompt(
        "latex_generation.j2",
        structured_content=json.dumps(structured_content, ensure_ascii=False, indent=2),
        template_content=template_content,
    )
    messages = [{"role": "user", "content": prompt}]
    async for chunk in doubao_client.chat_stream(messages, temperature=0.3):
        yield chunk


async def edit_selection_stream(
    full_latex: str,
    selected_text: str,
    instruction: str,
) -> AsyncGenerator[str, None]:
    """Stream edit a selected portion of LaTeX based on user instruction."""
    prompt = _render_prompt(
        "edit_selection.j2",
        full_latex=full_latex,
        selected_text=selected_text,
        instruction=instruction,
    )
    messages = [{"role": "user", "content": prompt}]
    async for chunk in doubao_client.chat_stream(messages, temperature=0.3):
        yield chunk


async def chat_modify_stream(
    current_latex: str,
    chat_history: list[dict],
    user_message: str,
) -> AsyncGenerator[str, None]:
    """Stream modify LaTeX based on chat instructions."""
    prompt = _render_prompt(
        "chat_modification.j2",
        current_latex=current_latex,
        chat_history=chat_history,
        user_message=user_message,
    )
    messages = [{"role": "user", "content": prompt}]
    async for chunk in doubao_client.chat_stream(messages, temperature=0.5):
        yield chunk


def _split_into_chunks(content: str, max_chars: int = 12000) -> list[str]:
    """Split content into chunks at paragraph boundaries, each ≤ max_chars."""
    if len(content) <= max_chars:
        return [content]

    chunks: list[str] = []
    remaining = content
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        # Find the last paragraph break within the limit
        split_pos = remaining.rfind("\n\n", 0, max_chars)
        if split_pos == -1:
            # No paragraph break found; try single newline
            split_pos = remaining.rfind("\n", 0, max_chars)
        if split_pos == -1:
            # No newline at all; hard cut at max_chars
            split_pos = max_chars
        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:].lstrip("\n")
    return chunks


async def _analyze_chunk(
    filename: str, chunk: str, chunk_index: int, total_chunks: int
) -> dict:
    """Analyze a single chunk of a document using the same LLM prompt."""
    prompt = _render_prompt(
        "document_analysis.j2",
        filename=filename,
        content=chunk,
        doc_index=chunk_index,
        total_docs=total_chunks,
    )
    messages = [{"role": "user", "content": prompt}]
    response = await doubao_client.chat(messages, temperature=0.2, max_tokens=8192)
    result = extract_json(response)
    if not result:
        result = {
            "title": filename,
            "authors": [],
            "type": "其他",
            "key_topics": [],
            "sections": [{"heading": "全文", "summary": chunk[:500], "key_points": []}],
            "abstract": chunk[:300],
            "references": [],
            "importance": "中",
        }
    return result


def _merge_chunk_analyses(chunk_results: list, filename: str) -> dict:
    """Merge analysis results from multiple chunks into a single analysis."""
    # Filter out exceptions
    valid: list[dict] = []
    for r in chunk_results:
        if isinstance(r, Exception):
            logger.warning("Chunk analysis failed for %s: %s", filename, r)
        elif isinstance(r, dict):
            valid.append(r)

    if not valid:
        return {
            "title": filename,
            "authors": [],
            "type": "其他",
            "key_topics": [],
            "sections": [{"heading": "全文", "summary": "", "key_points": []}],
            "abstract": "",
            "references": [],
            "importance": "中",
        }

    # Merge sections in order
    all_sections: list[dict] = []
    for v in valid:
        all_sections.extend(v.get("sections", []))

    # Deduplicate key_topics while preserving order
    seen_topics: set[str] = set()
    merged_topics: list[str] = []
    for v in valid:
        for topic in v.get("key_topics", []):
            if topic not in seen_topics:
                seen_topics.add(topic)
                merged_topics.append(topic)

    # Deduplicate references
    seen_refs: set[str] = set()
    merged_refs: list[str] = []
    for v in valid:
        for ref in v.get("references", []):
            ref_str = ref if isinstance(ref, str) else str(ref)
            if ref_str not in seen_refs:
                seen_refs.add(ref_str)
                merged_refs.append(ref)

    # Title / authors / type: first non-empty
    title = filename
    authors: list[str] = []
    doc_type = "其他"
    for v in valid:
        if v.get("title") and title == filename:
            title = v["title"]
        if v.get("authors") and not authors:
            authors = v["authors"]
        if v.get("type") and v["type"] != "其他" and doc_type == "其他":
            doc_type = v["type"]

    # Abstract: concatenate, cap at 500 chars
    abstract_parts = [v.get("abstract", "") for v in valid if v.get("abstract")]
    merged_abstract = " ".join(abstract_parts)[:500]

    # Importance: take the highest
    importance_order = {"高": 3, "中": 2, "低": 1}
    best_importance = "中"
    best_score = 0
    for v in valid:
        score = importance_order.get(v.get("importance", "中"), 2)
        if score > best_score:
            best_score = score
            best_importance = v.get("importance", "中")

    return {
        "title": title,
        "authors": authors,
        "type": doc_type,
        "key_topics": merged_topics,
        "sections": all_sections,
        "abstract": merged_abstract,
        "references": merged_refs,
        "importance": best_importance,
    }


async def analyze_document(
    filename: str, content: str, doc_index: int, total_docs: int
) -> dict:
    """Analyze a single document and extract structured info.

    For long documents (>12000 chars), splits into chunks, analyzes each
    concurrently, and merges the results so no content is lost.
    """
    chunks = _split_into_chunks(content, max_chars=12000)

    if len(chunks) == 1:
        # Short document: single-pass analysis (original path)
        return await _analyze_chunk(filename, chunks[0], doc_index, total_docs)

    # Long document: concurrent chunk analysis
    logger.info(
        "Document '%s' split into %d chunks for analysis", filename, len(chunks)
    )
    tasks = [
        _analyze_chunk(filename, chunk, i + 1, len(chunks))
        for i, chunk in enumerate(chunks)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return _merge_chunk_analyses(list(results), filename)


async def plan_outline(analyses: list[dict], template_id: str) -> dict:
    """Plan document outline from all document analyses."""
    prompt = _render_prompt(
        "outline_planning.j2",
        analyses=analyses,
        total_docs=len(analyses),
        template_id=template_id,
    )
    messages = [{"role": "user", "content": prompt}]
    response = await doubao_client.chat(messages, temperature=0.3, max_tokens=4096)
    result = extract_json(response)
    if not result or "chapters" not in result:
        # Fallback: single chapter with all docs
        result = {
            "title": analyses[0].get("title", "综合文档") if analyses else "综合文档",
            "author": "",
            "abstract": "",
            "chapters": [
                {
                    "chapter_id": 1,
                    "title": "主要内容",
                    "description": "所有文档内容整合",
                    "source_docs": list(range(1, len(analyses) + 1)),
                    "subsections": [],
                }
            ],
            "appendices": [],
        }
    return result


async def generate_chapter_stream(
    doc_title: str,
    chapter: dict,
    chapter_index: int,
    total_chapters: int,
    source_documents: list[dict],
    template_rules: str = "",
    section_commands: dict | None = None,
) -> AsyncGenerator[str, None]:
    """Stream generate LaTeX for a single chapter."""
    if section_commands is None:
        section_commands = {
            "top": r"\section",
            "second": r"\subsection",
            "third": r"\subsubsection",
            "fourth": r"\paragraph",
        }
    prompt = _render_prompt(
        "chapter_generation.j2",
        doc_title=doc_title,
        chapter=chapter,
        chapter_index=chapter_index,
        total_chapters=total_chapters,
        source_documents=source_documents,
        template_rules=template_rules,
        section_commands=section_commands,
    )
    messages = [{"role": "user", "content": prompt}]
    async for chunk in doubao_client.chat_stream(messages, temperature=0.3):
        yield chunk


async def generate_chapter(
    doc_title: str,
    chapter: dict,
    chapter_index: int,
    total_chapters: int,
    source_documents: list[dict],
    template_rules: str = "",
    section_commands: dict | None = None,
) -> str:
    """Non-streaming chapter generation (for parallel execution)."""
    content = ""
    async for chunk in generate_chapter_stream(
        doc_title, chapter, chapter_index, total_chapters, source_documents,
        template_rules=template_rules,
        section_commands=section_commands,
    ):
        content += chunk
    return content


async def fix_latex_errors(
    latex_content: str,
    errors: str,
) -> str:
    """Use LLM to fix LaTeX compilation errors."""
    prompt = _render_prompt(
        "fix_errors.j2",
        latex_content=latex_content,
        errors=errors,
    )
    messages = [{"role": "user", "content": prompt}]
    response = await doubao_client.chat(messages, temperature=0.2)
    return extract_latex(response)


async def fix_chapter_latex_errors(
    chapter_content: str,
    errors: str,
) -> str:
    """Use LLM to fix LaTeX errors in a chapter fragment (not a full document)."""
    prompt = _render_prompt(
        "fix_chapter_errors.j2",
        chapter_content=chapter_content,
        errors=errors,
    )
    messages = [{"role": "user", "content": prompt}]
    response = await doubao_client.chat(messages, temperature=0.2)
    return extract_latex(response)


async def extract_format_requirements(
    doc_text: str,
    formatting_metadata: dict,
) -> str:
    """Extract formatting requirements from document content and metadata.
    Uses streaming internally to avoid timeout with thinking models."""
    prompt = _render_prompt(
        "extract_format.j2",
        doc_text=doc_text,
        formatting=formatting_metadata,
    )
    messages = [{"role": "user", "content": prompt}]
    result = ""
    async for chunk in doubao_client.chat_stream(messages, temperature=0.2):
        result += chunk
    return result


async def generate_template_stream(
    description: str,
) -> AsyncGenerator[str, None]:
    """Stream generate a LaTeX template from a description."""
    prompt = _render_prompt(
        "template_generation.j2",
        description=description,
    )
    messages = [{"role": "user", "content": prompt}]
    async for chunk in doubao_client.chat_stream(messages, temperature=0.3):
        yield chunk
