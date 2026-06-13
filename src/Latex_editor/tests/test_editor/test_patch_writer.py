"""Test the async ``Writer`` facade actually delegates to ``write_patch``."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.editor.patch_writer import Writer
from app.editor.surgical_writer import Patch


@pytest.mark.asyncio
async def test_writer_apply_writes_file_and_creates_backup(tmp_path: Path) -> None:
    tex = tmp_path / "doc.tex"
    tex.write_text("a\nb\nc\n", encoding="utf-8")

    await Writer().apply(tex, Patch(start_line=2, end_line=2, new_text="B"))

    assert tex.read_text(encoding="utf-8") == "a\nB\nc\n"
    backup = tex.with_suffix(tex.suffix + ".bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "a\nb\nc\n"
