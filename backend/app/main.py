import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import settings
from app.models.database import init_db, close_db


def _setup_logging() -> None:
    """Configure root logger with console + rotating file handlers.

    Guarded against duplicate handlers on uvicorn --reload.
    """
    root = logging.getLogger()

    # Prevent duplicate handlers when module is re-imported (uvicorn --reload)
    if getattr(root, "_smart_latex_configured", False):
        return
    root._smart_latex_configured = True  # type: ignore[attr-defined]

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root.setLevel(level)

    # Console handler (respects uvicorn's own output)
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    # File handler — rotate at 5 MB, keep 3 backups
    log_path = Path(settings.LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_h = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    file_h.setLevel(level)
    file_h.setFormatter(fmt)
    root.addHandler(file_h)

    # Quiet noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


_setup_logging()

logger = logging.getLogger(__name__)

# Frontend build directory (relative to backend/)
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    # Initialize LLM config from DB (or seed from .env on first run).
    # Imports are deferred to avoid circular dependency at module load time.
    from sqlalchemy import select                          # noqa: E402
    from app.models.database import async_session          # noqa: E402
    from app.models.models import LLMConfig                # noqa: E402
    from app.core.llm.client import doubao_client, refresh_llm_config  # noqa: E402

    async with async_session() as session:
        result = await session.execute(select(LLMConfig).where(LLMConfig.id == 1))
        row = result.scalar_one_or_none()
        if not row:
            row = LLMConfig(
                id=1,
                api_key=settings.DOUBAO_API_KEY,
                base_url=settings.DOUBAO_BASE_URL,
                model=settings.DOUBAO_MODEL,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            logger.info("LLM config seeded from .env")

        doubao_client.reconfigure(row.api_key, row.base_url, row.model)
        refresh_llm_config()
        logger.info("LLM client configured: base_url=%s model=%s", row.base_url, row.model)

    yield
    await close_db()


app = FastAPI(
    title="Smart-LaTeX API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Only serve specific static subdirectories — never expose the entire storage dir
# (which contains the SQLite DB and other sensitive files)
# PDF files are served via the /api/v1/projects/{id}/pdf endpoint instead.

# Production mode: serve frontend build if dist/ exists
if FRONTEND_DIST.is_dir():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(request: Request, full_path: str):
        """Serve frontend SPA - all non-API routes return index.html."""
        resolved_base = FRONTEND_DIST.resolve()
        file_path = (FRONTEND_DIST / full_path).resolve()
        # Path traversal guard: ensure resolved path is within FRONTEND_DIST
        if full_path and file_path.is_file() and str(file_path).startswith(str(resolved_base)):
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIST / "index.html"))


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
