"""Tests for ``summarize_doc``."""

from __future__ import annotations

from app.agents.doc_summary import summarize_doc
from app.parser.section_indexer import parse_sections


def test_summarize_empty_doc() -> None:
    summary = summarize_doc(parse_sections([]))
    assert summary == {
        "total_lines": 0,
        "total_sections": 0,
        "sections": [],
    }


def test_summarize_doc_with_sections() -> None:
    doc = parse_sections(
        [
            "\\section{Intro}\n",
            "body\n",
            "\\subsection{Sub}\n",
            "sub body\n",
        ]
    )
    summary = summarize_doc(doc)

    assert summary["total_lines"] == 4
    assert summary["total_sections"] == 2

    titles = [s["title"] for s in summary["sections"]]
    depths = [s["depth"] for s in summary["sections"]]
    assert titles == ["Intro", "Sub"]
    assert depths == [1, 2]

    # Section ids should be 8-char stable hashes from ``make_stable_id``.
    for s in summary["sections"]:
        assert isinstance(s["id"], str)
        assert len(s["id"]) == 8
