"""Executor: maps a :class:`RoutedIntent` to a concrete agent operation.

The executor is intentionally side-effect-light: it only delegates to
:class:`LatexEditorAgent` (the orchestrator) and the surgical writer. It
never imports the Groq client directly - all LLM calls happen inside the
agent's edit/append paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agent import LatexEditorAgent
from ..models.schema import Section
from .intent_router import RoutedIntent


@dataclass
class ExecutionResult:
    intent: str
    ok: bool
    summary: str
    section_id: str | None = None
    section_title: str | None = None
    file_changed: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "ok": self.ok,
            "summary": self.summary,
            "section_id": self.section_id,
            "section_title": self.section_title,
            "file_changed": self.file_changed,
            "payload": self.payload,
            "error": self.error,
        }


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────
def execute(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    """Dispatch the routed intent to the right agent operation."""

    dispatcher = {
        "edit":            _do_edit,
        "add":             _do_add,
        "replace":         _do_replace,
        "delete_section":  _do_delete_section,
        "insert_section":  _do_insert_section,
        "rename_section":  _do_rename_section,
        "move_section":    _do_move_section,
        "list_sections":   _do_list_sections,
        "show_section":    _do_show_section,
        "summarize":       _do_summarize,
        "unknown":         _do_unknown,
    }
    handler = dispatcher.get(routed.intent, _do_unknown)
    try:
        return handler(routed, agent)
    except Exception as exc:  # noqa: BLE001 - surface to API caller
        return ExecutionResult(
            intent=routed.intent,
            ok=False,
            summary=f"Operation failed: {exc}",
            section_id=routed.section_id,
            section_title=routed.section_title,
            error=str(exc),
        )


# ────────────────────────────────────────────────────────────────────────────
# Per-intent handlers
# ────────────────────────────────────────────────────────────────────────────
def _do_edit(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    if routed.section_id is None:
        return _missing_section(routed, "Cannot edit: target section not identified.")
    if not routed.instruction and not routed.user_content:
        return ExecutionResult(
            intent=routed.intent,
            ok=False,
            summary="Edit needs either an instruction or content.",
            section_id=routed.section_id,
            section_title=routed.section_title,
            error="missing instruction",
        )

    section_before = agent.get_section(routed.section_id)

    if routed.user_content is not None and not routed.instruction:
        result = agent.replace_content(routed.section_id, routed.user_content)
        verb = "Replaced"
    else:
        result = agent.edit(routed.section_id, routed.instruction or "")
        verb = "Rewrote"

    return ExecutionResult(
        intent="edit",
        ok=True,
        summary=f"{verb} section '{section_before.title}'.",
        section_id=section_before.id,
        section_title=section_before.title,
        file_changed=True,
        payload={
            "start_line": result.start_line,
            "end_line": result.end_line,
            "was_empty": result.was_empty,
            "original_lines": result.original_lines,
            "edited_lines": result.edited_lines,
        },
    )


def _do_add(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    if routed.section_id is None:
        return _missing_section(routed, "Cannot add content: target section not identified.")
    if not routed.instruction and not routed.user_content:
        return ExecutionResult(
            intent=routed.intent,
            ok=False,
            summary="Add needs either an instruction or content.",
            section_id=routed.section_id,
            section_title=routed.section_title,
            error="missing instruction",
        )

    section_before = agent.get_section(routed.section_id)
    result = agent.append_content(
        routed.section_id,
        instruction=routed.instruction,
        user_content=routed.user_content,
    )
    via = "user-provided text" if routed.user_content else "LLM-generated text"
    return ExecutionResult(
        intent="add",
        ok=True,
        summary=f"Added {via} to section '{section_before.title}'.",
        section_id=section_before.id,
        section_title=section_before.title,
        file_changed=True,
        payload={
            "start_line": result.start_line,
            "end_line": result.end_line,
            "was_empty": result.was_empty,
            "original_lines": result.original_lines,
            "edited_lines": result.edited_lines,
        },
    )


def _do_replace(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    if routed.section_id is None:
        return _missing_section(routed, "Cannot replace: target section not identified.")
    if not routed.user_content:
        return ExecutionResult(
            intent=routed.intent,
            ok=False,
            summary="Replace needs user_content (literal LaTeX).",
            section_id=routed.section_id,
            section_title=routed.section_title,
            error="missing user_content",
        )

    section_before = agent.get_section(routed.section_id)
    result = agent.replace_content(routed.section_id, routed.user_content)
    return ExecutionResult(
        intent="replace",
        ok=True,
        summary=f"Replaced body of section '{section_before.title}' with user-provided LaTeX.",
        section_id=section_before.id,
        section_title=section_before.title,
        file_changed=True,
        payload={
            "start_line": result.start_line,
            "end_line": result.end_line,
            "original_lines": result.original_lines,
            "edited_lines": result.edited_lines,
        },
    )


def _do_delete_section(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    if routed.section_id is None:
        return _missing_section(routed, "Cannot delete: target section not identified.")

    section_before = agent.get_section(routed.section_id)
    result = agent.delete_section(routed.section_id)
    return ExecutionResult(
        intent="delete_section",
        ok=True,
        summary=f"Deleted section '{section_before.title}' (lines {section_before.start_line}-{section_before.end_line}).",
        section_id=section_before.id,
        section_title=section_before.title,
        file_changed=True,
        payload={
            "removed_lines": result.original_lines,
            "start_line": result.start_line,
            "end_line": result.end_line,
        },
    )


# ────────────────────────────────────────────────────────────────────────────
# Structural edits — create / rename / reorder section headers
# These wrap the tools added to ``LatexEditorAgent`` so the LLM router can
# actually invoke them. ``add`` only appends prose to a body — it does NOT
# create a new \section{} header; that's what ``insert_section`` is for.
# ────────────────────────────────────────────────────────────────────────────
def _do_insert_section(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    new_title = routed.new_title or routed.instruction
    depth = routed.depth or 1
    after_id = routed.after_id or routed.section_id

    if not new_title or not after_id:
        return ExecutionResult(
            intent="insert_section",
            ok=False,
            summary="Need both a title and an anchor section (after_id) to insert a new section.",
            section_id=None,
            section_title=None,
            error="missing_params",
            payload={
                "router_reasoning": routed.reasoning,
                "got": {
                    "new_title": new_title,
                    "depth": depth,
                    "after_id": after_id,
                },
            },
        )

    try:
        anchor_title = agent.get_section(after_id).title
    except KeyError:
        return ExecutionResult(
            intent="insert_section",
            ok=False,
            summary=f"Anchor section '{after_id}' not found.",
            error="anchor_not_found",
        )

    try:
        new_section = agent.insert_section(
            title=new_title,
            depth=int(depth),
            after_id=after_id,
            body=routed.user_content or "",
        )
    except Exception as exc:  # noqa: BLE001 - surface details to API caller
        return ExecutionResult(
            intent="insert_section",
            ok=False,
            summary=f"Insert failed: {exc}",
            error=str(exc),
        )

    kind = {1: "section", 2: "subsection", 3: "subsubsection"}.get(int(depth), "section")
    return ExecutionResult(
        intent="insert_section",
        ok=True,
        summary=f"Inserted {kind} '{new_title}' after '{anchor_title}'.",
        section_id=new_section.id,
        section_title=new_section.title,
        file_changed=True,
        payload={
            "new_section_id": new_section.id,
            "depth": int(depth),
            "after_id": after_id,
            "start_line": new_section.start_line,
            "end_line": new_section.end_line,
        },
    )


def _do_rename_section(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    if routed.section_id is None:
        return _missing_section(routed, "Cannot rename: target section not identified.")
    if not routed.new_title:
        return ExecutionResult(
            intent="rename_section",
            ok=False,
            summary="Rename needs a new_title.",
            section_id=routed.section_id,
            section_title=routed.section_title,
            error="missing_new_title",
        )

    section_before = agent.get_section(routed.section_id)
    renamed = agent.rename_section(routed.section_id, routed.new_title)
    return ExecutionResult(
        intent="rename_section",
        ok=True,
        summary=f"Renamed '{section_before.title}' → '{renamed.title}'.",
        section_id=renamed.id,
        section_title=renamed.title,
        file_changed=True,
        payload={
            "old_id": section_before.id,
            "old_title": section_before.title,
            "new_id": renamed.id,
            "new_title": renamed.title,
            "depth": renamed.depth,
            "start_line": renamed.start_line,
            "end_line": renamed.end_line,
        },
    )


def _do_move_section(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    if routed.section_id is None:
        return _missing_section(routed, "Cannot move: target section not identified.")
    if not routed.after_id:
        return ExecutionResult(
            intent="move_section",
            ok=False,
            summary="Move needs an after_id (the section the moved one should follow).",
            section_id=routed.section_id,
            section_title=routed.section_title,
            error="missing_after_id",
        )

    try:
        anchor_title = agent.get_section(routed.after_id).title
    except KeyError:
        return ExecutionResult(
            intent="move_section",
            ok=False,
            summary=f"Anchor section '{routed.after_id}' not found.",
            error="anchor_not_found",
        )

    section_before = agent.get_section(routed.section_id)
    moved = agent.move_section(routed.section_id, routed.after_id)
    return ExecutionResult(
        intent="move_section",
        ok=True,
        summary=f"Moved '{section_before.title}' to follow '{anchor_title}'.",
        section_id=moved.id,
        section_title=moved.title,
        file_changed=True,
        payload={
            "moved_id": moved.id,
            "after_id": routed.after_id,
            "start_line": moved.start_line,
            "end_line": moved.end_line,
        },
    )


def _do_list_sections(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    sections = agent.list_sections()
    return ExecutionResult(
        intent="list_sections",
        ok=True,
        summary=f"{len(sections)} sections in the document.",
        payload={"sections": [_section_brief(s) for s in sections]},
    )


def _do_show_section(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    if routed.section_id is None:
        return _missing_section(routed, "Cannot show: target section not identified.")
    section = agent.get_section(routed.section_id)
    return ExecutionResult(
        intent="show_section",
        ok=True,
        summary=f"Contents of '{section.title}'.",
        section_id=section.id,
        section_title=section.title,
        payload={
            "start_line": section.start_line,
            "end_line": section.end_line,
            "raw_lines": section.raw_lines,
            "citations": section.citations,
            "labels": section.labels,
            "is_empty": section.is_empty,
            "is_implicit": section.is_implicit,
        },
    )


def _do_summarize(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    doc = agent.load()
    return ExecutionResult(
        intent="summarize",
        ok=True,
        summary=(
            f"{doc.doc_class}/{doc.doc_style} paper titled "
            f"'{doc.metadata.get('title', 'Untitled')}' "
            f"with {len(doc.sections)} sections across {len(doc.zones)} zones."
        ),
        payload={
            "doc_class": doc.doc_class,
            "doc_style": doc.doc_style,
            "metadata": doc.metadata,
            "zones": [
                {"name": z.name, "start_line": z.start_line, "end_line": z.end_line}
                for z in doc.zones
            ],
            "sections": [_section_brief(s) for s in doc.sections],
        },
    )


def _do_unknown(routed: RoutedIntent, agent: LatexEditorAgent) -> ExecutionResult:
    sections = agent.list_sections()
    return ExecutionResult(
        intent="unknown",
        ok=False,
        summary=(
            "I could not determine what to do. "
            "Try: 'rewrite the introduction to be more formal', "
            "'add a paragraph about LaTeX to the methodology', "
            "or 'delete the results section'."
        ),
        payload={
            "router_reasoning": routed.reasoning,
            "available_sections": [_section_brief(s) for s in sections],
        },
        error="intent_unresolved",
    )


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────
def _missing_section(routed: RoutedIntent, message: str) -> ExecutionResult:
    return ExecutionResult(
        intent=routed.intent,
        ok=False,
        summary=message,
        section_id=None,
        section_title=None,
        error="section_not_resolved",
        payload={"router_reasoning": routed.reasoning},
    )


def _section_brief(section: Section) -> dict[str, Any]:
    return {
        "id": section.id,
        "title": section.title,
        "cmd": section.cmd,
        "depth": section.depth,
        "start_line": section.start_line,
        "end_line": section.end_line,
        "is_empty": section.is_empty,
        "is_implicit": section.is_implicit,
    }


__all__ = ["ExecutionResult", "execute"]
