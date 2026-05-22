"""Very small ``.bib`` parser: returns the list of citation keys.

The agent only needs the *keys* — the editor uses them to constrain Groq
to citing references that actually exist in the bibliography.
"""

from __future__ import annotations

from pathlib import Path

from ..utils.regex_patterns import BIB_ENTRY_RE


def parse_bib_file(bib_path: str | Path | None) -> list[str]:
    """Return all unique citation keys from a ``.bib`` file (in source order).

    Returns an empty list if ``bib_path`` is ``None`` or the file is missing.
    """

    if not bib_path:
        return []

    path = Path(bib_path)
    if not path.is_file():
        return []

    text = path.read_text(encoding="utf-8", errors="ignore")

    keys: list[str] = []
    seen: set[str] = set()
    for match in BIB_ENTRY_RE.finditer(text):
        key = match.group("key").strip()
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


__all__ = ["parse_bib_file"]
