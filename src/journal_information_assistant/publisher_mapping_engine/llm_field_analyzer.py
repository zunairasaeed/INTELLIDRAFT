"""
llm_field_analyzer.py

STEP 5-7 : LLM-based field identification, domain detection, application inference.
STEP 8   : FAISS vector similarity search (publisher-level embeddings).
STEP 9   : Rule-based scoring — combines LLM confidence + FAISS similarity + mapping.
STEP 10  : Final recommendation with journal link, detailed reasoning, search keywords.

Pipeline:
    User Input (query + keywords)
        │
        ├─► FAISS similarity search  → publisher cosine scores  (fast, local)
        │       uses: publisher_fields_faiss.index
        │             publisher_fields_meta.json
        │             sentence-transformers/all-MiniLM-L6-v2
        │
        ├─► Groq LLM classification  → identified_field, domain_type,
        │       uses: call_gpt()           application_area, confidence, reasoning
        │
        └─► Rule-based scoring       → combines both signals → top 2 publishers
                + recommendation block with portal link, reasoning, search keywords

Path: src/journal_information_assistant/publisher_mapping_engine/llm_field_analyzer.py
Input : {"query": str, "keywords": [...]}
Output: {identified_field, domain_type, application_area, publisher_recommendation,
         chatbot_response, success, error}
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from call_gpt import call_gpt
from ..utils.json_loader import load_publisher_mapping


# ── Paths to FAISS assets (same folder as build script) ───────────────────
_FAISS_DIR   = Path(__file__).resolve().parents[3] / "database" / "Journel_recommendations"
INDEX_PATH   = _FAISS_DIR / "publisher_fields_faiss.index"
META_PATH    = _FAISS_DIR / "publisher_fields_meta.json"

# ── Constants ──────────────────────────────────────────────────────────────
VALID_DOMAIN_TYPES = ["Technical", "Cross-domain"]

VALID_APPLICATION_AREAS = [
    "Healthcare / Medicine",
    "Finance / Economics",
    "Social Sciences / Policy",
    "Education / Learning",
    "Biology / Bioinformatics",
    "Industrial / Manufacturing",
    "Energy / Power Systems",
]

MAX_RETRIES = 2

PUBLISHER_PORTALS: Dict[str, str] = {
    "ACM":      "https://dl.acm.org/journals",
    "IEEE":     "https://publication-recommender.ieee.org/home",
    "Springer": "https://link.springer.com/journals/browse-subject?subject=TECHNOLOGY_AND_ENGINEERING",
    "Elsevier": "https://journalfinder.elsevier.com/",
}

PUBLISHER_DESCRIPTIONS: Dict[str, str] = {
    "ACM": (
        "ACM (Association for Computing Machinery) is the world's largest computing society. "
        "It focuses on computing theory, systems, human-computer interaction, and software engineering. "
        "Best for papers with a strong CS systems or HCI angle."
    ),
    "IEEE": (
        "IEEE (Institute of Electrical and Electronics Engineers) is the leading publisher for "
        "engineering, hardware, networks, embedded systems, IoT, and cybersecurity. "
        "Best for papers combining CS with real-world engineering systems."
    ),
    "Springer": (
        "Springer Nature specialises in theoretical and mathematical computer science, "
        "ML theory, algorithms, and foundational research. "
        "Best for papers with strong theoretical or formal contributions."
    ),
    "Elsevier": (
        "Elsevier covers applied, interdisciplinary research with real-world impact — "
        "especially AI in healthcare, finance, biology, and social sciences. "
        "Best for cross-domain applied research with domain-specific datasets."
    ),
}

# ── Prompt engineering for user-facing recommendation response ──────────────
JOURNAL_RECOMMENDATION_SYSTEM = """You are ResearchAdvisor, a warm and knowledgeable
academic publishing mentor inside IntelliDraft. You help researchers find the right
journal or publisher for their work.

You will receive a structured analysis of the user's research containing:
- The identified research field
- Domain type (Technical or Cross-domain)
- Application area (if cross-domain)
- Top publisher recommendation with reasoning
- Runner-up publisher
- Suggested search terms for the journal finder (if available)
- Journal finder link

