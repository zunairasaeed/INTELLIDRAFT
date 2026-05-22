"""Single source of truth for every regex used by the LaTeX Editor Agent.

The regex is written against the ACM LaTeX command vocabulary, which is a
superset of what every other paper class (IEEEtran, elsarticle, llncs,
neurips, icml, ...) uses. Only the ``\\documentclass[STYLE]{...}`` line
changes between paper types; the structural commands themselves do not.

No other file in :mod:`Latex_Alignment` should define its own regex — all
patterns must be imported from here.
"""

from __future__ import annotations

import re

# ────────────────────────────────────────────────────────────────────────────
# Zone boundary markers
# Run these first, line-by-line, to identify the 5 structural document zones.
# ────────────────────────────────────────────────────────────────────────────
ZONE_MARKERS = {
    "doc_class":  re.compile(r'^\s*\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}'),
    "begin_doc":  re.compile(r'^\s*\\begin\s*\{document\}'),
    "begin_abs":  re.compile(r'^\s*\\begin\s*\{abstract\}'),
    "end_abs":    re.compile(r'^\s*\\end\s*\{abstract\}'),
    "maketitle":  re.compile(r'^\s*\\maketitle\b'),
    "begin_acks": re.compile(r'^\s*\\begin\s*\{acks\}'),
    "end_doc":    re.compile(r'^\s*\\end\s*\{document\}'),
}

# ────────────────────────────────────────────────────────────────────────────
# Document style extractor
# Extracts the style name from \documentclass[sigconf]{acmart}
# Falls back to a permissive class name so that any paper class is captured.
# ────────────────────────────────────────────────────────────────────────────
DOCCLASS_STYLE_RE = re.compile(
    r'\\documentclass\[([^\]]+)\]\{(?:acmart|article|IEEEtran|elsarticle|llncs|'
    r'aaai|neurips|icml|iclr|cvpr|usenix|[a-zA-Z0-9_-]+)\}'
)

# Plain class-name extractor (no required options). Used when no bracketed
# style is present, e.g. ``\documentclass{article}``.
DOCCLASS_NAME_RE = re.compile(
    r'\\documentclass\s*(?:\[[^\]]*\])?\s*\{([a-zA-Z0-9_-]+)\}'
)

# ────────────────────────────────────────────────────────────────────────────
# Section headers — TWO-STEP MATCH
#
# Regex can't balance braces, so we ship a cheap pre-matcher that pins down
# the command (and optional starred / short-title forms) and leaves the
# *body* of ``{...}`` for a manual brace-counting scan. This is what makes
# titles like ``\section{The \textsc{Surgical} Editor}`` or
# ``\section[Short]{Background \& \emph{Related} Work}`` actually index.
#
# Callers should use ``parse_section_header(line)`` from
# ``parser.section_indexer`` (or the helper here) — never ``SECTION_RE``
# directly.
# ────────────────────────────────────────────────────────────────────────────
SECTION_PREFIX_RE = re.compile(
    r'^\s*\\(?P<cmd>(?:sub){0,2}section|paragraph|subparagraph)\*?'
    r'\s*(?:\[(?P<short>[^\]]*)\])?\s*\{'
)

# Kept for backward compat (e.g. ``groq_client._strip_leading_section_header``)
# but uses the same prefix matcher so it still returns ``cmd``.
SECTION_RE = SECTION_PREFIX_RE


def extract_balanced_braces(text: str, open_index: int) -> tuple[str, int] | None:
    """Return ``(inside, end_index)`` where ``text[open_index] == '{'``.

    Counts balanced braces, ignoring ``\\{`` / ``\\}`` escapes. ``end_index`` is
    one past the matching closing brace. Returns ``None`` if no match.
    """

    if open_index >= len(text) or text[open_index] != "{":
        return None
    depth = 0
    i = open_index
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            # skip escaped char (handles \{ \} \\ etc.)
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : i], i + 1
        i += 1
    return None


def parse_section_header(line: str) -> dict | None:
    """Parse one line for ``\\section{}`` / ``\\subsection{}`` / ... headers.

    Returns a dict with ``cmd``, ``short`` (or None), ``title``, ``end_col``
    (column just after the closing brace), or ``None`` when the line does not
    start a section header.
    """

    m = SECTION_PREFIX_RE.match(line)
    if not m:
        return None
    brace_open = m.end() - 1  # SECTION_PREFIX_RE consumes the opening ``{``
    body = extract_balanced_braces(line, brace_open)
    if body is None:
        # Title continues on later lines — keep what we have and signal the
        # caller to scan forward. We return title as everything after ``{``.
        title = line[m.end():].rstrip("\n")
        return {
            "cmd": m.group("cmd"),
            "short": m.group("short"),
            "title": title,
            "end_col": len(line),
            "open_brace_at": brace_open,
            "balanced": False,
        }
    title, end_col = body
    return {
        "cmd": m.group("cmd"),
        "short": m.group("short"),
        "title": title,
        "end_col": end_col,
        "open_brace_at": brace_open,
        "balanced": True,
    }

# Depth lookup used by the indexer to avoid magic numbers.
SECTION_DEPTH = {
    "section":       1,
    "subsection":    2,
    "subsubsection": 3,
    "paragraph":     4,
    "subparagraph":  5,
}

