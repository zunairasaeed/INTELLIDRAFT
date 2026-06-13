from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.dependencies import get_latex_edit_service
from app.usecases.latex_edit_service import LatexEditService

router = APIRouter()


class LatexMessageRequest(BaseModel):
    session_id: UUID
    user_id: UUID
    message: str


@router.post("/messages")
async def latex_message(
    payload: LatexMessageRequest,
    service: LatexEditService = Depends(get_latex_edit_service),
):
    session, workspace = await service.ensure_session(
        session_id=payload.session_id,
        user_id=payload.user_id,
    )
    result = await service.handle_message(
        session_id=session["id"],
        user_id=payload.user_id,
        message=payload.message,
    )
    return {
        "session": session,
        "workspace": {
            "workspace_id": str(workspace.workspace_id),
            "revision": workspace.revision,
        },
        "result": result,
    }
