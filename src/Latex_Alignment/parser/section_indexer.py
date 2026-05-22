"""Section indexer.

Builds the section index for the body zone of a LaTeX document, plus
"implicit" sections coming from named environments such as ``abstract``,
``acks``, ``appendix``, etc.

Implicit sections are injected into the main index via the local
``_implicit_sections_temp`` list and then merged in sorted order — exactly
as specified by the spec.
"""

from __future__ import annotations

import hashlib

from ..models.schema import Section, Zone
from ..utils.regex_patterns import (
    CITE_RE,
    COMMENT_LINE_RE,
    ENV_BEGIN,
    IMPLICIT_SECTION_ENVS,
    LABEL_RE,
    SECTION_DEPTH,
    extract_balanced_braces,
    parse_section_header,
)

# Implicit sections we *also* allow to appear inside the body zone. The
# abstract/acks/appendix entries are handled separately because they own
# their own zones (or border them).
_BODY_ONLY_IMPLICIT_ENVS: set[str] = {
    name
    for name in IMPLICIT_SECTION_ENVS
    if name not in {"abstract", "acks"}
}


def _make_stable_id(title: str, depth: int, first_body_line: str) -> str:
    """Content-derived 8-char hash that survives position shifts on reload.

    Replaces the legacy ``sec_{index}_{depth}`` scheme, where every insert /
    delete / move re-numbered every subsequent section. The hash uses
    ``title``, ``depth`` and the first non-blank, non-comment body line so two
    sections that look identical to the LLM also collide deterministically.
    """

    raw = f"{title}::{depth}::{first_body_line.strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────
def index_sections(lines: list[str], zones: list[Zone]) -> list[Section]:
    """Scan zones and return the merged, sorted list of sections.

    Lines are 1-based to match :class:`Zone` semantics.
    """

    body_zone = _find_zone(zones, "body")
    if body_zone is None:
        return []

    explicit_sections = _scan_explicit_sections(lines, body_zone)

    # ── Local temp list per spec — merged below into the main index. ────
    _implicit_sections_temp: list[Section] = []
    _implicit_sections_temp.extend(
        _scan_implicit_zone_sections(lines, zones)
    )
    _implicit_sections_temp.extend(
        _scan_implicit_body_environments(
            lines, body_zone, explicit_sections
        )
    )

    merged = sorted(
        explicit_sections + _implicit_sections_temp,
        key=lambda s: (s.start_line, -s.depth),
    )

    # ── FIX 2: build the parent/child tree on the flat list ────────────────
    _build_tree(merged)

    return merged


# ────────────────────────────────────────────────────────────────────────────
# Tree builder — populates parent_id + children on every node
# ────────────────────────────────────────────────────────────────────────────
def _build_tree(sections: list[Section]) -> dict[str, Section]:
    """Attach ``parent_id`` and ``children`` to every section in place.

    Rule (per the spec): a section is the child of the nearest preceding
    section with ``depth == self.depth - 1``. Implementation walks the flat
    (already source-ordered) list with an ancestor stack — same-depth or
    deeper neighbours are popped off before the new node is attached.

    Returns the ``{id: Section}`` lookup so the agent can adopt it as
    ``self.tree`` without a second pass.
    """

    for sec in sections:
        sec.parent_id = None
        sec.children = []

    stack: list[Section] = []
    for sec in sections:
        while stack and stack[-1].depth >= sec.depth:
            stack.pop()
        if stack:
            sec.parent_id = stack[-1].id
            stack[-1].children.append(sec.id)
        stack.append(sec)

    return {s.id: s for s in sections}


