"""
Per-user session CRUD (Supabase `sessions` + views).

- ``POST /sessions/`` — body ``{ "feature": "<Feature string>", "title": "..." }``; ``user_id`` from JWT.
- ``GET /sessions/`` — recent sessions (non-archived).
- ``GET /sessions/all`` — full history list.
- ``GET /sessions/{session_id}`` — one session row (metadata / replay).
- ``DELETE /sessions/{session_id}`` — delete if owned by caller.

``feature`` is **not** hardcoded to literature: use any value from ``backend.models.Feature``.
Supabase stores sessions in **PostgreSQL**; if the ``sessions.feature`` CHECK/enum omits a
value (e.g. ``research_publishing_guide`` for the writing guide / ``Research_and_publishing_guide_bot`` pipeline), Postgres returns **23514**. The API then responds **503** with ``fix_sql_file`` pointing at the SQL patch to run in the Supabase SQL editor.
"""

from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError

from backend.db import supabase
from backend.models import Feature, NewSessionRequest
from backend.routes.auth import get_current_user
from backend.session_feature_storage import outward_session, storage_feature_value

router = APIRouter(prefix="/sessions", tags=["Sessions"])

_ALLOWED_API_FEATURES = sorted(f.value for f in Feature)


def _outward_rows(rows: list | None) -> list:
    return [outward_session(r) for r in (rows or [])]


@router.post("/")
def create_session(body: NewSessionRequest, user=Depends(get_current_user)):
    feat = storage_feature_value(body.feature)
    try:
        res = (
            supabase.table("sessions")
            .insert(
                {
                    "user_id": str(user.id),
                    "title": (body.title or "New session")[:200],
                    "feature": feat,
                }
            )
            .execute()
        )
    except APIError as e:
        if e.code == "23514":
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "sessions_feature_not_allowed_by_database",
                    "message": (
                        "Supabase rejected the insert: `sessions.feature` CHECK (or enum) "
                        "does not allow this value. The FastAPI API uses `Feature` strings unchanged."
                    ),
                    "attempted_feature": feat,
                    "allowed_api_features": _ALLOWED_API_FEATURES,
                    "fix_sql_file": "database/sessions_fix_feature_check.sql",
                    "postgres_message": e.message,
                    "postgres_details": e.details,
                },
            ) from e
        raise
    return outward_session(res.data[0])


@router.get("/")
def list_sessions(user=Depends(get_current_user)):
    # returns active (non-archived) sessions for sidebar
    res = (
        supabase.table("recent_sessions")
        .select("*")
        .eq("user_id", str(user.id))
        .execute()
    )
    return _outward_rows(res.data)

@router.get("/all")
def list_all_sessions(user=Depends(get_current_user)):
    # returns all sessions including archived (full history)
    res = (
        supabase.table("session_history")
        .select(
            "session_id, title, feature, is_archived, message_count, last_message_at"
        )
        .eq("user_id", str(user.id))
        .execute()
    )
    return _outward_rows(res.data)

@router.get("/{session_id}")
def get_session(session_id: str, user=Depends(get_current_user)):
    # returns full session with all messages for chat replay
    res = (
        supabase.table("session_history")
        .select("*")
        .eq("session_id", session_id)
        .eq("user_id", str(user.id))
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "Session not found")
    return outward_session(res.data)

@router.delete("/{session_id}")
def delete_session(session_id: str, user=Depends(get_current_user)):
    supabase.table("sessions") \
        .delete() \
        .eq("id", session_id) \
        .eq("user_id", str(user.id)) \
        .execute()
    return {"message": "Session deleted"}