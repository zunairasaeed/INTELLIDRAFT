"""Tests for ``EditorAgent`` — JSON parsing, fallbacks, intent-aware validation."""

from __future__ import annotations

import pytest

from app.agents.editor_agent import EditorAgent, EditorOutput
from app.agents.llm_client import ScriptedLLMClient
from app.agents.router_agent import RouteIntent, RoutingDecision


def _decision(intent: RouteIntent = RouteIntent.EDIT, section_id: str | None = "sec-1") -> RoutingDecision:
    return RoutingDecision(intent=intent, section_id=section_id, instruction="rewrite")


@pytest.mark.asyncio
async def test_execute_returns_editor_output_from_json_dict() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({
        "section_id": "sec-1",
        "new_text": "New body content.",
        "summary": "rewrote intro",
        "require_citations": ["\\cite{x}"],
        "require_labels": [],
    })
    agent = EditorAgent(llm)

    out = await agent.execute(_decision(), doc_summary={"sections": []})

    assert isinstance(out, EditorOutput)
    assert out.section_id == "sec-1"
    assert out.new_text == "New body content."
    assert out.summary == "rewrote intro"
    assert out.require_citations == ["\\cite{x}"]
    assert out.require_labels == []


@pytest.mark.asyncio
async def test_execute_parses_valid_json_string() -> None:
    llm = ScriptedLLMClient()
    llm.push_json('{"new_text": "body", "summary": "ok"}')
    agent = EditorAgent(llm)

    out = await agent.execute(_decision(), {})
    assert out.new_text == "body"
    assert out.summary == "ok"


@pytest.mark.asyncio
async def test_execute_falls_back_to_unparseable_json_string() -> None:
    llm = ScriptedLLMClient()
    llm.push_json("not actually json")
    agent = EditorAgent(llm)

    out = await agent.execute(_decision(), {})
    assert out.new_text == ""
    assert out.summary == "Could not parse JSON"
    assert out.section_id == "sec-1"  # fell back to decision.section_id


@pytest.mark.asyncio
async def test_execute_falls_back_when_llm_returns_non_dict_non_string() -> None:
    llm = ScriptedLLMClient()
    llm.push_json(42)  # type: ignore[arg-type]
    agent = EditorAgent(llm)

    out = await agent.execute(_decision(), {})
    assert out.new_text == ""
    assert out.summary == "Invalid editor response"


@pytest.mark.asyncio
async def test_execute_fills_section_id_from_decision_when_missing() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({"new_text": "x", "section_id": None})
    agent = EditorAgent(llm)

    out = await agent.execute(_decision(section_id="from-decision"), {})
    assert out.section_id == "from-decision"


@pytest.mark.asyncio
async def test_execute_passes_through_for_read_only_intents() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({"new_text": "", "summary": "here are your sections"})
    agent = EditorAgent(llm)

    out = await agent.execute(_decision(intent=RouteIntent.LIST_SECTIONS), {})
    assert out.summary == "here are your sections"
    # No "Empty editor output" annotation for read-only intents.


@pytest.mark.asyncio
async def test_execute_annotates_empty_summary_for_content_intent() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({"new_text": "   ", "summary": ""})
    agent = EditorAgent(llm)

    out = await agent.execute(_decision(intent=RouteIntent.EDIT), {})
    assert out.summary == "Empty editor output"


@pytest.mark.asyncio
async def test_execute_skips_empty_annotation_for_delete_section() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({"new_text": "", "summary": ""})
    agent = EditorAgent(llm)

    out = await agent.execute(_decision(intent=RouteIntent.DELETE_SECTION), {})
    assert out.summary == ""  # not annotated for delete
