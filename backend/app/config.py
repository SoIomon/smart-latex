from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DOUBAO_API_KEY: str = ""
    DOUBAO_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    DOUBAO_MODEL: str = "doubao-pro-32k"

    DATABASE_URL: str = "sqlite+aiosqlite:///./storage/smart_latex.db"
    STORAGE_DIR: str = "./storage"
    LATEX_CMD: str = "latexmk"

    CJK_FONTSET: str = "mac"  # mac / windows / linux

    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    LOG_LEVEL: str = "DEBUG"
    LOG_FILE: str = "logs/smart_latex.log"

    @property
    def storage_path(self) -> Path:
        path = Path(self.STORAGE_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
