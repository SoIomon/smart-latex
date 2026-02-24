import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.schemas.schemas import EditSelectionRequest
from app.core.llm.chains import edit_selection_stream
from app.core.llm.output_parsers import extract_latex
from app.dependencies import get_db, get_project
from app.models.models import Project

router = APIRouter(tags=["selection"])


@router.post("/projects/{project_id}/edit-selection")
async def edit_selection(
    data: EditSelectionRequest,
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    async def event_stream():
        full_response = ""
        try:
            async for chunk in edit_selection_stream(
                full_latex=data.full_latex,
                selected_text=data.selected_text,
                instruction=data.instruction,
            ):
                full_response += chunk
                yield {"event": "chunk", "data": json.dumps({"content": chunk})}

            # Strip markdown code-block wrappers (```latex ... ```) if present
            cleaned = extract_latex(full_response)
            yield {"event": "done", "data": json.dumps({"content": cleaned})}

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_stream())
