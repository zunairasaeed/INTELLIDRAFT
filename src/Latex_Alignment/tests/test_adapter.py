"""Tests for service.py — verifies route response shapes match LatexEditor.jsx."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from src.Latex_Alignment.service import (
    AskPayload,
    LatexWorkspace,
    WorkspaceError,
    build_state,
    export_tex,
    reset_workspace,
    run_ask,
)

SAMPLE_TEX = r"""
\documentclass[sigconf]{acmart}
\begin{document}
\title{Test Paper}
\author{Test Author}
\maketitle
\begin{abstract}
This is the abstract.
\end{abstract}
\keywords{kw1, kw2}
\section{Introduction}
\label{sec:introduction}
This is intro text.
\section{Methodology}
\label{sec:methodology}
Methodology text here.
\subsection{Data Collection}
Data details.
\section{Results}
Results text.
\section{Conclusion}
Conclusion text.
\begin{acks}
Thanks everyone.
\end{acks}
\bibliographystyle{ACM-Reference-Format}
\bibliography{references}
\end{document}
""".strip().encode()

SAMPLE_BIB = b"""
@article{Smith2020,
  author = {Smith, J},
  title  = {A Paper},
  year   = {2020}
}
"""


@pytest.fixture
def loaded_ws():
    ws = LatexWorkspace()
    ws.load_files(SAMPLE_TEX, "test.tex", SAMPLE_BIB, "refs.bib")
    return ws


@pytest.fixture
def empty_ws():
    return LatexWorkspace()


class TestLatexWorkspace:
    def test_loaded_after_load_files(self, loaded_ws):
        assert loaded_ws.is_loaded()

    def test_has_agent(self, loaded_ws):
        assert loaded_ws.agent is not None


class TestBuildState:
    def test_loaded_state(self, loaded_ws):
        state = build_state(loaded_ws)
        assert state.loaded is True
        assert state.section_count >= 4


class TestListSections:
    def test_returns_objects_with_fields(self, loaded_ws):
        sections = loaded_ws.agent.list_sections()
        assert len(sections) >= 4
        assert sections[0].id
        assert isinstance(sections[0].raw_lines, list)


class TestGetSection:
    def test_returns_section(self, loaded_ws):
        section = loaded_ws.agent.get_section("introduction")
        assert section.title == "Introduction"

    def test_raw_lines_include_section_header(self, loaded_ws):
        section = loaded_ws.agent.get_section("introduction")
        assert section.raw_lines[0].strip().startswith("\\section{Introduction}")

    def test_raw_lines_body_visible_to_frontend(self, loaded_ws):
        """LatexEditor.jsx drops raw_lines[0] for explicit sections — body must remain."""
        section = loaded_ws.agent.get_section("introduction")
        body = "".join(section.raw_lines[1:]) if len(section.raw_lines) > 1 else ""
        assert "intro text" in body.lower()

    def test_abstract_raw_lines_include_env_wrapper(self, loaded_ws):
        section = loaded_ws.agent.get_section("abstract")
        assert section.raw_lines[0].strip().startswith("\\begin{abstract}")
        assert section.raw_lines[-1].strip().startswith("\\end{abstract}")

    def test_missing_raises_keyerror(self, loaded_ws):
        with pytest.raises(KeyError):
            loaded_ws.agent.get_section("nonexistent")


class TestReplaceContent:
    def test_replaces_content(self, loaded_ws):
        result = loaded_ws.agent.replace_content("introduction", "Brand new intro content.")
        assert result.section_id == "introduction"

    def test_after_add_paragraph_body_visible_in_raw_lines(self, loaded_ws):
        import src.Latex_Alignment.editor.operations as ops

        tree, _ = ops.add_paragraph(
            loaded_ws.session.tree,
            "introduction",
            "Machine learning has transformed how we process natural language data.",
            "end",
        )
        loaded_ws.session.tree = tree
        section = loaded_ws.agent.get_section("introduction")
        body = "".join(section.raw_lines[1:])
        assert "machine learning" in body.lower()
        assert "intro text" in body.lower()

    def test_persists_to_file(self, loaded_ws):
        loaded_ws.agent.replace_content("conclusion", "New conclusion.")
        tex = loaded_ws.tex_path.read_text()
        assert "New conclusion" in tex


class TestExportTex:
    def test_returns_tuple(self, loaded_ws):
        tex, filename = export_tex(loaded_ws)
        assert "\\begin{document}" in tex
        assert filename == "test.tex"


class TestResetWorkspace:
    def test_reset_unloads(self, loaded_ws):
        result = reset_workspace(loaded_ws)
        assert result["loaded"] is False
        assert result["status"] == "ok"


class TestRunAsk:
    def test_raises_if_not_loaded(self, empty_ws):
        with pytest.raises(WorkspaceError):
            run_ask(empty_ws, query="do something")

    def test_ask_payload_shape(self, loaded_ws, monkeypatch):
        import src.Latex_Alignment.agent.agent as ag

        monkeypatch.setattr(
            ag,
            "call_llm",
            lambda sys, usr: '{"action":"rewrite","target":"introduction","content":"New intro text."}',
        )
        result = run_ask(loaded_ws, query="rewrite the introduction")
        assert isinstance(result, AskPayload)
        assert result.intent == "edit"
