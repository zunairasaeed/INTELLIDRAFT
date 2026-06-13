"""Round-trip tests for ``InMemoryDbClient``."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.in_memory_db import InMemoryDbClient


@pytest.mark.asyncio
async def test_create_then_get_session_round_trips() -> None:
    db = InMemoryDbClient()
    user_id = uuid4()

    created = await db.create_session(user_id=user_id, title="Hello")
    fetched = await db.get_session(created["id"])

    assert fetched is not None
    assert fetched["title"] == "Hello"
    assert fetched["feature"] == "latex_editor"
    assert fetched["workspace_id"] is None


@pytest.mark.asyncio
async def test_update_session_workspace_persists() -> None:
    db = InMemoryDbClient()
    session = await db.create_session(user_id=uuid4(), title="t")
    workspace_id = uuid4()

    updated = await db.update_session_workspace(session["id"], workspace_id)
    assert updated["workspace_id"] == workspace_id


@pytest.mark.asyncio
async def test_upsert_workspace_creates_then_updates() -> None:
    db = InMemoryDbClient()
    session_id, user_id = uuid4(), uuid4()

    first = await db.upsert_workspace(
        workspace_id=None,
        session_id=session_id,
        user_id=user_id,
        tex_path="main.tex",
    )
    assert first["tex_path"] == "main.tex"

    second = await db.upsert_workspace(
        workspace_id=first["id"],
        session_id=session_id,
        user_id=user_id,
        tex_path="other.tex",
    )
    assert second["id"] == first["id"]
    assert second["tex_path"] == "other.tex"


@pytest.mark.asyncio
async def test_save_history_appends_row() -> None:
    db = InMemoryDbClient()
    row = await db.save_history(
        session_id=uuid4(),
        workspace_id=uuid4(),
        user_id=uuid4(),
        intent="edit_section",
        summary="ok",
    )
    assert row["intent"] == "edit_section"
    assert row["id"] in db.history
