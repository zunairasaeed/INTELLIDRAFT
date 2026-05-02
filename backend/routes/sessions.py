from fastapi import APIRouter, Depends, HTTPException
from backend.db import supabase
from backend.models import NewSessionRequest
from backend.routes.auth import get_current_user

router = APIRouter(prefix="/sessions", tags=["Sessions"])

@router.post("/")
def create_session(body: NewSessionRequest, user=Depends(get_current_user)):
    res = supabase.table("sessions").insert({
        "user_id": str(user.id),
        "title":   body.title,
        "feature": body.feature
    }).execute()
    return res.data[0]

@router.get("/")
def list_sessions(user=Depends(get_current_user)):
    # returns active (non-archived) sessions for sidebar
    res = supabase.table("recent_sessions") \
        .select("*") \
        .eq("user_id", str(user.id)) \
        .execute()
    return res.data

@router.get("/all")
def list_all_sessions(user=Depends(get_current_user)):
    # returns all sessions including archived (full history)
    res = supabase.table("session_history") \
        .select("session_id, title, feature, is_archived, message_count, last_message_at") \
        .eq("user_id", str(user.id)) \
        .execute()
    return res.data

@router.get("/{session_id}")
def get_session(session_id: str, user=Depends(get_current_user)):
    # returns full session with all messages for chat replay
    res = supabase.table("session_history") \
        .select("*") \
        .eq("session_id", session_id) \
        .eq("user_id", str(user.id)) \
        .single() \
        .execute()
    if not res.data:
        raise HTTPException(404, "Session not found")
    return res.data

@router.delete("/{session_id}")
def delete_session(session_id: str, user=Depends(get_current_user)):
    supabase.table("sessions") \
        .delete() \
        .eq("id", session_id) \
        .eq("user_id", str(user.id)) \
        .execute()
    return {"message": "Session deleted"}