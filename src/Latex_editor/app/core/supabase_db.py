from __future__ import annotations

import os
from uuid import UUID

from supabase import Client, create_client

from .db_client import DbClient


class SupabaseDbClient(DbClient):
    def __init__(self, client: Client | None = None) -> None:
        if client is None:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_KEY")
            if not url or not key:
                raise ValueError("SUPABASE_URL and SUPABASE_KEY are required")
            client = create_client(url, key)
        self.client = client

    async def get_session(self, session_id: UUID) -> dict | None:
        res = self.client.table("chat_sessions").select("*").eq("id", str(session_id)).limit(1).execute()
        data = res.data or []
        return data[0] if data else None

    async def create_session(self, user_id: UUID, title: str, feature: str = "latex_editor") -> dict:
        res = self.client.table("chat_sessions").insert({
            "user_id": str(user_id),
            "title": title,
            "feature": feature,
        }).execute()
        return res.data[0]

    async def update_session_workspace(self, session_id: UUID, workspace_id: UUID) -> dict:
        res = self.client.table("chat_sessions").update({
            "workspace_id": str(workspace_id),
        }).eq("id", str(session_id)).execute()
        return res.data[0]

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
        payload = {
            "session_id": str(session_id),
            "user_id": str(user_id),
            "tex_path": tex_path,
            "bib_path": bib_path,
            "doc_class": doc_class,
            "doc_mode": doc_mode,
        }
        if workspace_id is not None:
            payload["id"] = str(workspace_id)

        res = self.client.table("latex_workspaces").upsert(payload).execute()
        return res.data[0]

    async def save_history(
        self,
        session_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        intent: str,
        summary: str | None = None,
    ) -> dict:
        res = self.client.table("latex_edit_history").insert({
            "session_id": str(session_id),
            "workspace_id": str(workspace_id),
            "user_id": str(user_id),
            "intent": intent,
            "patch_summary": summary,
        }).execute()
        return res.data[0]
