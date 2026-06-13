"""Object facade over ``validate_latex_block`` that also assembles the ``Patch``.

The ``LatexEditService`` orchestrator expects a single ``validated`` object
carrying ``ok / error / patch / summary``. The function-level
``validate_latex_block`` only returns ``{ok, error}``, so this facade:

1. validates the new body text from the editor,
2. looks up the target section in the parsed document,
3. builds a ``Patch`` aimed at that section's body line range,
4. returns the combined ``ValidatedPatch``.

``EditorOutput`` is the agent → validator contract; it lives in
``app.agents.editor_agent`` (defined alongside the agent that produces
it). We re-export it from this module for backward compatibility so old
imports still work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..agents.editor_agent import EditorOutput  # re-exported below
from .surgical_writer import Patch
from .validation import validate_latex_block

__all__ = ["EditorOutput", "ValidatedPatch", "Validator"]


@dataclass
class ValidatedPatch:
    """What the orchestrator reads after validation."""

    ok: bool
    error: str | None = None
    patch: Patch | None = None
    summary: str | None = None


class Validator:
    """Validate an ``EditorOutput`` against the parsed document and emit a ``Patch``.

    ``doc`` is duck-typed (``ParsedDocument`` or ``ParsedView``); we only
    read ``.sections``.
    """

    def validate(self, result: EditorOutput, doc: Any) -> ValidatedPatch:
        check = validate_latex_block(
            result.new_text,
            require_citations=result.require_citations or None,
            require_labels=result.require_labels or None,
        )
        if not check.ok:
            return ValidatedPatch(ok=False, error=check.error)

        section = next((s for s in doc.sections if s.id == result.section_id), None)
        if section is None:
            return ValidatedPatch(
                ok=False, error=f"Unknown section id: {result.section_id!r}"
            )

        patch = Patch(
            start_line=section.body_start_line,
            end_line=section.body_end_line,
            new_text=result.new_text,
        )
        return ValidatedPatch(ok=True, patch=patch, summary=result.summary or None)
