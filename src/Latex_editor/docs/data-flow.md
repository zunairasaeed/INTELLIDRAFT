# Data flow — the canonical 12-step request lifecycle

This document is the source of truth for how a single edit request flows
through the LaTeX Editor backend. Every code path that mutates a `.tex`
file MUST follow these 12 steps, in order, with no shortcuts.

```
client ──HTTP──▶ api/routes ──▶ usecases ──▶ services / parser / agents / editor
                                        │
                                        └──▶ Supabase (sessions, messages, history)
                                        └──▶ workspace filesystem (.tex, .bib)
```

The orchestrator lives in `app/usecases/latex_edit_service.py`. Each step
below names the module that owns it.

---

## Step 1 — Load the session from Supabase

- **Owner:** `services/session_service.py`
- **Inputs:** `session_id` from the `X-Session-Id` header.
- **Action:** Fetch the session row from Supabase. Reject if the row is
  missing, expired, or not in `active` status.
- **Failure mode:** 401 — invalid or expired session.

## Step 2 — Load or create the workspace for that session

- **Owner:** `services/workspace_manager.py` + `usecases/workspace_service.py`
- **Action:** Look up the workspace bound to the session. If none exists,
  provision a fresh one by copying the chosen ACM template from
  `reference/acm/` into a session-scoped directory under `WORKSPACE_ROOT`.
- **Output:** A `Workspace` with `root_path`, `main_tex`, `bib_file`,
  `template`.
- **Invariant:** ACM reference files are read-only — we copy them in, we
  never write back.

## Step 3 — Acquire the workspace lock

- **Owner:** `services/workspace_manager.py`
- **Action:** Acquire an exclusive **per-workspace** lock (advisory file
  lock or in-process asyncio lock) and hold it for the remainder of the
  request. This serialises edits on the same workspace.
- **Failure mode:** 423 Locked / queue, depending on policy.
- **Invariant:** The lock MUST be released in step 12 even on error
  (use `try / finally`).

## Step 4 — Read the current `.tex` and `.bib`

