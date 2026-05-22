"""LLM-driven intent router.

Given a user's natural-language ask and the parsed document's section list,
returns a structured :class:`RoutedIntent` describing what the agent should do.

Supported intents:

* ``edit``            - rewrite an existing section per the instruction
* ``add``             - append new content to a section (LLM-generated or
                        user-provided)
* ``replace``         - replace a section's body with user-provided LaTeX
* ``delete_section``  - remove a section entirely
* ``list_sections``   - enumerate sections
* ``show_section``    - return one section's body
* ``summarize``       - describe the document structure / metadata
* ``unknown``         - intent unclear; ask the user to clarify

The router calls Groq with ``response_format={"type": "json_object"}`` so
parsing is robust. It then validates that the returned ``section_id`` is one
of the IDs we provided (or null) before handing the decision to the
executor.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

try:
    from groq import Groq
except ImportError:  # pragma: no cover
    Groq = None  # type: ignore[assignment]

from ..models.schema import Section

_INTENT_MODEL = "llama-3.3-70b-versatile"

VALID_INTENTS: set[str] = {
    "edit",
    "add",
    "replace",
    "delete_section",
    "insert_section",
    "rename_section",
    "move_section",
    "list_sections",
    "show_section",
    "summarize",
    "unknown",
}

INTENT_ROUTER_SYSTEM = """You are the intent router for an agentic LaTeX editor.

You receive:
- A user request in natural language.
- The list of sections in the user's LaTeX paper as JSON, each with id, title, depth, is_empty, is_implicit.
- The paper's metadata (title, doi, conference, keywords).

Your job: return ONE JSON object describing what to do.

Schema:
{
  "intent": "edit" | "add" | "replace" | "delete_section" |
            "insert_section" | "rename_section" | "move_section" |
            "list_sections" | "show_section" | "summarize" | "unknown",
  "section_id": <id from the list, or null>,
  "new_title": <title string for insert_section/rename_section, or null>,
  "depth": <1=section, 2=subsection, 3=subsubsection (insert_section only), or null>,
  "after_id": <existing section id to insert/move after, or null>,
  "instruction": <refined instruction to pass to the editor LLM, or null>,
  "user_content": <literal LaTeX content the user provided, or null>,
  "reasoning": <one short sentence>
}

Rules:
- Output JSON ONLY. No prose, no markdown, no code fences.
- section_id and after_id MUST exactly match one of the provided IDs, or be null.
- Match section references liberally: "the intro" -> Introduction, "methodology" -> Methodology, "section 3" -> the third explicit (non-implicit) section.
- intent="edit" when the user wants the LLM to rewrite an existing section's body.
- intent="add" when the user wants to APPEND new prose into an existing section's body. This NEVER creates a new \\section{} header — use insert_section for that. If they provided literal LaTeX to add, put it in user_content; otherwise leave user_content null and let instruction guide the LLM.
- intent="replace" when the user provided literal LaTeX content and wants it to OVERWRITE the section body.
- intent="delete_section" when the user wants a section gone entirely (its subsections are cascade-deleted).
- intent="insert_section" when the user wants a NEW \\section / \\subsection / \\subsubsection created. Set new_title to the desired title, depth to 1/2/3, and after_id to the existing section the new one should come after. user_content may carry an initial body.
- intent="rename_section" when the user wants to change a section's TITLE only. Set section_id to the target and new_title to the new name. depth and position stay unchanged.
- intent="move_section" when the user wants to REORDER sections. Set section_id to the section being moved and after_id to the section it should come after.
- intent="list_sections" / "show_section" / "summarize" for read-only asks.
- intent="unknown" if the ask is genuinely unclear.
- Never invent a section_id or after_id that is not in the list.
"""


# ────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class RoutedIntent:
    intent: str
    section_id: str | None = None
    instruction: str | None = None
    user_content: str | None = None
    reasoning: str = ""
    raw_response: str = ""
    section_title: str | None = None
    # Structural-edit fields (insert_section / rename_section / move_section).
    new_title: str | None = None
    depth: int | None = None
    after_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw_response", None)
        return d


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────
def route_intent(
    query: str,
    sections: list[Section],
    metadata: dict[str, Any] | None = None,
    *,
    model: str = _INTENT_MODEL,
    temperature: float = 0.0,
) -> RoutedIntent:
    """Run the LLM intent router. Always returns a :class:`RoutedIntent`.

    Falls back to ``intent="unknown"`` on any error.
    """

    section_payload = [
        {
            "id": s.id,
            "title": s.title,
            "depth": s.depth,
            "is_empty": s.is_empty,
            "is_implicit": s.is_implicit,
        }
        for s in sections
    ]
    valid_ids = {s.id for s in sections}

    user_message = (
        f"User request:\n{query}\n\n"
        f"Sections:\n{json.dumps(section_payload, indent=2)}\n\n"
        f"Metadata:\n{json.dumps(metadata or {}, indent=2)}\n"
    )

    try:
        raw = _call_groq_json(
            system=INTENT_ROUTER_SYSTEM,
            user=user_message,
            model=model,
            temperature=temperature,
        )
    except Exception as exc:  # noqa: BLE001
        return RoutedIntent(
            intent="unknown",
            reasoning=f"router error: {exc}",
            raw_response="",
        )

    parsed = _parse_intent_json(raw)
    routed = _validate(parsed, valid_ids=valid_ids, raw=raw)

    if routed.section_id is not None:
        for s in sections:
            if s.id == routed.section_id:
                routed.section_title = s.title
                break

    return routed


# ────────────────────────────────────────────────────────────────────────────
# Internals
# ────────────────────────────────────────────────────────────────────────────
_client: "Groq | None" = None


def _get_client() -> "Groq":
    if Groq is None:
        raise RuntimeError("The 'groq' package is not installed.")
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set.")
        _client = Groq(api_key=api_key)
    return _client


def _call_groq_json(
    system: str, user: str, model: str, temperature: float
) -> str:
    """Call Groq with JSON-object response format and return raw text."""

    response = _get_client().chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return response.choices[0].message.content or "{}"


def _parse_intent_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def _validate(parsed: dict[str, Any], *, valid_ids: set[str], raw: str) -> RoutedIntent:
    intent = str(parsed.get("intent", "unknown")).strip()
    if intent not in VALID_INTENTS:
        intent = "unknown"

    section_id = parsed.get("section_id")
    if section_id is not None:
        section_id = str(section_id).strip() or None
        if section_id is not None and section_id not in valid_ids:
            section_id = None

    def _opt_str(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    # ── Structural-edit fields ────────────────────────────────────────────
    new_title = _opt_str(parsed.get("new_title"))

    depth_raw = parsed.get("depth")
    try:
        depth: int | None = int(depth_raw) if depth_raw is not None else None
    except (TypeError, ValueError):
        depth = None

    after_id_raw = _opt_str(parsed.get("after_id"))
    # ``after_id`` MUST reference an existing section, just like ``section_id``.
    after_id = after_id_raw if (after_id_raw is not None and after_id_raw in valid_ids) else None

    return RoutedIntent(
        intent=intent,
        section_id=section_id,
        instruction=_opt_str(parsed.get("instruction")),
        user_content=_opt_str(parsed.get("user_content")),
        reasoning=str(parsed.get("reasoning", "")).strip(),
        raw_response=raw,
        new_title=new_title,
        depth=depth,
        after_id=after_id,
    )


__all__ = ["RoutedIntent", "route_intent", "VALID_INTENTS"]
