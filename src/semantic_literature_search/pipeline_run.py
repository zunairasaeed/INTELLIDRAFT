import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from .pipeline import run_pipeline
    from .input_validation import ValidationError
except ImportError:  # pragma: no cover - supports running as a script
    project_root = Path(__file__).resolve().parents[2]
    sys.path.append(str(project_root))
    from src.semantic_literature_search.pipeline import run_pipeline
    from src.semantic_literature_search.input_validation import ValidationError

app = FastAPI(title="Literature Search API")


class SearchRequest(BaseModel):
    title: str = Field(..., description="Paper title")
    abstract: str = Field(..., description="Paper abstract")


@app.post("/search/papers", response_model=Dict[str, Any])
async def search_papers(
    payload: SearchRequest,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.semantic_literature_search.pipeline_run:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
