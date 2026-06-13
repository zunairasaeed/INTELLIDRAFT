"""Tests for ``WorkspaceManager`` registration, idempotency, and isolation."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.services.workspace_manager import WorkspaceManager, WorkspaceState


def test_get_or_create_is_idempotent_per_session() -> None:
    mgr = WorkspaceManager()
    session_id, user_id = uuid4(), uuid4()

    first = mgr.get_or_create(session_id, user_id)
    second = mgr.get_or_create(session_id, user_id)

    assert first is second
    assert isinstance(first, WorkspaceState)


def test_get_returns_none_for_unknown_session() -> None:
    assert WorkspaceManager().get(uuid4()) is None


def test_each_workspace_has_its_own_lock() -> None:
    mgr = WorkspaceManager()
    a = mgr.get_or_create(uuid4(), uuid4())
    b = mgr.get_or_create(uuid4(), uuid4())
    assert a.lock is not b.lock


def test_remove_drops_workspace() -> None:
    mgr = WorkspaceManager()
    session_id = uuid4()
    mgr.get_or_create(session_id, uuid4())
    mgr.remove(session_id)
    assert mgr.get(session_id) is None


@pytest.mark.asyncio
async def test_workspace_lock_serialises_access() -> None:
    mgr = WorkspaceManager()
    ws = mgr.get_or_create(uuid4(), uuid4())

    timeline: list[str] = []

    async def critical_section(label: str) -> None:
        async with ws.lock:
            timeline.append(f"enter:{label}")
            await asyncio.sleep(0.01)
            timeline.append(f"exit:{label}")

    await asyncio.gather(critical_section("A"), critical_section("B"))

    # The two sections must not interleave.
    assert timeline.index("enter:A") < timeline.index("exit:A") < timeline.index("enter:B")
    assert timeline.index("enter:B") < timeline.index("exit:B")
