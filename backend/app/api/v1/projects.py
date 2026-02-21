from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.schemas import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectList,
)
from app.dependencies import get_db, get_project
from app.models.models import Project
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
):
    project = await project_service.create_project(
        db, name=data.name, description=data.description, template_id=data.template_id
    )
    return project


@router.get("", response_model=ProjectList)
async def list_projects(db: AsyncSession = Depends(get_db)):
    projects, total = await project_service.list_projects(db)
    return ProjectList(projects=projects, total=total)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_detail(project: Project = Depends(get_project)):
    return project


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    data: ProjectUpdate,
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    updated = await project_service.update_project(
        db,
        project,
        name=data.name,
        description=data.description,
        template_id=data.template_id,
        latex_content=data.latex_content,
    )
    return updated


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project: Project = Depends(get_project),
    db: AsyncSession = Depends(get_db),
):
    await project_service.delete_project(db, project)
