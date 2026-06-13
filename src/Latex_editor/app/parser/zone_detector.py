"""Detect implicit content zones (abstract, acknowledgements) in a LaTeX doc.

Some "sections" in ACM templates are environments rather than
``\\section{}`` headers. We treat them as virtual sections so the editor
can target them by name.
"""

from __future__ import annotations

import re
from typing import Any

_ZONE_PATTERNS: dict[str, re.Pattern[str]] = {
    "abstract": re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.DOTALL),
    "acknowledgements": re.compile(
        r"\\begin\{acks\}(.*?)\\end\{acks\}", re.DOTALL
    ),
}


def detect_zones(tex: str) -> list[dict[str, Any]]:
    """Return a list of ``{name, start, end, body}`` for each detected zone."""
    zones: list[dict[str, Any]] = []
    for name, pattern in _ZONE_PATTERNS.items():
        for m in pattern.finditer(tex):
            zones.append(
                {
                    "name": name,
                    "start": m.start(),
                    "end": m.end(),
                    "body": m.group(1),
                }
            )
    return zones
