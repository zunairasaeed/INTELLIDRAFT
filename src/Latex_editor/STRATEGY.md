# LaTeX Editor — Project Strategy

This document explains **why and how** the LaTeX Editor was built: the design strategy, request flow, database model, and what the project delivers. It is not a code walkthrough.

---

## What this project is

A **standalone backend service** for agent-assisted editing of ACM-style LaTeX papers. A user works inside a **session**; each session owns one working copy of a paper on disk. The user sends **natural-language instructions**; the system interprets intent, asks an LLM for **section body text only**, validates it, and applies a **small surgical patch** to the `.tex` file.

The LLM never writes files directly. Deterministic code owns parsing, validation, and saving.

This service was designed to plug into the wider **IntelliDraft** product (session history, user accounts, future frontend) while staying runnable on its own for development and testing.

---

## Core strategy

| Principle | Meaning |
|-----------|---------|
| **Surgical edits, not full rewrites** | Only the body lines of a target section change. Headers, labels, citations, figures, preamble, and bibliography stay protected. |
| **Clean layers** | HTTP → use case → parser / agents / editor / workspace. Each layer has one job and clear rules about what it may touch. |
| **LLM for language, code for truth** | Groq (or a stub in dev) produces plain text and intent. Parsing, patch ranges, validation, and disk writes are always deterministic. |
| **Session-scoped workspaces** | Every chat session maps to one workspace folder with `main.tex` (and optional `.bib`). Edits are serialized with a per-workspace lock. |
| **Audit trail** | Every successful edit is recorded with intent and summary so history, undo, and analytics are possible later. |
| **Pluggable persistence** | Local development uses in-memory database + disk workspaces. Production is intended to use **Supabase Postgres** for metadata; document bytes stay on the filesystem (not object storage yet). |

---

## Architecture (conceptual layers)

```
Client (frontend or API caller)
        │
        ▼
   HTTP API          ← thin: validate input, return JSON
        │
        ▼
   Use case           ← orchestrates one full edit turn
        │
   ┌────┴────┬──────────┬────────────┐
   ▼         ▼          ▼            ▼
 Parser    Agents     Editor     Workspace
 (read)    (LLM)      (patch)    (disk + lock)
        │
        ▼
   Database           ← sessions, workspace metadata, edit history
```

**Layer rules (invariants):**

- The API does not call the editor or LLM directly.
- Agents never touch the filesystem.
- The editor never calls an LLM.
- The parser is pure: text in, structure out.
- Only the use case composes all steps into one request.

---

## End-to-end flow

### A. Start or resume a session

1. Client sends session id, user id, and optional title.
2. Service creates or loads a **chat session** record.
3. A **workspace** is created on disk if needed (starter `main.tex` for a new session).
4. Session is linked to that workspace in the database.

### B. One edit message (main loop)

When the user sends a natural-language message:

1. **Lock** the workspace so two edits cannot run at once.
2. **Parse** the current `.tex` (and `.bib` if present) into a section tree with stable section ids and body line ranges.
3. **Summarize** structure for the LLM (section titles, ids, sizes — not the whole file).
4. **Route** the message to a fixed intent (e.g. edit, add, replace, list sections, summarize, or unknown).
5. **Editor agent** (if needed) returns new **body text** for the target section — not LaTeX structure commands.
6. **Validate** braces, environments, required cites/labels; build a line-range patch.
7. **Write** the patch surgically to disk (with backup).
8. **Save** intent + summary to **edit history**.
9. **Reparse** from disk so the next turn sees ground truth.
10. **Release** lock and return ok, intent, revision, and summary.

Without a Groq API key, a stub LLM is used so the service still starts; edits that need real language understanding will not succeed until a key is configured.

### Canonical vs shipped flow

The design doc describes a **12-step** lifecycle (Supabase session status, ACM template copy, content hashes, message table, undo). The **running service** implements the **core 8-step loop** above. Extra safety and persistence features are planned but not all wired yet.

---

## Database schema (Supabase / Postgres)

Three tables. Metadata lives in the database; `.tex` / `.bib` content lives on disk under a configurable workspace root.

| Table | Purpose |
|-------|---------|
| **`chat_sessions`** | One row per editing session: user, title, feature tag (`latex_editor`), link to workspace, timestamps. |
| **`workspaces`** | One row per on-disk workspace: paths to tex/bib, document class/mode, revision counter, lock version, tied to a session. |
| **`edit_history`** | Audit log per edit: session, workspace, user, classified **intent**, optional **summary**, timestamp. |

**Relationships:** A session may point to a workspace; a workspace always belongs to a session. Edit history references both. Deleting a session cascades to its history; workspace linkage is managed explicitly.

**Not in schema yet (planned):** a `messages` table for full chat transcripts; before/after content hashes on history rows for deterministic undo.

**Runtime today:** Default dependency injection uses an **in-memory** implementation of the same shape so local dev works without Supabase. The Supabase client and SQL schema exist; switching production to Postgres is a configuration step, not a redesign.

---

## API surface (what callers use today)

| Endpoint | Role |
|----------|------|
| Health check | Service is up. |
| Ensure session | Create or resume session + workspace. |
| LaTeX message | Run one full edit turn (the main pipeline). |

There is **no file-upload endpoint** in this service yet: the workspace is bootstrapped from a starter template on disk. Upload-and-parse flows live in the separate **Latex_Alignment** integration used by the IntelliDraft frontend today.

---

## What was achieved

**Delivered:**

- FastAPI service with health, session ensure, and message-driven editing.
- Session-scoped workspaces on disk with revision tracking and exclusive locks.
- Section-aware parser with stable ids and body line ranges for precise patches.
- Intent routing + editor agent via Groq (JSON mode), with dev stub fallback.
- Validate → surgical write → backup → reparse loop.
- Edit history recording (in-memory or Supabase-ready client).
- Layered automated tests across parser, editor, agents, workspace, and API.
- Architecture and data-flow documentation for future contributors.
- ACM reference assets and config hooks for template-based workspace bootstrap.

**Strategic goals partially done:**

- Full Supabase as default persistence (schema + client exist; runtime still in-memory by default).
- ACM template copy on every new workspace (documented; starter skeleton used today).
- Protected-region and zone-aware validation on every path (modules exist; not all on the hot path).
- Richer API: parse-only, history list, undo, session delete.
- Chat message persistence in the database.

---

## How this relates to IntelliDraft

| Piece | Role |
|-------|------|
| **Latex_editor** (this project) | Standalone, session-first LaTeX backend with clean architecture and Supabase-oriented persistence. Built for long-term product integration. |
| **Latex_Alignment** (elsewhere in the repo) | Drop-in engine currently wired to IntelliDraft’s frontend via `/pipelines/latex-alignment/*` — upload, sidebar sections, chat, export, reset. |

Both share the same product idea (agentic ACM LaTeX editing) but different integration shapes. This folder is the **structured backend experiment / future home**; Latex_Alignment is what the live frontend uses today.

---

## One-line summary

**Natural language in → intent + section body out → validate → patch only what changed → save history → reparse — with sessions, workspaces, and Postgres-ready metadata, while keeping the LLM away from the filesystem.**
