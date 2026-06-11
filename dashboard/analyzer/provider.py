"""AI provider abstractions for live segment analysis."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx

from dashboard.analyzer.prompts import CLAUDE_TOOL, SYSTEM_PROMPT, ollama_system_prompt
from dashboard.analyzer.sentiment import clamp_sentiment
from dashboard.config import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AnalysisContext:
    recording: dict[str, Any]
    segment: dict[str, Any]
    participants: list[dict[str, Any]]
    topics: list[dict[str, Any]]
    goals: list[dict[str, Any]]
    agenda_items: list[dict[str, Any]]
    recent_segments: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, default=str)


AnalysisResult = dict[str, Any]


class AIProvider(Protocol):
    async def analyze(self, context: AnalysisContext) -> AnalysisResult:
        ...


def _normalize_result(data: dict[str, Any]) -> AnalysisResult:
    return {
        "sentiment": clamp_sentiment(data.get("sentiment")) or 0.0,
        "speaker": data.get("speaker"),
        "topic_tags": data.get("topic_tags") or [],
        "add_synonyms": data.get("add_synonyms") or [],
        "goal_updates": data.get("goal_updates") or [],
        "new_goals": data.get("new_goals") or [],
        "agenda": data.get("agenda"),
        "decisions": data.get("decisions") or [],
        "action_items": data.get("action_items") or [],
        "key_moments": data.get("key_moments") or [],
    }


class ClaudeProvider:
    def __init__(self, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def analyze(self, context: AnalysisContext) -> AnalysisResult:
        if not self.api_key:
            raise RuntimeError("Anthropic API key not configured")
        try:
            from anthropic import AsyncAnthropic
        except Exception as exc:
            raise RuntimeError("anthropic package not available") from exc

        client = AsyncAnthropic(api_key=self.api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=[CLAUDE_TOOL],
            tool_choice={"type": "tool", "name": CLAUDE_TOOL["name"]},
            messages=[{"role": "user", "content": context.to_json()}],
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == CLAUDE_TOOL["name"]:
                return _normalize_result(dict(block.input))
        raise RuntimeError("Claude response did not contain tool output")


class OllamaProvider:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def analyze(self, context: AnalysisContext) -> AnalysisResult:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": ollama_system_prompt()},
                        {"role": "user", "content": context.to_json()},
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
        message = payload.get("message", {}).get("content") or payload.get("response") or "{}"
        data = message if isinstance(message, dict) else json.loads(message)
        return _normalize_result(data)


def _should_fallback(exc: Exception) -> bool:
    name = exc.__class__.__name__
    if isinstance(exc, RuntimeError) and "Anthropic API key not configured" in str(exc):
        return True
    return name in {
        "APIConnectionError",
        "AuthenticationError",
        "PermissionDeniedError",
        "RateLimitError",
    }


class FallbackProvider:
    def __init__(self, primary: ClaudeProvider, fallback: OllamaProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    async def analyze(self, context: AnalysisContext) -> AnalysisResult:
        try:
            return await self.primary.analyze(context)
        except Exception as exc:
            if not _should_fallback(exc):
                raise
            logger.warning("Falling back to Ollama after Claude failure: %s", exc)
            return await self.fallback.analyze(context)


def build_provider(settings: Settings) -> AIProvider:
    provider = (settings.ai_provider or "auto").lower()
    claude = ClaudeProvider(settings.anthropic_api_key, settings.anthropic_model)
    ollama = OllamaProvider(settings.ollama_base_url, settings.ollama_model)
    if provider == "claude":
        return claude
    if provider == "ollama":
        return ollama
    return FallbackProvider(claude, ollama)
