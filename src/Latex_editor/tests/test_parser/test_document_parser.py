"""Tests for the ``Parser`` facade and the ``ParsedView`` it returns."""

from __future__ import annotations

from pathlib import Path

from app.parser.document_parser import Parser, ParsedView


def test_parser_returns_parsed_view_with_paths_and_sections(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text(
        "\\section{Intro}\n"
        "intro body\n"
        "\\section{Conclusion}\n"
        "conclusion body\n",
        encoding="utf-8",
    )

    view = Parser().parse(tex)

    assert isinstance(view, ParsedView)
    assert view.tex_path == tex
    assert view.bib_path is None
    assert [s.title for s in view.sections] == ["Intro", "Conclusion"]
    assert view.lines == tex.read_text(encoding="utf-8").splitlines(keepends=True)


def test_parser_accepts_string_paths(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("\\section{S}\nbody\n", encoding="utf-8")
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{x, title={t}}", encoding="utf-8")

    view = Parser().parse(str(tex), bib_path=str(bib))

    assert view.tex_path == tex
    assert view.bib_path == bib
    assert len(view.sections) == 1


def test_parser_bib_path_defaults_to_none(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("\\section{X}\nx\n", encoding="utf-8")

    view = Parser().parse(tex)
    assert view.bib_path is None
