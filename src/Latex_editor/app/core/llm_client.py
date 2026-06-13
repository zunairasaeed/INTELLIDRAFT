from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    raw: Any


class LLMClient:
    async def generate_json(self, prompt: str) -> Any:
        raise NotImplementedError


class StubLLMClient(LLMClient):
    async def generate_json(self, prompt: str) -> Any:
        return {
            "intent": "unknown",
            "section_id": None,
            "after_id": None,
            "new_title": None,
            "depth": None,
            "instruction": None,
            "reasoning": "stub client",
            "new_text": "",
            "summary": "stub client",
            "require_citations": [],
            "require_labels": [],
        }
