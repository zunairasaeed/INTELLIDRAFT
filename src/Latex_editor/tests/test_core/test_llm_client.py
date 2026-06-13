"""Tests for the canonical LLM client interface and the in-process stub."""

from __future__ import annotations

import asyncio

import pytest

from app.core.llm_client import LLMClient, LLMResponse, StubLLMClient


def test_llm_response_is_dataclass_holding_raw() -> None:
    resp = LLMResponse(raw={"intent": "edit"})
    assert resp.raw == {"intent": "edit"}


def test_llm_client_base_raises_not_implemented() -> None:
    client = LLMClient()
    with pytest.raises(NotImplementedError):
        asyncio.run(client.generate_json("anything"))


def test_stub_returns_unknown_intent_with_unified_shape() -> None:
    result = asyncio.run(StubLLMClient().generate_json("hello"))

    assert result["intent"] == "unknown"
    assert result["reasoning"] == "stub client"
    assert result["new_text"] == ""
    assert result["summary"] == "stub client"
    assert result["require_citations"] == []
    assert result["require_labels"] == []

    for key in ("section_id", "after_id", "new_title", "depth", "instruction"):
        assert result[key] is None, f"expected {key!r} to be None"


def test_stub_is_pure_so_repeated_calls_match() -> None:
    stub = StubLLMClient()
    a = asyncio.run(stub.generate_json("one"))
    b = asyncio.run(stub.generate_json("two"))
    assert a == b


def test_stub_is_subclass_of_llm_client() -> None:
    assert isinstance(StubLLMClient(), LLMClient)