- **Owner:** `services/workspace_manager.py`
- **Action:** Read `main.tex` (and the workspace's bib file, if any) from
  disk into memory as strings. Capture the original SHA-256 hash for the
  history record.
- **Invariant:** No mutation here; this is a pure read.

## Step 5 — Parse the document into zones, sections, and protected regions

- **Owner:** `parser/`
  - `parser/zone_detector.py` — abstract, acks, environment zones.
  - `parser/section_indexer.py` — `\section{}` / `\subsection{}` / ... tree.
  - `parser/protected_regions.py` — preamble, `\bibliography{}`,
    `\end{document}`, any other regions the editor must not touch.
  - `parser/bib_parser.py` — extract bib keys for the agent context.
- **Output:** A structural tree:
  `{sections: [...], zones: [...], protected: [...], bib_keys: [...]}`.
- **Invariant:** The parser is pure — input text → output dataclasses. No
  I/O, no global state.

## Step 6 — Route the request to a fixed intent

- **Owner:** `agents/router_agent.py` + `services/intent_router.py`
- **Action:** Map the user's natural-language instruction to **exactly one**
  intent from a fixed enum (e.g. `edit`, `generate`, `append`, plus future
  structural intents like `add_citation`, `rename_label`). Unknown
  instructions are rejected.
- **Output:** An `Intent` with `mode`, `target_section_id`, and any
  intent-specific parameters.
- **Invariant:** The router NEVER invents new intents. Free-form output
  from the LLM is mapped onto the enum or rejected.

## Step 7 — If it is a content edit, call the editor LLM on only the target body

- **Owner:** `agents/editor_agent.py` + `agents/latex_agent.py`
- **Action:** For a content intent, build a focused prompt containing only:
  the target section's body (header stripped), the paper title, available
  bib keys, and the user instruction. Call Groq. Receive a body string.
- **Invariant:** The agent receives the **section body**, not the whole
  document. It returns a body string only — never a full file.
- **Invariant:** Non-content intents (e.g. structural / metadata changes)
  may skip this step entirely and go straight to a deterministic patch.

## Step 8 — Validate the returned LaTeX

- **Owner:** `editor/validation.py`
- **Action:** Run structural checks on the new body and the proposed patch:
  - Patch span does not overlap any protected region.
  - New text does not introduce `\begin{document}` / `\end{document}`.
  - `\label{}`, `\cite{}`, `\ref{}` references still resolve (or are
    intentionally changed by the instruction).
  - Brace balance and environment `\begin/\end` balance are preserved.
  - Body is non-empty (for `edit` / `generate`) or non-redundant (for
    `append`).
- **Failure mode:** `PatchValidationError`. The request fails **before**
  any disk write.

## Step 9 — Apply the patch through the surgical writer

- **Owner:** `editor/patch_engine.py` + `editor/surgical_writer.py`
- **Action:** The patch engine builds a `Patch{line_start, line_end,
  new_text, mode, summary}`. The surgical writer replaces exactly those
  lines and writes the file back to disk atomically (write-temp → rename).
- **Invariant:** Only the target line range is touched. Everything else
  in the document is byte-for-byte identical to before.

## Step 10 — Reparse the updated file

- **Owner:** `parser/`
- **Action:** Re-read the freshly written file from disk and rebuild the
  full structural tree from scratch. The new tree is the response payload
  and the source of truth for any follow-up edits in the same session.
- **Invariant:** No in-memory shortcuts — always reparse from disk.
- **Failure mode:** If the reparse fails (truncated file, broken
  environment), restore from the original text captured in step 4 and
  surface a 500 with the diagnostic.

## Step 11 — Save message / history rows in Supabase

- **Owner:** `usecases/history_service.py`
- **Action:** Insert a row into the `edit_history` table with:
  `session_id, workspace_id, section_id, intent, instruction,
  before_hash, after_hash, diff_summary, created_at`. Also append the
  user message and assistant response to the `messages` table for the
  chat transcript.
- **Invariant:** History writes happen **after** the successful disk
  write, and **before** releasing the lock.

## Step 12 — Release the lock

- **Owner:** `services/workspace_manager.py`
- **Action:** Release the per-workspace lock acquired in step 3.
- **Invariant:** Wrap steps 4–11 in `try / finally` so the lock is always
  released, even on validation or LLM errors.

---

## Sequence diagram

```
client         api/routes        usecases               services/parser/agents/editor       supabase   workspace fs
  │ POST /edit ─▶                                                                              │           │
  │                ─▶ apply_edit                                                               │           │
  │                       │ (1) load session ──────────────────────────────────────────────▶  │           │
  │                       │ (2) load/create workspace ──────────────────────────────────────▶ │           │
  │                       │ (3) acquire lock ───────────────────────────────────────────────────────────▶ │
  │                       │ (4) read .tex / .bib ───────────────────────────────────────────────────────▶ │
  │                       │ (5) parse → tree                                                              │
  │                       │ (6) route intent                                                              │
  │                       │ (7) editor LLM on section body                                                │
  │                       │ (8) validate patch                                                            │
  │                       │ (9) surgical write ─────────────────────────────────────────────────────────▶ │
  │                       │ (10) reparse from disk ─────────────────────────────────────────────────────▶ │
  │                       │ (11) insert message + history ─────────────────────────────────▶ │           │
  │                       │ (12) release lock ──────────────────────────────────────────────────────────▶ │
  │                ◀── EditResponse                                                                       │
  │ ◀── 200 OK                                                                                            │
```

## Failure-mode summary

| Step | What can fail                             | What we do                                  |
| ---: | ----------------------------------------- | ------------------------------------------- |
|    1 | Missing / expired session                 | 401, no further steps                       |
|    2 | Template missing                          | 500, no lock taken                          |
|    3 | Lock contention                           | 423 or queue, no read                       |
|    4 | File missing / unreadable                 | 500, release lock                           |
|    5 | Malformed source                          | 422, release lock                           |
|    6 | Unknown intent                            | 400, release lock                           |
|    7 | LLM error / timeout                       | 502, release lock                           |
|    8 | Patch fails validation                    | 422, release lock, **no write**             |
|    9 | Disk write error                          | 500, release lock                           |
|   10 | Reparse fails                             | restore original, 500, release lock         |
|   11 | Supabase write fails                      | 500, log discrepancy, release lock          |
|   12 | —                                         | always runs in `finally`                    |
