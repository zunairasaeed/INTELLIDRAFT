"""Test-friendly LLM client implementations.

The canonical ``LLMClient`` abstract class lives in
``app.core.llm_client``. This module re-exports it and adds concrete
subclasses useful for development and tests:

* ``EchoLLMClient``     — always returns an ``unknown`` routing payload.
* ``ScriptedLLMClient`` — returns pre-queued responses in FIFO order.

Production wiring (``app.api.dependencies``) uses ``StubLLMClient``
from ``app.core.llm_client``; ``ScriptedLLMClient`` here is for tests
that need to drive the loop with specific LLM responses.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from ..core.llm_client import LLMClient

__all__ = ["LLMClient", "EchoLLMClient", "ScriptedLLMClient"]


class EchoLLMClient(LLMClient):
    """Returns an ``unknown`` routing payload for every call."""

    async def generate_text(self, prompt: str) -> str:
        return ""

    async def generate_json(self, prompt: str) -> Any:
        return {"intent": "unknown", "reasoning": "EchoLLMClient stub (no LLM configured)"}


class ScriptedLLMClient(LLMClient):
    """Test double: returns pre-queued responses in FIFO order.

    Usage::

        llm = ScriptedLLMClient()
        llm.push_json({"intent": "edit", "section_id": "abc"})
        llm.push_text("new body content")
    """

    def __init__(self) -> None:
        self._json_queue: deque[dict[str, Any] | str] = deque()
        self._text_queue: deque[str] = deque()

    def push_json(self, response: Any) -> None:
        self._json_queue.append(response)

    def push_text(self, response: str) -> None:
        self._text_queue.append(response)

    async def generate_json(self, prompt: str) -> Any:
        if not self._json_queue:
            raise RuntimeError("ScriptedLLMClient: no JSON response queued.")
        return self._json_queue.popleft()

    async def generate_text(self, prompt: str) -> str:
        if not self._text_queue:
            raise RuntimeError("ScriptedLLMClient: no text response queued.")
        return self._text_queue.popleft()
