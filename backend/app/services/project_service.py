import datetime
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Project


async def create_project(db: AsyncSession, name: str, description: str = "", template_id: str = "") -> Project:
    project = Project(name=name, description=description, template_id=template_id)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def list_projects(db: AsyncSession) -> tuple[list[Project], int]:
    result = await db.execute(select(Project).order_by(Project.updated_at.desc()))
    projects = list(result.scalars().all())
    return projects, len(projects)


async def get_project(db: AsyncSession, project_id: str) -> Project | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def update_project(db: AsyncSession, project: Project, **kwargs) -> Project:
    for key, value in kwargs.items():
        if value is not None and hasattr(project, key):
            setattr(project, key, value)
    project.updated_at = datetime.datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(project)
    return project


async def delete_project(db: AsyncSession, project: Project) -> None:
    await db.delete(project)
    await db.commit()
