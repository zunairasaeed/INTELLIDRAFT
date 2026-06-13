# Architecture

The LaTeX Editor service is structured as a clean, layered application. Each
layer has a single responsibility and only talks to its immediate neighbours.

```
┌────────────────────────────────────────────────────────────────┐
│                         HTTP clients                            │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  api/        FastAPI routers, dependency injection, request    │
│              schemas. NO business logic.                        │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  usecases/   Application services. Orchestrate parsers,        │
│              agents, editor, DB. ONLY layer routers call.       │
└────────────────────────────────────────────────────────────────┘
        │                │                │                │
        ▼                ▼                ▼                ▼
┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────────┐
│ agents/    │  │ parser/    │  │ editor/    │  │ services/      │
│ LLM calls  │  │ Pure-fn    │  │ Patch /    │  │ Filesystem,    │
│            │  │ TeX read   │  │ write /    │  │ intent router  │
│            │  │            │  │ validate   │  │                │
└────────────┘  └────────────┘  └────────────┘  └────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  domain/     ORM models (SQLAlchemy) + Pydantic schemas         │
│  core/       Settings, db engine, security primitives           │
│  models/     In-memory dataclasses + enums                      │
│  utils/      Shared regex + hashing                             │
└────────────────────────────────────────────────────────────────┘
```

## Layer rules

- `api/` never imports from `editor/` or `agents/` directly.
- `agents/` never touches the filesystem.
- `editor/` never calls an LLM.
- `parser/` is pure: input text → output dataclasses. No I/O.
- `usecases/` is the only layer allowed to compose multiple other layers.

## Key invariants

1. The LLM produces a **body string** only; the patch engine wraps it back into
   a complete section span. The header line is always preserved by the host
   system, never by the model.
2. Every edit is recorded in `edit_history` with before/after hashes, so a
   future undo endpoint can roll back deterministically.
3. Protected regions (preamble, `\bibliography{}`, `\end{document}`) are never
   inside a patch span. The validator rejects any patch that would otherwise.
