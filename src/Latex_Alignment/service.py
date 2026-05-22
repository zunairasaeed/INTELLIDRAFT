"""Framework-agnostic service layer for the LaTeX Editor Agent.

This module owns the in-memory **working document** abstraction and the
ask / state / export / reset operations that the agentic flow needs.

Both the standalone testing app (``src.Latex_Alignment.api``) and the
main backend pipeline route (``backend.routes.pipelines``) use this
module so there is exactly one implementation. Frameworks (FastAPI /
anything else) just provide thin adapters around these functions.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .agent import LatexEditorAgent
from .agentic.executor import execute
from .agentic.intent_router import RoutedIntent, route_intent


# ════════════════════════════════════════════════════════════════════════════
# Workspace
# ════════════════════════════════════════════════════════════════════════════
class LatexWorkspace:
    """One in-memory working document. Replaced on every fresh upload.

    The instance is intentionally framework-free. Adapters (FastAPI etc.)
    hold and pass it around; identifying the right workspace per user /
    session is the adapter's job.
    """

    def __init__(self) -> None:
        self.workdir: Optional[Path] = None
        self.tex_path: Optional[Path] = None
        self.bib_path: Optional[Path] = None
        self.agent: Optional[LatexEditorAgent] = None
        self.original_tex_name: Optional[str] = None

    def is_loaded(self) -> bool:
        return self.agent is not None and self.tex_path is not None

    def reset(self) -> None:
        if self.workdir is not None and self.workdir.exists():
            shutil.rmtree(self.workdir, ignore_errors=True)
        self.workdir = None
        self.tex_path = None
        self.bib_path = None
        self.agent = None
        self.original_tex_name = None

    def load_files(
        self,
        tex_bytes: bytes,
        tex_filename: str,
        bib_bytes: Optional[bytes] = None,
        bib_filename: Optional[str] = None,
    ) -> None:
        """Wipe any previous workspace, write the new files to a temp dir, parse."""

        self.reset()
        self.workdir = Path(tempfile.mkdtemp(prefix="latex_align_ws_"))
        self.original_tex_name = Path(tex_filename).name
        self.tex_path = self.workdir / self.original_tex_name
        self.tex_path.write_bytes(tex_bytes)

        if bib_bytes is not None and bib_filename:
            self.bib_path = self.workdir / Path(bib_filename).name
            self.bib_path.write_bytes(bib_bytes)
        else:
            self.bib_path = None

        self.agent = LatexEditorAgent(
            str(self.tex_path),
            bib_path=str(self.bib_path) if self.bib_path else None,
        )
        self.agent.load()


# ════════════════════════════════════════════════════════════════════════════
# Result types (plain data — adapters serialize them however they want)
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class StatePayload:
    loaded: bool
    tex_filename: Optional[str] = None
    has_bib: bool = False
    doc_class: Optional[str] = None
    doc_style: Optional[str] = None
    section_count: int = 0
    bib_key_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "loaded": self.loaded,
            "tex_filename": self.tex_filename,
            "has_bib": self.has_bib,
            "doc_class": self.doc_class,
            "doc_style": self.doc_style,
            "section_count": self.section_count,
            "bib_key_count": self.bib_key_count,
            "metadata": self.metadata,
        }


@dataclass
class AskPayload:
    intent: str
    ok: bool
    summary: str
    section_id: Optional[str]
    section_title: Optional[str]
    file_changed: bool
    router: dict[str, Any]
    payload: dict[str, Any]
    state: StatePayload

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "ok": self.ok,
            "summary": self.summary,
            "section_id": self.section_id,
            "section_title": self.section_title,
            "file_changed": self.file_changed,
            "router": self.router,
            "payload": self.payload,
            "state": self.state.to_dict(),
        }


# ════════════════════════════════════════════════════════════════════════════
# Public operations (used by FastAPI adapters)
# ════════════════════════════════════════════════════════════════════════════
class WorkspaceError(Exception):
    """Raised when an operation cannot be completed against the workspace."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def build_state(workspace: LatexWorkspace) -> StatePayload:
    if not workspace.is_loaded() or workspace.agent is None:
        return StatePayload(loaded=False)
    doc = workspace.agent.load()
    return StatePayload(
        loaded=True,
        tex_filename=workspace.original_tex_name,
        has_bib=workspace.bib_path is not None,
        doc_class=doc.doc_class,
        doc_style=doc.doc_style,
        section_count=len(doc.sections),
        bib_key_count=len(doc.bib_keys),
        metadata=doc.metadata,
    )


def run_ask(
    workspace: LatexWorkspace,
    *,
    query: str,
    tex_bytes: Optional[bytes] = None,
    tex_filename: Optional[str] = None,
    bib_bytes: Optional[bytes] = None,
    bib_filename: Optional[str] = None,
) -> AskPayload:
    """Run one agentic ``/ask`` turn against the workspace.

    If ``tex_bytes`` is provided it replaces the working document before
    routing the query. If no working document exists and no ``tex_bytes``
    is provided, this raises :class:`WorkspaceError` (status 400).
    """

    if tex_bytes is not None:
        if not tex_filename or not tex_filename.lower().endswith(".tex"):
            raise WorkspaceError("tex_file must have a .tex filename", status_code=400)
        try:
            workspace.load_files(
                tex_bytes=tex_bytes,
                tex_filename=tex_filename,
                bib_bytes=bib_bytes,
                bib_filename=bib_filename,
            )
        except Exception as exc:  # noqa: BLE001
            workspace.reset()
            raise WorkspaceError(f"Failed to parse .tex: {exc}", status_code=400) from exc

    if not workspace.is_loaded() or workspace.agent is None:
        raise WorkspaceError(
            "No document loaded. Send tex_file with this request to start a working document.",
            status_code=400,
        )

    agent = workspace.agent
    try:
        agent.reload()
    except Exception as exc:  # noqa: BLE001
        raise WorkspaceError(f"Reload failed: {exc}", status_code=500) from exc

    doc = agent.load()
    routed: RoutedIntent = route_intent(
        query=query,
        sections=agent.list_sections(),
        metadata=doc.metadata,
    )
    result = execute(routed, agent)

    return AskPayload(
        intent=result.intent,
        ok=result.ok,
        summary=result.summary,
        section_id=result.section_id,
        section_title=result.section_title,
        file_changed=result.file_changed,
        router={
            "raw_intent": routed.intent,
            "section_id": routed.section_id,
            "section_title": routed.section_title,
            "instruction": routed.instruction,
            "has_user_content": routed.user_content is not None,
            "reasoning": routed.reasoning,
        },
        payload=result.payload,
        state=build_state(workspace),
    )


def export_tex(workspace: LatexWorkspace) -> tuple[str, str]:
    """Return ``(text, filename)`` for the current working ``.tex``.

    Raises :class:`WorkspaceError` (404) if no workspace is loaded.
    """

    if not workspace.is_loaded() or workspace.tex_path is None:
        raise WorkspaceError("No working document loaded.", status_code=404)
    text = workspace.tex_path.read_text(encoding="utf-8", errors="ignore")
    filename = workspace.original_tex_name or "document.tex"
    return text, filename


def reset_workspace(workspace: LatexWorkspace) -> dict[str, Any]:
    """Drop the working document. Idempotent; returns the prior loaded state."""

    was_loaded = workspace.is_loaded()
    workspace.reset()
    return {"status": "ok", "was_loaded": was_loaded, "loaded": False}


__all__ = [
    "LatexWorkspace",
    "StatePayload",
    "AskPayload",
    "WorkspaceError",
    "build_state",
    "run_ask",
    "export_tex",
    "reset_workspace",
]
