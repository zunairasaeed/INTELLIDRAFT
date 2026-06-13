"""Tests for ``write_patch`` — surgical line-range replacement + backup."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.editor.surgical_writer import Patch, write_patch


@pytest.fixture
def tex_file(tmp_path: Path) -> Path:
    path = tmp_path / "doc.tex"
    path.write_text("a\nb\nc\nd\n", encoding="utf-8")
    return path


def test_write_patch_replaces_only_target_range(tex_file: Path) -> None:
    write_patch(tex_file, Patch(start_line=2, end_line=3, new_text="B\nC"))
    assert tex_file.read_text(encoding="utf-8") == "a\nB\nC\nd\n"


def test_write_patch_creates_backup(tex_file: Path) -> None:
    original = tex_file.read_text(encoding="utf-8")
    write_patch(tex_file, Patch(start_line=1, end_line=1, new_text="A"))
    backup = tex_file.with_suffix(tex_file.suffix + ".bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original


def test_write_patch_appends_trailing_newline_if_missing(tex_file: Path) -> None:
    write_patch(tex_file, Patch(start_line=4, end_line=4, new_text="D"))
    out = tex_file.read_text(encoding="utf-8")
    assert out.endswith("\n")
    assert out == "a\nb\nc\nD\n"


def test_write_patch_clamps_out_of_range_end(tex_file: Path) -> None:
    write_patch(tex_file, Patch(start_line=3, end_line=999, new_text="X"))
    assert tex_file.read_text(encoding="utf-8") == "a\nb\nX\n"


def test_write_patch_clamps_negative_start(tex_file: Path) -> None:
    write_patch(tex_file, Patch(start_line=-5, end_line=2, new_text="HEAD"))
    assert tex_file.read_text(encoding="utf-8") == "HEAD\nc\nd\n"
