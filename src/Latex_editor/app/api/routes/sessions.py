from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_latex_edit_service
from app.usecases.latex_edit_service import LatexEditService

router = APIRouter()


class EnsureSessionRequest(BaseModel):
    session_id: UUID
    user_id: UUID
    title: str = "Latex Editor"


@router.post("/ensure")
async def ensure_session(
    payload: EnsureSessionRequest,
    service: LatexEditService = Depends(get_latex_edit_service),
):
    session, workspace = await service.ensure_session(
        session_id=payload.session_id,
        user_id=payload.user_id,
        title=payload.title,
    )
    return {
        "session": session,
        "workspace_id": str(workspace.workspace_id),
        "revision": workspace.revision,
    }
