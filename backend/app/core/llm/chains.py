import json
from collections.abc import AsyncGenerator
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.core.llm.client import doubao_client
from app.core.llm.output_parsers import extract_json, extract_latex

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


async def analyze_document(
    filename: str, content: str, doc_index: int, total_docs: int
) -> dict:
    """Analyze a single document and extract structured info."""
    # Truncate very long documents to avoid token limits
    truncated = content[:15000] if len(content) > 15000 else content
    prompt = _render_prompt(
        "document_analysis.j2",
        filename=filename,
        content=truncated,
        doc_index=doc_index,
        total_docs=total_docs,
    )
    messages = [{"role": "user", "content": prompt}]
    response = await doubao_client.chat(messages, temperature=0.2)
    result = extract_json(response)
    if not result:
        # Fallback: create a minimal analysis
        result = {
            "title": filename,
            "authors": [],
            "type": "其他",
            "key_topics": [],
            "sections": [{"heading": "全文", "summary": truncated[:500], "key_points": []}],
            "abstract": truncated[:300],
            "references": [],
            "importance": "中",
        }
    return result


async def plan_outline(analyses: list[dict], template_id: str) -> dict:
    """Plan document outline from all document analyses."""
    prompt = _render_prompt(
        "outline_planning.j2",
        analyses=analyses,
        total_docs=len(analyses),
        template_id=template_id,
    )
    messages = [{"role": "user", "content": prompt}]
    response = await doubao_client.chat(messages, temperature=0.3)
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