# ────────────────────────────────────────────────────────────────────────────
# Explicit \section / \subsection / ... discovery
# ────────────────────────────────────────────────────────────────────────────
def _scan_explicit_sections(lines: list[str], body_zone: Zone) -> list[Section]:
    """Walk the body zone and create one :class:`Section` per ``\\section{}``-style header.

    Uses the two-step parser from ``utils.regex_patterns`` so titles with
    nested braces (``\\section{The \\textsc{Foo} Bar}``) and titles that wrap
    across lines are captured correctly.
    """

    headers: list[tuple[int, str, str, int]] = []  # (line_no, cmd, title, depth)

    line_no = body_zone.start_line
    while line_no <= body_zone.end_line:
        line = _safe_line(lines, line_no)
        parsed = parse_section_header(line)
        if parsed is None:
            line_no += 1
            continue

        title = (parsed.get("title") or "").strip()
        if not parsed.get("balanced"):
            # Title's opening brace is on this line but the closing one is not.
            # Concatenate following body-zone lines until the brace closes.
            joined = line[parsed["open_brace_at"]:]
            scan = line_no
            while scan <= body_zone.end_line:
                scan += 1
                if scan > body_zone.end_line:
                    break
                joined += _safe_line(lines, scan)
                body = extract_balanced_braces(joined, 0)
                if body is not None:
                    title = body[0].strip()
                    break
        cmd = parsed["cmd"]
        depth = SECTION_DEPTH.get(cmd, 1)
        headers.append((line_no, cmd, title, depth))
        line_no += 1

    if not headers:
        return []

    sections: list[Section] = []
    for idx, (start, cmd, title, depth) in enumerate(headers):
        if idx + 1 < len(headers):
            end = headers[idx + 1][0] - 1
        else:
            end = body_zone.end_line

        section = _make_section(
            section_index=idx + 1,
            cmd=cmd,
            title=title,
            depth=depth,
            start_line=start,
            end_line=end,
            lines=lines,
            is_implicit=False,
        )
        sections.append(section)

    return sections


# ────────────────────────────────────────────────────────────────────────────
# Implicit sections — zones (abstract, acks)
# ────────────────────────────────────────────────────────────────────────────
def _scan_implicit_zone_sections(lines: list[str], zones: list[Zone]) -> list[Section]:
    """Create implicit sections for the abstract zone and the backmatter ``acks`` block."""

    results: list[Section] = []

    abstract_zone = _find_zone(zones, "abstract")
    if abstract_zone and abstract_zone.end_line >= abstract_zone.start_line:
        results.append(
            _make_section(
                section_index=len(results) + 1,
                cmd="abstract",
                title=IMPLICIT_SECTION_ENVS["abstract"],
                depth=1,
                start_line=abstract_zone.start_line,
                end_line=abstract_zone.end_line,
                lines=lines,
                is_implicit=True,
                id_prefix="impl_abstract",
            )
        )

    backmatter = _find_zone(zones, "backmatter")
    if backmatter:
        for line_no in range(backmatter.start_line, backmatter.end_line + 1):
            m = ENV_BEGIN.match(_safe_line(lines, line_no))
            if m and m.group("name") == "acks":
                end = _find_env_end(lines, "acks", line_no, backmatter.end_line)
                results.append(
                    _make_section(
                        section_index=len(results) + 1,
                        cmd="acks",
                        title=IMPLICIT_SECTION_ENVS["acks"],
                        depth=1,
                        start_line=line_no,
                        end_line=end,
                        lines=lines,
                        is_implicit=True,
                        id_prefix="impl_acks",
                    )
                )
                break

    return results


# ────────────────────────────────────────────────────────────────────────────
# Implicit sections — body environments outside any explicit section span
# ────────────────────────────────────────────────────────────────────────────
def _scan_implicit_body_environments(
    lines: list[str],
    body_zone: Zone,
    explicit_sections: list[Section],
) -> list[Section]:
    """Create implicit entries for body environments that live OUTSIDE explicit sections."""

    results: list[Section] = []
    explicit_ranges = [(s.start_line, s.end_line) for s in explicit_sections]

    line_no = body_zone.start_line
    while line_no <= body_zone.end_line:
        line = _safe_line(lines, line_no)
        m = ENV_BEGIN.match(line)
        if not m:
            line_no += 1
            continue

        env_name = m.group("name")
        if env_name not in _BODY_ONLY_IMPLICIT_ENVS:
            line_no += 1
            continue

        if _line_in_any_range(line_no, explicit_ranges):
            line_no += 1
            continue

        end = _find_env_end(lines, env_name, line_no, body_zone.end_line)
        results.append(
            _make_section(
                section_index=len(results) + 1,
                cmd=env_name,
                title=IMPLICIT_SECTION_ENVS[env_name],
                depth=2,
                start_line=line_no,
                end_line=end,
                lines=lines,
                is_implicit=True,
                id_prefix=f"impl_{env_name}",
            )
        )
        line_no = end + 1

    return results


