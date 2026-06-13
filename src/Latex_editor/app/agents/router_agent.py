from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class RouteIntent(str, Enum):
    EDIT = "edit"
    ADD = "add"
    REPLACE = "replace"
    DELETE_SECTION = "delete_section"
    INSERT_SECTION = "insert_section"
    RENAME_SECTION = "rename_section"
    MOVE_SECTION = "move_section"
    LIST_SECTIONS = "list_sections"
    SHOW_SECTION = "show_section"
    SUMMARIZE = "summarize"
    UNKNOWN = "unknown"


@dataclass
class RoutingDecision:
    intent: RouteIntent
    section_id: Optional[str] = None
    after_id: Optional[str] = None
    new_title: Optional[str] = None
    depth: Optional[int] = None
    instruction: Optional[str] = None
    reasoning: Optional[str] = None


class RouterAgent:
    def __init__(self, llm_client: Any, valid_section_ids: set[str] | None = None) -> None:
        self.llm_client = llm_client
        self.valid_section_ids = valid_section_ids or set()

    def _build_prompt(self, message: str, doc_summary: dict[str, Any]) -> str:
        return f"""
You are a routing agent for a LaTeX editor.

Your only job is to choose ONE intent from:
edit, add, replace, delete_section, insert_section, rename_section,
move_section, list_sections, show_section, summarize, unknown.

Return JSON only with:
intent, section_id, after_id, new_title, depth, instruction, reasoning.

User message:
{message}

Document summary:
{doc_summary}
""".strip()

    def _parse_response(self, raw: Any) -> RoutingDecision:
        if isinstance(raw, dict):
            intent = RouteIntent(raw.get("intent", "unknown"))
            return RoutingDecision(
                intent=intent,
                section_id=raw.get("section_id"),
                after_id=raw.get("after_id"),
                new_title=raw.get("new_title"),
                depth=raw.get("depth"),
                instruction=raw.get("instruction"),
                reasoning=raw.get("reasoning"),
            )
        return RoutingDecision(intent=RouteIntent.UNKNOWN, reasoning="Invalid router response")

    def _validate_decision(self, decision: RoutingDecision) -> RoutingDecision:
        if decision.section_id and decision.section_id not in self.valid_section_ids:
            decision.section_id = None
        if decision.after_id and decision.after_id not in self.valid_section_ids:
            decision.after_id = None
        if decision.depth is not None and decision.depth not in {1, 2, 3, 4, 5}:
            decision.depth = None
        return decision

    async def route(self, message: str, doc_summary: dict[str, Any]) -> RoutingDecision:
        prompt = self._build_prompt(message, doc_summary)

        raw = await self.llm_client.generate_json(prompt)

        if isinstance(raw, str):
            try:
                import json
                raw = json.loads(raw)
            except Exception:
                return RoutingDecision(intent=RouteIntent.UNKNOWN, reasoning="Could not parse JSON")

        decision = self._parse_response(raw)
        return self._validate_decision(decision)
