"""Tests for ``GroqLLMClient``.

We don't hit the real Groq API in unit tests; instead we monkey-patch
``_call_gpt`` (the only network-touching method) to simulate happy and
malformed responses.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest


def _make_client_without_network(monkeypatch: pytest.MonkeyPatch, response: str) -> Any:
    """Build a GroqLLMClient with a stubbed Groq SDK + stubbed call."""
    module = importlib.import_module("app.core.groq_llm_client")

    class _FakeGroq:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

    monkeypatch.setattr(module, "Groq", _FakeGroq)

    client = module.GroqLLMClient(api_key="test-key", model="llama-stub")
    monkeypatch.setattr(client, "_call_gpt", lambda prompt: response)
    return client


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("app.core.groq_llm_client")
    monkeypatch.setattr(module, "load_dotenv", None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    class _FakeGroq:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

    monkeypatch.setattr(module, "Groq", _FakeGroq)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        module.GroqLLMClient(api_key=None)


def test_missing_groq_package_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("app.core.groq_llm_client")
    monkeypatch.setattr(module, "Groq", None)
    with pytest.raises(RuntimeError, match="groq"):
        module.GroqLLMClient(api_key="ignored")


def test_generate_json_returns_dict_on_valid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client_without_network(
        monkeypatch,
        response='{"intent": "edit", "section_id": "abc", "reasoning": "ok"}',
    )
    result = asyncio.run(client.generate_json("prompt"))
    assert result == {"intent": "edit", "section_id": "abc", "reasoning": "ok"}


def test_generate_json_strips_code_fences(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client_without_network(
        monkeypatch,
        response='```json\n{"intent": "add", "section_id": "xyz"}\n```',
    )
    result = asyncio.run(client.generate_json("prompt"))
    assert result == {"intent": "add", "section_id": "xyz"}


def test_generate_json_falls_back_to_unknown_on_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_client_without_network(
        monkeypatch,
        response="this is not json at all",
    )
    result = asyncio.run(client.generate_json("prompt"))
    assert result["intent"] == "unknown"
    assert result["new_text"] == ""
    assert result["section_id"] is None


def test_generate_json_falls_back_on_call_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("app.core.groq_llm_client")

    class _FakeGroq:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

    monkeypatch.setattr(module, "Groq", _FakeGroq)
    client = module.GroqLLMClient(api_key="test-key")

    def _boom(_prompt: str) -> str:
        raise ConnectionError("network down")

    monkeypatch.setattr(client, "_call_gpt", _boom)

    result = asyncio.run(client.generate_json("prompt"))
    assert result["intent"] == "unknown"
    assert "Groq call failed" in result["reasoning"]
