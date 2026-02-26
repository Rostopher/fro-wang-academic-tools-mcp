"""Unified async LLM client (OpenAI-compatible, defaults to DeepSeek)."""

from __future__ import annotations

import json
from typing import Any, Optional, Type, TypeVar

import json_repair
from openai import AsyncOpenAI
from pydantic import BaseModel

from ..config import settings
from .prompt_utils import extract_json_from_response

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """
    Thin wrapper around AsyncOpenAI that provides two helpers:

    - ``get_json()``  → parse LLM response as a raw Python object
    - ``get_model()`` → parse LLM response into a Pydantic model
    - ``translate()`` → returns plain string (no JSON parsing)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._model = model or settings.LLM_MODEL
        self._client = AsyncOpenAI(
            api_key=api_key or settings.LLM_API_KEY,
            base_url=base_url or settings.LLM_BASE_URL,
        )

    async def _complete(
        self,
        user: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        kwargs: dict[str, Any] = {"model": model or self._model, "messages": messages}
        if temperature is not None:
            kwargs["temperature"] = temperature

        resp = await self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    async def get_json(
        self,
        user: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        """Call LLM and parse response as JSON (dict or list)."""
        content = await self._complete(user=user, system=system, model=model, temperature=temperature)
        raw = extract_json_from_response(content)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return json_repair.loads(raw)

    async def get_model(
        self,
        user: str,
        response_model: Type[T],
        system: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> T:
        """Call LLM and validate response into a Pydantic model."""
        data = await self.get_json(user=user, system=system, model=model, temperature=temperature)
        return response_model.model_validate(data)

    async def translate(
        self,
        user: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Call LLM and return plain text (no JSON parsing)."""
        return await self._complete(user=user, system=system, model=model, temperature=temperature)


# Module-level singleton — use this in tools unless you need custom params
_default_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Return the singleton LLM client (lazily initialized)."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
