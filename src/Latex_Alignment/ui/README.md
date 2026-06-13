# Streamlit test UI

Local chat + editor surface for `latex_agent_backend` (parser, agent, operations, serializer).

## Setup

```powershell
cd D:\INTELLIDRAFT\src\latex_agent_backend
..\..\venv\Scripts\pip.exe install -r requirements-ui.txt
```

Add one of these to `D:\INTELLIDRAFT\.env` (or `latex_agent_backend\.env`):

```env
GROQ_API_KEY=your_key_here
# optional
GROQ_MODEL=llama-3.3-70b-versatile
```

Or:

```env
ANTHROPIC_API_KEY=your_key_here
```

## Run

```powershell
cd D:\INTELLIDRAFT\src\latex_agent_backend
..\..\venv\Scripts\streamlit.exe run ui/app.py
```

Opens at http://localhost:8501

## What you can test

1. Upload `.tex` (+ optional `.bib`)
2. Browse sections in **Contents**
3. Edit section text in the centre panel (auto-saves via `rewrite`)
4. Chat in **Edit assistant** — runs `Session.command()` → agent → operations
5. **Export .tex**, **Reset**, **History**

Uses `tests/sample-sigconf.tex` as a sample file if needed.
