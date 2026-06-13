"""Tests for the ``Validator`` facade and ``ValidatedPatch`` assembly."""

from __future__ import annotations

from app.editor.patch_validator import EditorOutput, Validator
from app.parser.section_indexer import parse_sections


def _doc():
    return parse_sections(
        [
            "\\section{Intro}\n",  # line 1
            "old body\n",  # line 2
            "\\section{Other}\n",  # line 3
            "other body\n",  # line 4
        ]
    )


def test_validator_emits_patch_for_known_section() -> None:
    doc = _doc()
    target = doc.sections[0]
    result = EditorOutput(
        section_id=target.id,
        new_text="new body content.",
        summary="rewrote intro",
    )

    validated = Validator().validate(result, doc)

    assert validated.ok
    assert validated.error is None
    assert validated.patch is not None
    assert validated.patch.start_line == target.body_start_line
    assert validated.patch.end_line == target.body_end_line
    assert validated.patch.new_text == "new body content."
    assert validated.summary == "rewrote intro"


def test_validator_rejects_unbalanced_braces() -> None:
    doc = _doc()
    target = doc.sections[0]
    result = EditorOutput(section_id=target.id, new_text="bad {brace")

    validated = Validator().validate(result, doc)
    assert not validated.ok
    assert validated.patch is None


def test_validator_rejects_unknown_section() -> None:
    doc = _doc()
    result = EditorOutput(section_id="nonexistent", new_text="ok")
    validated = Validator().validate(result, doc)
    assert not validated.ok
    assert "Unknown section" in (validated.error or "")
    assert validated.patch is None


def test_validator_enforces_required_citation() -> None:
    doc = _doc()
    target = doc.sections[0]
    result = EditorOutput(
        section_id=target.id,
        new_text="body without cite",
        require_citations=["\\cite{key}"],
    )
    validated = Validator().validate(result, doc)
    assert not validated.ok
    assert "Missing citation" in (validated.error or "")
