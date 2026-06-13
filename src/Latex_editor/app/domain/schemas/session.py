"""Pydantic request schemas for session endpoints.

Responses are plain ``dict`` rows from the ``DbClient`` interface — the
shape of the underlying ``chat_sessions`` table — so we don't bind a
response model here.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    user_id: UUID
    title: str = Field(default="LaTeX Editor")
    feature: str = Field(default="latex_editor")
