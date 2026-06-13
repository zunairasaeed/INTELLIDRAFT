from __future__ import annotations

from uuid import UUID


class WorkspaceService:
    def __init__(self, db_client, manager) -> None:
        self.db = db_client
        self.manager = manager

    async def load_or_create_workspace(self, session_id: UUID, user_id: UUID, tex_path: str | None = None, bib_path: str | None = None):
        ws = self.manager.get_or_create(session_id=session_id, user_id=user_id, tex_path=tex_path, bib_path=bib_path)
        await self.db.upsert_workspace(
            workspace_id=ws.workspace_id,
            session_id=session_id,
            user_id=user_id,
            tex_path=tex_path,
            bib_path=bib_path,
        )
        return ws
