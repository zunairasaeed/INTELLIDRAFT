"""Pydantic request schemas for the LaTeX editing endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class EnsureSession(BaseModel):
    """Idempotently load (or create) the session + workspace pair."""

    session_id: UUID
    user_id: UUID
    title: str = Field(default="LaTeX Editor")


class HandleMessage(BaseModel):
    """A single user turn to be routed through the editor pipeline."""

    session_id: UUID
    user_id: UUID
    message: str
