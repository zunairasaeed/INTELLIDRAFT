"""UI helpers for the Streamlit test app — read/write section bodies on Session."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from editor.operations import rewrite
from editor.serializer import serialize_blocks
from parser.parser import find_node

DOC_TITLE_ID = "__doc_title__"


def flatten_sections(structure: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten nested section tree (document order) for lookups and counts."""
    items: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], indent: int = 0) -> None:
        row = dict(node)
        row["indent"] = indent
        items.append(row)
        for child in node.get("children") or []:
            walk(child, indent + 1)

    if structure.get("title"):
        items.append({
            "id": DOC_TITLE_ID,
            "label": "Title",
            "level": 0,
            "zone": "metadata",
            "indent": 0,
            "pseudo": True,
            "children": [],
        })

    for section in structure.get("sections") or []:
        walk(section, 0)
    for section in structure.get("appendix_sections") or []:
        row = dict(section)
        row["indent"] = 0
        row["zone"] = "appendix"
        items.append(row)
    return items


def count_sections(structure: dict[str, Any]) -> int:
    return len(flatten_sections(structure))


def section_indent_label(section: dict[str, Any], subtitle: str) -> str:
    depth = section.get("indent", 0)
    child_count = len(section.get("children") or [])
    if depth == 0:
        prefix = "▾ " if child_count else ""
    else:
        prefix = "    " * depth + "↳ "
    return f"{prefix}{section['label']} · {subtitle}"


def section_meta(session, section_id: str) -> dict[str, Any]:
    if section_id == DOC_TITLE_ID:
        title = session.tree.title or "Untitled"
        return {
            "label": "Title",
            "depth": 0,
            "zone": "metadata",
            "env_tag": "metadata",
            "line_start": 0,
            "line_end": 0,
            "line_count": 1,
            "char_count": len(title),
            "is_empty": not title.strip(),
        }

    node = find_node(session.tree, section_id)
    if node is None:
        return {}
    body = serialize_blocks(node.content_blocks)
    line_count = len([ln for ln in body.splitlines() if ln.strip()]) or (
        1 if body.strip() else 0
    )
    env_tag = None
    if node.env_wrapper:
        env_tag = f"{node.env_wrapper} env"
    elif node.zone == "appendix":
        env_tag = "appendix"
    return {
        "label": node.label,
        "depth": node.level,
        "zone": node.zone,
        "env_tag": env_tag,
        "line_start": node.line_start,
        "line_end": node.line_end,
        "line_count": line_count,
        "char_count": len(body),
        "is_empty": not body.strip(),
    }


def section_editor_text(session, section_id: str) -> str:
    if section_id == DOC_TITLE_ID:
        return session.tree.title or ""

    node = find_node(session.tree, section_id)
    if node is None:
        return ""
    body = serialize_blocks(node.content_blocks)
    if node.env_wrapper:
        return f"\\begin{{{node.env_wrapper}}}\n{body}\n\\end{{{node.env_wrapper}}}"
    return body


def _strip_env_wrapper(text: str, env_name: str) -> str:
    begin = f"\\begin{{{env_name}}}"
    end = f"\\end{{{env_name}}}"
    cleaned = text.strip()
    if cleaned.startswith(begin):
        cleaned = cleaned[len(begin) :].strip()
    if cleaned.endswith(end):
        cleaned = cleaned[: -len(end)].strip()
    return cleaned


def save_section_text(session, section_id: str, text: str) -> list[str]:
    """Persist manual textarea edits."""
    if section_id == DOC_TITLE_ID:
        from editor.operations import set_title

        session.snapshots.append(deepcopy(session.tree))
        session.tree, warnings = set_title(session.tree, text.strip())
        return warnings

    node = find_node(session.tree, section_id)
    if node is None:
        return [f"Section '{section_id}' not found"]

    content = text.strip()
    if node.env_wrapper:
        content = _strip_env_wrapper(content, node.env_wrapper)

    session.snapshots.append(deepcopy(session.tree))
    session.tree, warnings = rewrite(session.tree, section_id, content)
    return warnings


def format_action_result(result: dict[str, Any]) -> str:
    action = result.get("action") or {}
    name = action.get("action", "unknown")
    warnings = result.get("warnings") or []

    if result.get("clarification"):
        return result["clarification"]

    lines = [f"Applied action: **{name}**"]
    if action.get("target"):
        lines.append(f"- target: `{action['target']}`")
    if action.get("parent"):
        lines.append(f"- parent: `{action['parent']}`")
    if action.get("after"):
        lines.append(f"- after: `{action['after']}`")
    if action.get("label"):
        lines.append(f"- label: {action['label']}")
    if action.get("new_label"):
        lines.append(f"- new label: {action['new_label']}")
    if action.get("content"):
        preview = str(action["content"])[:180]
        lines.append(f"- content: {preview}{'…' if len(str(action['content'])) > 180 else ''}")
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def refresh_ui_after_structure_change(session) -> None:
    """Drop cached widget state so sidebar + editor reflect the live tree."""
    st_state = _get_streamlit_state()
    if st_state is None:
        return

    st_state.editor_versions = {}
    st_state.structure_version = st_state.get("structure_version", 0) + 1

    drop_keys = [
        key
        for key in list(st_state.keys())
        if key.startswith("textarea_") or key.startswith("sec_")
    ]
    for key in drop_keys:
        del st_state[key]

    selected = st_state.get("selected_section")
    if selected and selected != DOC_TITLE_ID and find_node(session.tree, selected) is None:
        sections = flatten_sections(session.get_structure())
        st_state.selected_section = sections[0]["id"] if sections else None


def _get_streamlit_state():
    try:
        import streamlit as st

        return st.session_state
    except Exception:
        return None
