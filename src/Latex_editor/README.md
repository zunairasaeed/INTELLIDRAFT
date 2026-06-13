# LaTeX Editor

> **Strategy & flow (no code):** see [STRATEGY.md](./STRATEGY.md) — architecture, request lifecycle, database tables, and what this project achieved.

An agentic, session-scoped LaTeX editor for ACM academic papers. Users submit
natural-language instructions; the service routes them through an editor agent
(Groq) and applies the result as a **surgical patch** that preserves every
`\label{}`, `\cite{}`, `\ref{}`, environment, and protected region in the
source.

## Features

- FastAPI service with session + workspace lifecycle.
- Section-aware parser (sections, zones, bib keys, protected regions).
- Three edit modes: `edit`, `generate`, `append` (plus `auto`).
- Patch / validate / write pipeline — the LLM never writes to disk directly.
- Full edit history per session for audit and undo.
- ACM templates bundled (`acmart.cls`, sample `.tex` files, ACM bib).

## Layout

```
Latex_editor/
├── app/                # Application code (clean architecture)
│   ├── api/            # FastAPI routers + dependencies
│   ├── usecases/       # Application services
│   ├── agents/         # LLM agents
│   ├── parser/         # Pure-function TeX parsers
│   ├── editor/         # Patch engine + surgical writer + validation
│   ├── services/       # Infrastructure (filesystem, intent routing)
│   ├── domain/         # ORM models + Pydantic schemas
│   ├── core/           # Config, db, security
│   ├── utils/          # Regex, hashing
│   └── models/         # In-memory dataclasses + enums
├── reference/acm/      # acmart.cls, sample .tex, .bst, .bib files
├── database/           # SQL schema + migrations
├── tests/              # Pytest suites, one folder per layer
└── docs/               # Architecture, data-flow, Cursor instructions
```

## Quickstart

```bash
cd src/Latex_editor
python -m venv .venv
.venv/Scripts/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # then edit GROQ_API_KEY and SECRET_KEY
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` for the interactive API.

## API at a glance

| Method | Path                       | Description                              |
| ------ | -------------------------- | ---------------------------------------- |
| GET    | `/healthz`                 | Liveness probe                           |
| POST   | `/sessions`                | Create a new editing session             |
| GET    | `/sessions/{id}`           | Inspect a session                        |
| DELETE | `/sessions/{id}`           | Terminate a session                      |
| GET    | `/latex/parse`             | Section index, zones, bib keys           |
| POST   | `/latex/edit`              | Apply an edit/generate/append instruction|
| GET    | `/latex/history`           | List edit history for the session        |

The `X-Session-Id` header is required on every `/latex/*` call.

## Testing

```bash
pytest
```

## License

MIT