# ────────────────────────────────────────────────────────────────────────────
# ACM-specific metadata (preamble zone only)
# ────────────────────────────────────────────────────────────────────────────
ACM_META = {
    "style":      re.compile(r'\\documentclass\[([^\]]+)\]\{acmart\}'),
    "title":      re.compile(r'\\title(?:\[[^\]]*\])?\{([^}]+)\}'),
    "doi":        re.compile(r'\\acmDOI\{([^}]+)\}'),
    "conference": re.compile(r'\\acmConference\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}'),
    "journal":    re.compile(r'\\acmJournal\{([^}]+)\}'),
    "keywords":   re.compile(r'\\keywords\{([^}]+)\}'),
    "abstract":   re.compile(r'\\begin\{abstract\}(.*?)\\end\{abstract\}', re.DOTALL),
}

# ────────────────────────────────────────────────────────────────────────────
# Generic metadata (non-ACM papers)
# ────────────────────────────────────────────────────────────────────────────
GENERIC_META = {
    "title":      re.compile(r'\\title(?:\[[^\]]*\])?\{([^}]+)\}'),
    "author":     re.compile(r'\\author(?:\[[^\]]*\])?\{([^}]+)\}'),
    "date":       re.compile(r'\\date\{([^}]*)\}'),
    "keywords":   re.compile(r'\\keywords\{([^}]+)\}'),
}

# ────────────────────────────────────────────────────────────────────────────
# Environment open/close
# ────────────────────────────────────────────────────────────────────────────
ENV_BEGIN = re.compile(r'^\s*\\begin\s*\{(?P<name>[^}]+)\}')
ENV_END   = re.compile(r'^\s*\\end\s*\{(?P<name>[^}]+)\}')

# ────────────────────────────────────────────────────────────────────────────
# Citations — all variants
# Handles: \cite, \citep, \citet, \citealt, \citealp, \citeauthor,
#          \citeyear, \citenum, \citetitle, \citeurl, \citetext, \citefull,
#          \autocite, \parencite, \footcite, biblatex variants,
#          plus optional [pre][post] notes and placeholder ``\cite{??}``.
# ────────────────────────────────────────────────────────────────────────────
CITE_RE = re.compile(
    r'\\(?:cite[tp]?(?:alt|alp|author|year|num|title|url|text|full)?[a-z]*'
    r'|autocite|parencite|footcite|textcite|smartcite|fullcite)'
    r'\s*(?:\[[^\]]*\]){0,2}\s*\{([^}]+)\}'
)

# ────────────────────────────────────────────────────────────────────────────
# Labels and refs
# ────────────────────────────────────────────────────────────────────────────
LABEL_RE = re.compile(r'\\label\s*\{([^}]+)\}')
REF_RE   = re.compile(r'\\(?:eq|auto|name|page|vp)?ref\*?\s*\{([^}]+)\}')

# ────────────────────────────────────────────────────────────────────────────
# TODO / placeholder comments — used to recognise "draft" sections
# ────────────────────────────────────────────────────────────────────────────
TODO_RE  = re.compile(r'%\s*TODO[:\s].*', re.IGNORECASE)
FIXME_RE = re.compile(r'%\s*FIXME[:\s].*', re.IGNORECASE)

# Any pure-comment line (whitespace then ``%``). Used by emptiness checks.
COMMENT_LINE_RE = re.compile(r'^\s*%')

# ────────────────────────────────────────────────────────────────────────────
# .bib parsing — minimal but tolerant of formatting variation
# ────────────────────────────────────────────────────────────────────────────
BIB_ENTRY_RE = re.compile(
    r'@(?P<type>[A-Za-z]+)\s*\{\s*(?P<key>[^,\s]+)\s*,',
)

# ────────────────────────────────────────────────────────────────────────────
# Sections that may NOT appear as \section{} but must still be indexed.
# These are LaTeX environments that act as logical sections; the indexer
# injects synthetic Section entries for them with ``is_implicit=True``.
# ────────────────────────────────────────────────────────────────────────────
IMPLICIT_SECTION_ENVS: dict[str, str] = {
    "abstract":     "Abstract",
    "acks":         "Acknowledgments",
    "appendix":     "Appendix",
    "theorem":      "Theorem",
    "proof":        "Proof",
    "algorithm":    "Algorithm",
    "figure":       "Figure",
    "table":        "Table",
    "lstlisting":   "Code Listing",
    "verbatim":     "Verbatim Block",
    "quote":        "Quote",
    "itemize":      "List",
    "enumerate":    "Numbered List",
}


__all__ = [
    "ZONE_MARKERS",
    "DOCCLASS_STYLE_RE",
    "DOCCLASS_NAME_RE",
    "SECTION_RE",
    "SECTION_PREFIX_RE",
    "SECTION_DEPTH",
    "extract_balanced_braces",
    "parse_section_header",
    "ACM_META",
    "GENERIC_META",
    "ENV_BEGIN",
    "ENV_END",
    "CITE_RE",
    "LABEL_RE",
    "REF_RE",
    "TODO_RE",
    "FIXME_RE",
    "COMMENT_LINE_RE",
    "BIB_ENTRY_RE",
    "IMPLICIT_SECTION_ENVS",
]
