"""Shared compiled regex patterns used by the parser and editor."""

from __future__ import annotations

import re

SECTION_RE = re.compile(
    r"^\s*\\(?P<cmd>section|subsection|subsubsection|paragraph|subparagraph)"
    r"\*?\s*\{(?P<title>.*?)\}\s*$"
)

CITE_RE = re.compile(r"\\cite[tp]?\*?\s*\{([^}]+)\}")
LABEL_RE = re.compile(r"\\label\s*\{([^}]+)\}")
REF_RE = re.compile(r"\\(?:ref|eqref|autoref|Cref|cref)\s*\{([^}]+)\}")
ENV_BEGIN_RE = re.compile(r"\\begin\s*\{([^}]+)\}")
ENV_END_RE = re.compile(r"\\end\s*\{([^}]+)\}")
