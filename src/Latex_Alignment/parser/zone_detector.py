"""Detect the 5 structural zones of a LaTeX paper.

| # | Zone        | Starts at            | Ends at              |
|---|-------------|----------------------|----------------------|
| 1 | preamble    | ``\\documentclass``  | ``\\begin{document}``|
| 2 | frontmatter | ``\\begin{document}``| ``\\begin{abstract}``|
| 3 | abstract    | ``\\begin{abstract}``| ``\\maketitle``      |
| 4 | body        | ``\\maketitle``      | ``\\begin{acks}``    |
| 5 | backmatter  | ``\\begin{acks}``    | ``\\end{document}``  |

Fallbacks for papers without ``\\maketitle`` or ``\\begin{acks}`` live in
the local ``_fallback_boundaries`` dict in this module (intentionally not
in the public schema).

Paper-type configuration (``_paper_type_config``) is also local to this
module — the public schema only exposes ``doc_class`` and ``doc_style``.
"""

from __future__ import annotations

from typing import Any

from ..models.schema import ParsedDocument, Zone
from ..utils.regex_patterns import (
    ACM_META,
    DOCCLASS_NAME_RE,
    DOCCLASS_STYLE_RE,
    GENERIC_META,
    ZONE_MARKERS,
)

# ────────────────────────────────────────────────────────────────────────────
# Local-only configuration tables (NOT part of the public schema).
# ────────────────────────────────────────────────────────────────────────────
_fallback_boundaries: dict[str, str] = {
    "body_start_fallback":       "end_abstract",  # if \maketitle is missing
    "backmatter_start_fallback": "end_doc",       # if \begin{acks} is missing
}

_paper_type_config: dict[str, dict[str, Any]] = {
    # ── ACM variants (all 5 supported by the editor agent) ──────────────
    "sigconf":    {"has_acks": True,  "has_maketitle": True,  "bib_style": "ACM-Reference-Format"},
    "acmsmall":   {"has_acks": True,  "has_maketitle": True,  "bib_style": "ACM-Reference-Format"},
    "acmtog":     {"has_acks": True,  "has_maketitle": True,  "bib_style": "ACM-Reference-Format"},
    "sigplan":    {"has_acks": True,  "has_maketitle": True,  "bib_style": "ACM-Reference-Format"},
    "manuscript": {"has_acks": True,  "has_maketitle": True,  "bib_style": "ACM-Reference-Format"},
    # ── Other ACM variants kept for back-compat ─────────────────────────
    "acmlarge":   {"has_acks": True,  "has_maketitle": True,  "bib_style": "ACM-Reference-Format"},
    "sigchi":     {"has_acks": True,  "has_maketitle": True,  "bib_style": "ACM-Reference-Format"},
    # ── IEEE ────────────────────────────────────────────────────────────
    "IEEEtran":   {"has_acks": False, "has_maketitle": True,  "bib_style": "IEEEtran"},
    # ── Elsevier ────────────────────────────────────────────────────────
    "elsarticle": {"has_acks": False, "has_maketitle": False, "bib_style": "elsarticle-num"},
    # ── Springer LNCS ───────────────────────────────────────────────────
    "llncs":      {"has_acks": False, "has_maketitle": True,  "bib_style": "splncs04"},
    # ── ML conference templates ─────────────────────────────────────────
    "neurips":    {"has_acks": True,  "has_maketitle": True,  "bib_style": "neurips"},
    "icml":       {"has_acks": False, "has_maketitle": True,  "bib_style": "icml"},
    # ── Generic article (fallback) ──────────────────────────────────────
    "article":    {"has_acks": False, "has_maketitle": True,  "bib_style": "plain"},
}

_UNKNOWN_STYLE_FALLBACK = "article"


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────
def detect_zones(file_path: str, lines: list[str]) -> ParsedDocument:
    """Scan a LaTeX file and return a :class:`ParsedDocument` with the 5 zones.

    Sections are intentionally left empty — the section indexer fills them in.
    """

    doc_class, doc_style = _read_doc_class(lines)

    config = _resolve_paper_config(doc_style)

    marker_lines = _scan_zone_markers(lines)

    zones = _build_zones(
        total_lines=len(lines),
        marker_lines=marker_lines,
        config=config,
    )

    metadata = _extract_metadata(lines, doc_class)

    return ParsedDocument(
        file_path=file_path,
        doc_class=doc_class,
        doc_style=doc_style,
        zones=zones,
        sections=[],
        metadata=metadata,
        bib_keys=[],
    )


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────
def _read_doc_class(lines: list[str]) -> tuple[str, str]:
    """Return ``(doc_class, doc_style)`` from the first matching line."""

    for line in lines:
        m_style = DOCCLASS_STYLE_RE.search(line)
        if m_style:
            style = m_style.group(1).split(",")[0].strip()
            name_match = DOCCLASS_NAME_RE.search(line)
            cls = name_match.group(1) if name_match else "article"
            return cls, style

        m_name = DOCCLASS_NAME_RE.search(line)
        if m_name:
            return m_name.group(1), _UNKNOWN_STYLE_FALLBACK

    return "article", _UNKNOWN_STYLE_FALLBACK


