from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.parser.section_indexer import ParsedDocument, parse_sections


@dataclass
class ParsedView:
    tex_path: Path
    bib_path: Path | None
    lines: list[str]
    sections: list


class Parser:
    def parse(self, tex_path: str | Path, bib_path: str | None = None):
        tex_path = Path(tex_path)
        lines = tex_path.read_text(encoding="utf-8").splitlines(keepends=True)
        doc: ParsedDocument = parse_sections(lines)
        return ParsedView(
            tex_path=tex_path,
            bib_path=Path(bib_path) if bib_path else None,
            lines=doc.lines,
            sections=doc.sections,
        )
