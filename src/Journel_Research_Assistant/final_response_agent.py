# -*- coding: utf-8 -*-
"""
Final response agent — turns pipeline JSON into a user-facing markdown answer (Groq via call_gpt).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_MODULE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _MODULE_DIR.parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from call_gpt import call_gpt  # noqa: E402

FINAL_RESPONSE_SYSTEM = """You are the FINAL RESPONSE AGENT in a journal research system.

You receive a fully processed JSON object from upstream pipelines.
This JSON already contains:
- retrieved journals
- metrics (SJR, h-index, citations)
- classification (quartile, subject areas)
- open access metadata (may be partial)
- ranking signals and confidence scores

Your job is ONLY to convert this into a clean, user-facing answer.

---

# CRITICAL RULES
- Do NOT call tools
- Do NOT explain the system
- Do NOT mention JSON, APIs, pipelines, or retrieval steps
- Do NOT hallucinate missing data (fees, impact factor, etc.)
- Do NOT invent journals or metrics
- Use ONLY what is present in the input
- If data is missing, say "not clearly available"

---

# CORE OBJECTIVE

Turn raw journal results into:
1. A ranked recommendation
2. A short explanation of why
3. A clear final suggestion for the user

Focus on clarity, usefulness, and decision-making.

---

# DECISION RULES

When ranking journals:
- Q1 > Q2 > Q3 > Q4
- Higher SJR = better
- Higher h-index = stronger reputation
- Higher citations = more established
- Prefer higher confidence_score when present
- Prefer well-known publishers if available

If journals are close:
- choose the one with stronger overall balance (not just one metric)

---

# OUTPUT FORMAT (STRICT)

Return ONLY this structure:

## Top Journal Recommendations

### 1. <Journal Name>
- Publisher:
- Quartile:
- SJR / Impact signal:
- h-index:
- Subject areas:
- Why this is ranked #1:

### 2. <Journal Name>
- Publisher:
- Quartile:
- Metrics:
- Why it ranks here:

### 3. <Journal Name>
- Publisher:
- Key strengths:

(Include fewer than three sections if fewer journals exist.)

---

## Summary Insight
Explain in 2-4 paragraphs:
- what field these journals belong to
- how strong the top journal is
- tradeoffs between top options
- which type of researcher each journal fits

---

## Final Recommendation
Give ONE clear suggestion:
- best journal for the user's stated goal
Be direct and decisive.

If there are NO journals in the input, explain briefly what was asked and suggest how to rephrase.
Do NOT invent journal names.

---

# FORBIDDEN
- No JSON output
- No system explanations
- No speculation about fees if missing
- No naming data vendors or sources
- No verbosity or filler

---

