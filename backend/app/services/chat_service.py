from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.agent import AgentEvent, run_agent_loop
from app.models.models import ChatMessage, Project
from app.services.project_service import update_project


async def get_chat_history(db: AsyncSession, project_id: str) -> list[dict]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.project_id == project_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()
    return [{"role": m.role, "content": m.content} for m in messages]


async def get_chat_messages(db: AsyncSession, project_id: str) -> list[ChatMessage]:
    """Return ChatMessage ORM objects for API serialization."""
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.project_id == project_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return list(result.scalars().all())


async def save_message(db: AsyncSession, project_id: str, role: str, content: str) -> ChatMessage:
    msg = ChatMessage(project_id=project_id, role=role, content=content)
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def chat_modify_latex(
    db: AsyncSession,
    project: Project,
    user_message: str,
) -> AsyncGenerator[AgentEvent, None]:
    """Chat-based LaTeX modification via agent loop."""
    # Save user message
    await save_message(db, project.id, "user", user_message)

    # Get chat history (excluding the message we just saved — it's passed separately)
    history = await get_chat_history(db, project.id)
    # history now includes the user message we just saved as the last item; exclude it
    previous_history = history[:-1]

    current_latex = project.latex_content or ""

    # Run agent loop and forward events
    full_content = ""
    async for event in run_agent_loop(current_latex, previous_history, user_message):
        if event.type == "content":
            full_content += event.data
        elif event.type == "latex":
            # Persist the updated LaTeX to the project
            await update_project(db, project, latex_content=event.data)
        yield event

    # Save assistant response
    if full_content:
        await save_message(db, project.id, "assistant", full_content)
