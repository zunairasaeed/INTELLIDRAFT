"""
Tests for service_adapter.py
Verifies every route response shape matches what LatexEditor.jsx expects.
No LLM calls — operations tested directly.
Run: python -m pytest tests/test_adapter.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from service_adapter import (
    LatexWorkspace, WorkspaceError,
    build_state, run_ask, export_tex, reset_workspace,
    _flatten_sections, StatePayload, AskPayload,
)
from editor.operations import execute_action
from editor.serializer import serialize
from parser.parser import parse

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


# ── LatexWorkspace ─────────────────────────────────────────────────────────────

class TestLatexWorkspace:
    def test_not_loaded_by_default(self, empty_ws):
        assert not empty_ws.is_loaded()

    def test_loaded_after_load_files(self, loaded_ws):
        assert loaded_ws.is_loaded()

    def test_stores_tex_name(self, loaded_ws):
        assert loaded_ws.original_tex_name == "test.tex"

    def test_stores_bib_content(self, loaded_ws):
        assert "Smith2020" in loaded_ws.bib_content

    def test_tex_path_exists(self, loaded_ws):
        assert loaded_ws.tex_path.exists()

    def test_reset_clears_state(self, loaded_ws):
        loaded_ws.reset()
        assert not loaded_ws.is_loaded()

    def test_has_agent(self, loaded_ws):
        assert loaded_ws.agent is not None

    def test_persist_writes_file(self, loaded_ws):
        loaded_ws._persist_tex()
        content = loaded_ws.tex_path.read_text()
        assert "\\begin{document}" in content


# ── build_state ────────────────────────────────────────────────────────────────

class TestBuildState:
    def test_loaded_state(self, loaded_ws):
        s = build_state(loaded_ws)
        assert s.loaded is True
        assert s.tex_filename == "test.tex"
        assert s.has_bib is True
        assert s.doc_class == "sigconf"
        assert s.section_count >= 4
        assert s.bib_key_count == 1

    def test_unloaded_state(self, empty_ws):
        s = build_state(empty_ws)
        assert s.loaded is False
        assert s.section_count == 0

    def test_to_dict_keys(self, loaded_ws):
        d = build_state(loaded_ws).to_dict()
        for key in ["loaded","tex_filename","has_bib","doc_class",
                    "doc_style","section_count","bib_key_count","metadata"]:
            assert key in d, f"Missing key: {key}"

    def test_metadata_has_title(self, loaded_ws):
        d = build_state(loaded_ws).to_dict()
        assert "title" in d["metadata"]


# ── AgentFacade.list_sections ──────────────────────────────────────────────────

class TestListSections:
    def test_returns_list(self, loaded_ws):
        sections = loaded_ws.agent.list_sections()
        assert isinstance(sections, list)
        assert len(sections) >= 4

    def test_section_has_required_fields(self, loaded_ws):
        sections = loaded_ws.agent.list_sections()
        required = ["id","title","cmd","depth","start_line","end_line",
                    "line_count","is_empty","is_implicit","citations",
                    "labels","raw_lines","raw_text"]
        for key in required:
            assert key in sections[0], f"Missing field: {key}"

    def test_abstract_is_implicit(self, loaded_ws):
        sections = loaded_ws.agent.list_sections()
        abstract = next(s for s in sections if s["id"] == "abstract")
        assert abstract["is_implicit"] is True

    def test_section_cmd_values(self, loaded_ws):
        sections = loaded_ws.agent.list_sections()
        cmds = {s["cmd"] for s in sections}
        assert "section" in cmds

    def test_subsection_depth(self, loaded_ws):
        sections = loaded_ws.agent.list_sections()
        subsections = [s for s in sections if s["cmd"] == "subsection"]
        assert len(subsections) >= 1
        assert subsections[0]["depth"] == 2

    def test_acks_present(self, loaded_ws):
        sections = loaded_ws.agent.list_sections()
        ids = [s["id"] for s in sections]
        assert "acks" in ids


# ── AgentFacade.get_section ────────────────────────────────────────────────────

class TestGetSection:
    def test_returns_section(self, loaded_ws):
        s = loaded_ws.agent.get_section("introduction")
        assert s["id"] == "introduction"
        assert s["title"] == "Introduction"

    def test_returns_raw_text(self, loaded_ws):
        s = loaded_ws.agent.get_section("introduction")
        assert "intro text" in s["raw_text"].lower()

    def test_404_on_missing(self, loaded_ws):
        with pytest.raises(WorkspaceError) as exc:
            loaded_ws.agent.get_section("nonexistent")
        assert exc.value.status_code == 404

    def test_abstract_section(self, loaded_ws):
        s = loaded_ws.agent.get_section("abstract")
        assert s["cmd"] == "abstract"
        assert "abstract" in s["raw_text"].lower()


# ── AgentFacade.replace_content ───────────────────────────────────────────────

class TestReplaceContent:
    def test_replaces_content(self, loaded_ws):
        result = loaded_ws.agent.replace_content(
            "introduction", "Brand new intro content."
        )
        assert result["ok"] is True
        assert result["section_id"] == "introduction"

    def test_persists_to_file(self, loaded_ws):
        loaded_ws.agent.replace_content("conclusion", "New conclusion.")
        tex = loaded_ws.tex_path.read_text()
        assert "New conclusion" in tex

    def test_404_on_missing(self, loaded_ws):
        with pytest.raises(WorkspaceError) as exc:
            loaded_ws.agent.replace_content("ghost", "text")
        assert exc.value.status_code == 404

    def test_response_has_required_keys(self, loaded_ws):
        result = loaded_ws.agent.replace_content("results", "Updated results.")
        for key in ["ok","section_id","section_title","raw_text","summary"]:
            assert key in result, f"Missing key: {key}"


# ── export_tex ─────────────────────────────────────────────────────────────────

class TestExportTex:
    def test_returns_tuple(self, loaded_ws):
        tex, filename = export_tex(loaded_ws)
        assert isinstance(tex, str)
        assert filename == "test.tex"

    def test_tex_is_valid(self, loaded_ws):
        tex, _ = export_tex(loaded_ws)
        assert "\\begin{document}" in tex
        assert "\\end{document}" in tex

    def test_raises_if_not_loaded(self, empty_ws):
        with pytest.raises(WorkspaceError):
            export_tex(empty_ws)

    def test_bib_unchanged(self, loaded_ws):
        # bib content separate — should still be Smith2020
        assert "Smith2020" in loaded_ws.bib_content


# ── reset_workspace ────────────────────────────────────────────────────────────

class TestResetWorkspace:
    def test_reset_response_shape(self, loaded_ws):
        result = reset_workspace(loaded_ws)
        assert "status" in result
        assert "was_loaded" in result
        assert "loaded" in result

    def test_was_loaded_true(self, loaded_ws):
        result = reset_workspace(loaded_ws)
        assert result["was_loaded"] is True

    def test_still_loaded_after_reset(self, loaded_ws):
        # reset restores original, doesn't unload
        result = reset_workspace(loaded_ws)
        assert result["loaded"] is True

    def test_content_restored(self, loaded_ws):
        # Dirty the tree first
        loaded_ws.agent.replace_content("introduction", "DIRTY CONTENT")
        reset_workspace(loaded_ws)
        # After reset, intro should NOT have dirty content
        intro = loaded_ws.agent.get_section("introduction")
        assert "DIRTY CONTENT" not in intro["raw_text"]


# ── run_ask (without LLM — patch agent.get_action) ────────────────────────────

class TestRunAsk:
    """
    We patch agent.get_action to return a known action dict,
    so we can test run_ask's response shape without an LLM call.
    """

    def test_raises_if_not_loaded(self, empty_ws):
        with pytest.raises(WorkspaceError):
            # Monkeypatch to avoid actual LLM call
            run_ask(empty_ws, "do something")

    def test_loads_tex_if_provided(self, empty_ws, monkeypatch):
        import agent.agent as ag
        monkeypatch.setattr(ag, "call_llm", lambda sys, usr: '{"action":"clarify","question":"ok?"}')
        result = run_ask(empty_ws, "rewrite intro",
                         tex_bytes=SAMPLE_TEX, tex_filename="test.tex")
        assert empty_ws.is_loaded()

    def test_ask_payload_shape(self, loaded_ws, monkeypatch):
        import agent.agent as ag
        monkeypatch.setattr(ag, "call_llm", lambda sys, usr: (
            '{"action":"rewrite","target":"introduction","content":"New intro text."}'
        ))
        result = run_ask(loaded_ws, "rewrite the introduction")
        assert isinstance(result, AskPayload)
        for key in ["intent","ok","summary","section_id","section_title",
                    "file_changed","router","payload","state"]:
            assert hasattr(result, key), f"Missing field: {key}"

    def test_ask_to_dict_shape(self, loaded_ws, monkeypatch):
        import agent.agent as ag
        monkeypatch.setattr(ag, "call_llm", lambda sys, usr: (
            '{"action":"add_section","after":"results","label":"Discussion"}'
        ))
        result = run_ask(loaded_ws, "add a Discussion section after Results")
        d = result.to_dict()
        assert d["intent"] == "insert_section"
        assert d["ok"] is True

    def test_clarify_returns_unknown_intent(self, loaded_ws, monkeypatch):
        import agent.agent as ag
        monkeypatch.setattr(ag, "call_llm", lambda sys, usr: (
            '{"action":"clarify","question":"Which section?"}'
        ))
        result = run_ask(loaded_ws, "do the thing")
        assert result.intent == "unknown"
        assert result.ok is False

    def test_state_field_complete(self, loaded_ws, monkeypatch):
        import agent.agent as ag
        monkeypatch.setattr(ag, "call_llm", lambda sys, usr: (
            '{"action":"rename","target":"results","new_label":"Evaluation"}'
        ))
        result = run_ask(loaded_ws, "rename results to evaluation")
        state = result.state
        for key in ["loaded","tex_filename","has_bib","doc_class","section_count"]:
            assert key in state, f"Missing state key: {key}"

    def test_file_changed_after_edit(self, loaded_ws, monkeypatch):
        import agent.agent as ag
        monkeypatch.setattr(ag, "call_llm", lambda sys, usr: (
            '{"action":"add_paragraph","target":"conclusion","content":"Future work."}'
        ))
        result = run_ask(loaded_ws, "add paragraph to conclusion")
        assert result.file_changed is True

    def test_tex_persisted_after_edit(self, loaded_ws, monkeypatch):
        import agent.agent as ag
        monkeypatch.setattr(ag, "call_llm", lambda sys, usr: (
            '{"action":"rewrite","target":"conclusion","content":"Final thoughts."}'
        ))
        run_ask(loaded_ws, "rewrite conclusion")
        tex = loaded_ws.tex_path.read_text()
        assert "Final thoughts" in tex


# ── Full integration: upload → edit → export ──────────────────────────────────

class TestFullFlow:
    def test_upload_list_edit_export(self, monkeypatch):
        import agent.agent as ag
        monkeypatch.setattr(ag, "call_llm", lambda sys, usr: (
            '{"action":"add_section","after":"results","label":"Discussion"}'
        ))

        ws = LatexWorkspace()
        ws.load_files(SAMPLE_TEX, "paper.tex")

        # 1. sections load
        sections = ws.agent.list_sections()
        assert len(sections) >= 4

        # 2. chat command adds section
        result = run_ask(ws, "add a Discussion section")
        assert result.ok is True

        # 3. new section appears in list
        sections2 = ws.agent.list_sections()
        ids = [s["id"] for s in sections2]
        assert "discussion" in ids

        # 4. export contains new section
        tex, _ = export_tex(ws)
        assert "Discussion" in tex

    def test_replace_then_export(self):
        ws = LatexWorkspace()
        ws.load_files(SAMPLE_TEX, "paper.tex")
        ws.agent.replace_content("introduction", "Completely new introduction.")
        tex, _ = export_tex(ws)
        assert "Completely new introduction" in tex

    def test_reset_after_edits(self, monkeypatch):
        import agent.agent as ag
        monkeypatch.setattr(ag, "call_llm", lambda sys, usr: (
            '{"action":"delete","target":"conclusion"}'
        ))
        ws = LatexWorkspace()
        ws.load_files(SAMPLE_TEX, "paper.tex")
        run_ask(ws, "delete conclusion")
        reset_workspace(ws)
        sections = ws.agent.list_sections()
        ids = [s["id"] for s in sections]
        assert "conclusion" in ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
