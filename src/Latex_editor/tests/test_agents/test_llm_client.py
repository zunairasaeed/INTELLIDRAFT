"""Tests for the LLM client stubs."""

from __future__ import annotations

import pytest

from app.agents.llm_client import EchoLLMClient, ScriptedLLMClient


@pytest.mark.asyncio
async def test_echo_client_returns_unknown_routing_payload() -> None:
    client = EchoLLMClient()
    response = await client.generate_json("anything")
    assert response == {
        "intent": "unknown",
        "reasoning": "EchoLLMClient stub (no LLM configured)",
    }


@pytest.mark.asyncio
async def test_echo_client_returns_empty_text() -> None:
    assert await EchoLLMClient().generate_text("anything") == ""


@pytest.mark.asyncio
async def test_scripted_client_returns_queued_responses_in_order() -> None:
    client = ScriptedLLMClient()
    client.push_text("first")
    client.push_text("second")
    assert await client.generate_text("p") == "first"
    assert await client.generate_text("p") == "second"


@pytest.mark.asyncio
async def test_scripted_client_separate_queues_for_text_and_json() -> None:
    client = ScriptedLLMClient()
    client.push_text("text-only")
    client.push_json({"intent": "edit"})
    assert await client.generate_text("p") == "text-only"
    assert await client.generate_json("p") == {"intent": "edit"}


@pytest.mark.asyncio
async def test_scripted_client_raises_when_queue_empty() -> None:
    client = ScriptedLLMClient()
    with pytest.raises(RuntimeError, match="no JSON"):
        await client.generate_json("p")
    with pytest.raises(RuntimeError, match="no text"):
        await client.generate_text("p")
