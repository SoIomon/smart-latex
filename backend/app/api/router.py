from fastapi import APIRouter

from app.api.v1.projects import router as projects_router
from app.api.v1.documents import router as documents_router
from app.api.v1.templates import router as templates_router
from app.api.v1.generation import router as generation_router
from app.api.v1.chat import router as chat_router
from app.api.v1.compiler import router as compiler_router
from app.api.v1.selection import router as selection_router
from app.api.v1.settings import router as settings_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(projects_router)
api_router.include_router(documents_router)
api_router.include_router(templates_router)
api_router.include_router(generation_router)
api_router.include_router(chat_router)
api_router.include_router(compiler_router)
api_router.include_router(selection_router)
api_router.include_router(settings_router)
