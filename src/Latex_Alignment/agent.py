"""Top-level orchestrator for the LaTeX Editor Agent.

Typical use::

    from src.Latex_Alignment import LatexEditorAgent

    agent = LatexEditorAgent("paper.tex", bib_path="refs.bib")
    doc = agent.load()
    for s in agent.list_sections():
        print(s.id, s.title, "(empty)" if s.is_empty else "")

    # Preview without writing:
    preview_text = agent.preview("sec_2_1", "Make this more formal.")

    # Apply the edit (writes paper.tex, creates paper.tex.bak):
    result = agent.edit("sec_2_1", "Make this more formal.")
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Iterable

from .editor.groq_client import call_groq_edit
from .editor.surgical_writer import delete_lines, write_edit
from .models.schema import (
    EditRequest,
    EditResult,
    ParsedDocument,
    Section,
)
from .parser.bib_parser import parse_bib_file
from .parser.section_indexer import _make_stable_id, index_sections
from .parser.zone_detector import detect_zones


class LatexEditorAgent:
    """Parses a LaTeX paper and performs surgical, Groq-driven edits on sections."""

    # FIX 3: depth → LaTeX command for header generation in structural edits.
    _DEPTH_TO_CMD: dict[int, str] = {
        1: "section",
        2: "subsection",
        3: "subsubsection",
        4: "paragraph",
        5: "subparagraph",
    }

    def __init__(self, tex_path: str, bib_path: str | None = None) -> None:
        self.tex_path = str(Path(tex_path).resolve())
        self.bib_path = str(Path(bib_path).resolve()) if bib_path else None

        self._document: ParsedDocument | None = None
        self._lines: list[str] = []
        # FIX 2: id → Section dict, populated on every (re)load.
        self.tree: dict[str, Section] = {}

    # ────────────────────────────────────────────────────────────────────
    # Loading / parsing
    # ────────────────────────────────────────────────────────────────────
    def load(self) -> ParsedDocument:
        """Parse the ``.tex`` file into zones + sections and cache the result."""

        path = Path(self.tex_path)
        if not path.is_file():
            raise FileNotFoundError(f"LaTeX file not found: {self.tex_path}")

        self._lines = path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines(keepends=True)

        document = detect_zones(self.tex_path, self._lines)
        document.sections = index_sections(self._lines, document.zones)
        document.bib_keys = parse_bib_file(self.bib_path)

        self._document = document
        # FIX 2: refresh the id → Section lookup so all the structural tools
        # (insert / rename / move / delete) can resolve targets in O(1).
        self.tree = {s.id: s for s in document.sections}
        return document

    def reload(self) -> ParsedDocument:
        """Force a fresh parse from disk (useful after external file changes)."""

        self._document = None
        return self.load()

    # FIX 3: alias matching the reference spec's vocabulary.
    def _reindex(self) -> ParsedDocument:
        """Re-read the .tex from disk and rebuild zones / sections / tree."""

        return self.reload()

    # ────────────────────────────────────────────────────────────────────
    # Inspection
    # ────────────────────────────────────────────────────────────────────
    def list_sections(self) -> list[Section]:
        return list(self._ensure_loaded().sections)

    def get_section(self, section_id: str) -> Section:
        for s in self._ensure_loaded().sections:
            if s.id == section_id:
                return s
        raise KeyError(f"Section not found: {section_id}")

    # ────────────────────────────────────────────────────────────────────
    # Editing
    # ────────────────────────────────────────────────────────────────────
    def edit(self, section_id: str, instruction: str) -> EditResult:
        """Run a Groq-driven edit and write the result back to disk."""

        return self._run_edit(section_id, instruction, dry_run=False)

    def preview(self, section_id: str, instruction: str) -> str:
        """Same as :meth:`edit` but does not write — returns the would-be file body."""

        result = self._run_edit(section_id, instruction, dry_run=True)
        return write_edit(self.tex_path, result, dry_run=True)

    def edit_with_request(self, request: EditRequest) -> EditResult:
        """Convenience wrapper that accepts an :class:`EditRequest` object."""

        return self.edit(request.section_id, request.instruction)

    # ────────────────────────────────────────────────────────────────────
    # Agentic operations (used by the intent router / executor)
    # ────────────────────────────────────────────────────────────────────
    def append_content(
        self,
        section_id: str,
        instruction: str | None = None,
        user_content: str | None = None,
    ) -> EditResult:
        """Append new content to a section's body.

        If ``user_content`` is provided, it is appended verbatim. Otherwise
        Groq is called in *append* mode with ``instruction``.
        """

        if not instruction and not user_content:
            raise ValueError("append_content requires instruction or user_content")

        document = self._ensure_loaded()
        section = self.get_section(section_id)
        body_start, body_end = self._body_range(section, self._lines)
        original_body = self._lines[body_start - 1 : body_end]

        if user_content is None:
            new_text = call_groq_edit(
                section=section,
                instruction=instruction or "",
                bib_keys=document.bib_keys,
                metadata=document.metadata,
                mode="append",
            )
        else:
            new_text = user_content

        appended_lines = self._split_edited_text(new_text)
        combined = list(original_body)
        if combined and not combined[-1].endswith("\n"):
            combined[-1] = combined[-1] + "\n"
        if combined:
            combined.append("\n")
        combined.extend(appended_lines)

        result = EditResult(
            section_id=section.id,
            original_lines=original_body,
            edited_lines=combined,
            start_line=body_start,
            end_line=body_end,
            was_empty=section.is_empty,
        )
        write_edit(self.tex_path, result, dry_run=False)
        self.reload()
        return result

    def replace_content(self, section_id: str, user_content: str) -> EditResult:
        """Replace a section's body with the literal ``user_content`` provided."""

        section = self.get_section(section_id)
        body_start, body_end = self._body_range(section, self._lines)
        original_body = self._lines[body_start - 1 : body_end]

        edited_lines = self._split_edited_text(user_content)

        result = EditResult(
            section_id=section.id,
            original_lines=original_body,
            edited_lines=edited_lines,
            start_line=body_start,
            end_line=body_end,
            was_empty=section.is_empty,
        )
        write_edit(self.tex_path, result, dry_run=False)
        self.reload()
        return result

    def delete_section(
        self, section_id: str, cascade: bool = True
    ) -> EditResult:
        """Remove a section's header + body.

        When ``cascade`` is ``True`` (the default), every descendant in the
        parent/child tree is removed as well, so deleting ``Background`` also
        removes ``\\subsection{Editors}`` underneath it instead of leaving an
        orphaned subsection floating in the file.

        The returned :class:`EditResult` reports the combined span across
        every line that was actually removed.
        """

        self._ensure_loaded()
        section = self.get_section(section_id)

        ids_to_delete: list[str] = [section_id]
        if cascade:
            ids_to_delete.extend(self._collect_descendants(section_id))

        targets: list[Section] = []
        seen: set[str] = set()
        for sid in ids_to_delete:
            if sid in seen:
                continue
            seen.add(sid)
            try:
                targets.append(self.get_section(sid))
            except KeyError:
                continue
        if not targets:
            raise KeyError(f"Section not found: {section_id}")

        # Snapshot the lines that will disappear (in source order, low → high)
        # so the EditResult preview matches what the user saw on screen.
        original_lines: list[str] = []
        for s in sorted(targets, key=lambda x: x.start_line):
            original_lines.extend(self._lines[s.start_line - 1 : s.end_line])

        span_start = min(s.start_line for s in targets)
        span_end = max(s.end_line for s in targets)

        # Apply every deletion to one in-memory copy, descending by start_line
        # so earlier deletions never invalidate later ones.
        working = list(self._lines)
        for s in sorted(targets, key=lambda x: x.start_line, reverse=True):
            del working[s.start_line - 1 : s.end_line]

        self._write_and_reindex(working)

        return EditResult(
            section_id=section.id,
            original_lines=original_lines,
            edited_lines=[],
            start_line=span_start,
            end_line=span_end,
            was_empty=section.is_empty,
        )

    # ────────────────────────────────────────────────────────────────────
    # FIX 3: structural-edit tools
    # ────────────────────────────────────────────────────────────────────
    def insert_section(
        self,
        title: str,
        depth: int,
        after_id: str,
        body: str = "",
    ) -> Section:
        """Insert a new ``\\section`` / ``\\subsection`` / ``\\subsubsection``
        block immediately after the section ``after_id``.

        Position rule: the new block is spliced in at ``anchor.end_line``,
        i.e. just after the *entire* range of the anchor section (which for
        a parent ``\\section`` includes any subsections that already live
        below it). No regex is used to locate the boundary — only the
        ``start_line`` / ``end_line`` already on the anchor node.

        Returns the freshly-indexed :class:`Section` after the file is
        reloaded. Because section IDs are content-derived (FIX 1) the new
        section's id is also deterministic and stable across future reloads.
        """

        self._ensure_loaded()
        anchor = self.get_section(after_id)

        cmd = self._DEPTH_TO_CMD.get(depth, "section")
        # ``self._lines`` keeps one line per element (each ending in ``\n``);
        # the inserted block preserves that invariant.
        new_block: list[str] = ["\n", f"\\{cmd}{{{title}}}\n"]
        if body:
            for body_line in body.splitlines() or [""]:
                new_block.append(body_line + "\n")
        else:
            new_block.append("\n")

        insert_idx = anchor.end_line  # 0-based slot AFTER anchor's last line
        working = list(self._lines)
        working[insert_idx:insert_idx] = new_block

        self._write_and_reindex(working)

        # Prefer the deterministic prediction; fall back to title+depth match
        # in case the indexer trimmed/normalised the body line differently.
        first_body_line = ""
        for body_line in body.splitlines() if body else []:
            stripped = body_line.strip()
            if not stripped or stripped.startswith("%"):
                continue
            first_body_line = stripped
            break
        predicted_id = _make_stable_id(title, depth, first_body_line)
        if predicted_id in self.tree:
            return self.tree[predicted_id]

        candidates = [
            s
            for s in self.list_sections()
            if not s.is_implicit and s.title == title and s.depth == depth
        ]
        if not candidates:
            raise RuntimeError(
                f"Inserted section '{title}' (depth={depth}) was not found after "
                "reload — the file may have an unbalanced \\begin/\\end."
            )
        # Closest to where we asked for the insert.
        return min(
            candidates,
            key=lambda s: abs(s.start_line - (insert_idx + 1)),
        )

    def rename_section(self, section_id: str, new_title: str) -> Section:
        """Replace a section's header in place; depth + position unchanged.

        Implicit sections (``\\begin{abstract}`` / ``\\begin{acks}`` / floating
        ``\\begin{figure}`` blocks, …) have no ``\\section`` header to rewrite
        and raise :class:`ValueError` instead of silently doing nothing.
        """

        self._ensure_loaded()
        section = self.get_section(section_id)
        if section.is_implicit:
            raise ValueError(
                f"Cannot rename implicit section '{section.title}' — it has no "
                "\\section header (it is a \\begin{...} environment)."
            )

        cmd = self._DEPTH_TO_CMD.get(section.depth, "section")
        working = list(self._lines)
        working[section.start_line - 1] = f"\\{cmd}{{{new_title}}}\n"

        self._write_and_reindex(working)

        # The title changed → the stable hash changed. Predict it.
        first_body_line = ""
        for line in section.raw_lines[1:]:
            stripped = line.strip()
            if not stripped or stripped.startswith("%"):
                continue
            first_body_line = stripped
            break
        predicted_id = _make_stable_id(new_title, section.depth, first_body_line)
        if predicted_id in self.tree:
            return self.tree[predicted_id]

        for s in self.list_sections():
            if (
                not s.is_implicit
                and s.title == new_title
                and s.depth == section.depth
                and s.start_line == section.start_line
            ):
                return s
        raise RuntimeError(
            f"Renamed section '{new_title}' not found after reload."
        )

    def move_section(self, section_id: str, after_id: str) -> Section:
        """Cut the block of ``section_id`` and paste it after ``after_id``.

        Raises :class:`ValueError` if ``after_id`` lives inside the moved
        section's own range (which would create a cycle and corrupt the file).
        Uses only the ``start_line`` / ``end_line`` already on the nodes — no
        regex scan of file contents.
        """

        self._ensure_loaded()
        section = self.get_section(section_id)
        anchor = self.get_section(after_id)

        if section.id == anchor.id:
            raise ValueError("Cannot move a section relative to itself.")
        if section.start_line <= anchor.start_line <= section.end_line:
            raise ValueError(
                "Cannot move a section inside its own range "
                f"({section.start_line}-{section.end_line})."
            )

        working = list(self._lines)
        block_start = section.start_line - 1  # 0-based inclusive
        block_end = section.end_line  # 0-based exclusive
        block = working[block_start:block_end]
        del working[block_start:block_end]

        block_size = block_end - block_start
        insert_idx = anchor.end_line  # 0-based slot after anchor's last line
        if anchor.start_line > section.start_line:
            # Deletion happened earlier in the file — shift the anchor slot up.
            insert_idx -= block_size

        working[insert_idx:insert_idx] = block

        self._write_and_reindex(working)

        # Title/depth/first body line are unchanged → id is preserved.
        if section.id in self.tree:
            return self.tree[section.id]
        raise RuntimeError(
            f"Moved section '{section.title}' not found after reload."
        )

    # ────────────────────────────────────────────────────────────────────
    # FIX 3: helpers shared by the structural-edit tools
    # ────────────────────────────────────────────────────────────────────
    def _collect_descendants(self, section_id: str) -> list[str]:
        """Return every descendant id under ``section_id`` (depth-first)."""

        out: list[str] = []
        node = self.tree.get(section_id)
        if node is None:
            return out
        for child_id in node.children:
            out.append(child_id)
            out.extend(self._collect_descendants(child_id))
        return out

    def _write_and_reindex(self, new_lines: list[str]) -> None:
        """Back up to ``*.bak``, write ``new_lines`` to disk, then reload+rebuild.

        Centralises the "always reindex after a write" rule from FIX 3 so the
        four structural tools never disagree about how disk state syncs back
        into ``self._lines`` / ``self.tree``.
        """

        src = Path(self.tex_path)
        if src.is_file():
            shutil.copy2(src, src.with_suffix(src.suffix + ".bak"))
        src.write_text("".join(new_lines), encoding="utf-8")
        self._reindex()

    # ────────────────────────────────────────────────────────────────────
    # Internals
    # ────────────────────────────────────────────────────────────────────
    def _run_edit(
        self, section_id: str, instruction: str, *, dry_run: bool
    ) -> EditResult:
        document = self._ensure_loaded()
        section = self.get_section(section_id)

        body_start, body_end = self._body_range(section, self._lines)
        original_body = self._lines[body_start - 1 : body_end]

        edited_text = call_groq_edit(
            section=section,
            instruction=instruction,
            bib_keys=document.bib_keys,
            metadata=document.metadata,
        )
        edited_lines = self._split_edited_text(edited_text)

        result = EditResult(
            section_id=section.id,
            original_lines=original_body,
            edited_lines=edited_lines,
            start_line=body_start,
            end_line=body_end,
            was_empty=section.is_empty,
        )

        if not dry_run:
            write_edit(self.tex_path, result, dry_run=False)
            self.reload()

        return result

    def _ensure_loaded(self) -> ParsedDocument:
        if self._document is None:
            self.load()
        assert self._document is not None
        return self._document

    @staticmethod
    def _body_range(section: Section, lines: list[str]) -> tuple[int, int]:
        """Return ``(body_start_line, body_end_line)`` — the lines safe to overwrite.

        Explicit sections (``\\section{Title}``) expose their header on the
        first line, so the editable body starts one line later.

        Implicit sections (``\\begin{abstract}…\\end{abstract}``, ``acks``,
        ``appendix``, body figures/tables, …) MUST keep their ``\\begin``
        and ``\\end`` lines on disk — otherwise the next parse can't locate
        the env, the implicit section silently disappears from the index,
        and the section count drops by one. We detect that wrapper here and
        narrow the editable range to the lines *between* the markers.

        Trailing blank lines inside the editable range are trimmed so the
        visual separator between sections is preserved across rewrites.
        """

        if section.is_implicit:
            first_line_no = section.start_line
            first = lines[first_line_no - 1] if 1 <= first_line_no <= len(lines) else ""
            has_begin = first.lstrip().startswith("\\begin{")

            # The implicit's last line is often a trailing blank from the zone
            # bounds — scan backward past blanks/comments to find the real
            # ``\end{...}`` so we preserve it across edits.
            end_marker_line = None
            scan = section.end_line
            while scan >= section.start_line:
                line = lines[scan - 1] if 1 <= scan <= len(lines) else ""
                stripped = line.lstrip()
                if stripped.startswith("\\end{"):
                    end_marker_line = scan
                    break
                if stripped == "" or stripped.startswith("%"):
                    scan -= 1
                    continue
                break

            if (
                has_begin
                and end_marker_line is not None
                and end_marker_line > section.start_line
            ):
                body_start = section.start_line + 1
                body_end = end_marker_line - 1
            else:
                return section.start_line, section.end_line
        else:
            body_start = section.start_line + 1
            body_end = max(body_start - 1, section.end_line)

        while body_end >= body_start:
            line = lines[body_end - 1] if 1 <= body_end <= len(lines) else ""
            if line.strip() == "":
                body_end -= 1
            else:
                break

        if body_end < body_start:
            body_end = body_start - 1

        return body_start, body_end

    @staticmethod
    def _split_edited_text(text: str) -> list[str]:
        if not text:
            return ["\n"]
        if not text.endswith("\n"):
            text = text + "\n"
        return [line + "\n" for line in text.splitlines()]


def list_section_ids(sections: Iterable[Section]) -> list[str]:
    """Tiny helper used by tests / external tooling."""

    return [s.id for s in sections]


__all__ = ["LatexEditorAgent", "list_section_ids"]
