from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4


class DbClient(ABC):
    @abstractmethod
    async def get_session(self, session_id: UUID) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    async def create_session(self, user_id: UUID, title: str, feature: str = "latex_editor") -> dict:
        raise NotImplementedError

    @abstractmethod
    async def update_session_workspace(self, session_id: UUID, workspace_id: UUID) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def upsert_workspace(
        self,
        workspace_id: UUID | None,
        session_id: UUID,
        user_id: UUID,
        tex_path: str | None = None,
        bib_path: str | None = None,
        doc_class: str | None = None,
        doc_mode: str | None = None,
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def save_history(
        self,
        session_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        intent: str,
        summary: str | None = None,
    ) -> dict:
        raise NotImplementedError
