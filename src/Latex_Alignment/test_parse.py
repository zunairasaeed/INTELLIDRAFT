"""Quick smoke test for the LaTeX Editor Agent parser.

Run from the repository root::

    python -m src.Latex_Alignment.test_parse

The script looks for ``sample-sigconf.tex`` next to this file. If it is
missing, a tiny synthetic ACM sample is written there automatically so the
parser can still be exercised end-to-end. No Groq call is made.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow direct ``python test_parse.py`` invocation (not just module mode).
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.Latex_Alignment.agent import LatexEditorAgent  # noqa: E402

SAMPLE_NAME = "sample-sigconf.tex"

_FALLBACK_SAMPLE = r"""\documentclass[sigconf]{acmart}

\acmConference[CONF '26]{ACM Conference}{June 01--03, 2026}{New York, NY}
\acmDOI{10.1145/1122334.4455667}
\keywords{LaTeX, parsing, editing, agents}

\title{A Surgical LaTeX Editor Agent}

\begin{document}

\begin{abstract}
We present a backend agent that parses LaTeX papers into structural zones
and edits individual sections under natural-language instructions.
\end{abstract}

\maketitle

\section{Introduction}
This section motivates the work and outlines our contributions
\cite{Knuth1984Literate, Lamport1994LaTeX}.

\section{Background}
\label{sec:background}
Prior work on academic-writing assistants is reviewed here.

\subsection{Editors}
Existing LaTeX editors focus on syntax, not semantics.

\section{Methodology}
% TODO: write this section

\section{Results}

\section{Conclusion}
We have described a surgical editor for ACM-style papers.

\begin{acks}
We thank the IntelliDraft team for valuable feedback.
\end{acks}

\bibliographystyle{ACM-Reference-Format}
\bibliography{refs}

\end{document}
"""


def _ensure_sample() -> Path:
    sample_path = _THIS_DIR / SAMPLE_NAME
    if not sample_path.is_file():
        sample_path.write_text(_FALLBACK_SAMPLE, encoding="utf-8")
        print(f"[test_parse] No {SAMPLE_NAME} found — wrote a synthetic ACM sample.")
    return sample_path


def main() -> int:
    sample_path = _ensure_sample()
    print(f"[test_parse] Parsing: {sample_path}\n")

    agent = LatexEditorAgent(str(sample_path))
    document = agent.load()

    print("-- Document metadata -------------------------------------------")
    print(f"  doc_class : {document.doc_class}")
    print(f"  doc_style : {document.doc_style}")
    for key, value in document.metadata.items():
        short = (value[:80] + "...") if isinstance(value, str) and len(value) > 80 else value
        print(f"  {key:<10}: {short}")
    print()

    print("-- Zones (5) ---------------------------------------------------")
    for zone in document.zones:
        span = f"{zone.start_line:>4}-{zone.end_line:<4}"
        print(f"  [{span}]  {zone.name}")
    print()

    print("-- Sections ----------------------------------------------------")
    if not document.sections:
        print("  (no sections indexed)")
    for section in document.sections:
        tag = []
        if section.is_empty:
            tag.append("EMPTY")
        if section.is_implicit:
            tag.append("implicit")
        flag = f"  [{', '.join(tag)}]" if tag else ""
        print(
            f"  {section.id:<22} L{section.start_line:>4}-{section.end_line:<4} "
            f"d{section.depth} {section.cmd:<14} {section.title}{flag}"
        )
        if section.citations:
            print(f"    cites : {', '.join(section.citations)}")
        if section.labels:
            print(f"    labels: {', '.join(section.labels)}")
    print()

    empty_count = sum(1 for s in document.sections if s.is_empty)
    implicit_count = sum(1 for s in document.sections if s.is_implicit)
    print(
        f"[test_parse] OK — {len(document.sections)} sections "
        f"({empty_count} empty, {implicit_count} implicit) across "
        f"{len(document.zones)} zones."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