YOUR JOB:
Transform this structured data into a natural, helpful, mentor-style response.

STRICT RULES:
- NEVER show raw JSON, scores, or technical internals to the user
- NEVER mention "FAISS", "cosine scores", "rule-based scoring" or any pipeline details
- NEVER invent publishers or journals not present in the structured data
- ALWAYS base your answer on the structured analysis provided
TONE & STYLE:
- Talk like a friendly academic advisor who genuinely wants to help
- Be encouraging and practical
- Keep it conversational and digestible - not a wall of text
- Use simple clear language, avoid unnecessary jargon

ANSWER FORMAT:
1. Start by acknowledging what their research is about (1 sentence)
2. Recommend the best publisher and explain WHY it fits their work naturally (2-3 sentences)
3. Mention the runner-up as an alternative worth exploring (1 sentence)
4. Give them the journal finder link and, only if concrete search hints are listed, suggest a few fitting terms — otherwise steer them to browse by topic in the finder
5. End with ONE helpful follow-up question like:
   "Would you like tips on how to shortlist specific journals within [publisher]?"
"""

JOURNAL_RECOMMENDATION_USER = """
The user asked: "{user_query}"

Structured analysis result:
- Research Field: {identified_field}
- Domain Type: {domain_type}
- Application Area: {application_area}
- Best Publisher: {best_publisher}
- Why This Publisher: {why_this_publisher}
- Why This Domain: {why_this_domain}
- Runner-up Publisher: {runner_up}
- Journal Finder Link: {journal_finder_link}
- Journal finder hints (may be sparse): {search_keywords}

