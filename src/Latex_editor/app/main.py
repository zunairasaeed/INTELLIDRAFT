from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.latex import router as latex_router
from app.api.routes.sessions import router as sessions_router

app = FastAPI(title="Latex_editor")
app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
app.include_router(latex_router, prefix="/latex", tags=["latex"])
