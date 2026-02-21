import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.schemas.schemas import ChatRequest, ChatMessageResponse
from app.dependencies import get_db, get_project
from app.models.models import Project
from app.services.chat_service import chat_modify_latex, get_chat_messages

router = APIRouter(tags=["chat"])


# Mapping from AgentEvent.type to SSE event name and data builder
def _sse_from_agent_event(event) -> dict:
    if event.type == "thinking":
        return {"event": "thinking", "data": json.dumps({"message": event.data})}
    elif event.type == "tool_call":
        return {"event": "tool_call", "data": json.dumps({"tool": event.data})}
    elif event.type == "tool_result":
        return {"event": "tool_result", "data": json.dumps({"tool": event.data})}
    elif event.type == "content":
        return {"event": "chunk", "data": json.dumps({"content": event.data})}
    elif event.type == "latex":
        return {"event": "latex", "data": json.dumps({"content": event.data})}
    elif event.type == "done":
        return {"event": "done", "data": json.dumps({"content": ""})}
    elif event.type == "error":
        return {"event": "error", "data": json.dumps({"error": event.data})}
    # fallback
    return {"event": event.type, "data": json.dumps({"data": event.data})}


@router.post("/projects/{project_id}/chat")
async def chat(
    data: ChatRequest,
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    if not project.latex_content:
        raise HTTPException(
            status_code=400,
            detail="No LaTeX content in project. Generate LaTeX first.",
        )

    async def event_stream():
        try:
            async for agent_event in chat_modify_latex(db, project, data.message):
                yield _sse_from_agent_event(agent_event)

        except Exception as e:
            yield {"event": "error", "data": json.dumps({"error": str(e)})}

    return EventSourceResponse(event_stream())


@router.get("/projects/{project_id}/chat/history", response_model=list[ChatMessageResponse])
async def get_history(
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    return await get_chat_messages(db, project.id)
