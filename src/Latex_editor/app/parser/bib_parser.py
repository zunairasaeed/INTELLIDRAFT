"""Minimal BibTeX parser: extract citation keys.

Only the cite keys are needed by the editor agent — full bib parsing
would be overkill. We just match ``@type{key, ...}`` entries.
"""

from __future__ import annotations

import re

_ENTRY_RE = re.compile(r"@\w+\s*\{\s*([^,\s}]+)\s*,", re.MULTILINE)


def extract_bib_keys(bib_text: str) -> list[str]:
    """Return the list of cite keys (preserving order, deduplicated)."""
    seen: set[str] = set()
    keys: list[str] = []
    for m in _ENTRY_RE.finditer(bib_text):
        key = m.group(1)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys
