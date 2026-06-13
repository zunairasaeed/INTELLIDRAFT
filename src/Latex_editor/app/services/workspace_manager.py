"""In-memory registry of per-session LaTeX workspaces, with optional
on-disk materialization.

A ``WorkspaceState`` carries the immutable identifiers (workspace_id,
session_id, user_id), the paths to the ``.tex`` and ``.bib`` files,
the current revision counter, and a per-instance ``asyncio.Lock``
that serialises edits on the same workspace.

When ``WorkspaceManager`` is constructed with a ``root`` directory,
``get_or_create`` will materialise a fresh ``main.tex`` skeleton on
disk for any session that doesn't supply its own paths. This is what
lets ``POST /sessions/ensure`` followed by ``POST /latex/messages``
work out-of-the-box with no upload step.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4


_STARTER_TEX = """\\documentclass{article}

\\begin{document}

\\section{Introduction}
This is a fresh LaTeX workspace. Send a message to the editor to
modify this section, add new ones, or restructure the document.

\\section{Methods}
Describe your approach here.

\\section{Results}
Summarise findings here.

\\section{Conclusion}
Wrap up here.

\\end{document}
"""


@dataclass
class WorkspaceState:
    workspace_id: UUID
    session_id: UUID
    user_id: UUID
    tex_path: Optional[Path] = None
    bib_path: Optional[Path] = None
    revision: int = 0
    lock: asyncio.Lock = asyncio.Lock()


class WorkspaceManager:
    """Per-session workspace registry.

    Parameters
    ----------
    root
        Optional filesystem root. When supplied, ``get_or_create``
        materialises a ``<root>/<workspace_id>/main.tex`` skeleton
        when no explicit ``tex_path`` is provided. When ``None``,
        the manager stays purely in-memory (useful for unit tests).
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self._workspaces: dict[UUID, WorkspaceState] = {}
        self._root: Path | None = Path(root) if root else None
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)

    def get_or_create(
        self,
        session_id: UUID,
        user_id: UUID,
        tex_path: Optional[str] = None,
        bib_path: Optional[str] = None,
        workspace_id: Optional[UUID] = None,
    ) -> WorkspaceState:
        if session_id in self._workspaces:
            return self._workspaces[session_id]

        wid = workspace_id or uuid4()

        resolved_tex: Path | None = Path(tex_path) if tex_path else None
        resolved_bib: Path | None = Path(bib_path) if bib_path else None

        if resolved_tex is None and self._root is not None:
            ws_dir = self._root / str(wid)
            ws_dir.mkdir(parents=True, exist_ok=True)
            resolved_tex = ws_dir / "main.tex"
            if not resolved_tex.exists():
                resolved_tex.write_text(_STARTER_TEX, encoding="utf-8")

        state = WorkspaceState(
            workspace_id=wid,
            session_id=session_id,
            user_id=user_id,
            tex_path=resolved_tex,
            bib_path=resolved_bib,
            revision=0,
            lock=asyncio.Lock(),
        )
        self._workspaces[session_id] = state
        return state

    def get(self, session_id: UUID) -> Optional[WorkspaceState]:
        return self._workspaces.get(session_id)

    def remove(self, session_id: UUID) -> None:
        self._workspaces.pop(session_id, None)
