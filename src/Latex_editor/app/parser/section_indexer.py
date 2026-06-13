from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import hashlib
import re


SECTION_RE = re.compile(r"\\(section|subsection|subsubsection|paragraph|subparagraph)\s*\{")
BEGIN_RE = re.compile(r"\\begin\{([^\}]+)\}")
END_RE = re.compile(r"\\end\{([^\}]+)\}")
COMMENT_RE = re.compile(r"^\s*%")
SECTION_DEPTH = {
    "section": 1,
    "subsection": 2,
    "subsubsection": 3,
    "paragraph": 4,
    "subparagraph": 5,
}


@dataclass
class SectionNode:
    id: str
    title: str
    depth: int
    start_line: int
    end_line: int
    body_start_line: int
    body_end_line: int
    is_implicit: bool = False
    parent_id: Optional[str] = None
    children: list[str] = field(default_factory=list)


@dataclass
class ParsedDocument:
    lines: list[str]
    sections: list[SectionNode] = field(default_factory=list)


def make_stable_id(title: str, depth: int, first_body_line: str) -> str:
    raw = f"{title}::{depth}::{first_body_line.strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def count_meaningful_lines(lines: list[str]) -> int:
    return sum(1 for line in lines if line.strip() and not COMMENT_RE.match(line))


def parse_sections(lines: list[str]) -> ParsedDocument:
    doc = ParsedDocument(lines=lines)
    current = None

    for i, line in enumerate(lines, start=1):
        match = SECTION_RE.search(line)
        if match:
            if current is not None:
                current.end_line = i - 1
                current.body_end_line = i - 1
                doc.sections.append(current)

            cmd = match.group(1)
            depth = SECTION_DEPTH[cmd]
            title = line.split("{", 1)[1].rsplit("}", 1)[0].strip()
            current = SectionNode(
                id="",
                title=title,
                depth=depth,
                start_line=i,
                end_line=len(lines),
                body_start_line=i + 1,
                body_end_line=len(lines),
            )

    if current is not None:
        current.end_line = len(lines)
        current.body_end_line = len(lines)
        doc.sections.append(current)

    for sec in doc.sections:
        body_lines = lines[sec.body_start_line - 1 : sec.body_end_line]
        first_body_line = next((ln for ln in body_lines if ln.strip() and not COMMENT_RE.match(ln)), "")
        sec.id = make_stable_id(sec.title, sec.depth, first_body_line)

    return doc
