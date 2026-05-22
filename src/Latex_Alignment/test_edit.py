"""End-to-end test for the LaTeX Editor Agent including a real Groq call.

What it does:
  1. Loads .env from the repo root so GROQ_API_KEY is available.
  2. Parses ``sample-sigconf.tex`` next to this file.
  3. Picks an EMPTY section (generation mode) and runs a preview (dry-run).
  4. Picks a non-empty section (edit mode) and runs a preview (dry-run).
  5. If ``--apply`` is passed, actually rewrites the .tex file (creates .tex.bak).

Run from the repo root::

    python -m src.Latex_Alignment.test_edit           # preview only, safe
    python -m src.Latex_Alignment.test_edit --apply   # writes paper.tex.bak + paper.tex
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv(_PROJECT_ROOT / ".env")

from src.Latex_Alignment.agent import LatexEditorAgent  # noqa: E402
from src.Latex_Alignment.editor.groq_client import (    # noqa: E402
    build_groq_payload,
    call_groq_edit,
)

SAMPLE_NAME = "sample-sigconf.tex"


def _hr(title: str) -> None:
    print()
    print("=" * 72)
    print(f" {title}")
    print("=" * 72)


def _print_section_block(label: str, lines: list[str]) -> None:
    print(f"\n--- {label} ---")
    if not lines:
        print("(empty)")
    else:
        for line in lines:
            print(line.rstrip("\n"))
    print("--- end ---")


def _pick_section(agent: LatexEditorAgent, *, want_empty: bool):
    for s in agent.list_sections():
        if s.is_implicit:
            continue
        if s.is_empty is want_empty:
            return s
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the edits back to the .tex file (creates .tex.bak).",
    )
    args = parser.parse_args()

    sample_path = _THIS_DIR / SAMPLE_NAME
    if not sample_path.is_file():
        print(f"[test_edit] Missing {sample_path} - run test_parse.py first.")
        return 1

    _hr("Load")
    agent = LatexEditorAgent(str(sample_path))
    doc = agent.load()
    print(f"  file        : {doc.file_path}")
    print(f"  doc_class   : {doc.doc_class}")
    print(f"  doc_style   : {doc.doc_style}")
    print(f"  sections    : {len(doc.sections)} total")
    print(f"  empty count : {sum(1 for s in doc.sections if s.is_empty)}")
    print(f"  bib_keys    : {len(doc.bib_keys)}")

    empty_section    = _pick_section(agent, want_empty=True)
    nonempty_section = _pick_section(agent, want_empty=False)

    if empty_section is None:
        print("[test_edit] No empty section found in sample; skipping generate test.")
    if nonempty_section is None:
        print("[test_edit] No non-empty section found in sample; skipping edit test.")

    # ── 1. GENERATE MODE (empty section) ────────────────────────────────
    if empty_section is not None:
        _hr(f"GENERATE  --  section '{empty_section.title}' ({empty_section.id})")
        instruction = (
            "Write a concise 4-5 sentence section explaining the methodology "
            "behind a LaTeX-section-level editor that uses zone/section parsing "
            "and Groq for instruction-driven rewrites. Cite Knuth1984Literate."
        )
        payload = build_groq_payload(
            empty_section, instruction, doc.bib_keys, doc.metadata
        )
        print(f"  mode        : {payload['mode']}")
        print(f"  instruction : {instruction}")

        print("\n[test_edit] Calling Groq (generate mode)...")
        edited = call_groq_edit(
            section=empty_section,
            instruction=instruction,
            bib_keys=doc.bib_keys,
            metadata=doc.metadata,
        )
        _print_section_block("Groq output (generate)", edited.splitlines())

        if args.apply:
            print("\n[test_edit] Applying generate edit to disk...")
            result = agent.edit(empty_section.id, instruction)
            print(
                f"  wrote lines {result.start_line}-{result.end_line} "
                f"(was_empty={result.was_empty})"
            )

    # ── 2. EDIT MODE (non-empty section) ────────────────────────────────
    if nonempty_section is not None:
        # Reload because a previous --apply call would have shifted line numbers.
        if args.apply:
            agent.reload()
            nonempty_section = _pick_section(agent, want_empty=False) or nonempty_section

        _hr(
            f"EDIT      --  section '{nonempty_section.title}' "
            f"({nonempty_section.id})"
        )
        _print_section_block("Original lines", nonempty_section.raw_lines)

        instruction = "Make this section noticeably more formal and academic in tone, but keep it under 5 sentences and preserve any citations or labels."
        payload = build_groq_payload(
            nonempty_section, instruction, doc.bib_keys, doc.metadata
        )
        print(f"  mode        : {payload['mode']}")
        print(f"  instruction : {instruction}")

        print("\n[test_edit] Calling Groq (edit mode)...")
        edited = call_groq_edit(
            section=nonempty_section,
            instruction=instruction,
            bib_keys=doc.bib_keys,
            metadata=doc.metadata,
        )
        _print_section_block("Groq output (edit)", edited.splitlines())

        if args.apply:
            print("\n[test_edit] Applying edit to disk...")
            result = agent.edit(nonempty_section.id, instruction)
            print(
                f"  wrote lines {result.start_line}-{result.end_line} "
                f"(was_empty={result.was_empty})"
            )

    _hr("DONE")
    if not args.apply:
        print("Preview-only run. Re-run with --apply to actually modify the file.")
    else:
        print("File written. Backup at:")
        print(f"  {sample_path}.bak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
