import logging

import httpx
from fastapi import APIRouter
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy import select

from app.api.schemas.schemas import LLMConfigResponse, LLMConfigUpdate
from app.core.llm.client import doubao_client, get_llm_config, refresh_llm_config
from app.models.database import async_session
from app.models.models import LLMConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class LLMTestResponse(BaseModel):
    success: bool
    message: str


def _mask_api_key(key: str) -> str:
    """Mask API key for display, e.g. 'sk-abc...xyzw' → 'sk-****xyzw'."""
    if not key or len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


@router.get("/llm", response_model=LLMConfigResponse)
async def get_llm_settings():
    """Return current LLM configuration (API key is masked)."""
    cfg = await get_llm_config()
    return LLMConfigResponse(
        api_key_masked=_mask_api_key(cfg["api_key"]),
        base_url=cfg["base_url"],
        model=cfg["model"],
        updated_at=cfg["updated_at"],
    )


@router.put("/llm", response_model=LLMConfigResponse)
async def update_llm_settings(body: LLMConfigUpdate):
    """Update LLM configuration. Only non-null fields are updated."""
    async with async_session() as session:
        result = await session.execute(select(LLMConfig).where(LLMConfig.id == 1))
        row = result.scalar_one_or_none()
        if not row:
            row = LLMConfig(id=1)
            session.add(row)

        if body.api_key is not None:
            row.api_key = body.api_key
        if body.base_url is not None:
            row.base_url = body.base_url
        if body.model is not None:
            row.model = body.model

        await session.commit()
        await session.refresh(row)

        refresh_llm_config()
        doubao_client.reconfigure(row.api_key, row.base_url, row.model)

        return LLMConfigResponse(
            api_key_masked=_mask_api_key(row.api_key),
            base_url=row.base_url,
            model=row.model,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_connection(body: LLMConfigUpdate):
    """Test connectivity with the given (or current saved) LLM configuration."""
    cfg = await get_llm_config()

    api_key = body.api_key if body.api_key is not None else cfg["api_key"]
    base_url = body.base_url if body.base_url is not None else cfg["base_url"]
    model = body.model if body.model is not None else cfg["model"]

    try:
        async with AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=httpx.Timeout(15.0, connect=5.0),
            max_retries=0,
        ) as client:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            if resp.choices:
                return LLMTestResponse(success=True, message="连接成功")
            return LLMTestResponse(success=False, message="模型返回空结果")
    except Exception as e:
        logger.warning("LLM connection test failed: %s", e)
        # Only expose the exception type, not the full message
        # (which may contain API keys or internal URLs)
        err_type = type(e).__name__
        return LLMTestResponse(success=False, message=f"连接失败 ({err_type})")
