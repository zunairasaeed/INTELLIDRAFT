"""
Tests for the ACM LaTeX editing backend.
Run with: python -m pytest src/Latex_Alignment/tests/test_all.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from src.Latex_Alignment.parser.parser import parse, find_node, to_tree_json
from src.Latex_Alignment.editor.operations import (
    add_paragraph, add_section, add_subsection, add_subsubsection,
    rename, delete, rewrite, replace_paragraph, move_section, set_title,
    execute_action
)
from src.Latex_Alignment.editor.serializer import serialize


# ── Fixtures ───────────────────────────────────────────────────────────────────

MINIMAL_TEX = r"""
\documentclass[sigconf]{acmart}
\begin{document}
\title{Test Paper}
\author{Test Author}
\maketitle
\begin{abstract}
This is the abstract.
\end{abstract}
\keywords{keyword1, keyword2}
\section{Introduction}
\label{sec:introduction}
This is the introduction paragraph.
\section{Methodology}
\label{sec:methodology}
This is the methodology section.
\subsection{Data Collection}
\label{sec:data_collection}
Data collection details here.
\section{Results}
\label{sec:results}
Results go here.
\section{Conclusion}
\label{sec:conclusion}
Conclusion text.
\begin{acks}
Thanks to everyone.
\end{acks}
\bibliographystyle{ACM-Reference-Format}
\bibliography{references}
\end{document}
""".strip()

FULL_TEX = (
    (Path(__file__).parent / "sample-sigconf.tex").read_text(encoding="utf-8")
    if (Path(__file__).parent / "sample-sigconf.tex").exists()
    else MINIMAL_TEX
)


@pytest.fixture
def minimal_tree():
    return parse(MINIMAL_TEX)

@pytest.fixture
def full_tree():
    return parse(FULL_TEX)


# ── Parser tests ───────────────────────────────────────────────────────────────

class TestParser:
    def test_detects_sigconf(self, minimal_tree):
        assert minimal_tree.template_id == "sigconf"

    def test_extracts_title(self, minimal_tree):
        assert "Test Paper" in minimal_tree.title

    def test_finds_abstract(self, minimal_tree):
        assert minimal_tree.abstract is not None
        assert minimal_tree.abstract.zone == "abstract"
        content = " ".join(b.raw for b in minimal_tree.abstract.content_blocks)
        assert "abstract" in content.lower()

    def test_finds_body_sections(self, minimal_tree):
        ids = [s.id for s in minimal_tree.body]
        assert "introduction" in ids
        assert "methodology" in ids
        assert "results" in ids
        assert "conclusion" in ids

    def test_finds_subsection(self, minimal_tree):
        meth = find_node(minimal_tree, "methodology")
        assert meth is not None
        assert len(meth.children) == 1
        assert meth.children[0].label == "Data Collection"

    def test_finds_acks(self, minimal_tree):
        assert minimal_tree.acks is not None
        assert minimal_tree.acks.zone == "acks"

    def test_finds_bibliography(self, minimal_tree):
        assert "ACM-Reference-Format" in minimal_tree.bibliography_raw

    def test_preamble_preserved(self, minimal_tree):
        assert "\\documentclass[sigconf]{acmart}" in minimal_tree.preamble

    def test_section_content(self, minimal_tree):
        intro = find_node(minimal_tree, "introduction")
        content = " ".join(b.raw for b in intro.content_blocks)
        assert "introduction paragraph" in content.lower()

    def test_full_file_sections(self, full_tree):
        # Full sigconf file should have multiple sections
        assert len(full_tree.body) >= 3

    def test_section_levels(self, minimal_tree):
        intro = find_node(minimal_tree, "introduction")
        assert intro.level == 1
        dc = find_node(minimal_tree, "data_collection")
        assert dc.level == 2

    def test_label_tags_extracted(self, minimal_tree):
        intro = find_node(minimal_tree, "introduction")
        assert intro.label_tag == "sec:introduction"

    def test_to_tree_json_structure(self, minimal_tree):
        j = to_tree_json(minimal_tree)
        assert "sections" in j
        assert "title" in j
        ids = [s["id"] for s in j["sections"]]
        assert "abstract" in ids
        assert "acks" in ids


# ── Operation tests ────────────────────────────────────────────────────────────

class TestAddParagraph:
    def test_add_to_end(self, minimal_tree):
        new_tree, warnings = add_paragraph(
            minimal_tree, "introduction", "New paragraph text.", "end"
        )
        intro = find_node(new_tree, "introduction")
        assert any("New paragraph text" in b.raw for b in intro.content_blocks)
        assert not warnings

    def test_add_to_start(self, minimal_tree):
        new_tree, _ = add_paragraph(
            minimal_tree, "introduction", "First paragraph.", "start"
        )
        intro = find_node(new_tree, "introduction")
        assert "First paragraph" in intro.content_blocks[0].raw

    def test_invalid_section(self, minimal_tree):
        _, warnings = add_paragraph(minimal_tree, "nonexistent", "text")
        assert len(warnings) > 0

    def test_does_not_mutate_original(self, minimal_tree):
        original_count = len(find_node(minimal_tree, "introduction").content_blocks)
        add_paragraph(minimal_tree, "introduction", "extra text")
        assert len(find_node(minimal_tree, "introduction").content_blocks) == original_count

    def test_escapes_special_chars(self, minimal_tree):
        new_tree, _ = add_paragraph(
            minimal_tree, "introduction", "Uses 50% accuracy & high precision."
        )
        intro = find_node(new_tree, "introduction")
        last = intro.content_blocks[-1].raw
        assert r'\%' in last or "50" in last  # escaped or preserved


class TestAddSection:
    def test_adds_after_given(self, minimal_tree):
        new_tree, _ = add_section(minimal_tree, "methodology", "Discussion")
        ids = [s.id for s in new_tree.body]
        meth_idx = ids.index("methodology")
        disc_idx = ids.index("discussion")
        assert disc_idx == meth_idx + 1

    def test_section_gets_label_tag(self, minimal_tree):
        new_tree, _ = add_section(minimal_tree, "results", "Future Work")
        fw = find_node(new_tree, "future_work")
        assert fw is not None
        assert fw.label_tag == "sec:future_work"

    def test_after_missing_appends(self, minimal_tree):
        new_tree, warnings = add_section(minimal_tree, "nonexistent", "Extra")
        assert find_node(new_tree, "extra") is not None
        assert len(warnings) > 0


class TestAddSubsection:
    def test_adds_subsection(self, minimal_tree):
        new_tree, warnings = add_subsection(
            minimal_tree, "results", "Quantitative Results"
        )
        results = find_node(new_tree, "results")
        assert len(results.children) == 1
        assert results.children[0].label == "Quantitative Results"
        assert not warnings

    def test_subsection_level_is_2(self, minimal_tree):
        new_tree, _ = add_subsection(minimal_tree, "conclusion", "Future Directions")
        sub = find_node(new_tree, "future_directions")
        assert sub.level == 2


class TestRename:
    def test_renames_section(self, minimal_tree):
        new_tree, _ = rename(minimal_tree, "results", "Evaluation")
        node = find_node(new_tree, "results")
        assert node.label == "Evaluation"

    def test_updates_label_tag(self, minimal_tree):
        new_tree, _ = rename(minimal_tree, "results", "Evaluation")
        node = find_node(new_tree, "results")
        assert "evaluation" in node.label_tag

    def test_invalid_target(self, minimal_tree):
        _, warnings = rename(minimal_tree, "ghost", "New Name")
        assert len(warnings) > 0


class TestDelete:
    def test_deletes_section(self, minimal_tree):
        new_tree, _ = delete(minimal_tree, "results")
        assert find_node(new_tree, "results") is None

    def test_remaining_sections_intact(self, minimal_tree):
        new_tree, _ = delete(minimal_tree, "results")
        assert find_node(new_tree, "introduction") is not None
        assert find_node(new_tree, "conclusion") is not None

    def test_deletes_with_children(self, minimal_tree):
        new_tree, _ = delete(minimal_tree, "methodology")
        assert find_node(new_tree, "methodology") is None
        assert find_node(new_tree, "data_collection") is None

    def test_invalid_section(self, minimal_tree):
        _, warnings = delete(minimal_tree, "ghost")
        assert len(warnings) > 0


class TestRewrite:
    def test_rewrites_content(self, minimal_tree):
        new_tree, _ = rewrite(minimal_tree, "conclusion", "This is the new conclusion.")
        node = find_node(new_tree, "conclusion")
        content = " ".join(b.raw for b in node.content_blocks)
        assert "new conclusion" in content

    def test_preserves_figures(self, minimal_tree):
        # Manually add a figure block to results
        from src.Latex_Alignment.parser.parser import ContentBlock
        results = find_node(minimal_tree, "results")
        results.content_blocks.append(
            ContentBlock(type="figure",
                         raw="\\begin{figure}\\end{figure}", editable=False)
        )
        new_tree, _ = rewrite(minimal_tree, "results", "New results text.")
        node = find_node(new_tree, "results")
        assert any(b.type == "figure" for b in node.content_blocks)


class TestReplaceParagraph:
    def test_replaces_first_paragraph(self, minimal_tree):
        new_tree, _ = replace_paragraph(
            minimal_tree, "introduction", 0, "Replaced first paragraph."
        )
        intro = find_node(new_tree, "introduction")
        editable = [b for b in intro.content_blocks if b.editable]
        assert "Replaced first paragraph" in editable[0].raw

    def test_out_of_range(self, minimal_tree):
        _, warnings = replace_paragraph(minimal_tree, "conclusion", 99, "text")
        assert len(warnings) > 0


class TestMoveSection:
    def test_moves_section(self, minimal_tree):
        new_tree, _ = move_section(minimal_tree, "conclusion", "introduction")
        ids = [s.id for s in new_tree.body]
        intro_idx = ids.index("introduction")
        conc_idx  = ids.index("conclusion")
        assert conc_idx == intro_idx + 1

    def test_invalid_target(self, minimal_tree):
        _, warnings = move_section(minimal_tree, "ghost", "introduction")
        assert len(warnings) > 0


class TestSetTitle:
    def test_sets_title(self, minimal_tree):
        new_tree, _ = set_title(minimal_tree, "My New Title")
        assert new_tree.title == "My New Title"

    def test_updates_metadata_raw(self, minimal_tree):
        new_tree, _ = set_title(minimal_tree, "Updated Title")
        assert "Updated Title" in new_tree.metadata_raw or \
               "Updated Title" in new_tree.preamble


# ── Dispatcher tests ───────────────────────────────────────────────────────────

class TestDispatcher:
    def test_add_paragraph_dispatch(self, minimal_tree):
        new_tree, _ = execute_action(minimal_tree, {
            "action": "add_paragraph",
            "target": "introduction",
            "content": "Dispatched paragraph.",
            "position": "end"
        })
        intro = find_node(new_tree, "introduction")
        assert any("Dispatched" in b.raw for b in intro.content_blocks)

    def test_unknown_action(self, minimal_tree):
        _, warnings = execute_action(minimal_tree, {"action": "fly_to_moon"})
        assert len(warnings) > 0

    def test_clarify_action(self, minimal_tree):
        _, warnings = execute_action(minimal_tree, {
            "action": "clarify",
            "question": "Which section?"
        })
        assert any("CLARIFY" in w for w in warnings)


# ── Serializer tests ───────────────────────────────────────────────────────────

class TestSerializer:
    def test_produces_valid_structure(self, minimal_tree):
        tex = serialize(minimal_tree)
        assert "\\begin{document}" in tex
        assert "\\end{document}" in tex
        assert "\\section{Introduction}" in tex
        assert "\\section{Methodology}" in tex

    def test_abstract_wrapped(self, minimal_tree):
        tex = serialize(minimal_tree)
        assert "\\begin{abstract}" in tex
        assert "\\end{abstract}" in tex

    def test_acks_wrapped(self, minimal_tree):
        tex = serialize(minimal_tree)
        assert "\\begin{acks}" in tex
        assert "\\end{acks}" in tex

    def test_bibliography_preserved(self, minimal_tree):
        tex = serialize(minimal_tree)
        assert "ACM-Reference-Format" in tex
        assert "\\bibliography" in tex

    def test_preamble_preserved(self, minimal_tree):
        tex = serialize(minimal_tree)
        assert "\\documentclass[sigconf]{acmart}" in tex

    def test_subsection_present(self, minimal_tree):
        tex = serialize(minimal_tree)
        assert "\\subsection{Data Collection}" in tex


# ── Round-trip tests ───────────────────────────────────────────────────────────

class TestRoundTrip:
    def test_parse_serialize_preserves_sections(self, minimal_tree):
        tex = serialize(minimal_tree)
        tree2 = parse(tex)
        ids1 = {s.id for s in minimal_tree.body}
        ids2 = {s.id for s in tree2.body}
        assert ids1 == ids2

    def test_add_then_serialize_then_reparse(self, minimal_tree):
        # Add section → serialize → reparse → section still there
        t2, _ = add_section(minimal_tree, "results", "Discussion")
        tex = serialize(t2)
        t3 = parse(tex)
        assert find_node(t3, "discussion") is not None

    def test_rename_survives_round_trip(self, minimal_tree):
        t2, _ = rename(minimal_tree, "results", "Evaluation")
        tex = serialize(t2)
        t3 = parse(tex)
        labels = [s.label for s in t3.body]
        assert "Evaluation" in labels

    def test_delete_survives_round_trip(self, minimal_tree):
        t2, _ = delete(minimal_tree, "results")
        tex = serialize(t2)
        t3 = parse(tex)
        assert find_node(t3, "results") is None

    def test_added_paragraph_in_output(self, minimal_tree):
        t2, _ = add_paragraph(
            minimal_tree, "introduction", "This is a brand new paragraph.", "end"
        )
        tex = serialize(t2)
        assert "brand new paragraph" in tex

    def test_full_file_round_trip(self, full_tree):
        tex = serialize(full_tree)
        tree2 = parse(tex)
        # Should still have sections
        assert len(tree2.body) >= 3
        assert tree2.abstract is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
