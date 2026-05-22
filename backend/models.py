from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from enum import Enum

# Human / repo-folder strings accepted on input and normalized to ``Feature.value`` before DB insert.
FEATURE_INPUT_ALIASES: dict[str, str] = {
    # Matches ``src/Research_and_publishing_guide_bot/`` — persisted value is still ``research_publishing_guide``.
    "research_and_publishing_guide_bot": "research_publishing_guide",
    "Research_and_publishing_guide_bot": "research_publishing_guide",
}


class Feature(str, Enum):
    """
    Values persisted in Supabase on ``sessions.feature`` (PostgreSQL CHECK / enum).

    These are the **API contract strings** — not Python package paths. For example, the
    writing-guide RAG is implemented under ``src/Research_and_publishing_guide_bot/``, but
    clients and the DB must use ``research_publishing_guide`` here.
    """

    semantic_literature_search = "semantic_literature_search"
    journal_information_assistant = "journal_information_assistant"
    # Writing guide: code in ``src/Research_and_publishing_guide_bot/``; HTTP ``/pipelines/research-guide/*``.
    research_publishing_guide = "research_publishing_guide"
    latex_alignment = "latex_alignment"

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
    """
    Create a session row tied to the authenticated user (`user_id` is set server-side).

    `feature` must be one of `Feature` enum strings. The OpenAPI **example** is not special-cased:
    literature, writing guide, journal, and LaTeX all use the same endpoint with different
    `feature` values.     If Postgres returns 23514, your Supabase project (PostgreSQL) ``sessions.feature``
    CHECK or enum must allow that string (run ``database/sessions_fix_feature_check.sql``
    in the Supabase SQL editor).
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"feature": "semantic_literature_search", "title": "Literature search"},
                {"feature": "research_publishing_guide", "title": "Writing guide"},
                {
                    "feature": "Research_and_publishing_guide_bot",
                    "title": "Writing guide (folder alias → research_publishing_guide)",
                },
                {"feature": "journal_information_assistant", "title": "Journal finder"},
                {"feature": "latex_alignment", "title": "LaTeX assist"},
            ],
        }
    )

    feature: str = Field(
        ...,
        description=(
            "Workspace feature string (same as `Feature` enum). Stored on `sessions.feature` "
            "for this user. Allowed: `semantic_literature_search`, `journal_information_assistant`, "
            "`research_publishing_guide`, `latex_alignment`. "
            "Alias accepted for the writing guide: `Research_and_publishing_guide_bot` → "
            "`research_publishing_guide`."
        ),
    )
    title: Optional[str] = Field(
        default="New session",
        description="Short label shown in session lists.",
    )

    @field_validator("feature")
    @classmethod
    def feature_must_be_known(cls, v: str) -> str:
        s = (v or "").strip()
        s = FEATURE_INPUT_ALIASES.get(s, s)
        allowed = {f.value for f in Feature}
        if s not in allowed:
            raise ValueError(
                f"Unknown feature {v!r}. Allowed: {sorted(allowed)} "
                f"(writing guide alias: Research_and_publishing_guide_bot)"
            )
        return s

    @field_validator("title")
    @classmethod
    def title_strip(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return "New session"
        t = v.strip()
        return t if t else "New session"

class ChatRequest(BaseModel):
    """
    Persist conversation in `messages`; workspace type comes from the session.
    Invoke pipelines only via `/pipelines/*`, not through this endpoint.
    """

    session_id: str
    message: str
