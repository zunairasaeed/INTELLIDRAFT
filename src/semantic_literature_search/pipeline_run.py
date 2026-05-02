"""
Standalone FastAPI app for semantic literature search (Semantic Scholar).

Run from project root (recommended):
    uvicorn src.semantic_literature_search.pipeline_run:app --reload --host 127.0.0.1 --port 8002

Or:
    python -m uvicorn src.semantic_literature_search.pipeline_run:app --reload --host 127.0.0.1 --port 8002

Requires SEMANTIC_SCHOLAR_API_KEY in the project `.env`.

Endpoints:
    POST /search/papers       — primary route
    POST /literature/search   — compatibility alias (same body/query params)
"""

import sys
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from .pipeline import run_pipeline
    from .input_validation import ValidationError
except ImportError:  # pragma: no cover - supports running as a script
    project_root = Path(__file__).resolve().parents[2]
    sys.path.append(str(project_root))
    from src.semantic_literature_search.pipeline import run_pipeline
    from src.semantic_literature_search.input_validation import ValidationError

DEFAULT_PORT = 8002


app = FastAPI(
    title="Semantic Literature Search API",
    description=(
        "Title + abstract → keyword query → Semantic Scholar paper search. "
        "Not bundled with the journal recommendation API."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["System"])
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "semantic_literature_search"}


class SearchRequest(BaseModel):
    title: str = Field(..., description="Paper title")
    abstract: str = Field(..., description="Paper abstract")


class SearchResponse(BaseModel):
    results: List[Dict[str, Any]]
    chat_response: str = Field(
        default="",
        description="Conversational ResearchPal rundown (Groq-generated from results)",
    )


async def _literature_search(
    payload: SearchRequest,
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    try:
        return await run_pipeline(
            title=payload.title,
            abstract=payload.abstract,
            limit=limit,
            offset=offset,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface as HTTP 500
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/search/papers", response_model=SearchResponse, tags=["Search"])
async def search_papers(
    payload: SearchRequest,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await _literature_search(payload, limit, offset)


@app.post("/literature/search", response_model=SearchResponse, tags=["Search"])
async def literature_search_alias(
    payload: SearchRequest,
    limit: int = Query(
        10,
        ge=1,
        le=100,
        description="Max number of papers to return",
    ),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """Same as POST /search/papers — kept so existing clients keep working."""
    return await _literature_search(payload, limit, offset)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.semantic_literature_search.pipeline_run:app",
        host="127.0.0.1",
        port=DEFAULT_PORT,
        reload=True,
    )
