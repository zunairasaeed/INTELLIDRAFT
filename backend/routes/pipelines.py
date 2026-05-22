"""
Unified pipeline endpoints — all AI chains exposed on the main backend port.

Prefer this unified router over running multiple standalone uvicorn processes on different ports.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.semantic_literature_search.pipeline import run_pipeline as run_literature_pipeline
from src.semantic_literature_search.input_validation import ValidationError
from src.Research_and_publishing_guide_bot.rag_engine import ResearchGuideRAG, get_rag

_JOURNAL_RESEARCH_DIR = PROJECT_ROOT / "src" / "Journel_Research_Assistant"
if str(_JOURNAL_RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_JOURNAL_RESEARCH_DIR))
import journal_research as journal_research_chain  # noqa: E402
import final_response_agent as journal_research_presenter  # noqa: E402

from src.Latex_Alignment.service import (  # noqa: E402
    LatexWorkspace,
    WorkspaceError,
    build_state,
    export_tex,
    reset_workspace,
    run_ask,
)

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])

# ── Process-wide LaTeX-alignment working document ──────────────────────────
# Single in-memory workspace per backend process. The full per-(user, session)
# variant lives in service.py and will be plumbed through here once the
# Supabase Storage handoff is wired (Phase 2 of latex_alignment integration).
_LATEX_WORKSPACE = LatexWorkspace()

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


class LatexAlignmentStateOut(BaseModel):
    loaded: bool
    tex_filename: str | None = None
    has_bib: bool = False
    doc_class: str | None = None
    doc_style: str | None = None
    section_count: int = 0
    bib_key_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LatexAlignmentAskOut(BaseModel):
    intent: str
    ok: bool
    summary: str
    section_id: str | None = None
    section_title: str | None = None
    file_changed: bool = False
    router: Dict[str, Any] = Field(default_factory=dict)
    payload: Dict[str, Any] = Field(default_factory=dict)
    state: LatexAlignmentStateOut


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
            "available": False,
            "deprecated": True,
            "note": "Removed from repo. Use journal_research_assistant (Journel_Research_Assistant).",
            "legacy_post": "/pipelines/journal/recommend",
        },
        "semantic_literature_search": {
            "available": _literature_has_api_key(),
            "post": "/pipelines/literature/search",
            "get": "/pipelines/literature/health",
            "note": "Set SEMANTIC_SCHOLAR_API_KEY when unavailable",
        },
        # Chain id matches Feature.research_publishing_guide; RAG code: src/Research_and_publishing_guide_bot/
        "research_publishing_guide": {
            "available": rag.is_ready,
            "post_ask": "/pipelines/research-guide/ask",
            "post_search": "/pipelines/research-guide/search",
            "get": "/pipelines/research-guide/health",
            "startup_error": rag_err if not rag.is_ready else None,
        },
        "latex_alignment": {
            "available": True,
            "get_health":          "/pipelines/latex-alignment/health",
            "post_ask":            "/pipelines/latex-alignment/ask",
            "get_state":           "/pipelines/latex-alignment/state",
            "get_sections":        "/pipelines/latex-alignment/sections",
            "get_section":         "/pipelines/latex-alignment/sections/{id}",
            "put_section_replace": "/pipelines/latex-alignment/sections/{id}",
            "get_export":          "/pipelines/latex-alignment/export",
            "delete_reset":        "/pipelines/latex-alignment/reset",
            "get_citations_guide": "/pipelines/latex-alignment/citations",
            "authenticated_crud": "/citations",
            "loaded": _LATEX_WORKSPACE.is_loaded(),
            "note": (
                "Agentic LaTeX editor: upload .tex (+ optional .bib) and ask in "
                "natural language. The router picks the section and operation."
            ),
        },
        "journal_research_assistant": {
            "available": True,
            "get_ask": "/pipelines/journal-research/ask",
            "get": "/pipelines/journal-research/health",
            "note": "OpenAlex + DOAJ + local Scimago CSV; same logic as src/Journel_Research_Assistant",
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1 — Legacy journal information assistant (removed; use journal-research below)
# ═══════════════════════════════════════════════════════════════════════════


_JOURNAL_LEGACY_MSG = (
    "The publisher-mapping module (journal_information_assistant) is not in this repo. "
    "Use GET /pipelines/journal-research/ask?q=... (Journel_Research_Assistant)."
)


@router.get("/journal/health")
def journal_health() -> Dict[str, Any]:
    return {
        "status": "deprecated",
        "chain": "journal_information_assistant",
        "use_instead": "/pipelines/journal-research/health",
    }


@router.post("/journal/recommend", summary="[Deprecated] use /pipelines/journal-research/ask")
def journal_recommend(_request: JournalRecommendRequest) -> Dict[str, Any]:
    raise HTTPException(status_code=410, detail=_JOURNAL_LEGACY_MSG)


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
# 3b — Journal research assistant (NL query → OpenAlex + DOAJ + Scimago CSV)
# ═══════════════════════════════════════════════════════════════════════════


def _journal_research_csv_path() -> Path:
    rel = os.getenv(
        "JOURNAL_RESEARCH_SCIMAGO_CSV_PATH",
        "database/Journel_recommendations/scimagojr.csv",
    )
    p = Path(rel)
    return p if p.is_absolute() else PROJECT_ROOT / p


@router.get("/journal-research/health")
def journal_research_health() -> Dict[str, Any]:
    csv_p = _journal_research_csv_path()
    return {
        "status": "ok",
        "chain": "journal_research_assistant",
        "scimago_csv_present": csv_p.is_file(),
        "scimago_csv_path": str(csv_p),
    }


@router.get(
    "/journal-research/ask",
    summary="Natural-language journal question → OpenAlex + Scimago CSV + optional DOAJ",
)
def journal_research_ask(
    q: str = Query(..., description="Natural language research question"),
) -> Dict[str, Any]:
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    raw = journal_research_chain.handle_query(q.strip())
    routing = journal_research_chain.routing_metadata(str(raw.get("intent")))
    return journal_research_presenter.build_api_response(raw, routing=routing)


# ═══════════════════════════════════════════════════════════════════════════
# 5 — LaTeX alignment (agentic editor)
#
# Same inputs as the standalone src/Latex_Alignment/api.py test surface:
#   - multipart `tex_file` (.tex)
#   - optional multipart `bib_file` (.bib)
#   - form-field `query` (natural-language ask)
#
# Plus state / export / reset for the working document.
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/latex-alignment/health")
def latex_alignment_health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "chain": "latex_alignment",
        "loaded": _LATEX_WORKSPACE.is_loaded(),
        "groq_key_present": bool(os.getenv("GROQ_API_KEY")),
        "endpoints": {
            "ask":             "/pipelines/latex-alignment/ask",
            "state":           "/pipelines/latex-alignment/state",
            "sections":        "/pipelines/latex-alignment/sections",
            "section":         "/pipelines/latex-alignment/sections/{id}",
            "section_replace": "PUT /pipelines/latex-alignment/sections/{id}",
            "export":          "/pipelines/latex-alignment/export",
            "reset":           "/pipelines/latex-alignment/reset",
        },
        "citations": {
            "crud_on": "/citations",
            "discovery": "/pipelines/latex-alignment/citations",
        },
    }


@router.post(
    "/latex-alignment/ask",
    response_model=LatexAlignmentAskOut,
    summary="Agentic LaTeX editor — upload .tex (+ optional .bib) and ask in natural language",
)
async def latex_alignment_ask(
    query: str = Form(
        ...,
        description=(
            "Natural-language instruction. Examples: "
            "'rewrite the introduction to be more formal', "
            "'add a paragraph about LaTeX to the methodology', "
            "'replace the abstract with this: \\textbf{Hello}', "
            "'delete the results section', 'list all sections', "
            "'show me the introduction', 'summarize this paper'."
        ),
    ),
    tex_file: UploadFile | None = File(
        None, description=".tex source file. Optional after the first upload."
    ),
    bib_file: UploadFile | None = File(
        None, description="Optional .bib bibliography."
    ),
) -> LatexAlignmentAskOut:
    tex_bytes: bytes | None = None
    tex_filename: str | None = None
    bib_bytes: bytes | None = None
    bib_filename: str | None = None

    if tex_file is not None and tex_file.filename:
        tex_bytes = await tex_file.read()
        tex_filename = tex_file.filename
        if bib_file is not None and bib_file.filename:
            bib_bytes = await bib_file.read()
            bib_filename = bib_file.filename

    try:
        result = run_ask(
            _LATEX_WORKSPACE,
            query=query,
            tex_bytes=tex_bytes,
            tex_filename=tex_filename,
            bib_bytes=bib_bytes,
            bib_filename=bib_filename,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return LatexAlignmentAskOut(**result.to_dict())


@router.get(
    "/latex-alignment/state",
    response_model=LatexAlignmentStateOut,
    summary="Is a working document loaded? Document metadata + counts.",
)
def latex_alignment_state() -> LatexAlignmentStateOut:
    return LatexAlignmentStateOut(**build_state(_LATEX_WORKSPACE).to_dict())


@router.get(
    "/latex-alignment/sections",
    summary="Fast non-LLM list of sections for the editor sidebar",
)
def latex_alignment_sections() -> Dict[str, Any]:
    if not _LATEX_WORKSPACE.is_loaded() or _LATEX_WORKSPACE.agent is None:
        raise HTTPException(status_code=404, detail="No working document loaded.")
    sections = _LATEX_WORKSPACE.agent.list_sections()
    return {
        "count": len(sections),
        "sections": [
            {
                "id": s.id,
                "title": s.title,
                "cmd": s.cmd,
                "depth": s.depth,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "line_count": max(0, s.end_line - s.start_line + 1),
                "is_empty": s.is_empty,
                "is_implicit": s.is_implicit,
                "citations": s.citations,
                "labels": s.labels,
            }
            for s in sections
        ],
    }


@router.get(
    "/latex-alignment/sections/{section_id}",
    summary="Fast non-LLM fetch of one section's raw lines",
)
def latex_alignment_section_detail(section_id: str) -> Dict[str, Any]:
    if not _LATEX_WORKSPACE.is_loaded() or _LATEX_WORKSPACE.agent is None:
        raise HTTPException(status_code=404, detail="No working document loaded.")
    try:
        section = _LATEX_WORKSPACE.agent.get_section(section_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "id": section.id,
        "title": section.title,
        "cmd": section.cmd,
        "depth": section.depth,
        "start_line": section.start_line,
        "end_line": section.end_line,
        "line_count": max(0, section.end_line - section.start_line + 1),
        "is_empty": section.is_empty,
        "is_implicit": section.is_implicit,
        "citations": section.citations,
        "labels": section.labels,
        "raw_lines": section.raw_lines,
        "raw_text": "".join(section.raw_lines),
    }


class LatexSectionEditRequest(BaseModel):
    """Direct in-place edit — user-supplied LaTeX replaces the section body literally.

    No LLM call. The section header line is preserved for explicit sections by
    ``agent.replace_content`` (it knows the body range starts after the header).
    """

    content: str = Field(
        ...,
        description=(
            "Replacement body text. For explicit \\section{} headers do NOT include "
            "the header line — only the body. For implicit sections (abstract, acks, "
            "appendix, etc.) include the full block."
        ),
    )


@router.put(
    "/latex-alignment/sections/{section_id}",
    summary="Replace a section's body with literal user text (no LLM call)",
)
def latex_alignment_section_replace(
    section_id: str, body: LatexSectionEditRequest
) -> Dict[str, Any]:
    if not _LATEX_WORKSPACE.is_loaded() or _LATEX_WORKSPACE.agent is None:
        raise HTTPException(status_code=404, detail="No working document loaded.")
    try:
        before = _LATEX_WORKSPACE.agent.get_section(section_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        result = _LATEX_WORKSPACE.agent.replace_content(section_id, body.content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    after_raw: list[str] = []
    after_lines = 0
    try:
        after = _LATEX_WORKSPACE.agent.get_section(section_id)
        after_raw = after.raw_lines
        after_lines = max(0, after.end_line - after.start_line + 1)
    except KeyError:
        after_raw = result.edited_lines
        after_lines = len(result.edited_lines)

    return {
        "ok": True,
        "section_id": section_id,
        "section_title": before.title,
        "start_line": result.start_line,
        "end_line": result.end_line,
        "lines_before": len(result.original_lines),
        "lines_after": after_lines,
        "raw_text": "".join(after_raw),
        "summary": (
            f"Saved '{before.title}' — {len(result.original_lines)} → {after_lines} lines."
        ),
    }


@router.get(
    "/latex-alignment/export",
    response_class=PlainTextResponse,
    summary="Download the current edited .tex (attachment)",
)
def latex_alignment_export() -> PlainTextResponse:
    try:
        text, filename = export_tex(_LATEX_WORKSPACE)
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return PlainTextResponse(
        text,
        media_type="text/x-tex; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/latex-alignment/reset",
    summary="Drop the working document and clean temp files",
)
def latex_alignment_reset() -> Dict[str, Any]:
    return reset_workspace(_LATEX_WORKSPACE)


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


# ── Deprecated stubs (kept for backward compatibility) ─────────────────────
@router.post(
    "/latex-alignment/template",
    summary="[Deprecated] use /pipelines/latex-alignment/ask",
    deprecated=True,
)
def latex_alignment_template_deprecated() -> Dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail=(
            "Endpoint deprecated. Use POST /pipelines/latex-alignment/ask "
            "with multipart `query` + optional `tex_file` + optional `bib_file`."
        ),
    )


@router.post(
    "/latex-alignment/assist",
    summary="[Deprecated] use /pipelines/latex-alignment/ask",
    deprecated=True,
)
def latex_alignment_assist_deprecated() -> Dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail=(
            "Endpoint deprecated. Use POST /pipelines/latex-alignment/ask "
            "with multipart `query` + optional `tex_file` + optional `bib_file`."
        ),
    )
