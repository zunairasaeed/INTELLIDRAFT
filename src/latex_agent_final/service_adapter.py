"""
service_adapter.py
Drop-in replacement for src/Latex_Alignment/service.py.

pipelines.py imports:
    from src.latex_agent_backend.service_adapter import (
        LatexWorkspace, WorkspaceError, StatePayload, AskPayload,
        build_state, run_ask, export_tex, reset_workspace,
    )

Nothing else in the codebase changes.
"""
from __future__ import annotations

import re
import sys
import os
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── make sure our sibling packages are importable ─────────────────────────────
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from parser.parser import (
    DocumentTree, SectionNode, to_tree_json, find_node, parse
)
from editor.operations import execute_action, rewrite as op_rewrite
from editor.serializer import serialize
from session import Session


# ══════════════════════════════════════════════════════════════════════════════
# Exceptions
# ══════════════════════════════════════════════════════════════════════════════

class WorkspaceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ══════════════════════════════════════════════════════════════════════════════
# Payload dataclasses  (same shape as old service.py)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class StatePayload:
    loaded: bool
    tex_filename: str
    has_bib: bool
    doc_class: str
    doc_style: str
    section_count: int
    bib_key_count: int
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "loaded":        self.loaded,
            "tex_filename":  self.tex_filename,
            "has_bib":       self.has_bib,
            "doc_class":     self.doc_class,
            "doc_style":     self.doc_style,
            "section_count": self.section_count,
            "bib_key_count": self.bib_key_count,
            "metadata":      self.metadata,
        }


@dataclass
class AskPayload:
    intent: str
    ok: bool
    summary: str
    section_id: str
    section_title: str
    file_changed: bool
    router: dict
    payload: dict
    state: dict

    def to_dict(self) -> dict:
        return {
            "intent":        self.intent,
            "ok":            self.ok,
            "summary":       self.summary,
            "section_id":    self.section_id,
            "section_title": self.section_title,
            "file_changed":  self.file_changed,
            "router":        self.router,
            "payload":       self.payload,
            "state":         self.state,
        }


# ══════════════════════════════════════════════════════════════════════════════
# LegacySection  — shape the frontend /sections routes expect
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class LegacySection:
    id: str
    title: str
    cmd: str          # "abstract" | "section" | "subsection" | "subsubsection"
    depth: int        # 0=abstract/acks  1=section  2=subsection  3=subsubsection
    start_line: int
    end_line: int
    line_count: int
    is_empty: bool
    is_implicit: bool # True for abstract / acks (env-wrapped, not \section)
    citations: list
    labels: list
    raw_lines: list
    raw_text: str

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _extract_citations(raw: str) -> list:
    return re.findall(r'\\cite\{([^}]+)\}', raw)


def _extract_labels(raw: str) -> list:
    return re.findall(r'\\label\{([^}]+)\}', raw)


def _node_raw_text(node: SectionNode) -> str:
    parts = []
    for b in node.content_blocks:
        if b.raw.strip():
            parts.append(b.raw.strip())
    return "\n\n".join(parts)


def _node_to_legacy(node: SectionNode, line_counter: list) -> LegacySection:
    """Convert a SectionNode to a LegacySection the frontend understands."""
    raw = _node_raw_text(node)
    lines = raw.splitlines() if raw else []
    line_count = max(len(lines), 1)
    start = line_counter[0]
    end   = start + line_count
    line_counter[0] = end + 1

    if node.env_wrapper in ("abstract",):
        cmd = "abstract"
    elif node.env_wrapper in ("acks",):
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
        line_count=line_count,
        is_empty=not bool(raw.strip()),
        is_implicit=node.env_wrapper is not None,
        citations=_extract_citations(raw),
        labels=_extract_labels(raw),
        raw_lines=lines,
        raw_text=raw,
    )


def _flatten_sections(tree: DocumentTree) -> list[LegacySection]:
    """Flatten entire tree into a flat ordered list of LegacySections."""
    counter = [1]
    result  = []

    def walk(nodes):
        for n in nodes:
            result.append(_node_to_legacy(n, counter))
            walk(n.children)

    if tree.abstract:
        result.append(_node_to_legacy(tree.abstract, counter))
    walk(tree.body)
    if tree.acks:
        result.append(_node_to_legacy(tree.acks, counter))
    for s in tree.appendix_sections:
        result.append(_node_to_legacy(s, counter))

    return result


# ══════════════════════════════════════════════════════════════════════════════
# AgentFacade  — mimics LatexEditorAgent for the 3 direct .agent routes
# ══════════════════════════════════════════════════════════════════════════════

