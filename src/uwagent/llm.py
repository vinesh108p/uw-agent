"""Thin wrapper over the Anthropic SDK so the rest of the code (and tests) depend on a two-method protocol."""

from __future__ import annotations

from typing import Any, Protocol

import anthropic
from pydantic import BaseModel

from .config import Settings

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLM(Protocol):
    def create(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], effort: str = "low") -> Any: ...

    def parse(self, *, system: str, user: str, output_format: type[BaseModel]) -> BaseModel | None: ...


class AnthropicLLM:
    def __init__(self, model: str, client: Any | None = None):
        self.model = model
        self.client = client if client is not None else anthropic.Anthropic()

    def create(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], effort: str = "low") -> Any:
        # Agent turns: cached system prompt, low effort, server-side refusal fallback. Never force tool_choice on Opus 5.5.
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            tools=tools,
            output_config={"effort": effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )

    def parse(self, *, system: str, user: str, output_format: type[BaseModel]) -> BaseModel | None:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
        )
        if response.stop_reason == "refusal":
            return None
        return response.parsed_output


def make_llm(settings: Settings) -> LLM | None:
    return AnthropicLLM(settings.model) if settings.live_llm else None
