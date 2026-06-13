"""Compact JSON-friendly view of a parsed document for the router/editor prompts.

Accepts anything with ``.lines`` and ``.sections`` attributes — in
practice that's either ``ParsedDocument`` (from ``section_indexer``)
or ``ParsedView`` (from ``document_parser``). Both expose the same
shape, so this function stays duck-typed.
"""

from __future__ import annotations

from typing import Any


def summarize_doc(doc: Any) -> dict[str, Any]:
    """Return a small dict describing the parsed document's structure."""
    return {
        "total_lines": len(doc.lines),
        "total_sections": len(doc.sections),
        "sections": [
            {
                "id": s.id,
                "title": s.title,
                "depth": s.depth,
                "is_implicit": s.is_implicit,
                "body_lines": max(0, s.body_end_line - s.body_start_line + 1),
            }
            for s in doc.sections
        ],
    }