class AgentFacade:
    """
    Routes call workspace.agent.list_sections() / get_section() / replace_content().
    We serve those from the live Session.
    """

    def __init__(self, workspace: "LatexWorkspace"):
        self._ws = workspace

    # ── list_sections ─────────────────────────────────────────────────────────
    def list_sections(self) -> list[dict]:
        sections = _flatten_sections(self._ws.session.tree)
        return [s.to_dict() for s in sections]

    # ── get_section ───────────────────────────────────────────────────────────
    def get_section(self, section_id: str) -> dict:
        sections = _flatten_sections(self._ws.session.tree)
        for s in sections:
            if s.id == section_id:
                return s.to_dict()
        raise WorkspaceError(f"Section '{section_id}' not found", 404)

    # ── replace_content ───────────────────────────────────────────────────────
    def replace_content(self, section_id: str, content: str) -> dict:
        """Direct PUT /sections/{id} — rewrite the section, persist to file."""
        node = find_node(self._ws.session.tree, section_id)
        if node is None:
            raise WorkspaceError(f"Section '{section_id}' not found", 404)

        new_tree, warnings = op_rewrite(
            self._ws.session.tree, section_id, content
        )
        self._ws.session.tree = new_tree
        self._ws._persist_tex()

        # Build response
        updated = find_node(new_tree, section_id)
        raw = _node_raw_text(updated)
        return {
            "ok":            True,
            "section_id":    section_id,
            "section_title": updated.label,
            "start_line":    updated.line_start,
            "end_line":      updated.line_end,
            "lines_before":  updated.line_start,
            "lines_after":   updated.line_end,
            "raw_text":      raw,
            "summary":       f"Rewrote '{updated.label}'",
            "warnings":      warnings,
        }


# ══════════════════════════════════════════════════════════════════════════════
# LatexWorkspace  — the single global object pipelines.py holds
# ══════════════════════════════════════════════════════════════════════════════

