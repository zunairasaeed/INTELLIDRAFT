# -*- coding: utf-8 -*-
"""
Journal Research API - FastAPI Wrapper
========================================
**Standalone testing** (optional — production uses the main backend ``/pipelines``)::

    cd src/Journel_Research_Assistan
    uvicorn api:app --reload --host %JOURNAL_RESEARCH_STANDALONE_HOST% --port %JOURNAL_RESEARCH_STANDALONE_PORT%

Port and host default from ``.env`` via ``JOURNAL_RESEARCH_STANDALONE_PORT`` (default ``8012``)
and ``JOURNAL_RESEARCH_STANDALONE_HOST`` (default ``127.0.0.1``). Or pass ``--port`` explicitly.

**Integrated (recommended):** ``GET /pipelines/journal-research/ask`` on ``backend.main`` (same
origin as the rest of IntelliDraft).

Primary endpoint:
  GET /ask?q=your+question

Design:
  - One flexible endpoint for natural-language researcher questions
  - Intent classifier routes to the right free API flow internally
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

import journal_research as jr
import final_response_agent as presenter

app = FastAPI(
    title="Journal Research Module",
    description="Free-API journal discovery with real quartiles and honest metrics.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


class JournalResult(BaseModel):
    """Validated journal row; extra keys from enrichment are preserved."""

    model_config = ConfigDict(extra="allow")

    name: str
    issn: Optional[str] = None
    publisher: Optional[str] = None
    country: Optional[str] = None
    is_oa: Optional[bool] = None
    homepage: Optional[str] = None
    best_quartile: Optional[str] = None
    sjr_score: Optional[float] = None
    citation_score_2yr: Optional[float] = None
    h_index: Optional[int] = None
    apc_usd: Optional[int] = None
    doaj_apc_amount: Optional[float] = None
    doaj_apc_currency: Optional[str] = None
    doaj_verified: Optional[bool] = None
    subject_areas: Optional[List[str]] = None
    total_citations: Optional[int] = None
    review_process: Optional[List[str]] = None


class QueryResponse(BaseModel):
    """Slim client response — LLM summary in ``answer``; raw journal rows are not returned."""

    query: str
    intent: str
    domain: str = ""
    answer: str = Field(..., description="Markdown summary for the user")
    results_count: int = 0
    source_note: Optional[str] = None
    fee_note: Optional[str] = None
    metrics_note: Optional[str] = None
    filter_quartile: Optional[str] = None
    error: Optional[str] = None
    suggestion: Optional[str] = None
    fallback_used: Optional[bool] = None
    reason: Optional[str] = None
    routing: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Lightweight routing hint (sources used).",
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "sources": ["OpenAlex", "DOAJ", "Scimago (local CSV)"],
    }


@app.get("/ask", response_model=QueryResponse)
def ask(
    q: str = Query(..., description="Natural language research question"),
):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    raw = jr.handle_query(q)
    intent = raw.get("intent")
    routing = jr.routing_metadata(str(intent))
    return QueryResponse(**presenter.build_api_response(raw, routing=routing))


if __name__ == "__main__":
    import uvicorn

    _port = int(os.getenv("JOURNAL_RESEARCH_STANDALONE_PORT", "8012"))
    _host = os.getenv("JOURNAL_RESEARCH_STANDALONE_HOST", "127.0.0.1")
    uvicorn.run(app, host=_host, port=_port)
