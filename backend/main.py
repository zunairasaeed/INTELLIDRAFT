from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes import auth, sessions, chat, files, citations, pipelines


app = FastAPI(
    title="IntelliDraft Backend API",
    description=(
        "Auth, sessions, chat, files, citations, and unified `/pipelines` for "
        "journal recommendation, literature search, research-guide RAG, and stubs."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(files.router)
app.include_router(citations.router)
app.include_router(pipelines.router)


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "service": "IntelliDraft Backend"}
