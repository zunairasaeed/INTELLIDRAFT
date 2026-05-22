"""
Canonical session features match ``backend.models.Feature`` (``.value`` strings).

Supabase is hosted **PostgreSQL**; ``sessions.feature`` is validated there (CHECK or enum),
not by the Python package name ``Research_and_publishing_guide_bot``.

Older rows may store legacy slugs. On **read**, we map those to canonical API strings for
the frontend. On **insert**, we persist the canonical enum string unchanged.

If INSERT still fails for ``research_publishing_guide``, align the table constraint in
Supabase: ``database/sessions_fix_feature_check.sql`` (SQL editor).
"""

from __future__ import annotations

from backend.models import Feature

_LEGACY_TO_CANONICAL: dict[str, str] = {
    # legacy DB slugs → API / frontend FEATURES.*
    "writing_guide": Feature.research_publishing_guide.value,
    "journal_recommender": Feature.journal_information_assistant.value,
    "latex_editor": Feature.latex_alignment.value,
    "latex_template": Feature.latex_alignment.value,
    "citation_management": Feature.latex_alignment.value,
}


def storage_feature_value(canonical: str) -> str:
    """Value written to Postgres `sessions.feature` (must satisfy DB CHECK / enum)."""
    return (canonical or "").strip()


def canonical_feature_value(stored: str | None) -> str | None:
    """Normalize rows read from the DB for API clients."""
    if stored is None:
        return None
    s = str(stored).strip()
    return _LEGACY_TO_CANONICAL.get(s, s)


def outward_session(row: dict) -> dict:
    out = dict(row)
    feat = out.get("feature")
    if feat is not None:
        out["feature"] = canonical_feature_value(str(feat)) or feat
    return out
