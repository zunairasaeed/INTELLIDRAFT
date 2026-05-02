"""
Unified pipeline endpoints — all AI chains exposed on the main backend port.

Use these instead of separate uvicorn apps on 8000 / 8002 / 8010 when testing from one origin.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.journal_information_assistant.publisher_mapping_engine.pipeline_run import (
    run_pipeline as run_journal_pipeline,
)
from src.semantic_literature_search.pipeline import run_pipeline as run_literature_pipeline
from src.semantic_literature_search.input_validation import ValidationError
from src.Research_and_publishing_guide_bot.rag_engine import ResearchGuideRAG, get_rag

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])

# ── Request / response models (aligned with standalone apps) ───────────────


class JournalRecommendRequest(BaseModel):
    title: str = ""
    abstract: str = ""
    user_input: str = ""


class LiteratureSearchRequest(BaseModel):
    title: str = Field(..., description="Paper title")
    abstract: str = Field(..., description="Paper abstract")


class ResearchGuideAskRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Question about writing / publishing / review")
    top_k: int = Field(5, ge=1, le=20)
    refine_query: bool = Field(True, description="LLM compression for retrieval query")


class ResearchGuideSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=20)


class LatexAlignmentTemplateRequest(BaseModel):
    """Placeholder until the LaTeX alignment / template chain is implemented."""

    prompt: str = ""
    document_type: str = Field("article", description='e.g. "article", "ieeeconf"')


class LatexAlignmentAssistRequest(BaseModel):
    """Placeholder for future LaTeX-alignment / citation assistant."""

    message: str = ""


def _literature_has_api_key() -> bool:
    return bool(os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip())


def _research_guide_startup_error(request: Request) -> str | None:
    return getattr(request.app.state, "research_guide_error", None)


# ═══════════════════════════════════════════════════════════════════════════
# Aggregate status — one GET for the whole matrix
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/status", summary="Status of every pipeline chain")
def pipelines_status(request: Request) -> Dict[str, Any]:
    rag = get_rag()
    rag_err = _research_guide_startup_error(request)
    return {
        "journal_information_assistant": {
            "available": True,
            "post": "/pipelines/journal/recommend",
            "get": "/pipelines/journal/health",
        },
        "semantic_literature_search": {
            "available": _literature_has_api_key(),
            "post": "/pipelines/literature/search",
            "get": "/pipelines/literature/health",
            "note": "Set SEMANTIC_SCHOLAR_API_KEY when unavailable",
        },
        "research_publishing_guide": {
            "available": rag.is_ready,
            "post_ask": "/pipelines/research-guide/ask",
            "post_search": "/pipelines/research-guide/search",
            "get": "/pipelines/research-guide/health",
            "startup_error": rag_err if not rag.is_ready else None,
        },
        "latex_alignment": {
            "available": True,
            "get_health": "/pipelines/latex-alignment/health",
            "post_template_stub": "/pipelines/latex-alignment/template",
            "get_citations_guide": "/pipelines/latex-alignment/citations",
            "post_assist_stub": "/pipelines/latex-alignment/assist",
            "authenticated_crud": "/citations",
            "note": "LaTeX alignment: template stub + citation workflow (CRUD on /citations)",
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1 — Journal information assistant
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/journal/health")
def journal_health() -> Dict[str, str]:
    return {"status": "ok", "chain": "journal_information_assistant"}


@router.post("/journal/recommend", summary="Title + abstract / user_input → publisher recommendation")
def journal_recommend(request: JournalRecommendRequest) -> Dict[str, Any]:
    if not (
        request.user_input.strip()
        or (request.title.strip() and request.abstract.strip())
    ):
        raise HTTPException(
            status_code=422,
            detail="Provide either user_input, or both title and abstract.",
        )
    try:
        return run_journal_pipeline(
            title=request.title,
            abstract=request.abstract,
            user_input=request.user_input,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════════════════
# 2 — Semantic literature search
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/literature/health")
def literature_health() -> Dict[str, Any]:
    ok = _literature_has_api_key()
    return {
        "status": "ok" if ok else "degraded",
        "chain": "semantic_literature_search",
        "api_key_configured": ok,
    }


async def _run_literature(
    payload: LiteratureSearchRequest, limit: int, offset: int
) -> Dict[str, Any]:
    try:
        return await run_literature_pipeline(
            title=payload.title,
            abstract=payload.abstract,
            limit=limit,
            offset=offset,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/literature/search", summary="Title + abstract → Semantic Scholar papers")
async def literature_search(
    payload: LiteratureSearchRequest,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await _run_literature(payload, limit, offset)


@router.post("/literature/search/papers", summary="Alias of /literature/search")
async def literature_search_papers_alias(
    payload: LiteratureSearchRequest,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await _run_literature(payload, limit, offset)


# ═══════════════════════════════════════════════════════════════════════════
# 3 — Research & publishing guide (RAG)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/research-guide/health")
def research_guide_health(request: Request) -> Dict[str, Any]:
    rag = get_rag()
    err = _research_guide_startup_error(request)
    ok = rag.is_ready
    return {
        "status": "ok" if ok else "degraded",
        "chain": "research_publishing_guide",
        "rag_ready": ok,
        "index_path": str(ResearchGuideRAG().index_path()),
        "meta_path": str(ResearchGuideRAG().meta_path()),
        "startup_error": err if not ok else None,
    }


@router.post("/research-guide/ask")
def research_guide_ask(body: ResearchGuideAskRequest, request: Request) -> Dict[str, Any]:
    rag = get_rag()
    if not rag.is_ready:
        startup = getattr(request.app.state, "research_guide_error", None)
        raise HTTPException(
            status_code=503,
            detail=startup
            or (
                "RAG not ready. Ensure database/paper_guide_rag.faiss and "
                "paper_guide_rag_meta.json exist under database/ "
                "(run create_embeddings)."
            ),
        )
    try:
        return rag.answer(
            user_query=body.query,
            top_k=body.top_k,
            use_query_refinement=body.refine_query,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/research-guide/search", summary="Retrieve chunks only (no LLM answer)")
def research_guide_search(body: ResearchGuideSearchRequest, request: Request) -> Dict[str, Any]:
    rag = get_rag()
    if not rag.is_ready:
        startup = getattr(request.app.state, "research_guide_error", None)
        raise HTTPException(
            status_code=503,
            detail=startup or "RAG not ready. Build the FAISS bundle under database/.",
        )
    try:
        hits = rag.search(body.query.strip(), top_k=body.top_k)
        return {"query": body.query, "hits": hits}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ═══════════════════════════════════════════════════════════════════════════
# 4 — LaTeX alignment (template stub + citation workflow under one chain name)
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/latex-alignment/health")
def latex_alignment_health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "chain": "latex_alignment",
        "template_ai": {
            "implemented": False,
            "post": "/pipelines/latex-alignment/template",
        },
        "citations": {
            "crud_on": "/citations",
            "discovery": "/pipelines/latex-alignment/citations",
        },
    }


@router.post(
    "/latex-alignment/template",
    summary="Placeholder for future LaTeX / template alignment AI",
)
def latex_alignment_template(body: LatexAlignmentTemplateRequest) -> Dict[str, Any]:
    return {
        "success": False,
        "chain": "latex_alignment",
        "facet": "template",
        "message": "LaTeX alignment (template generation) is not implemented yet.",
        "echo": {
            "document_type": body.document_type,
            "prompt_preview": (body.prompt or "")[:500],
        },
    }


@router.get("/latex-alignment/citations", summary="How to use authenticated /citations")
def latex_alignment_citations_guide() -> Dict[str, Any]:
    return {
        "chain": "latex_alignment",
        "facet": "citations",
        "authenticated_base": "/citations",
        "routes": {
            "save": {"method": "POST", "path": "/citations/save"},
            "save_from_search": {"method": "POST", "path": "/citations/save-from-search"},
            "list": {"method": "GET", "path": "/citations/"},
            "export_bibtex": {"method": "GET", "path": "/citations/export/bibtex"},
            "export_latex": {"method": "GET", "path": "/citations/export/latex"},
            "export_ieee": {"method": "GET", "path": "/citations/export/ieee"},
            "export_apa": {"method": "GET", "path": "/citations/export/apa"},
            "delete": {"method": "DELETE", "path": "/citations/{citation_id}"},
        },
        "authorization": "Bearer JWT (same as rest of IntelliDraft backend)",
    }


@router.post("/latex-alignment/assist", summary="Placeholder LaTeX-alignment assistant")
def latex_alignment_assist(body: LatexAlignmentAssistRequest) -> Dict[str, Any]:
    return {
        "success": False,
        "chain": "latex_alignment",
        "facet": "assist",
        "message": (
            "AI assist for LaTeX alignment is not implemented yet. "
            "Use /citations (authenticated) for bibliography storage and export."
        ),
        "message_echo": (body.message or "")[:800],
    }
