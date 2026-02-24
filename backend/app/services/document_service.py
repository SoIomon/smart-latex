import asyncio
import base64
import logging
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.parsers.registry import ParserRegistry
from app.models.models import Document

logger = logging.getLogger(__name__)


def _enrich_text_with_descriptions(
    parsed_text: str,
    images: list[dict],
    descriptions: dict[str, str],
) -> str:
    """Replace basic image placeholders with description-enriched versions."""
    for img in images:
        if img.get("dedup") or img.get("skipped"):
            continue
        desc = descriptions.get(img["filename"], "")
        if desc:
            fn = img["filename"]
            # Handle both formats:
            #   [IMAGE: figure_001.png, width=12.5cm] → has comma
            #   [IMAGE: figure_001.png]               → no comma (no width)
            old_with_comma = f"[IMAGE: {fn},"
            old_no_comma = f"[IMAGE: {fn}]"
            if old_with_comma in parsed_text:
                parsed_text = parsed_text.replace(
                    old_with_comma,
                    f"[IMAGE: {fn}, 描述: {desc},",
                )
            elif old_no_comma in parsed_text:
                parsed_text = parsed_text.replace(
                    old_no_comma,
                    f"[IMAGE: {fn}, 描述: {desc}]",
                )
    return parsed_text


def _is_vision_unsupported_error(e: Exception) -> bool:
    """Check if an LLM error indicates the model doesn't support image input."""
    err_str = str(e).lower()
    return any(kw in err_str for kw in [
        "not support image", "image_url", "do not support image",
    ])


async def _describe_from_context(filename: str, parsed_text: str) -> str:
    """Fallback: infer image description from surrounding text context."""
    if not parsed_text:
        return ""

    from app.core.llm.client import doubao_client

    idx = parsed_text.find(f"[IMAGE: {filename}")
    if idx == -1:
        return ""

    start = max(0, idx - 300)
    end = min(len(parsed_text), idx + 300)
    context = parsed_text[start:end]

    messages = [{"role": "user", "content": (
        f"以下是一段文档内容，其中包含一个图片占位符 [IMAGE: {filename}]。"
        f"请根据上下文推断这张图片可能展示的内容，用一句简短的中文描述（不超过30字）。"
        f"如果无法推断，请回复「文档插图」。\n\n"
        f"文档片段：\n{context}"
    )}]
    try:
        desc = await doubao_client.chat(messages, temperature=0.3, max_tokens=100)
        return desc.strip()
    except Exception as e:
        logger.warning("Context-based image description failed for %s: %s", filename, e)
        return ""


async def _describe_images(
    images: list[dict], parsed_text: str = "",
) -> dict[str, str]:
    """调用视觉模型为每张图片生成简短中文描述。

    当模型不支持图片输入时，自动降级为基于上下文的文本推断。
    """
    from app.core.llm.client import doubao_client

    describable = [img for img in images if img.get("data")]
    if not describable:
        return {}

    _VISION_PROMPT = (
        "请用一句简短的中文描述这张图片的内容（不超过50字），"
        "重点说明：图表类型、展示的数据/内容、关键数值或结论。"
    )

    descriptions: dict[str, str] = {}
    use_vision = True

    # Probe vision support with the first image
    first = describable[0]
    try:
        b64 = base64.b64encode(first["data"]).decode()
        mime = first["content_type"]
        messages = [{"role": "user", "content": [
            {"type": "text", "text": _VISION_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        ]}]
        desc = await doubao_client.chat(messages, temperature=0.3, max_tokens=200)
        descriptions[first["filename"]] = desc.strip()
    except Exception as e:
        if _is_vision_unsupported_error(e):
            logger.warning("模型不支持图片输入，将降级为上下文推断: %s", e)
            use_vision = False
            descriptions[first["filename"]] = await _describe_from_context(
                first["filename"], parsed_text,
            )
        else:
            logger.warning("Failed to describe image %s: %s", first["filename"], e)
            descriptions[first["filename"]] = ""

    # Process remaining images
    remaining = describable[1:]
    if not remaining:
        return descriptions

    async def _do_one(img: dict) -> tuple[str, str]:
        if use_vision:
            b64 = base64.b64encode(img["data"]).decode()
            mime = img["content_type"]
            messages = [{"role": "user", "content": [
                {"type": "text", "text": _VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}]
            try:
                desc = await doubao_client.chat(messages, temperature=0.3, max_tokens=200)
                return img["filename"], desc.strip()
            except Exception as e:
                logger.warning("Failed to describe image %s: %s", img["filename"], e)
                return img["filename"], ""
        else:
            desc = await _describe_from_context(img["filename"], parsed_text)
            return img["filename"], desc

    results = await asyncio.gather(*[_do_one(img) for img in remaining])
    for filename, desc in results:
        descriptions[filename] = desc

    return descriptions


async def upload_document(
    db: AsyncSession,
    project_id: str,
    file: UploadFile,
) -> Document:
    original_name = file.filename or "unknown"
    ext = Path(original_name).suffix.lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"

    # Save file to storage
    doc_dir = settings.storage_path / project_id / "documents"
    doc_dir.mkdir(parents=True, exist_ok=True)
    file_path = doc_dir / unique_name

    content = await file.read()
    file_path.write_bytes(content)

    # Parse content
    parsed_text = ""
    parser = ParserRegistry.get_parser(ext)
    if parser:
        parsed = await parser.parse(file_path)
        parsed_text = parsed.text

        if parsed.images:
            # Save image files to disk
            images_dir = settings.storage_path / project_id / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            for img in parsed.images:
                if img.get("data") and not img.get("dedup"):
                    (images_dir / img["filename"]).write_bytes(img["data"])

            # Describe all images concurrently, enrich placeholders
            try:
                descriptions = await _describe_images(parsed.images, parsed_text=parsed_text)
            except Exception as e:
                logger.warning("Image description failed: %s", e)
                descriptions = {}
            parsed_text = _enrich_text_with_descriptions(
                parsed_text, parsed.images, descriptions,
            )

    doc = Document(
        project_id=project_id,
        filename=unique_name,
        original_name=original_name,
        file_type=ext,
        parsed_content=parsed_text,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def list_documents(db: AsyncSession, project_id: str) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def get_document(db: AsyncSession, document_id: str) -> Document | None:
    result = await db.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def delete_document(db: AsyncSession, document: Document) -> None:
    # Remove file from storage
    file_path = settings.storage_path / document.project_id / "documents" / document.filename
    if file_path.exists():
        file_path.unlink()
    await db.delete(document)
    await db.commit()
