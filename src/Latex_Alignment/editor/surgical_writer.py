"""Surgical writer.

Writes the result of an edit back into a ``.tex`` file while leaving every
line outside the target body interval byte-identical to the original.

A ``.tex.bak`` snapshot is always taken before the real file is modified.
The header line of a section (``\\section{...}``) is never touched: the
caller must populate ``EditResult.start_line`` with the **first** line of
the section body, i.e. one line *after* the header.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..models.schema import EditResult


def write_edit(file_path: str, result: EditResult, dry_run: bool = False) -> str:
    """Replace ``[start_line, end_line]`` in ``file_path`` with ``result.edited_lines``.

    Parameters
    ----------
    file_path:
        Absolute or relative path to the source ``.tex`` file.
    result:
        Edit outcome returned by the Groq client + agent pipeline.
    dry_run:
        When ``True``, returns the would-be file contents as a string and
        does **not** modify the file (no backup is written either).

    Returns
    -------
    The full new file contents as a single string (whether or not the
    file was written).
    """

    src = Path(file_path)
    if not src.is_file():
        raise FileNotFoundError(f"LaTeX file not found: {file_path}")

    original_lines = src.read_text(encoding="utf-8", errors="ignore").splitlines(
        keepends=True
    )

    start_idx = max(0, result.start_line - 1)
    end_idx = min(len(original_lines), result.end_line)

    if start_idx > end_idx:
        raise ValueError(
            f"Invalid edit range: start_line={result.start_line}, "
            f"end_line={result.end_line}"
        )

    new_block = _normalise_block(result.edited_lines)

    new_lines = (
        original_lines[:start_idx]
        + new_block
        + original_lines[end_idx:]
    )
    new_contents = "".join(new_lines)

    if dry_run:
        return new_contents

    backup_path = src.with_suffix(src.suffix + ".bak")
    shutil.copy2(src, backup_path)

    src.write_text(new_contents, encoding="utf-8")
    return new_contents


# ────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ────────────────────────────────────────────────────────────────────────────
def _normalise_block(lines: list[str]) -> list[str]:
    """Make sure every replacement line ends with ``\\n``.

    Groq commonly returns the edited body as a single multi-line string or
    a list without trailing newlines. We split on newlines and re-attach
    ``\n`` so the surrounding file structure is preserved exactly.
    """

    if not lines:
        return ["\n"]

    rebuilt: list[str] = []
    for raw in lines:
        parts = raw.splitlines() or [""]
        for part in parts:
            rebuilt.append(part + "\n")
    return rebuilt


def delete_lines(file_path: str, start_line: int, end_line: int, dry_run: bool = False) -> str:
    """Delete the inclusive 1-based line range ``[start_line, end_line]``.

    Backs up to ``*.bak`` (unless ``dry_run``). Also collapses a double-blank
    that may appear after the deletion so the file stays visually clean.
    """

    src = Path(file_path)
    if not src.is_file():
        raise FileNotFoundError(f"LaTeX file not found: {file_path}")

    original_lines = src.read_text(encoding="utf-8", errors="ignore").splitlines(
        keepends=True
    )

    start_idx = max(0, start_line - 1)
    end_idx = min(len(original_lines), end_line)
    if start_idx > end_idx:
        raise ValueError(
            f"Invalid delete range: start_line={start_line}, end_line={end_line}"
        )

    new_lines = original_lines[:start_idx] + original_lines[end_idx:]

    new_lines = _collapse_blank_run(new_lines, around_index=start_idx)
    new_contents = "".join(new_lines)

    if dry_run:
        return new_contents

    backup_path = src.with_suffix(src.suffix + ".bak")
    shutil.copy2(src, backup_path)
    src.write_text(new_contents, encoding="utf-8")
    return new_contents


def _collapse_blank_run(lines: list[str], *, around_index: int) -> list[str]:
    """If the join point has two adjacent blank lines, collapse them to one."""

    if 0 < around_index < len(lines):
        prev_is_blank = lines[around_index - 1].strip() == ""
        next_is_blank = lines[around_index].strip() == ""
        if prev_is_blank and next_is_blank:
            return lines[:around_index] + lines[around_index + 1 :]
    return lines


__all__ = ["write_edit", "delete_lines"]
