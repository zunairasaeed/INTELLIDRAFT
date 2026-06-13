"""FastAPI dependency providers.

Singletons (``@lru_cache(maxsize=1)``) so every request shares the
same parser, validator, writer, agents, DbClient, and workspace
manager. The LLM client is selected at startup:

* ``GroqLLMClient`` when ``GROQ_API_KEY`` is set (real LLM).
* ``StubLLMClient`` otherwise (router will return ``intent=unknown``
  so the loop short-circuits cleanly instead of crashing).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.agents.editor_agent import EditorAgent
from app.agents.router_agent import RouterAgent
from app.core.config import get_settings
from app.core.db_client import DbClient
from app.core.in_memory_db import InMemoryDbClient
from app.core.llm_client import LLMClient, StubLLMClient
from app.editor.patch_validator import Validator
from app.editor.patch_writer import Writer
from app.parser.document_parser import Parser
from app.services.workspace_manager import WorkspaceManager
from app.usecases.latex_edit_service import LatexEditService

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.groq_api_key:
        try:
            from app.core.groq_llm_client import GroqLLMClient

            logger.info("LLM client: GroqLLMClient (model=%s).", settings.groq_model)
            return GroqLLMClient(
                api_key=settings.groq_api_key,
                model=settings.groq_model,
                temperature=settings.groq_temperature,
                max_tokens=settings.groq_max_tokens,
            )
        except Exception as exc:
            logger.warning(
                "GroqLLMClient construction failed (%s); falling back to StubLLMClient.",
                exc,
            )
    logger.info("LLM client: StubLLMClient (no GROQ_API_KEY configured).")
    return StubLLMClient()


@lru_cache(maxsize=1)
def get_db_client() -> DbClient:
    # TODO: switch to SupabaseDbClient when settings.supabase_url + key are set.
    return InMemoryDbClient()


@lru_cache(maxsize=1)
def get_workspace_manager() -> WorkspaceManager:
    settings = get_settings()
    return WorkspaceManager(root=settings.workspace_root)


@lru_cache(maxsize=1)
def get_parser() -> Parser:
    return Parser()


@lru_cache(maxsize=1)
def get_validator() -> Validator:
    return Validator()


@lru_cache(maxsize=1)
def get_writer() -> Writer:
    return Writer()


@lru_cache(maxsize=1)
def get_router_agent() -> RouterAgent:
    return RouterAgent(llm_client=get_llm_client())


@lru_cache(maxsize=1)
def get_editor_agent() -> EditorAgent:
    return EditorAgent(llm_client=get_llm_client())


@lru_cache(maxsize=1)
def get_latex_edit_service() -> LatexEditService:
    return LatexEditService(
        parser=get_parser(),
        router=get_router_agent(),
        editor=get_editor_agent(),
        writer=get_writer(),
        validator=get_validator(),
        db_client=get_db_client(),
        workspace_manager=get_workspace_manager(),
    )