Now respond to the user as ResearchAdvisor in a warm, conversational, mentor-like way.
Do NOT mention scores, FAISS, pipeline details, or raw JSON.
"""

# ── Scoring weights ────────────────────────────────────────────────────────
# Rule-based (from field_to_publishers_mapping)
SCORE_PRIMARY               = 50    # publisher is primary for LLM-identified field
SCORE_SECONDARY             = 25    # publisher is secondary for LLM-identified field
SCORE_CONFIDENCE_MULTIPLIER = 20    # LLM confidence × 20  (max +20)

# FAISS similarity (cosine score is 0.0–1.0, scaled to points)
SCORE_FAISS_MULTIPLIER      = 30    # faiss_cosine × 30    (max +30)


# ── FAISS loader (cached after first load) ────────────────────────────────
_faiss_cache: Optional[Dict[str, Any]] = None

def _load_faiss_assets() -> Dict[str, Any]:
    """Load FAISS index + meta once, cache for reuse."""
    global _faiss_cache
    if _faiss_cache is not None:
        return _faiss_cache

    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            f"FAISS index not found: {INDEX_PATH}\n"
            "Run build_publisher_field_embeddings.py first."
        )
    if not META_PATH.exists():
        raise FileNotFoundError(
            f"Meta file not found: {META_PATH}\n"
            "Run build_publisher_field_embeddings.py first."
        )

    meta        = json.loads(META_PATH.read_text(encoding="utf-8"))
    index       = faiss.read_index(str(INDEX_PATH))
    model_name  = meta["model_name"]
    index_order = meta["index_order"]   # e.g. ["ACM","IEEE","Springer","Elsevier"]
    publishers  = meta["publishers"]    # list of publisher dicts, same order

    model = SentenceTransformer(model_name)

    _faiss_cache = {
        "index":       index,
        "model":       model,
        "index_order": index_order,
        "publishers":  publishers,
    }
    return _faiss_cache


def _faiss_search(query_text: str) -> Dict[str, float]:
    """
    Embed query_text and run cosine similarity against all 4 publisher vectors.
    Returns {publisher_key: cosine_score} for all publishers.
    """
    assets = _load_faiss_assets()
    model  = assets["model"]
    index  = assets["index"]
    order  = assets["index_order"]

    vec = model.encode([query_text], convert_to_numpy=True)
    vec = vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-12)
    vec = vec.astype("float32")

    # Search all publishers (k = total count)
    scores, indices = index.search(vec, len(order))

    result: Dict[str, float] = {}
    for idx, score in zip(indices[0], scores[0]):
        if idx >= 0:
            result[order[idx]] = float(score)

    return result  # e.g. {"Elsevier": 0.87, "IEEE": 0.61, ...}


# ── Rule-based scoring (combines mapping + FAISS + LLM confidence) ─────────

def _score_publishers(
    field: str,
    domain_type: str,
    application_area: Optional[str],
    confidence: float,
    field_mapping: Dict[str, Any],
    faiss_scores: Dict[str, float],
) -> List[Dict[str, Any]]:
    """
    Scores all 4 publishers using 3 signals:

    Signal 1 — Field mapping rule  (from JSON, deterministic)
        +50 if PRIMARY publisher for LLM-identified field
        +25 if SECONDARY publisher for LLM-identified field

    Signal 2 — LLM confidence bonus  (rewards high-certainty classifications)
        + confidence × 20  (max +20)

    Signal 3 — FAISS cosine similarity  (semantic match of query to publisher profile)
        + cosine_score × 30  (max +30)

    Total possible max score = 50 + 20 + 30 = 100 pts
    """
    field_info = field_mapping.get(field, {})
    primary    = field_info.get("primary", [])
    secondary  = field_info.get("secondary", [])

    if isinstance(primary, dict):
        primary = list(primary.values())
    if isinstance(primary, str):
        primary = [primary]
    if isinstance(secondary, str):
        secondary = [secondary]

    confidence_bonus = round(confidence * SCORE_CONFIDENCE_MULTIPLIER, 1)

    results = []
    for pub_key, portal in PUBLISHER_PORTALS.items():
        score   = 0.0
        reasons = []

        # Signal 1: field mapping
        if pub_key in primary:
            score += SCORE_PRIMARY
            reasons.append(f"Primary publisher for '{field}' (+{SCORE_PRIMARY} pts)")
        elif pub_key in secondary:
            score += SCORE_SECONDARY
            reasons.append(f"Secondary publisher for '{field}' (+{SCORE_SECONDARY} pts)")
        else:
            reasons.append(f"Not in mapping for '{field}' (+0 pts)")

        # Signal 2: LLM confidence bonus
        score += confidence_bonus
        reasons.append(f"LLM confidence {confidence:.0%} (+{confidence_bonus} pts)")

        # Signal 3: FAISS cosine similarity
        cosine      = faiss_scores.get(pub_key, 0.0)
        faiss_bonus = round(cosine * SCORE_FAISS_MULTIPLIER, 1)
        score      += faiss_bonus
        reasons.append(
            f"FAISS semantic similarity {cosine:.2f} (+{faiss_bonus} pts)"
        )

        results.append({
            "publisher":     pub_key,
            "score":         round(score, 1),
            "score_reasons": reasons,
            "faiss_cosine":  round(cosine, 4),
            "confidence":    confidence,
            "portal":        portal,
            "description":   PUBLISHER_DESCRIPTIONS[pub_key],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i

    return results


# ── Recommendation builder ─────────────────────────────────────────────────

def _build_recommendation(
    scores: List[Dict[str, Any]],
    field: str,
    domain_type: str,
    application_area: Optional[str],
    llm_reasoning: str,
    keywords: List[str],
    field_mapping: Dict[str, Any],
) -> Dict[str, Any]:
    best   = scores[0]
    second = scores[1] if len(scores) > 1 else None

    field_note = field_mapping.get(field, {}).get("note", "")

    # Why this domain
    why_domain = f"This paper is classified as '{domain_type}' because: {llm_reasoning}. "
    if domain_type == "Cross-domain" and application_area:
        why_domain += (
            f"Domain-specific concepts from '{application_area}' alongside "
            f"core CS/ML techniques confirm the cross-domain nature."
        )
    else:
        why_domain += (
            "The paper deals purely with CS/engineering concepts "
            "without significant application to an external domain."
        )

    # Why this publisher
    why_publisher = (
        f"{best['publisher']} is the best fit because: {best['description']} "
        f"Field-level guidance: {field_note}"
    )

    clean_keywords = []
    for kw in keywords or []:
        if not isinstance(kw, str):
            continue
        kw = kw.strip()
        # Must be more than one word OR a known technical term
        words = kw.split()
        if len(words) >= 2:  # keep only multi-word keywords
            clean_keywords.append(kw)

    search_kws = list(
        dict.fromkeys(
            [field]
            + ([application_area] if application_area else [])
            + clean_keywords[:4]
        )
    )[:6]

    return {
        "best_publisher":      best["publisher"],
        "why_this_domain":     why_domain,
        "why_this_publisher":  why_publisher,
        "journal_finder_link": best["portal"],
        "search_keywords":     search_kws,
        "runner_up": {
            "publisher": second["publisher"] if second else None,
            "portal":    second["portal"]    if second else None,
        },
    }


def _pub_full_name(key: str) -> str:
    return {
        "ACM":      "Association for Computing Machinery (ACM)",
        "IEEE":     "Institute of Electrical and Electronics Engineers (IEEE)",
        "Springer": "Springer Nature",
        "Elsevier": "Elsevier",
    }.get(key, key)


def _build_mentor_recommendation_text(
    user_query: str,
    identified_field: str,
    domain_type: str,
    application_area: Optional[str],
    recommendation: Dict[str, Any],
) -> str:
    """Render final mentor-style text from structured recommendation output."""
    runner_up = (recommendation.get("runner_up") or {}).get("publisher")
    search_keywords = recommendation.get("search_keywords") or []

    kw_hints = ", ".join(search_keywords[:6]) if search_keywords else ""

    user_prompt = JOURNAL_RECOMMENDATION_USER.format(
        user_query=user_query,
        identified_field=identified_field,
        domain_type=domain_type,
        application_area=application_area or "None",
        best_publisher=recommendation.get("best_publisher"),
        why_this_publisher=recommendation.get("why_this_publisher"),
        why_this_domain=recommendation.get("why_this_domain"),
        runner_up=runner_up or "None",
        journal_finder_link=recommendation.get("journal_finder_link"),
        search_keywords=kw_hints if kw_hints else "(none extracted — steer user to publisher browse + their topic wording)",
    )

    text = call_gpt(
        system_prompt=JOURNAL_RECOMMENDATION_SYSTEM,
        user_prompt=user_prompt,
        max_tokens=420,
        temperature=0.3,
    )
    if text and text.strip():
        return text.strip()

    # Safe fallback (if LLM unavailable): concise, friendly plain-text response.
    best = recommendation.get("best_publisher", "a suitable publisher")
    link = recommendation.get("journal_finder_link", "")
    if search_keywords:
        kw_sentence = (
            "Try filtering in the finder with terms such as "
            + ", ".join(search_keywords[:3])
            + ". "
        )
    else:
        kw_sentence = (
            "Use the journal finder to browse inside that publisher and match your wording from the title "
            "or abstract — no crisp keyword phrases were extracted from your input. "
        )
    return (
        f"Your work looks aligned with {identified_field}, and the best current fit is {best}. "
        f"It matches your topic focus and publication direction well. "
        f"You could also explore {runner_up or 'an alternative publisher'} as a second option. "
        f"{kw_sentence}"
        f"{('Journal finder: ' + link + '. ') if link else ''}"
        "Would you like help shortlisting specific journals next?"
    )


# ── LLM prompt builders ────────────────────────────────────────────────────

def _get_system_prompt(valid_fields: List[str], valid_apps: List[str]) -> str:
    fields_str = " | ".join(f'"{f}"' for f in valid_fields)
    apps_str   = " | ".join(f'"{a}"' for a in valid_apps)
    return f"""You are a research domain classification engine for an academic journal recommendation system.