class LatexWorkspace:
    """
    Drop-in for the old LatexWorkspace.
    Holds one Session + metadata the routes need.
    """

    def __init__(self):
        self.session: Optional[Session] = None
        self.tex_path: Optional[Path]   = None
        self.bib_path: Optional[Path]   = None
        self.original_tex_name: str     = ""
        self.bib_content: str           = ""
        self.agent: AgentFacade         = AgentFacade(self)

    # ── is_loaded ─────────────────────────────────────────────────────────────
    def is_loaded(self) -> bool:
        return self.session is not None

    # ── reset ─────────────────────────────────────────────────────────────────
    def reset(self) -> None:
        self.session        = None
        self.tex_path       = None
        self.bib_path       = None
        self.original_tex_name = ""
        self.bib_content    = ""

    # ── load_files ────────────────────────────────────────────────────────────
    def load_files(
        self,
        tex_bytes: bytes,
        tex_filename: str,
        bib_bytes: Optional[bytes] = None,
        bib_filename: Optional[str] = None,
    ) -> None:
        tex_text = tex_bytes.decode("utf-8", errors="replace")
        bib_text = bib_bytes.decode("utf-8", errors="replace") if bib_bytes else ""

        self.original_tex_name = tex_filename
        self.bib_content       = bib_text
        self.session           = Session(tex_text, bib_text)

        # Write to tmp files so /export can stream them
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp(prefix="latex_ws_"))
        self.tex_path = tmp_dir / tex_filename
        self.tex_path.write_text(tex_text, encoding="utf-8")

        if bib_bytes and bib_filename:
            self.bib_path = tmp_dir / bib_filename
            self.bib_path.write_text(bib_text, encoding="utf-8")
        else:
            self.bib_path = None

    # ── internal: write serialized tree back to tex_path ──────────────────────
    def _persist_tex(self) -> None:
        if self.tex_path and self.session:
            self.tex_path.write_text(
                serialize(self.session.tree), encoding="utf-8"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Intent mapping
# ══════════════════════════════════════════════════════════════════════════════

_ACTION_TO_INTENT = {
    "rewrite":           "edit",
    "replace_paragraph": "edit",
    "add_paragraph":     "add",
    "add_section":       "insert_section",
    "add_subsection":    "insert_section",
    "add_subsubsection": "insert_section",
    "rename":            "rename_section",
    "delete":            "delete_section",
    "move":              "move_section",
    "set_title":         "edit",
    "clarify":           "unknown",
}


def _action_to_ask_payload(
    action: dict,
    warnings: list,
    tree: DocumentTree,
    bib_key_count: int,
    tex_filename: str,
    has_bib: bool,
) -> AskPayload:
    act_name    = action.get("action", "unknown")
    intent      = _ACTION_TO_INTENT.get(act_name, "unknown")
    ok          = act_name != "clarify" and not any("not found" in w for w in warnings)
    section_id  = action.get("target") or action.get("parent") or action.get("after") or ""
    node        = find_node_safe(tree, section_id)
    section_title = node.label if node else ""
    file_changed  = ok and act_name not in ("clarify",)

    summary = _build_summary(act_name, action, section_title, warnings)

    state_payload = StatePayload(
        loaded=True,
        tex_filename=tex_filename,
        has_bib=has_bib,
        doc_class=tree.template_id,
        doc_style=tree.template_id,
        section_count=_count_sections(tree),
        bib_key_count=bib_key_count,
        metadata={"title": tree.title},
    )

    return AskPayload(
        intent=intent,
        ok=ok,
        summary=summary,
        section_id=section_id,
        section_title=section_title,
        file_changed=file_changed,
        router={
            "raw_intent":    intent,
            "section_id":    section_id,
            "section_title": section_title,
            "instruction":   action.get("content", ""),
            "has_user_content": bool(action.get("content")),
            "reasoning":     summary,
        },
        payload=action,
        state=state_payload.to_dict(),
    )


def find_node_safe(tree: DocumentTree, node_id: str):
    try:
        return find_node(tree, node_id)
    except Exception:
        return None


def _count_sections(tree: DocumentTree) -> int:
    count = 0
    def walk(nodes):
        nonlocal count
        for n in nodes:
            count += 1
            walk(n.children)
    if tree.abstract: count += 1
    walk(tree.body)
    if tree.acks: count += 1
    return count


def _build_summary(act: str, action: dict, section_title: str, warnings: list) -> str:
    label = action.get("label", "")
    content_preview = (action.get("content") or "")[:60]

    summaries = {
        "add_paragraph":     f"Added paragraph to '{section_title}'",
        "add_section":       f"Added new section '{label}'",
        "add_subsection":    f"Added subsection '{label}' under '{section_title}'",
        "add_subsubsection": f"Added subsubsection '{label}'",
        "rename":            f"Renamed section to '{action.get('new_label','')}'",
        "delete":            f"Deleted section '{section_title}'",
        "rewrite":           f"Rewrote '{section_title}': {content_preview}...",
        "replace_paragraph": f"Replaced paragraph in '{section_title}'",
        "move":              f"Moved '{section_title}'",
        "set_title":         f"Title updated to '{action.get('content','')}'",
        "clarify":           action.get("question", "Clarification needed"),
    }
    base = summaries.get(act, f"Executed {act}")
    if warnings:
        base += f" (warnings: {'; '.join(warnings)})"
    return base


# ══════════════════════════════════════════════════════════════════════════════
# Public service functions  (same signatures as old service.py)
# ══════════════════════════════════════════════════════════════════════════════

def build_state(workspace: LatexWorkspace) -> StatePayload:
    if not workspace.is_loaded():
        return StatePayload(
            loaded=False, tex_filename="", has_bib=False,
            doc_class="", doc_style="", section_count=0, bib_key_count=0,
        )
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
    query: str,
    tex_bytes: Optional[bytes] = None,
    tex_filename: Optional[str] = None,
    bib_bytes: Optional[bytes] = None,
    bib_filename: Optional[str] = None,
) -> AskPayload:
    # Re-load files if a new tex was uploaded with this request
    if tex_bytes:
        workspace.load_files(tex_bytes, tex_filename or "document.tex",
                             bib_bytes, bib_filename)

    if not workspace.is_loaded():
        raise WorkspaceError("No document loaded. Upload a .tex file first.", 400)

    # Run the command through the session agent
    result = workspace.session.command(query)
    action   = result.get("action", {})
    warnings = result.get("warnings", [])

    # Persist updated tex to disk (for export)
    workspace._persist_tex()

    tree = workspace.session.tree
    return _action_to_ask_payload(
        action=action,
        warnings=warnings,
        tree=tree,
        bib_key_count=len(workspace.session.bib_keys),
        tex_filename=workspace.original_tex_name,
        has_bib=bool(workspace.bib_content),
    )


def export_tex(workspace: LatexWorkspace) -> tuple[str, str]:
    """Returns (tex_text, filename)."""
    if not workspace.is_loaded():
        raise WorkspaceError("No document loaded.", 400)
    tex = serialize(workspace.session.tree)
    return tex, workspace.original_tex_name


def reset_workspace(workspace: LatexWorkspace) -> dict:
    was_loaded = workspace.is_loaded()
    if workspace.is_loaded():
        workspace.session.reset()
        workspace._persist_tex()
    return {
        "status":     "reset",
        "was_loaded": was_loaded,
        "loaded":     workspace.is_loaded(),
    }
