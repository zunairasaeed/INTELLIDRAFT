"""Tests for ``parse_sections`` and ``SectionNode``."""

from __future__ import annotations

from app.parser.section_indexer import (
    SECTION_DEPTH,
    ParsedDocument,
    SectionNode,
    make_stable_id,
    parse_sections,
)


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def test_parse_sections_returns_three_sections() -> None:
    src = _lines(
        "\\documentclass{acmart}\n"
        "\\begin{document}\n"
        "\\section{Introduction}\n"
        "Intro body.\n"
        "\\section{Methods}\n"
        "\\subsection{Setup}\n"
        "Setup body.\n"
        "\\end{document}\n"
    )
    doc = parse_sections(src)
    assert isinstance(doc, ParsedDocument)
    titles = [s.title for s in doc.sections]
    assert titles == ["Introduction", "Methods", "Setup"]


def test_section_line_ranges_are_correct() -> None:
    src = _lines(
        "\\section{A}\n"  # line 1
        "a-body\n"  # line 2
        "\\section{B}\n"  # line 3
        "b-body\n"  # line 4
    )
    doc = parse_sections(src)
    a, b = doc.sections
    assert (a.start_line, a.end_line) == (1, 2)
    assert (a.body_start_line, a.body_end_line) == (2, 2)
    assert (b.start_line, b.end_line) == (3, 4)
    assert (b.body_start_line, b.body_end_line) == (4, 4)


def test_depths_match_command_table() -> None:
    src = _lines(
        "\\section{S}\n"
        "\\subsection{SS}\n"
        "\\subsubsection{SSS}\n"
        "\\paragraph{P}\n"
        "\\subparagraph{SP}\n"
    )
    doc = parse_sections(src)
    depths = [s.depth for s in doc.sections]
    assert depths == [
        SECTION_DEPTH["section"],
        SECTION_DEPTH["subsection"],
        SECTION_DEPTH["subsubsection"],
        SECTION_DEPTH["paragraph"],
        SECTION_DEPTH["subparagraph"],
    ]


def test_stable_id_is_deterministic() -> None:
    a = make_stable_id("Title", 1, "first line")
    b = make_stable_id("Title", 1, "first line")
    c = make_stable_id("Title", 1, "other line")
    assert a == b
    assert a != c
    assert len(a) == 8


def test_section_node_defaults() -> None:
    node = SectionNode(
        id="x",
        title="t",
        depth=1,
        start_line=1,
        end_line=2,
        body_start_line=2,
        body_end_line=2,
    )
    assert node.is_implicit is False
    assert node.parent_id is None
    assert node.children == []


def test_parse_assigns_unique_ids_for_distinct_sections() -> None:
    src = _lines(
        "\\section{A}\n"
        "a-body\n"
        "\\section{B}\n"
        "b-body\n"
    )
    doc = parse_sections(src)
    ids = [s.id for s in doc.sections]
    assert len(set(ids)) == 2