Your task is to analyze research text and produce STRICT JSON output.
You must follow all constraints exactly.

---------------------
KNOWLEDGE BASE
---------------------
Valid research fields (choose ONE exact match):
[{fields_str}]

Valid application areas (ONLY if domain_type is "Cross-domain"):
[{apps_str}]

---------------------
CLASSIFICATION LOGIC
---------------------
1. Identify the research field using keywords and technical concepts.
2. domain_type rules:
   - "Technical"    -> only computer science / engineering concepts.
   - "Cross-domain" -> CS combined with medical, business, finance, social, or biological domain.
3. application_area: null if Technical; required if Cross-domain.
4. confidence: 0.9-1.0 clear | 0.7-0.89 strong | 0.5-0.69 moderate | <0.5 uncertain.

---------------------
OUTPUT FORMAT - STRICT JSON ONLY. No markdown. No text outside JSON.
---------------------
{{
  "identified_field": "<exact string from valid fields list>",
  "domain_type": "Technical" or "Cross-domain",
  "application_area": null or "<exact string from valid application areas>",
  "confidence": <float 0.0 to 1.0>,
  "reasoning": "<max 25 words citing specific keywords>"
}}"""


def _get_user_prompt(query: str, keywords: List[str], attempt: int) -> str:
    base = f"""INPUT
