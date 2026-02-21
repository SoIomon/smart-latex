import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.parsers.registry import ParserRegistry
from app.models.models import Document


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
