"""Service layer for the LaTeX editor — drop-in for the legacy Latex_Alignment API.

Used by ``backend.routes.pipelines`` at ``/pipelines/latex-alignment/*``.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .editor.operations import rewrite as op_rewrite
from .editor.serializer import serialize
from .parser.parser import DocumentTree, SectionNode, find_node
from .session import Session


class WorkspaceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


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


@dataclass
class LegacySection:
    id: str
    title: str
    cmd: str
    depth: int
    start_line: int
    end_line: int
    content_hash: str = ""
    citations: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    is_empty: bool = False
    is_implicit: bool = False
    raw_lines: list[str] = field(default_factory=list)
    parent_id: str | None = None
    children: list[str] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return max(0, self.end_line - self.start_line + 1)


@dataclass
class EditResult:
    section_id: str
    original_lines: list[str]
    edited_lines: list[str]
    start_line: int
    end_line: int
    was_empty: bool


def _extract_citations(raw: str) -> list[str]:
    keys: list[str] = []
    for match in re.findall(r"\\cite\{([^}]+)\}", raw):
        keys.extend(k.strip() for k in match.split(",") if k.strip())
    return keys


def _extract_labels(raw: str) -> list[str]:
    return re.findall(r"\\label\{([^}]+)\}", raw)


def _node_raw_text(node: SectionNode) -> str:
    parts = [b.raw.strip() for b in node.content_blocks if b.raw.strip()]
    return "\n\n".join(parts)


def _legacy_raw_lines(node: SectionNode) -> list[str]:
    """Build raw_lines the way LatexEditor.jsx expects (header/env wrapper included).

    The frontend strips line 0 for explicit ``\\section{}`` blocks and strips
    ``\\begin{}`` / ``\\end{}`` for implicit env sections before showing the
    editable body. Body-only lines caused empty editors and autosave wipe loops.
    """
    lines: list[str] = []

    if node.env_wrapper:
        lines.append(f"\\begin{{{node.env_wrapper}}}\n")
    else:
        level_cmd = {1: "\\section", 2: "\\subsection", 3: "\\subsubsection"}
        cmd = level_cmd.get(node.level, "\\section")
        if not node.numbered:
            cmd += "*"
        lines.append(f"{cmd}{{{node.label}}}\n")
        if node.label_tag and node.numbered:
            lines.append(f"\\label{{{node.label_tag}}}\n")

    body = _node_raw_text(node)
    if body:
        body_lines = body.splitlines(keepends=True)
        if body_lines and not body_lines[-1].endswith("\n"):
            body_lines[-1] += "\n"
        lines.extend(body_lines)

    if node.env_wrapper:
        lines.append(f"\\end{{{node.env_wrapper}}}\n")

    return lines


def _node_to_legacy(node: SectionNode, line_counter: list[int]) -> LegacySection:
    raw = _node_raw_text(node)
    lines = _legacy_raw_lines(node)
    line_count = max(len(lines), 1)
    start = line_counter[0]
    end = start + line_count - 1
    line_counter[0] = end + 1

    if node.env_wrapper == "abstract":
        cmd = "abstract"
    elif node.env_wrapper == "acks":
        cmd = "acks"
    elif node.level == 1:
        cmd = "section"
    elif node.level == 2:
        cmd = "subsection"
    else:
        cmd = "subsubsection"

    return LegacySection(
        id=node.id,
        title=node.label,
        cmd=cmd,
        depth=node.level,
        start_line=start,
        end_line=end,
        content_hash="",
        citations=_extract_citations(raw),
        labels=_extract_labels(raw),
        is_empty=not bool(raw.strip()),
        is_implicit=node.env_wrapper is not None,
        raw_lines=lines,
    )


def _flatten_sections(tree: DocumentTree) -> list[LegacySection]:
    counter = [1]
    result: list[LegacySection] = []

    def walk(nodes: list[SectionNode]) -> None:
        for node in nodes:
            result.append(_node_to_legacy(node, counter))
            walk(node.children)

    if tree.abstract:
        result.append(_node_to_legacy(tree.abstract, counter))
    walk(tree.body)
    if tree.acks:
        result.append(_node_to_legacy(tree.acks, counter))
    for section in tree.appendix_sections:
        result.append(_node_to_legacy(section, counter))
    return result


class AgentFacade:
    """Mimics ``LatexEditorAgent`` for the routes that call ``workspace.agent``."""

    def __init__(self, workspace: LatexWorkspace) -> None:
        self._ws = workspace

    def load(self) -> DocumentTree:
        if self._ws.session is None:
            raise WorkspaceError("No document loaded.", 404)
        return self._ws.session.tree

    def reload(self) -> DocumentTree:
        return self.load()

    def list_sections(self) -> list[LegacySection]:
        if self._ws.session is None:
            return []
        return _flatten_sections(self._ws.session.tree)

    def get_section(self, section_id: str) -> LegacySection:
        for section in self.list_sections():
            if section.id == section_id:
                return section
        raise KeyError(f"Section not found: {section_id}")

    def replace_content(self, section_id: str, content: str) -> EditResult:
        if self._ws.session is None:
            raise WorkspaceError("No document loaded.", 404)

        before = self.get_section(section_id)
        original_lines = list(before.raw_lines)
        edited_lines = content.splitlines(keepends=True)
        if content and not content.endswith("\n") and edited_lines:
            edited_lines[-1] = edited_lines[-1].rstrip("\n") + "\n"

        new_tree, _warnings = op_rewrite(self._ws.session.tree, section_id, content)
        self._ws.session.tree = new_tree
        self._ws._persist_tex()

        after = self.get_section(section_id)
        return EditResult(
            section_id=section_id,
            original_lines=original_lines,
            edited_lines=edited_lines or list(after.raw_lines),
            start_line=after.start_line,
            end_line=after.end_line,
            was_empty=before.is_empty,
        )


class LatexWorkspace:
    def __init__(self) -> None:
        self.session: Optional[Session] = None
        self.workdir: Optional[Path] = None
        self.tex_path: Optional[Path] = None
        self.bib_path: Optional[Path] = None
        self.original_tex_name: Optional[str] = None
        self.bib_content: str = ""
        self.agent: Optional[AgentFacade] = AgentFacade(self)

    def is_loaded(self) -> bool:
        return self.session is not None and self.tex_path is not None

    def reset(self) -> None:
        if self.workdir is not None and self.workdir.exists():
            import shutil

            shutil.rmtree(self.workdir, ignore_errors=True)
        self.session = None
        self.workdir = None
        self.tex_path = None
        self.bib_path = None
        self.original_tex_name = None
        self.bib_content = ""

    def load_files(
        self,
        tex_bytes: bytes,
        tex_filename: str,
        bib_bytes: Optional[bytes] = None,
        bib_filename: Optional[str] = None,
    ) -> None:
        self.reset()
        tex_text = tex_bytes.decode("utf-8", errors="replace")
        bib_text = bib_bytes.decode("utf-8", errors="replace") if bib_bytes else ""

        self.original_tex_name = Path(tex_filename).name
        self.bib_content = bib_text
        self.session = Session(tex_text, bib_text)

        self.workdir = Path(tempfile.mkdtemp(prefix="latex_align_ws_"))
        self.tex_path = self.workdir / self.original_tex_name
        self.tex_path.write_text(tex_text, encoding="utf-8")
        self._persist_tex()

        if bib_bytes and bib_filename:
            self.bib_path = self.workdir / Path(bib_filename).name
            self.bib_path.write_bytes(bib_bytes)
        else:
            self.bib_path = None

    def _persist_tex(self) -> None:
        if self.tex_path and self.session:
            self.tex_path.write_text(serialize(self.session.tree), encoding="utf-8")


_ACTION_TO_INTENT = {
    "rewrite": "edit",
    "replace_paragraph": "edit",
    "add_paragraph": "add",
    "add_section": "insert_section",
    "add_subsection": "insert_section",
    "add_subsubsection": "insert_section",
    "rename": "rename_section",
    "delete": "delete_section",
    "move": "move_section",
    "set_title": "edit",
    "list_sections": "list_sections",
    "show_section": "show_section",
    "summarize": "summarize",
    "clarify": "unknown",
}

_READ_ONLY_ACTIONS = frozenset({"list_sections", "show_section", "summarize", "get_structure", "clarify"})


def _count_sections(tree: DocumentTree) -> int:
    count = 0

    def walk(nodes: list[SectionNode]) -> None:
        nonlocal count
        for node in nodes:
            count += 1
            walk(node.children)

    if tree.abstract:
        count += 1
    walk(tree.body)
    if tree.acks:
        count += 1
    count += len(tree.appendix_sections)
    return count


def _build_summary(act: str, action: dict, section_title: str, warnings: list[str]) -> str:
    label = action.get("label", "")
    content_preview = (action.get("content") or "")[:60]
    summaries = {
        "add_paragraph": f"Added paragraph to '{section_title}'",
        "add_section": f"Added new section '{label}'",
        "add_subsection": f"Added subsection '{label}' under '{section_title}'",
        "add_subsubsection": f"Added subsubsection '{label}'",
        "rename": f"Renamed section to '{action.get('new_label', '')}'",
        "delete": f"Deleted section '{section_title}'",
        "rewrite": f"Rewrote '{section_title}': {content_preview}...",
        "replace_paragraph": f"Replaced paragraph in '{section_title}'",
        "move": f"Moved '{section_title}'",
        "set_title": f"Title updated to '{action.get('content', '')}'",
        "clarify": action.get("question", "Clarification needed"),
    }
    base = summaries.get(act, f"Executed {act}")
    if warnings:
        base += f" (warnings: {'; '.join(warnings)})"
    return base


def _action_to_ask_payload(
    action: dict,
    warnings: list[str],
    tree: DocumentTree,
    bib_key_count: int,
    tex_filename: str,
    has_bib: bool,
) -> AskPayload:
    act_name = action.get("action", "unknown")
    intent = _ACTION_TO_INTENT.get(act_name, "unknown")
    ok = act_name != "clarify" and not any("not found" in w.lower() for w in warnings)
    section_id = action.get("target") or action.get("parent") or action.get("after")
    node = find_node(tree, section_id) if section_id else None
    section_title = node.label if node else None
    file_changed = ok and act_name not in _READ_ONLY_ACTIONS
    summary = _build_summary(act_name, action, section_title or "", warnings)

    state_payload = StatePayload(
        loaded=True,
        tex_filename=tex_filename,
        has_bib=has_bib,
        doc_class=tree.template_id,
        doc_style=tree.template_id,
        section_count=_count_sections(tree),
        bib_key_count=bib_key_count,
        metadata={"title": tree.title, **({"keywords": tree.keywords} if tree.keywords else {})},
    )

    return AskPayload(
        intent=intent,
        ok=ok,
        summary=summary,
        section_id=section_id,
        section_title=section_title,
        file_changed=file_changed,
        router={
            "raw_intent": intent,
            "section_id": section_id,
            "section_title": section_title,
            "instruction": action.get("content", ""),
            "has_user_content": bool(action.get("content")),
            "reasoning": summary,
        },
        payload=action,
        state=state_payload,
    )


def build_state(workspace: LatexWorkspace) -> StatePayload:
    if not workspace.is_loaded() or workspace.session is None:
        return StatePayload(loaded=False)
    tree = workspace.session.tree
    return StatePayload(
        loaded=True,
        tex_filename=workspace.original_tex_name,
        has_bib=bool(workspace.bib_content),
        doc_class=tree.template_id,
        doc_style=tree.template_id,
        section_count=_count_sections(tree),
        bib_key_count=len(workspace.session.bib_keys),
        metadata={"title": tree.title},
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

    if not workspace.is_loaded() or workspace.session is None:
        raise WorkspaceError(
            "No document loaded. Send tex_file with this request to start a working document.",
            status_code=400,
        )

    result = workspace.session.command(query)
    action = result.get("action", {})
    warnings = result.get("warnings", [])
    if action.get("action") not in _READ_ONLY_ACTIONS:
        workspace._persist_tex()

    return _action_to_ask_payload(
        action=action,
        warnings=warnings,
        tree=workspace.session.tree,
        bib_key_count=len(workspace.session.bib_keys),
        tex_filename=workspace.original_tex_name or "document.tex",
        has_bib=bool(workspace.bib_content),
    )


def export_tex(workspace: LatexWorkspace) -> tuple[str, str]:
    if not workspace.is_loaded() or workspace.session is None:
        raise WorkspaceError("No working document loaded.", status_code=404)
    return serialize(workspace.session.tree), workspace.original_tex_name or "document.tex"


def reset_workspace(workspace: LatexWorkspace) -> dict[str, Any]:
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
