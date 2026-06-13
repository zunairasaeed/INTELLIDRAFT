"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_tex() -> str:
    return (
        "\\documentclass{acmart}\n"
        "\\begin{document}\n"
        "\\title{Sample Paper}\n"
        "\\begin{abstract}\n"
        "We present a sample paper.\n"
        "\\end{abstract}\n"
        "\\section{Introduction}\n"
        "Introduction body.\n"
        "\\section{Methods}\n"
        "\\subsection{Setup}\n"
        "Setup body.\n"
        "\\bibliography{sample}\n"
        "\\end{document}\n"
    )
