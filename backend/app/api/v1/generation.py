import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.schemas.schemas import GenerateRequest
from app.dependencies import get_db, get_project
from app.models.models import Project
from app.core.llm.output_parsers import extract_latex
from app.services.generation_service import (
    generate_latex_from_documents,
    generate_latex_pipeline,
)
from app.services import project_service

router = APIRouter(tags=["generation"])


@router.post("/projects/{project_id}/generate")
async def generate_latex(
    data: GenerateRequest,
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    """Generate LaTeX with pipeline (progress events for multi-doc, simple for few docs)."""
    template_id = data.template_id or "academic_paper"

    async def event_stream():
        full_content = ""
        try:
            async for event in generate_latex_pipeline(
                db, project.id, template_id, data.document_ids
            ):
                evt_type = event.get("event", "")

                if evt_type == "stage":
                    yield {
                        "event": "stage",
                        "data": json.dumps({
                            "stage": event.get("stage"),
                            "message": event.get("message"),
                            "progress": event.get("progress", 0),
                            "detail": event.get("detail", ""),
                        }),
                    }

                elif evt_type == "outline":
                    yield {
                        "event": "outline",
                        "data": json.dumps({
                            "message": event.get("message"),
                            "outline": event.get("outline"),
                        }),
                    }

                elif evt_type == "chunk":
                    content = event.get("content", "")
                    full_content += content
                    yield {
                        "event": "chunk",
                        "data": json.dumps({"content": content}),
                    }

                elif evt_type == "done":
                    cleaned = event.get("content", extract_latex(full_content))
                    await project_service.update_project(
                        db, project, latex_content=cleaned, template_id=template_id
                    )
                    yield {
                        "event": "done",
                        "data": json.dumps({
                            "content": cleaned,
                            "message": event.get("message", ""),
                        }),
                    }

                elif evt_type == "error":
                    yield {
                        "event": "error",
                        "data": json.dumps({"error": event.get("message", "Unknown error")}),
                    }

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_stream())