# STYLE
- clear
- academic but simple
- confident
- decision-oriented
"""

_SKIP_LLM = os.getenv("JOURNAL_RESEARCH_SKIP_LLM_SUMMARY", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


def _pick(row: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _compact_journal(row: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    prov = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
    quality = row.get("quality") if isinstance(row.get("quality"), dict) else {}
    return {
        "name": _pick(row, "name") or "Unknown",
        "publisher": _pick(row, "publisher"),
        "country": _pick(row, "country"),
        "best_quartile": _pick(row, "best_quartile"),
        "sjr_score": _pick(row, "sjr_score"),
        "h_index": _pick(row, "h_index", "h_index_scimago"),
        "citation_score_2yr": _pick(row, "citation_score_2yr"),
        "total_citations": _pick(row, "total_citations"),
        "subject_areas": (_pick(row, "subject_areas") or [])[:6],
        "is_oa": _pick(row, "is_oa"),
        "apc_usd": _pick(row, "apc_usd"),
        "doaj_apc_amount": _pick(row, "doaj_apc_amount"),
        "doaj_apc_currency": _pick(row, "doaj_apc_currency"),
        "confidence_score": quality.get("confidence_score"),
        "retrieval_relevance_score": row.get("retrieval_relevance_score"),
        "search_context": prov.get("search_context"),
    }


def _payload_for_llm(raw: Dict[str, Any]) -> Dict[str, Any]:
    results = raw.get("results") if isinstance(raw.get("results"), list) else []
    journals = [_compact_journal(r) for r in results[:8] if isinstance(r, dict)]
    return {
        "user_question": raw.get("query"),
        "intent": raw.get("intent"),
        "domain": raw.get("domain"),
        "filter_quartile": raw.get("filter_quartile"),
        "source_note": raw.get("source_note"),
        "fee_note": raw.get("fee_note"),
        "metrics_note": raw.get("metrics_note"),
        "error": raw.get("error"),
        "reason": raw.get("reason"),
        "suggestion": raw.get("suggestion"),
        "journals": journals,
    }


def _fallback_answer(raw: Dict[str, Any]) -> str:
    """Deterministic summary when Groq is unavailable."""
    payload = _payload_for_llm(raw)
    q = payload.get("user_question") or ""
    journals = payload.get("journals") or []
    if not journals:
        parts = ["## Top Journal Recommendations", "", "No matching journals were found for your query."]
        if payload.get("suggestion"):
            parts.append(f"\n**Suggestion:** {payload['suggestion']}")
        if payload.get("reason"):
            parts.append(f"\n**Note:** {payload['reason']}")
        parts.extend(["", "## Final Recommendation", "Try broadening your topic or rephrasing the question."])
        return "\n".join(parts)

    lines = ["## Top Journal Recommendations", ""]
    medals = ("1.", "2.", "3.")
    for i, j in enumerate(journals[:3]):
        label = medals[i] if i < len(medals) else f"{i + 1}."
        lines.append(f"### {label} {j.get('name', 'Unknown')}")
        for key, label_txt in (
            ("publisher", "Publisher"),
            ("best_quartile", "Quartile"),
            ("sjr_score", "SJR"),
            ("h_index", "h-index"),
        ):
            val = j.get(key)
            if val is not None:
                lines.append(f"- {label_txt}: {val}")
        subs = j.get("subject_areas") or []
        if subs:
            lines.append(f"- Subject areas: {', '.join(str(s) for s in subs[:4])}")
        lines.append("")
    lines.extend(
        [
            "## Summary Insight",
            f"Results for: {q}",
            "",
            "## Final Recommendation",
            f"Consider **{journals[0].get('name', 'the top-ranked journal')}** first based on available quartile and SJR signals.",
        ]
    )
    return "\n".join(lines)


def generate_final_answer(raw: Dict[str, Any]) -> str:
    if _SKIP_LLM:
        return _fallback_answer(raw)
    if not os.getenv("GROQ_API_KEY", "").strip():
        return _fallback_answer(raw)

    payload = _payload_for_llm(raw)
    user_prompt = (
        f"User question:\n{payload.get('user_question') or ''}\n\n"
        f"Processed pipeline output (use only this data):\n"
        f"{json.dumps(payload, indent=2, ensure_ascii=False)}"
    )
    try:
        text = call_gpt(
            system_prompt=FINAL_RESPONSE_SYSTEM,
            user_prompt=user_prompt,
            max_tokens=int(os.getenv("JOURNAL_RESEARCH_LLM_MAX_TOKENS", "2048")),
            temperature=float(os.getenv("JOURNAL_RESEARCH_LLM_TEMPERATURE", "0.25")),
            model=os.getenv("JOURNAL_RESEARCH_LLM_MODEL", "llama-3.3-70b-versatile"),
        )
        return (text or "").strip() or _fallback_answer(raw)
    except Exception:
        return _fallback_answer(raw)


def format_public_response(raw: Dict[str, Any], answer: str) -> Dict[str, Any]:
    """Slim API body: primary field is markdown ``answer``."""
    results = raw.get("results") if isinstance(raw.get("results"), list) else []
    out: Dict[str, Any] = {
        "query": raw.get("query") or "",
        "intent": raw.get("intent") or "",
        "domain": raw.get("domain") or "",
        "answer": answer,
        "results_count": len(results),
    }
    for key in (
        "error",
        "suggestion",
        "source_note",
        "fee_note",
        "metrics_note",
        "filter_quartile",
        "fallback_used",
        "reason",
    ):
        val = raw.get(key)
        if val is not None and val != "":
            out[key] = val
    return out


def build_api_response(
    raw: Dict[str, Any],
    routing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    answer = generate_final_answer(raw)
    out = format_public_response(raw, answer)
    if routing is not None:
        out["routing"] = routing
    return out
