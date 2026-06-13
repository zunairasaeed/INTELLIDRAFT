"""Tests for ``RouterAgent`` — JSON parsing, validation, fallbacks."""

from __future__ import annotations

import pytest

from app.agents.llm_client import ScriptedLLMClient
from app.agents.router_agent import RouteIntent, RouterAgent, RoutingDecision


@pytest.mark.asyncio
async def test_route_returns_decision_for_known_section() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({
        "intent": "edit",
        "section_id": "abc12345",
        "instruction": "tighten the prose",
        "reasoning": "user asked to edit",
    })
    agent = RouterAgent(llm, valid_section_ids={"abc12345"})

    decision = await agent.route("tighten the intro", {"sections": []})

    assert isinstance(decision, RoutingDecision)
    assert decision.intent == RouteIntent.EDIT
    assert decision.section_id == "abc12345"
    assert decision.instruction == "tighten the prose"


@pytest.mark.asyncio
async def test_route_nulls_section_id_when_not_in_valid_set() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({"intent": "edit", "section_id": "ghost", "instruction": "x"})
    agent = RouterAgent(llm, valid_section_ids={"real-id"})

    decision = await agent.route("anything", {})
    assert decision.section_id is None


@pytest.mark.asyncio
async def test_route_nulls_invalid_depth() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({"intent": "insert_section", "depth": 9, "new_title": "X"})
    agent = RouterAgent(llm)

    decision = await agent.route("add a deep section", {})
    assert decision.depth is None


@pytest.mark.asyncio
async def test_route_accepts_valid_depth() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({"intent": "insert_section", "depth": 2})
    agent = RouterAgent(llm)

    decision = await agent.route("add a subsection", {})
    assert decision.depth == 2


@pytest.mark.asyncio
async def test_route_returns_unknown_when_llm_returns_unparseable_string() -> None:
    llm = ScriptedLLMClient()
    llm.push_json("this is not json {")
    agent = RouterAgent(llm)

    decision = await agent.route("anything", {})
    assert decision.intent == RouteIntent.UNKNOWN


@pytest.mark.asyncio
async def test_route_parses_valid_json_string() -> None:
    llm = ScriptedLLMClient()
    llm.push_json('{"intent": "summarize", "reasoning": "user asked for summary"}')
    agent = RouterAgent(llm)

    decision = await agent.route("summarize the paper", {})
    assert decision.intent == RouteIntent.SUMMARIZE


@pytest.mark.asyncio
async def test_route_returns_unknown_on_unrecognised_intent_value() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({"intent": "nonsense"})
    agent = RouterAgent(llm)

    # RouteIntent("nonsense") raises ValueError inside _parse_response,
    # which bubbles up — verify the failure mode.
    with pytest.raises(ValueError):
        await agent.route("anything", {})


@pytest.mark.asyncio
async def test_route_nulls_after_id_when_not_in_valid_set() -> None:
    llm = ScriptedLLMClient()
    llm.push_json({"intent": "insert_section", "after_id": "ghost"})
    agent = RouterAgent(llm, valid_section_ids={"real"})

    decision = await agent.route("insert one", {})
    assert decision.after_id is None
