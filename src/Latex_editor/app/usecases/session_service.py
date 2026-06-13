from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass
class ChatSession:
    id: UUID
    user_id: UUID
    title: str
    feature: str
    workspace_id: UUID | None = None


class SessionService:
    def __init__(self, db_client) -> None:
        self.db = db_client

    async def get_session(self, session_id: UUID) -> dict:
        return await self.db.get_session(session_id)

    async def create_session(self, user_id: UUID, title: str, feature: str = "latex_editor") -> dict:
        return await self.db.create_session(user_id=user_id, title=title, feature=feature)

    async def update_workspace(self, session_id: UUID, workspace_id: UUID) -> dict:
        return await self.db.update_session_workspace(session_id, workspace_id)
