"""
Journal-only FastAPI app (optional).

Production-style testing normally uses **one backend** (`uvicorn backend.main:app`):
  POST /pipelines/journal/recommend — same workflow as below.

Standalone run:
    uvicorn api.main:app --reload --port 8000
  POST /journal/recommend

Literature search and research-guide RAG are on `backend.main` under `/pipelines/...`
(see `backend/routes/pipelines.py`). Legacy separate ports remain documented in each
pipeline's own `pipeline_run.py`.
"""

import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.journal_information_assistant.publisher_mapping_engine.pipeline_run import run_pipeline as run_journal_pipeline


# ── App setup ──────────────────────────────────────────────────────────────
app = FastAPI(
    title       = "IntelliDraft Journal API",
    description=(
        "Journal publisher recommendation (`/journal/recommend`). "
        "For all chains on one port, use **`backend.main`** → `/pipelines/*`."
    ),
    version = "1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["System"], summary="Health check")
def health_check() -> Dict[str, str]:
    """Confirms the API is running. Check this first."""
    return {
        "status":  "ok",
        "service": "IntelliDraft Journal API",
    }


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE 1 — Journal Information Assistant
# ══════════════════════════════════════════════════════════════════════════════

class JournalRequest(BaseModel):
    title: str = ""
    abstract: str = ""
    user_input: str = ""


@app.post(
    "/journal/recommend",
    tags=["Journal Information Assistant"],
    summary="Get best publisher recommendation for a research paper",
)
def journal_recommend(request: JournalRequest) -> Dict[str, Any]:
    """
    Pipeline: title + abstract → input processing → LLM field analysis → publisher recommendation.
    Response always has `success` and `error`; when `success` is false, `error` explains why.
    """
    try:
        if not (request.user_input.strip() or (request.title.strip() and request.abstract.strip())):
            raise HTTPException(
                status_code=422,
                detail="Provide either user_input, or both title and abstract.",
            )
        result = run_journal_pipeline(
            title=request.title,
            abstract=request.abstract,
            user_input=request.user_input,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e