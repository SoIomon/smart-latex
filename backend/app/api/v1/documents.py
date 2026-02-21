from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.schemas import DocumentResponse
from app.core.parsers.registry import ParserRegistry
from app.dependencies import get_db, get_project
from app.models.models import Project
from app.services import document_service

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])


MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    supported = ParserRegistry.supported_extensions()
    if ext not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {supported}",
        )

    # Check file size by reading content (the service will re-read via file object)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Max 50MB.")
    # Seek back so service layer can read the file
    await file.seek(0)

    doc = await document_service.upload_document(db, project.id, file)
    return doc


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    return await document_service.list_documents(db, project.id)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.get_document(db, document_id)
    if not doc or doc.project_id != project.id:
        raise HTTPException(status_code=404, detail="Document not found")
    await document_service.delete_document(db, doc)
