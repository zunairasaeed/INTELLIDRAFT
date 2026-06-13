# Cursor instructions

These are the working agreements every Cursor-assisted change in this
project should follow. The short version lives in `.cursorrules` at the repo
root; this is the long-form reference.

## When adding a feature

1. **Start at the use case.** Most features land as a new method on a
   `*_service.py` under `app/usecases/`. The API router is a thin shell that
   validates input and forwards.
2. **Add a schema.** Request/response shapes go under `app/domain/schemas/`.
   Never let raw dicts cross a layer boundary.
3. **Keep the editor pipeline intact.** Any edit must still flow through
   `EditorAgent → PatchEngine → validate_patch → SurgicalWriter`. Even an
   "apply this verbatim" feature should build a `Patch`.
4. **Write a test per layer.** Parser changes → `tests/test_parser/`,
   editor changes → `tests/test_editor/`, etc. Mock `LatexAgent.call`.

## When fixing a bug

1. Reproduce with a test before patching.
2. If the bug is in the LLM output (header echoed, citation lost), fix it in
   the **sanitiser** inside `latex_agent.py`, not in the calling code.
3. If the bug is structural (wrong section span, lost newline), fix it in
   `section_indexer.py` or `surgical_writer.py` and add a regression test.

## Style

- `from __future__ import annotations` at the top of every module.
- `dataclass(slots=True)` for value objects.
- Type-annotate every public callable.
- Run `ruff check . && mypy app/` before opening a PR.

## Things never to do

- Never call Groq from inside `editor/`, `parser/`, or `api/`.
- Never write to the workspace from anywhere except `SurgicalWriter` and
  `WorkspaceManager`.
- Never mutate a `Section` in place — produce a new body string and rebuild.
- Never commit a real `GROQ_API_KEY`. Only `.env.example` should reference it.
