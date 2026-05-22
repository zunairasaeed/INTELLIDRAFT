from pathlib import Path
import sys

from fastapi import APIRouter, Depends, HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.db import supabase
from backend.models import ChatRequest, Feature
from backend.routes.auth import get_current_user
from backend.session_feature_storage import canonical_feature_value

router = APIRouter(prefix="/chat", tags=["Chat"])

# DB rows stored before renaming may still use these strings
_LEGACY_LATEX_FEATURE = frozenset({"latex_template", "citation_management"})


def _session_feature(raw: str | None) -> Feature:
    if raw in _LEGACY_LATEX_FEATURE:
        return Feature.latex_alignment
    if raw is None:
        raise HTTPException(
            400,
            "Session has unknown feature None; update the session or database.",
        )
    canon = canonical_feature_value(raw)
    try:
        return Feature(canon)
    except ValueError as e:
        raise HTTPException(
            400,
            f"Session has unknown feature {raw!r}; update the session or database.",
        ) from e


def _pipeline_routes_for_feature(feature: Feature) -> str:
    """Short hint so users know which HTTP endpoints to call for this workspace."""
    lines = {
        Feature.journal_information_assistant: (
            "POST /pipelines/journal/recommend\n"
            "GET /pipelines/journal/health"
        ),
        Feature.semantic_literature_search: (
            "POST /pipelines/literature/search\n"
            "GET /pipelines/literature/health"
        ),
        Feature.research_publishing_guide: (
            "POST /pipelines/research-guide/ask\n"
            "POST /pipelines/research-guide/search\n"
            "GET /pipelines/research-guide/health"
        ),
        Feature.latex_alignment: (
            "POST /pipelines/latex-alignment/ask  (multipart: query + optional tex_file + optional bib_file)\n"
            "GET /pipelines/latex-alignment/state\n"
            "GET /pipelines/latex-alignment/export  (download edited .tex)\n"
            "DELETE /pipelines/latex-alignment/reset\n"
            "GET /pipelines/latex-alignment/health\n"
            "GET /pipelines/latex-alignment/citations  (how to use /citations)\n"
            "Authenticated saves/exports: /citations/*"
        ),
    }
    return lines[feature]


def load_history(session_id: str) -> list:
    res = (
        supabase.table("messages")
        .select("role, content")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    return res.data or []


def save_message(session_id: str, role: str, content: str):
    supabase.table("messages").insert(
        {
            "session_id": session_id,
            "role": role,
            "content": content,
        }
    ).execute()


def update_session_title(session_id: str, title: str, user_id: str):
    supabase.table("sessions").update({"title": title[:80]}).eq("id", session_id).eq(
        "user_id", user_id
    ).execute()


@router.post("/", summary="Store chat turns; pipelines are separate (/pipelines/*)")
async def chat(body: ChatRequest, user=Depends(get_current_user)):
    session = (
        supabase.table("sessions")
        .select("*")
        .eq("id", body.session_id)
        .eq("user_id", str(user.id))
        .execute()
    )
    if not session.data:
        raise HTTPException(403, "Session not found or access denied")

    feature = _session_feature(session.data[0].get("feature"))

    history = load_history(body.session_id)
    save_message(body.session_id, "user", body.message)

    pipelines_help = _pipeline_routes_for_feature(feature)
    answer = (
        "Message saved to this session.\n\n"
        f"Workspace: `{feature.value}`. IntelliDraft AI chains run on dedicated "
        f"routes (not via chat). For `{feature.value}` use:\n{pipelines_help}\n\n"
        "Overview: GET /pipelines/status"
    )

    save_message(body.session_id, "assistant", answer)

    if session.data[0].get("title") == "New session" and body.message:
        update_session_title(body.session_id, body.message[:80], str(user.id))

    return {
        "answer": answer,
        "session_id": body.session_id,
        "feature": feature.value,
        "history": history
        + [
            {"role": "user", "content": body.message},
            {"role": "assistant", "content": answer},
        ],
    }
