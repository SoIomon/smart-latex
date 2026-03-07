from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

# Anchor paths to backend/ so they're stable regardless of working directory.
_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    DOUBAO_API_KEY: str = ""
    DOUBAO_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    DOUBAO_MODEL: str = "doubao-pro-32k"

    DATABASE_URL: str = "sqlite+aiosqlite:///./storage/smart_latex.db"
    STORAGE_DIR: str = "./storage"
    LATEX_CMD: str = "latexmk"

    CJK_FONTSET: str = "auto"  # auto / mac / windows / linux

    CORS_ORIGINS: list[str] = ["http://localhost:15173", "http://127.0.0.1:15173"]

    LOG_LEVEL: str = "DEBUG"
    LOG_FILE: str = "logs/smart_latex.log"

    @model_validator(mode="after")
    def _resolve_relative_paths(self) -> "Settings":
        """Resolve relative STORAGE_DIR / DATABASE_URL / LOG_FILE to backend/ directory."""
        storage = Path(self.STORAGE_DIR)
        if not storage.is_absolute():
            self.STORAGE_DIR = str(_BACKEND_DIR / storage)

        prefix = "sqlite+aiosqlite:///"
        if self.DATABASE_URL.startswith(prefix):
            db_path = Path(self.DATABASE_URL[len(prefix):])
            if not db_path.is_absolute():
                self.DATABASE_URL = prefix + str(_BACKEND_DIR / db_path)

        log_path = Path(self.LOG_FILE)
        if not log_path.is_absolute():
            self.LOG_FILE = str(_BACKEND_DIR / log_path)

        return self

    @property
    def storage_path(self) -> Path:
        path = Path(self.STORAGE_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