def _resolve_paper_config(doc_style: str) -> dict[str, Any]:
    return _paper_type_config.get(
        doc_style, _paper_type_config[_UNKNOWN_STYLE_FALLBACK]
    )


def _scan_zone_markers(lines: list[str]) -> dict[str, int]:
    """Return first-occurrence line number (1-based) for every zone marker."""

    found: dict[str, int] = {}
    for idx, line in enumerate(lines, start=1):
        for name, pattern in ZONE_MARKERS.items():
            if name in found:
                continue
            if pattern.search(line):
                found[name] = idx
    return found


def _build_zones(
    total_lines: int,
    marker_lines: dict[str, int],
    config: dict[str, Any],
) -> list[Zone]:
    """Construct the 5 Zone objects with sensible fallbacks for half-done papers."""

    doc_class_line = marker_lines.get("doc_class", 1)
    begin_doc_line = marker_lines.get("begin_doc", doc_class_line)
    begin_abs_line = marker_lines.get("begin_abs")
    end_abs_line   = marker_lines.get("end_abs")
    maketitle_line = marker_lines.get("maketitle")
    begin_acks_line = marker_lines.get("begin_acks")
    end_doc_line   = marker_lines.get("end_doc", total_lines)

    # ── Zone 1: preamble ────────────────────────────────────────────────
    preamble_start = doc_class_line
    preamble_end   = max(preamble_start, begin_doc_line - 1)

    # ── Zone 2: frontmatter ─────────────────────────────────────────────
    frontmatter_start = begin_doc_line
    if begin_abs_line:
        frontmatter_end = max(frontmatter_start, begin_abs_line - 1)
    elif maketitle_line:
        frontmatter_end = max(frontmatter_start, maketitle_line - 1)
    else:
        frontmatter_end = frontmatter_start

    # ── Zone 3: abstract ────────────────────────────────────────────────
    if begin_abs_line:
        abstract_start = begin_abs_line
        if maketitle_line and maketitle_line > begin_abs_line:
            abstract_end = maketitle_line - 1
        elif end_abs_line:
            abstract_end = end_abs_line
        else:
            abstract_end = begin_abs_line
    else:
        # No abstract present — collapse to an empty interval right after frontmatter.
        abstract_start = frontmatter_end + 1
        abstract_end   = abstract_start - 1  # empty span

    # ── Zone 4: body ────────────────────────────────────────────────────
    if maketitle_line:
        body_start = maketitle_line + 1
    elif _fallback_boundaries["body_start_fallback"] == "end_abstract" and end_abs_line:
        body_start = end_abs_line + 1
    elif begin_abs_line:
        body_start = (end_abs_line or begin_abs_line) + 1
    else:
        body_start = frontmatter_end + 1

    if config.get("has_acks", False) and begin_acks_line:
        body_end = max(body_start, begin_acks_line - 1)
    else:
        if _fallback_boundaries["backmatter_start_fallback"] == "end_doc":
            body_end = max(body_start, end_doc_line - 1)
        else:
            body_end = max(body_start, end_doc_line - 1)

    # ── Zone 5: backmatter ──────────────────────────────────────────────
    if config.get("has_acks", False) and begin_acks_line:
        backmatter_start = begin_acks_line
    else:
        backmatter_start = end_doc_line
    backmatter_end = end_doc_line

    return [
        Zone(name="preamble",    start_line=preamble_start,    end_line=preamble_end),
        Zone(name="frontmatter", start_line=frontmatter_start, end_line=frontmatter_end),
        Zone(name="abstract",    start_line=abstract_start,    end_line=abstract_end),
        Zone(name="body",        start_line=body_start,        end_line=body_end),
        Zone(name="backmatter",  start_line=backmatter_start,  end_line=backmatter_end),
    ]


def _extract_metadata(lines: list[str], doc_class: str) -> dict[str, Any]:
    """Pull title / DOI / keywords / abstract text from the preamble + frontmatter."""

    text = "".join(lines)
    metadata: dict[str, Any] = {}

    table = ACM_META if doc_class == "acmart" else GENERIC_META
    for key, pattern in table.items():
        match = pattern.search(text)
        if match:
            metadata[key] = match.group(1).strip()

    if doc_class != "acmart":
        abs_match = ACM_META["abstract"].search(text)
        if abs_match:
            metadata["abstract"] = abs_match.group(1).strip()

    return metadata


__all__ = ["detect_zones"]
