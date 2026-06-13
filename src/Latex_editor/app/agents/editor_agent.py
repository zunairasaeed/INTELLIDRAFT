from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.agents.router_agent import RoutingDecision, RouteIntent


@dataclass
class EditorOutput:
    section_id: Optional[str]
    new_text: str
    summary: str = ""
    require_citations: list[str] = field(default_factory=list)
    require_labels: list[str] = field(default_factory=list)


class EditorAgent:
    def __init__(self, llm_client: Any) -> None:
        self.llm_client = llm_client

    def _build_prompt(self, decision: RoutingDecision, doc_summary: dict[str, Any]) -> str:
        return f"""
You are a LaTeX editor agent.

Your job is to produce ONLY the new LaTeX body text for the target region.

Rules:
- Preserve valid LaTeX.
- Do not add section headers unless explicitly requested.
- Do not rewrite the full document.
- Return JSON only with:
  section_id, new_text, summary, require_citations, require_labels.

Routing decision:
{decision}

Document summary:
{doc_summary}
""".strip()

    def _parse_response(self, raw: Any, decision: RoutingDecision) -> EditorOutput:
        if isinstance(raw, dict):
            return EditorOutput(
                section_id=raw.get("section_id", decision.section_id),
                new_text=raw.get("new_text", ""),
                summary=raw.get("summary", ""),
                require_citations=raw.get("require_citations", []) or [],
                require_labels=raw.get("require_labels", []) or [],
            )
        return EditorOutput(
            section_id=decision.section_id,
            new_text="",
            summary="Invalid editor response",
        )

    def _validate_output(self, output: EditorOutput, decision: RoutingDecision) -> EditorOutput:
        if not output.section_id:
            output.section_id = decision.section_id

        if decision.intent in {RouteIntent.LIST_SECTIONS, RouteIntent.SHOW_SECTION, RouteIntent.SUMMARIZE}:
            return output

        if not output.new_text.strip() and decision.intent not in {RouteIntent.DELETE_SECTION}:
            output.summary = output.summary or "Empty editor output"
        return output

    async def execute(self, decision: RoutingDecision, doc_summary: dict[str, Any]) -> EditorOutput:
        prompt = self._build_prompt(decision, doc_summary)

        raw = await self.llm_client.generate_json(prompt)

        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except Exception:
                return EditorOutput(
                    section_id=decision.section_id,
                    new_text="",
                    summary="Could not parse JSON",
                )

        output = self._parse_response(raw, decision)
        return self._validate_output(output, decision)
