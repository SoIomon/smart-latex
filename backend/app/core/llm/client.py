from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion

from app.config import settings


class DoubaoClient:
    """OpenAI-compatible LLM client with runtime reconfiguration support."""

    def __init__(self):
        self._client = AsyncOpenAI(
            api_key=settings.DOUBAO_API_KEY,
            base_url=settings.DOUBAO_BASE_URL,
            timeout=httpx.Timeout(180.0, connect=10.0),
            max_retries=2,
        )
        self._model = settings.DOUBAO_MODEL

    def reconfigure(self, api_key: str, base_url: str, model: str):
        """Rebuild internal client with new configuration."""
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=httpx.Timeout(180.0, connect=10.0),
            max_retries=2,
        )
        self._model = model

    async def chat(self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 16384) -> str:
        """Non-streaming chat completion."""
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not response.choices:
            return ""
        return response.choices[0].message.content or ""

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.5,
        max_tokens: int = 16384,
    ) -> ChatCompletion:
        """Non-streaming chat completion with function calling.

        Returns the full ChatCompletion object so the caller can inspect
        tool_calls on the response message.
        """
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response

    async def chat_stream(
        self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 16384
    ) -> AsyncGenerator[str, None]:
        """Streaming chat completion, yields content chunks."""
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content


doubao_client = DoubaoClient()


# ---------------------------------------------------------------------------
# LLM configuration cache
#
# Imports for DB access are deferred to avoid circular imports at module load
# time (database.py → config.py → settings, while client.py is imported by
# route modules that also depend on database.py).
# ---------------------------------------------------------------------------
_llm_config_cache: dict | None = None


async def get_llm_config() -> dict:
    """Return current LLM config, reading from DB on first call."""
    global _llm_config_cache
    if _llm_config_cache is not None:
        return _llm_config_cache

    from app.models.database import async_session  # noqa: E402 — deferred to break circular import
    from app.models.models import LLMConfig
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(LLMConfig).where(LLMConfig.id == 1))
        row = result.scalar_one_or_none()
        if row:
            _llm_config_cache = {
                "api_key": row.api_key,
                "base_url": row.base_url,
                "model": row.model,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        else:
            _llm_config_cache = {
                "api_key": settings.DOUBAO_API_KEY,
                "base_url": settings.DOUBAO_BASE_URL,
                "model": settings.DOUBAO_MODEL,
                "updated_at": None,
            }
    return _llm_config_cache


def refresh_llm_config():
    """Invalidate cache so next get_llm_config() re-reads from DB."""
    global _llm_config_cache
    _llm_config_cache = None