# ────────────────────────────────────────────────────────────────────────────
# Section factory
# ────────────────────────────────────────────────────────────────────────────
def _make_section(
    *,
    section_index: int,
    cmd: str,
    title: str,
    depth: int,
    start_line: int,
    end_line: int,
    lines: list[str],
    is_implicit: bool,
    id_prefix: str | None = None,
) -> Section:
    raw_lines = _slice_lines(lines, start_line, end_line)
    content_hash = hashlib.md5("".join(raw_lines).encode("utf-8")).hexdigest()

    citations = _unique(_findall_keys(raw_lines, CITE_RE))
    labels = _unique(_findall_keys(raw_lines, LABEL_RE))

    body_after_header = raw_lines[1:] if raw_lines and not is_implicit else raw_lines
    is_empty = _count_meaningful_lines(body_after_header) < 3

    # ── FIX 1: stable, content-derived ID ──────────────────────────────────
    # We always skip ``raw_lines[0]`` here regardless of explicit/implicit:
    # for explicit sections it's the ``\section{...}`` header; for implicit
    # sections it's the ``\begin{env}`` line. The first non-blank /
    # non-comment line *after* that is what feeds the hash.
    first_body_line = ""
    for line in raw_lines[1:]:
        stripped = line.strip()
        if not stripped or COMMENT_LINE_RE.match(line):
            continue
        first_body_line = stripped
        break

    sid = _make_stable_id(title, depth, first_body_line)

    display_title = title or f"(untitled {cmd})"

    return Section(
        id=sid,
        title=display_title,
        cmd=cmd,
        depth=depth,
        start_line=start_line,
        end_line=end_line,
        content_hash=content_hash,
        citations=citations,
        labels=labels,
        is_empty=is_empty,
        is_implicit=is_implicit,
        raw_lines=raw_lines,
    )


# ────────────────────────────────────────────────────────────────────────────
# Small helpers
# ────────────────────────────────────────────────────────────────────────────
def _find_zone(zones: list[Zone], name: str) -> Zone | None:
    for z in zones:
        if z.name == name:
            return z
    return None


def _safe_line(lines: list[str], line_no: int) -> str:
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def _slice_lines(lines: list[str], start: int, end: int) -> list[str]:
    if start < 1 or end < start:
        return []
    start_idx = start - 1
    end_idx = min(end, len(lines))
    return list(lines[start_idx:end_idx])


def _findall_keys(raw_lines: list[str], pattern) -> list[str]:
    keys: list[str] = []
    for line in raw_lines:
        for match in pattern.finditer(line):
            keys.extend(k.strip() for k in match.group(1).split(",") if k.strip())
    return keys


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _count_meaningful_lines(raw_lines: list[str]) -> int:
    count = 0
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if COMMENT_LINE_RE.match(line):
            continue
        count += 1
    return count


def _find_env_end(
    lines: list[str], env_name: str, start_line: int, hard_stop: int
) -> int:
    """Return the line number of the matching ``\\end{env_name}``.

    Handles nested environments of the same name. Falls back to ``hard_stop``
    if the closing tag is missing.
    """

    from ..utils.regex_patterns import ENV_END  # local import to keep module surface clean

    depth = 0
    for line_no in range(start_line, hard_stop + 1):
        line = _safe_line(lines, line_no)
        mb = ENV_BEGIN.match(line)
        if mb and mb.group("name") == env_name:
            depth += 1
            continue
        me = ENV_END.match(line)
        if me and me.group("name") == env_name:
            depth -= 1
            if depth == 0:
                return line_no
    return hard_stop


def _line_in_any_range(line_no: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= line_no <= end for start, end in ranges)


__all__ = ["index_sections", "_build_tree", "_make_stable_id"]
