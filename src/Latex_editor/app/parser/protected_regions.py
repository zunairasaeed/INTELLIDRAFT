"""Identify regions of the TeX source that must never be modified.

Examples: the preamble (everything before ``\\begin{document}``), the
``\\bibliography{}`` declaration, and the ``\\end{document}`` line.
"""

from __future__ import annotations

import re
from typing import Any

_PROTECTED_PATTERNS: dict[str, re.Pattern[str]] = {
    "preamble": re.compile(r"\A(.*?)\\begin\{document\}", re.DOTALL),
    "bibliography": re.compile(r"\\bibliography\{[^}]+\}"),
    "document_end": re.compile(r"\\end\{document\}"),
}


def find_protected_regions(tex: str) -> list[dict[str, Any]]:
    """Return list of ``{name, start, end}`` for each protected match."""
    regions: list[dict[str, Any]] = []
    for name, pattern in _PROTECTED_PATTERNS.items():
        for m in pattern.finditer(tex):
            regions.append({"name": name, "start": m.start(), "end": m.end()})
    return regions


def is_in_protected_region(tex: str, char_offset: int) -> bool:
    """Return ``True`` if ``char_offset`` falls within any protected region."""
    for region in find_protected_regions(tex):
        if region["start"] <= char_offset < region["end"]:
            return True
    return False
