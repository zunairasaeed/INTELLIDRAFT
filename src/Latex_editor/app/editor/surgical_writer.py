from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass
class Patch:
    start_line: int
    end_line: int
    new_text: str


def write_patch(file_path: str | Path, patch: Patch) -> None:
    path = Path(file_path)
    original = path.read_text(encoding="utf-8").splitlines(keepends=True)

    start = max(patch.start_line - 1, 0)
    end = min(patch.end_line, len(original))
    replacement = patch.new_text
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    new_lines = replacement.splitlines(keepends=True)

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)

    updated = original[:start] + new_lines + original[end:]
    path.write_text("".join(updated), encoding="utf-8")
