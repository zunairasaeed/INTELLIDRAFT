from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from .db_client import DbClient


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryDbClient(DbClient):
    def __init__(self) -> None:
        self.sessions: dict[UUID, dict] = {}
        self.workspaces: dict[UUID, dict] = {}
        self.history: dict[UUID, dict] = {}

    async def get_session(self, session_id: UUID) -> dict | None:
        return self.sessions.get(session_id)

    async def create_session(self, user_id: UUID, title: str, feature: str = "latex_editor") -> dict:
        session_id = uuid4()
        row = {
            "id": session_id,
            "user_id": user_id,
            "title": title,
            "feature": feature,
            "workspace_id": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.sessions[session_id] = row
        return row

    async def update_session_workspace(self, session_id: UUID, workspace_id: UUID) -> dict:
        row = self.sessions[session_id]
        row["workspace_id"] = workspace_id
        row["updated_at"] = _now()
        return row

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
        if workspace_id is None:
            workspace_id = uuid4()

        row = self.workspaces.get(workspace_id)
        if row is None:
            row = {
                "id": workspace_id,
                "session_id": session_id,
                "user_id": user_id,
                "tex_path": tex_path,
                "bib_path": bib_path,
                "doc_class": doc_class,
                "doc_mode": doc_mode,
                "current_revision": 0,
                "lock_version": 0,
                "created_at": _now(),
                "updated_at": _now(),
            }
        else:
            row["session_id"] = session_id
            row["user_id"] = user_id
            row["tex_path"] = tex_path
            row["bib_path"] = bib_path
            row["doc_class"] = doc_class
            row["doc_mode"] = doc_mode
            row["updated_at"] = _now()

        self.workspaces[workspace_id] = row
        return row

    async def save_history(
        self,
        session_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        intent: str,
        summary: str | None = None,
    ) -> dict:
        history_id = uuid4()
        row = {
            "id": history_id,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "intent": intent,
            "summary": summary,
            "created_at": _now(),
        }
        self.history[history_id] = row
        return row
