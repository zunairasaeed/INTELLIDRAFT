"""LaTeX Editor Agent.

A backend module that parses LaTeX papers into zones and sections, then
performs surgical, instruction-driven edits via Groq.

Entry point: :class:`agent.LatexEditorAgent`.
"""

from .agent import LatexEditorAgent
from .models.schema import (
    EditRequest,
    EditResult,
    ParsedDocument,
    Section,
    Zone,
)

__all__ = [
    "LatexEditorAgent",
    "ParsedDocument",
    "Zone",
    "Section",
    "EditRequest",
    "EditResult",
]
