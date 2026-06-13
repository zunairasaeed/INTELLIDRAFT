"""Real ``LLMClient`` backed by Groq (chat completions, JSON mode).

The router and editor agents call ``generate_json(prompt)`` and expect
a Python ``dict``. This client:

  1. Loads ``GROQ_API_KEY`` from ``.env`` (via ``python-dotenv``) or
     from process env.
  2. Lazily constructs a single ``groq.Groq`` client and reuses it.
  3. Calls ``chat.completions.create`` with ``response_format=json_object``
     and a system message instructing strict-JSON output.
  4. Parses ``response.choices[0].message.content`` as JSON and returns
     the dict. On parse failure, returns an ``unknown`` payload so the
     edit loop short-circuits cleanly instead of crashing.

The Groq SDK is synchronous; we wrap the call in ``asyncio.to_thread``
so the FastAPI event loop is not blocked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv missing
    load_dotenv = None  # type: ignore[assignment]

try:
    from groq import Groq
except ImportError:  # pragma: no cover - groq missing
    Groq = None  # type: ignore[assignment]

from .llm_client import LLMClient

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "You are a strict JSON-producing assistant for a LaTeX editor pipeline. "
    "Reply with a single JSON object only - no prose, no markdown, no code fences. "
    "Use only the keys requested by the user prompt. Unknown values must be null."
)


_UNKNOWN_FALLBACK: dict[str, Any] = {
    "intent": "unknown",
    "section_id": None,
    "after_id": None,
    "new_title": None,
    "depth": None,
    "instruction": None,
    "reasoning": "Groq response could not be parsed as JSON.",
    "new_text": "",
    "summary": "Groq response could not be parsed as JSON.",
    "require_citations": [],
    "require_labels": [],
}


class GroqLLMClient(LLMClient):
    """Production ``LLMClient`` implementation."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "llama-3.3-70b-versatile",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> None:
        if Groq is None:
            raise RuntimeError(
                "The 'groq' package is not installed. Install it with "
                "'pip install groq' or add it to requirements.txt."
            )

        if api_key is None and load_dotenv is not None:
            load_dotenv()
            api_key = os.environ.get("GROQ_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to your .env file or "
                "the process environment, or use StubLLMClient instead."
            )

        self._client = Groq(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    def _call_gpt(self, prompt: str) -> str:
        """Synchronous Groq call. Returns the raw assistant content."""
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""

    async def generate_json(self, prompt: str) -> Any:
        try:
            raw = await asyncio.to_thread(self._call_gpt, prompt)
        except Exception as exc:  # pragma: no cover - network/api errors
            logger.exception("Groq call failed: %s", exc)
            fallback = dict(_UNKNOWN_FALLBACK)
            fallback["reasoning"] = f"Groq call failed: {exc}"
            fallback["summary"] = "Groq call failed."
            return fallback

        cleaned = _strip_code_fences(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("Groq returned non-JSON content: %s | raw=%r", exc, raw)
            return dict(_UNKNOWN_FALLBACK)


def _strip_code_fences(text: str) -> str:
    """Defensive: strip Markdown code fences if the model ignored the system rule."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        cleaned = cleaned[first_nl + 1 :] if first_nl != -1 else cleaned[3:]
    if cleaned.rstrip().endswith("```"):
        cleaned = cleaned.rstrip()[:-3].rstrip()
    return cleaned


__all__ = ["GroqLLMClient"]
