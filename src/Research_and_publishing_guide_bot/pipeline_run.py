"""
FastAPI entrypoint for the Research & Publishing Guide RAG pipeline.

Run from project root:
    uvicorn src.Research_and_publishing_guide_bot.pipeline_run:app --reload --port 8010

Requires:
    - GROQ_API_KEY in .env (project root) for call_gpt
    - FAISS bundle in database/ (run create_embeddings; writes paper_guide_rag.faiss + paper_guide_rag_meta.json)
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

_BOT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BOT_DIR.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.Research_and_publishing_guide_bot.rag_engine import (  # noqa: E402
    ResearchGuideRAG,
    get_rag,
)


_rag: Optional[ResearchGuideRAG] = None
_startup_error: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _rag, _startup_error
    _startup_error = None
    try:
        r = get_rag()
        r.load()
        _rag = r
    except Exception as e:
        _startup_error = str(e)
        _rag = None
    yield


app = FastAPI(
    title="Research & Publishing Guide RAG",
    description="ResearchGuide (IntelliDraft): FAISS retrieval + synthesized mentor-style answers via Groq (call_gpt).",
    version="0.1.0",
    lifespan=lifespan,
)


class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User question about writing/publishing/review")
    top_k: int = Field(5, ge=1, le=20, description="Number of chunks to retrieve")
    refine_query: bool = Field(True, description="Use LLM to compress question into a search query")


class AskResponse(BaseModel):
    answer: str
    retrieval_query: str
    sources: List[Dict[str, Any]]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=20)


@app.get("/health")
def health() -> Dict[str, Any]:
    ok = _rag is not None and _rag.is_ready
    return {
        "status": "ok" if ok else "degraded",
        "rag_ready": ok,
        "index_path": str(ResearchGuideRAG().index_path()),
        "meta_path": str(ResearchGuideRAG().meta_path()),
        "error": _startup_error,
    }


@app.post("/rag/ask", response_model=AskResponse)
def rag_ask(body: AskRequest) -> AskResponse:
    if _rag is None:
        raise HTTPException(
            status_code=503,
            detail=_startup_error or "RAG not initialized. Build index with create_embeddings.",
        )
    try:
        out = _rag.answer(
            user_query=body.query,
            top_k=body.top_k,
            use_query_refinement=body.refine_query,
        )
        return AskResponse(**out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/rag/search")
def rag_search(body: SearchRequest) -> Dict[str, Any]:
    """Retrieve only (no LLM answer) — useful for debugging."""
    if _rag is None:
        raise HTTPException(status_code=503, detail=_startup_error or "RAG not initialized.")
    try:
        hits = _rag.search(body.query.strip(), top_k=body.top_k)
        return {"query": body.query, "hits": hits}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.Research_and_publishing_guide_bot.pipeline_run:app",
        host="127.0.0.1",
        port=8010,
        reload=False,
    )
