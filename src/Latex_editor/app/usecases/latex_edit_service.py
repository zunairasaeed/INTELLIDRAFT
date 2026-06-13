"""Application-layer orchestrator for the LaTeX editing loop.

Flow (one user turn):

    parse → summarize → route → edit → validate → write → reparse → save history → release lock

The per-workspace lock comes from ``WorkspaceManager``. The deterministic
layers (parser, validator, writer) are injected as typed facades from
``app.parser`` / ``app.editor``; the LLM-backed layers (router, editor)
are injected as ``RouterAgent`` / ``EditorAgent`` from ``app.agents``.

This service owns the orchestration but never reaches into LaTeX text,
file I/O, or LLM prompts directly — every step delegates to its layer.
"""

from __future__ import annotations

import logging
from uuid import UUID

from ..agents.doc_summary import summarize_doc
from ..agents.router_agent import RouteIntent

logger = logging.getLogger(__name__)


class LatexEditService:
    def __init__(self, parser, router, editor, writer, validator, db_client, workspace_manager) -> None:
        self.parser = parser
        self.router = router
        self.editor = editor
        self.writer = writer
        self.validator = validator
        self.db = db_client
        self.workspaces = workspace_manager

    async def ensure_session(self, session_id: UUID, user_id: UUID, title: str = "Latex Editor"):
        """Idempotently load or create the session and its workspace."""
        session = await self.db.get_session(session_id)
        if session is None:
            session = await self.db.create_session(user_id=user_id, title=title, feature="latex_editor")

        workspace = self.workspaces.get(session["id"])
        if workspace is None:
            workspace = self.workspaces.get_or_create(session["id"], user_id)
        if not session.get("workspace_id"):
            updated = await self.db.update_session_workspace(session["id"], workspace.workspace_id)
            session["workspace_id"] = updated["workspace_id"]

        return session, workspace

    async def handle_message(self, session_id: UUID, user_id: UUID, message: str) -> dict:
        """Run one user turn through the full editing pipeline."""
        workspace = self.workspaces.get(session_id)
        if workspace is None:
            raise ValueError("Workspace not found")

        async with workspace.lock:
            # 1. Parse the current document.
            doc = self.parser.parse(workspace.tex_path, workspace.bib_path)

            # 2. Build the compact summary the LLM agents consume.
            doc_summary = summarize_doc(doc)

            # 3. Route the user message to a fixed intent.
            #
            # NOTE: ``RouterAgent.valid_section_ids`` lives on the singleton
            # injected from ``dependencies.py`` (one shared router across
            # all workspaces). Mutating it here is safe only because the
            # default ``llm_client`` is ``None`` — no concurrent network
            # call can run on it. When a real LLM client is wired in,
            # refactor this to construct a fresh ``RouterAgent`` per
            # request (or move ``valid_section_ids`` from ``__init__`` to
            # ``route``) so concurrent workspaces can't race on it.
            self.router.valid_section_ids = {s.id for s in doc.sections}
            decision = await self.router.route(message, doc_summary)
            if decision.intent == RouteIntent.UNKNOWN:
                logger.info("Router returned UNKNOWN: %s", decision.reasoning)
                return {
                    "ok": False,
                    "intent": decision.intent.value,
                    "error": "Could not classify request.",
                    "reasoning": decision.reasoning,
                }

            # 4. Editor agent produces the patch body (JSON-shaped output).
            result = await self.editor.execute(decision, doc_summary)

            # 5. Validate + assemble the patch (uses the full ParsedDocument
            #    to look up the target section's body line range).
            validated = self.validator.validate(result, doc)
            if not validated.ok:
                logger.info(
                    "Validator rejected patch for intent %s: %s",
                    decision.intent.value,
                    validated.error,
                )
                return {
                    "ok": False,
                    "intent": decision.intent.value,
                    "error": validated.error,
                }

            # 6. Apply the patch surgically.
            await self.writer.apply(workspace.tex_path, validated.patch)

            # 7. Record history.
            await self.db.save_history(
                session_id=session_id,
                workspace_id=workspace.workspace_id,
                user_id=user_id,
                intent=decision.intent.value,
                summary=validated.summary,
            )
            workspace.revision += 1

            # 8. Reparse-after-write per the project rules — the freshly
            #    parsed tree is the new ground truth for any follow-up.
            self.parser.parse(workspace.tex_path, workspace.bib_path)

            return {
                "ok": True,
                "intent": decision.intent.value,
                "revision": workspace.revision,
                "summary": validated.summary,
            }
