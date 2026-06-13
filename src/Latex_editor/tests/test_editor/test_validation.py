"""Tests for ``validate_latex_block`` and its helpers."""

from __future__ import annotations

from app.editor.validation import (
    braces_balanced,
    envs_balanced,
    validate_latex_block,
)


def test_braces_balanced_simple_cases() -> None:
    assert braces_balanced("{a}{b}")
    assert braces_balanced("nested {x {y} z}")
    assert not braces_balanced("{a")
    assert not braces_balanced("a}")
    assert not braces_balanced("}{")


def test_envs_balanced_simple_cases() -> None:
    assert envs_balanced("\\begin{itemize}\n\\item x\n\\end{itemize}")
    assert envs_balanced(
        "\\begin{enumerate}\n\\begin{itemize}\n\\item y\n\\end{itemize}\n\\end{enumerate}"
    )
    assert not envs_balanced("\\begin{itemize}")
    assert not envs_balanced("\\end{itemize}")
    assert not envs_balanced("\\begin{a}\\end{b}")


def test_validate_accepts_clean_block() -> None:
    result = validate_latex_block("Hello \\cite{x}.")
    assert result.ok
    assert result.error is None


def test_validate_rejects_unbalanced_braces() -> None:
    result = validate_latex_block("Hello {world")
    assert not result.ok
    assert "braces" in (result.error or "").lower()


def test_validate_rejects_unbalanced_envs() -> None:
    result = validate_latex_block("\\begin{itemize}\n\\item x\n")
    assert not result.ok
    assert "environments" in (result.error or "").lower()


def test_validate_requires_citations_when_provided() -> None:
    text = "Body without any cites."
    result = validate_latex_block(text, require_citations=["\\cite{key}"])
    assert not result.ok
    assert "Missing citation" in (result.error or "")


def test_validate_passes_when_required_citation_present() -> None:
    text = "Body that mentions \\cite{key}."
    result = validate_latex_block(text, require_citations=["\\cite{key}"])
    assert result.ok


def test_validate_requires_labels_when_provided() -> None:
    text = "Body without labels."
    result = validate_latex_block(text, require_labels=["\\label{sec:intro}"])
    assert not result.ok
    assert "Missing label" in (result.error or "")
