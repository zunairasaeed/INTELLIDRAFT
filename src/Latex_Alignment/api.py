# -*- coding: utf-8 -*-
"""LaTeX Editor Agent - Agentic FastAPI test surface.

Standalone testing::

    cd D:\\INTELLIDRAFT
    uvicorn src.Latex_Alignment.api:app --reload --host 127.0.0.1 --port 8020

Or simply::

    python -m src.Latex_Alignment.api

This module is intentionally session-free; the JWT-keyed per-user
workspace lives in the main backend at ``/pipelines/latex-alignment/*``
(see ``backend.routes.pipelines``). For local testing we hold ONE
working document in memory and reuse the shared service layer.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

_MODULE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _MODULE_DIR.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv(_PROJECT_ROOT / ".env")

from src.Latex_Alignment.service import (  # noqa: E402
    LatexWorkspace,
    WorkspaceError,
    build_state,
    export_tex,
    reset_workspace,
    run_ask,
)


# ════════════════════════════════════════════════════════════════════════════
# In-memory single working document (one per server process)
# ════════════════════════════════════════════════════════════════════════════
_WORKSPACE = LatexWorkspace()


# ════════════════════════════════════════════════════════════════════════════
# Response models
# ════════════════════════════════════════════════════════════════════════════
class StateOut(BaseModel):
    loaded: bool
    tex_filename: Optional[str] = None
    has_bib: bool = False
    doc_class: Optional[str] = None
    doc_style: Optional[str] = None
    section_count: int = 0
    bib_key_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class AskOut(BaseModel):
    intent: str
    ok: bool
    summary: str
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    file_changed: bool = False
    router: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    state: StateOut


# ════════════════════════════════════════════════════════════════════════════
# FastAPI app
# ════════════════════════════════════════════════════════════════════════════
app = FastAPI(
    title="LaTeX Editor Agent (Agentic)",
    description=(
        "Agentic LaTeX editor: upload a .tex (+ optional .bib) and ask in "
        "natural language - the LLM router picks the section and operation."
    ),
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["System"])
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "Latex_Alignment-agentic",
        "loaded": _WORKSPACE.is_loaded(),
        "groq_key_present": bool(os.environ.get("GROQ_API_KEY")),
    }


@app.get("/latex/state", response_model=StateOut, tags=["LaTeX"])
def get_state() -> StateOut:
    return StateOut(**build_state(_WORKSPACE).to_dict())


@app.post("/latex/ask", response_model=AskOut, tags=["LaTeX"])
async def ask(
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
    tex_file: Optional[UploadFile] = File(
        None, description=".tex source file. Optional after the first upload."
    ),
    bib_file: Optional[UploadFile] = File(
        None, description="Optional .bib bibliography."
    ),
) -> AskOut:
    tex_bytes: Optional[bytes] = None
    tex_filename: Optional[str] = None
    bib_bytes: Optional[bytes] = None
    bib_filename: Optional[str] = None

    if tex_file is not None and tex_file.filename:
        tex_bytes = await tex_file.read()
        tex_filename = tex_file.filename
        if bib_file is not None and bib_file.filename:
            bib_bytes = await bib_file.read()
            bib_filename = bib_file.filename

    try:
        result = run_ask(
            _WORKSPACE,
            query=query,
            tex_bytes=tex_bytes,
            tex_filename=tex_filename,
            bib_bytes=bib_bytes,
            bib_filename=bib_filename,
        )
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return AskOut(**result.to_dict())


@app.get(
    "/latex/export",
    response_class=PlainTextResponse,
    tags=["LaTeX"],
)
def export() -> PlainTextResponse:
    try:
        text, filename = export_tex(_WORKSPACE)
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return PlainTextResponse(
        text,
        media_type="text/x-tex; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/latex/reset", tags=["LaTeX"])
def reset() -> dict[str, Any]:
    return reset_workspace(_WORKSPACE)


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn

    _port = int(os.getenv("LATEX_ALIGNMENT_PORT", "8020"))
    _host = os.getenv("LATEX_ALIGNMENT_HOST", "127.0.0.1")
    uvicorn.run(app, host=_host, port=_port)
