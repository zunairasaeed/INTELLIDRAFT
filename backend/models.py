from pydantic import BaseModel, field_validator
from typing import Optional
from enum import Enum

class Feature(str, Enum):
    semantic_literature_search    = "semantic_literature_search"
    journal_information_assistant = "journal_information_assistant"
    research_publishing_guide    = "research_publishing_guide"
    latex_alignment              = "latex_alignment"

class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None

    @field_validator("email")
    @classmethod
    def strip_email(cls, v: str) -> str:
        return (v or "").strip()

class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def strip_email(cls, v: str) -> str:
        return (v or "").strip()

class NewSessionRequest(BaseModel):
    feature: Feature
    title: Optional[str] = "New session"

class ChatRequest(BaseModel):
    """
    Persist conversation in `messages`; workspace type comes from the session.
    Invoke pipelines only via `/pipelines/*`, not through this endpoint.
    """

    session_id: str
    message: str