-----
Query   : {query}
Keywords: {', '.join(keywords[:20])}

Return STRICT JSON only. No markdown. No explanation outside JSON."""
    if attempt > 1:
        base += "\n\nIMPORTANT: Your previous response failed to parse. Return ONLY a raw JSON object, nothing else."
    return base


# ── JSON parsing & validation ──────────────────────────────────────────────

def _parse_llm_json(response: str) -> Optional[Dict[str, Any]]:
    if not response or not response.strip():
        return None
    cleaned = response.replace("```json", "").replace("```", "").strip()
    if "{" in cleaned and "}" in cleaned:
        cleaned = cleaned[cleaned.find("{") : cleaned.rfind("}") + 1]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _fuzzy_match_application(value: str, valid_apps: List[str]) -> Optional[str]:
    if not value:
        return None
    val_lower = value.strip().lower()
    for app in valid_apps:
        if app.lower() == val_lower:
            return app
    for app in valid_apps:
        first_word = app.split("/")[0].strip().lower()
        if first_word in val_lower or val_lower in first_word:
            return app
    return None


def _validate_output(
    parsed: Dict[str, Any],
    valid_fields: List[str],
    valid_apps: List[str],
) -> Tuple[bool, str]:
    required = ["identified_field", "domain_type", "application_area", "confidence", "reasoning"]
    missing  = [k for k in required if k not in parsed]
    if missing:
        return False, f"Missing keys: {missing}"

    field     = str(parsed["identified_field"]).strip()
    valid_map = {f.strip().lower(): f for f in valid_fields}
    if field.lower() not in valid_map:
        return False, f"Unknown field: '{field}'"
    parsed["identified_field"] = valid_map[field.lower()]

    if parsed["domain_type"] not in VALID_DOMAIN_TYPES:
        return False, f"Invalid domain_type: '{parsed['domain_type']}'"

    if parsed["domain_type"] == "Technical":
        # Canonical: Technical work has no external application ribbon — never store "" here
        parsed["application_area"] = None
    elif parsed["domain_type"] == "Cross-domain":
        raw_app = parsed.get("application_area")
        if not raw_app:
            return False, "application_area required for Cross-domain but is null"
        matched = _fuzzy_match_application(str(raw_app), valid_apps)
        if not matched:
            return False, f"Unknown application_area: '{raw_app}'"
        parsed["application_area"] = matched

    try:
        conf = float(parsed["confidence"])
    except (TypeError, ValueError):
        return False, "confidence must be a float"
    if not 0.0 <= conf <= 1.0:
        return False, f"confidence out of range: {conf}"
    parsed["confidence"] = round(conf, 4)
    return True, ""


# ── Main public function ───────────────────────────────────────────────────

def analyze_research_field(keywords: List[str], query: str) -> Dict[str, Any]:
    """
    Full pipeline:
      1. FAISS semantic search  → cosine scores per publisher
      2. Groq LLM classification → field, domain, classification confidence (internal scoring only), reasoning
      3. Rule-based scoring     → combines all 3 signals
      4. Build recommendation   → best publisher + journal link + reasoning
    """
    # ── Step 1: FAISS search (run before LLM — fast, local) ───────────────
    faiss_query = f"{query} {' '.join(keywords[:10])}"
    try:
        faiss_scores = _faiss_search(faiss_query)
    except FileNotFoundError as e:
        faiss_scores = {k: 0.0 for k in PUBLISHER_PORTALS}
        print(f"[WARN] FAISS unavailable, using 0 scores: {e}", file=sys.stderr)

    # ── Step 2: LLM classification ─────────────────────────────────────────
    publisher_data = load_publisher_mapping()
    field_mapping  = publisher_data.get("field_to_publishers_mapping", {})
    valid_fields   = list(field_mapping.keys())
    valid_apps     = VALID_APPLICATION_AREAS
    system_prompt  = _get_system_prompt(valid_fields, valid_apps)

    last_error = "Unknown error"

    for attempt in range(1, MAX_RETRIES + 1):
        user_prompt = _get_user_prompt(query, keywords, attempt)

        raw = call_gpt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=512,
            temperature=0.2,
        )

        parsed = _parse_llm_json(raw)
        if not parsed:
            last_error = f"Attempt {attempt}: Could not parse JSON from LLM"
            continue

        is_valid, err = _validate_output(parsed, valid_fields, valid_apps)
        if not is_valid:
            last_error = f"Attempt {attempt}: Validation failed - {err}"
            continue

        # ── Step 3: Rule-based scoring (all 3 signals combined) ────────────
        reasoning = " ".join(str(parsed.get("reasoning", "")).split()[:25])

        scores = _score_publishers(
            field            = parsed["identified_field"],
            domain_type      = parsed["domain_type"],
            application_area = parsed["application_area"],
            confidence       = parsed["confidence"],
            field_mapping    = field_mapping,
            faiss_scores     = faiss_scores,
        )

        # ── Step 4: Build recommendation ───────────────────────────────────
        recommendation = _build_recommendation(
            scores           = scores,
            field            = parsed["identified_field"],
            domain_type      = parsed["domain_type"],
            application_area = parsed["application_area"],
            llm_reasoning    = reasoning,
            keywords         = keywords,
            field_mapping    = field_mapping,
        )
        mentor_response = _build_mentor_recommendation_text(
            user_query=query,
            identified_field=parsed["identified_field"],
            domain_type=parsed["domain_type"],
            application_area=parsed["application_area"],
            recommendation=recommendation,
        )

        return {
            "identified_field":         parsed["identified_field"],
            "domain_type":              parsed["domain_type"],
            "application_area":         parsed["application_area"],
            "publisher_recommendation": recommendation,
            "chatbot_response":         mentor_response,
            "success":                  True,
            "error":                    None,
        }

    return {
        "identified_field":         None,
        "domain_type":              None,
        "application_area":         None,
        "faiss_publisher_scores":   faiss_scores,
        "publisher_recommendation": None,
        "success":                  False,
        "error":                    last_error,
    }


# ── CLI ────────────────────────────────────────────────────────────────────

def _read_and_clean_json_input(raw: str) -> Dict[str, Any]:
    raw = raw.strip().lstrip("\ufeff")
    raw = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", raw)
    if "{" in raw and "}" in raw:
        raw = raw[raw.find("{") : raw.rfind("}") + 1]
    return json.loads(raw)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLM Field Analyzer + FAISS + Publisher Recommender")
    parser.add_argument("--file", "-f", type=str, default=None,
                        help="Path to JSON file containing {query, keywords}")
    args = parser.parse_args()

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(json.dumps({"success": False, "error": f"File not found: {args.file}"}, indent=2))
            sys.exit(1)
        raw = file_path.read_text(encoding="utf-8")
    else:
        print('Paste your JSON {"query": "...", "keywords": [...]}:\n')
        lines   = []
        depth   = 0
        started = False
        while True:
            try:
                line = input()
            except EOFError:
                break
            lines.append(line)
            depth += line.count('{') - line.count('}')
            if '{' in line:
                started = True
            if started and depth <= 0:
                break
        raw = "\n".join(lines)

    try:
        data = _read_and_clean_json_input(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"success": False, "error": f"Invalid JSON input: {e}"}, indent=2))
        sys.exit(1)

    result = analyze_research_field(
        keywords=data.get("keywords", []),
        query=data.get("query", ""),
    )
    print(json.dumps(result, indent=2))