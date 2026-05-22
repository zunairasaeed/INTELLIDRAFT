# -*- coding: utf-8 -*-
"""
Journal Research Module
=======================
Fully free APIs. Accurate quartiles. Honest metrics.

APIs used:
  - OpenAlex       -> journal search, citation scores, OA status, APC fees
  - Scimago        -> quartiles and SJR from bundled CSV (live JSON endpoint is HTML)
  - DOAJ           -> verified APC fees for open access journals

NO paid keys required.
"""

from __future__ import annotations

import copy
import csv
import difflib
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths & env
# ---------------------------------------------------------------------------
_MODULE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=False)

OPENALEX_BASE = os.getenv(
    "JOURNAL_RESEARCH_OPENALEX_BASE_URL", "https://api.openalex.org"
).rstrip("/")
DOAJ_SEARCH_BASE = os.getenv(
    "JOURNAL_RESEARCH_DOAJ_SEARCH_JOURNALS_BASE_URL",
    "https://doaj.org/api/v2/search/journals",
).rstrip("/")

_SCIMAGO_CSV_REL = os.getenv(
    "JOURNAL_RESEARCH_SCIMAGO_CSV_PATH",
    "database/Journel_recommendations/scimagojr.csv",
)
_SCIMAGO_CSV_PATH = (
    Path(_SCIMAGO_CSV_REL)
    if Path(_SCIMAGO_CSV_REL).is_absolute()
    else _PROJECT_ROOT / _SCIMAGO_CSV_REL
)

_CACHE_TTL = int(os.getenv("JOURNAL_RESEARCH_CACHE_TTL_SECONDS", "3600"))
_MAX_HTTP_RETRIES = int(os.getenv("JOURNAL_RESEARCH_HTTP_MAX_RETRIES", "5"))
_HTTP_BACKOFF_BASE = float(os.getenv("JOURNAL_RESEARCH_HTTP_BACKOFF_BASE", "0.5"))

HEADERS = {"User-Agent": "JournalResearchModule/1.1 (research tool)"}

_SMART_QUOTE_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2039": "'",
        "\u203a": "'",
    }
)


def sanitize_journal_query(text: str) -> str:
    """
    Normalize punctuation and typography before intent / topic / retrieval logic.
    Does **not** remove fee or OA phrases (those are handled in semantic constraint extraction).
    """
    if not text:
        return ""
    s = text.strip().translate(_SMART_QUOTE_TRANSLATION)
    s = re.sub(r"[\u200b-\u200d\ufeff]", "", s)
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    s = re.sub(r"[^\w\s\-'.,/&]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Phrases stripped only from the **topic / search-term** working string (not used for constraint detection).
_SEARCH_META_NOISE_PHRASES: Tuple[str, ...] = (
    "directory of open access journals",
    "according to the doaj",
    "according to doaj",
    "as listed in doaj",
    "listed in the doaj",
    "listed in doaj",
    "registered with doaj",
    "registered in doaj",
    "indexed in doaj",
    "from the doaj",
    "from doaj",
    "via doaj",
    "on doaj",
    "in the doaj",
    "in doaj",
    "check the doaj",
    "check doaj",
    "see doaj",
    "doaj database",
    "doaj listing",
    "doaj record",
    "doaj website",
    "the doaj",
    "information on apcs",
    "information on apc",
    "apc information",
    "fee information",
    "pricing information",
)


def _strip_search_meta_noise(qlow: str) -> str:
    """Remove API / catalogue meta wording so it never becomes OpenAlex ``search`` tokens."""
    work = qlow
    for phrase in sorted(_SEARCH_META_NOISE_PHRASES, key=len, reverse=True):
        if phrase in work:
            work = work.replace(phrase, " ")
    work = re.sub(r"(?i)\bdoaj\b", " ", work)
    return re.sub(r"\s+", " ", work).strip()


# TTL caches: key -> (expires_monotonic, value)
_openalex_cache: Dict[Tuple[str, int, bool], Tuple[float, List[Dict[str, Any]]]] = {}
_scimago_lookup_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------
def classify_intent(query: str) -> str:
    """
    Classify what the researcher is asking for.

    **Structure (first match wins — order matters):**

    1. **compare** — Substrings: ``compare``, `` vs ``, ``vs.``, ``versus``,
       ``difference between``. Splits the query for dual OpenAlex searches
       (see ``_split_compare_query``).
    2. **oa_journals** — Phrases like ``open access``, ``oa `` (word-ish),
       ``free to publish``, ``free to read``. Checked **before** fee-related
       intents so queries such as “open access journals with low fees” map
       here, not ``fee_search``.
    3. **fee_search** — ``fee``, ``cost``, ``apc``, ``charge``, ``pay``, ``price``.
    4. **quartile_list** — ``quartile``, ``q1``–``q4``, ``ranking``, ``rank``.
    5. **journal_detail** — ``impact``, ``cite``, ``score``, ``metric``, ``sjr``,
       ``h-index``, ``h index``.
    6. **top_journals** — ``top``, ``best``, ``leading``, ``list``, ``show me``, ``find``.
    7. **Default** — ``top_journals`` if nothing matched.

    Returns one of:
    ``compare`` | ``oa_journals`` | ``fee_search`` | ``quartile_list`` |
    ``journal_detail`` | ``top_journals``
    """
    q = query.lower()

    if any(w in q for w in ("compare", " vs ", "vs.", "versus", "difference between")):
        return "compare"
    # Open-access intent before fee intent ("open access ... low fees")
    if any(
        w in q
        for w in (
            "open access",
            " open access",
            "oa ",
            " oa ",
            "free to publish",
            "free to read",
        )
    ):
        return "oa_journals"
    if any(w in q for w in ("fee", "cost", "apc", "charge", "pay", "price")):
        return "fee_search"
    if any(w in q for w in ("quartile", "q1", "q2", "q3", "q4", "ranking", "rank")):
        return "quartile_list"
    if any(w in q for w in ("impact", "cite", "score", "metric", "sjr", "h-index", "h index")):
        return "journal_detail"
    if any(w in q for w in ("top", "best", "leading", "list", "show me", "find")):
        return "top_journals"

    return "top_journals"


def _split_compare_query(query: str) -> List[str]:
    """Split a compare-style query into two subject strings for OpenAlex search."""
    q = query.strip()
    low = q.lower()

    if "difference between" in low:
        inner = re.sub(r"(?i)difference\s+between\s+", "", q).strip()
        if re.search(r"\band\b", inner, flags=re.I):
            left, right = re.split(r"\s+and\s+", inner, maxsplit=1, flags=re.I)
            return [left.strip(), right.strip()]
    q2 = re.sub(r"(?i)\bcompare\b", "", q).strip()
    q2 = re.sub(r"(?i)\bversus\b", "|", q2)
    q2 = re.sub(r"(?i)\bvs\.?\b", "|", q2)
    if "|" in q2:
        return [p.strip() for p in q2.split("|") if p.strip()]
    if re.search(r"\s+and\s+", q2, flags=re.I):
        left, right = re.split(r"\s+and\s+", q2, maxsplit=1, flags=re.I)
        return [left.strip(), right.strip()]
    return [q2] if q2 else []


def extract_domain(query: str, intent: Optional[str] = None) -> str:
    """Pull the research domain/field from the query."""
    query = sanitize_journal_query(query or "")
    if intent == "compare":
        parts = _split_compare_query(query)
        cleaned = [_strip_compare_noise(p) for p in parts[:2] if p.strip()]
        if cleaned:
            return " | ".join(cleaned)
    stopwords = {
        "what",
        "are",
        "the",
        "top",
        "best",
        "journals",
        "journal",
        "in",
        "for",
        "show",
        "me",
        "list",
        "find",
        "give",
        "with",
        "that",
        "have",
        "a",
        "high",
        "impact",
        "factor",
        "score",
        "open",
        "access",
        "fee",
        "cost",
        "quartile",
        "q1",
        "q2",
        "q3",
        "q4",
        "rank",
        "ranked",
        "good",
        "reputable",
        "about",
        "related",
        "to",
        "on",
        "of",
        "is",
        "my",
        "field",
        "domain",
        "area",
        "compare",
        "versus",
        "difference",
        "between",
        "and",
        "vs",
    }
    words = query.lower().split()
    domain_words = [w for w in words if w not in stopwords and len(w) > 2]
    return " ".join(domain_words) if domain_words else query


def _strip_compare_noise(s: str) -> str:
    s = re.sub(r"(?i)\bjournals?\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Semantic query normalization + multi-query retrieval
# ---------------------------------------------------------------------------
TOPIC_PHRASE_MAP: Dict[str, List[str]] = {
    "deep learning": ["deep learning", "machine learning", "neural networks", "artificial intelligence"],
    "machine learning": ["machine learning", "statistical learning", "predictive modeling"],
    "natural language processing": ["natural language processing", "computational linguistics", "text mining"],
    "neural networks": ["neural networks", "deep learning", "machine learning"],
    "computer vision": ["computer vision", "image processing", "pattern recognition"],
    "bioinformatics": ["bioinformatics", "computational biology", "genomics"],
    "reinforcement learning": ["reinforcement learning", "machine learning", "decision making"],
    "data mining": ["data mining", "knowledge discovery", "machine learning"],
    "robotics": ["robotics", "automation", "control systems"],
    "human computer interaction": ["human computer interaction", "HCI", "usability"],
}

TOKEN_SYNONYMS: Dict[str, List[str]] = {
    "nlp": ["natural language processing", "text mining", "computational linguistics"],
    "cv": ["computer vision", "image understanding"],
    "ml": ["machine learning", "statistical learning"],
    "ai": ["artificial intelligence", "machine learning"],
    "hci": ["human computer interaction", "usability"],
}

_APC_LOW = frozenset(
    {"low", "cheap", "affordable", "lower", "minimal", "free", "zero", "no fee", "without fee", "no charge"}
)
_APC_HIGH = frozenset({"high", "expensive", "costly", "premium"})


def _detect_quartile_constraint(qlow: str) -> Optional[str]:
    for q in ("Q1", "Q2", "Q3", "Q4"):
        if q.lower() in qlow:
            return q
    return None


def _detect_apc_constraint(qlow: str) -> Optional[str]:
    if "low apc" in qlow or "lower apc" in qlow:
        return "low"
    if "high apc" in qlow:
        return "high"
    if any(w in qlow for w in (" no apc", "no apc", "zero apc", "free apc", "no publication fee", "no fee")):
        return "low"
    if any(w in qlow for w in ("affordable", "cheap", "inexpensive", "low cost", "low-cost")):
        return "low"
    if "apc" in qlow or "article processing" in qlow or "publication fee" in qlow or "fee" in qlow or "fees" in qlow:
        toks = set(re.findall(r"[a-z0-9]+", qlow))
        if toks & _APC_LOW:
            return "low"
        if toks & _APC_HIGH:
            return "high"
    return None


def _detect_open_access_constraint(qlow: str) -> Optional[bool]:
    if any(
        x in qlow
        for x in (
            "open access",
            "open-access",
            " oa ",
            "oa journal",
            "free to read",
            "free to publish",
        )
    ):
        return True
    if "subscription" in qlow and "open" not in qlow:
        return False
    return None


# Phrases removed from OpenAlex search strings (mapped to constraints instead).
_COST_AND_FEE_PHRASES: Tuple[str, ...] = (
    "article processing charge",
    "processing charge",
    "publication fee",
    "publication fees",
    "low apc",
    "high apc",
    "lower apc",
    "no publication fee",
    "no fee",
    "no fees",
    "no charge",
    "zero fee",
    "zero fees",
    "zero apc",
    "free to publish",
    "free to read",
    "low cost",
    "low-cost",
    "affordable",
    "inexpensive",
    "cheap",
)


def _phrase_hits_in_query(qlow: str) -> List[str]:
    """Multi-word topic phrases from TOPIC_PHRASE_MAP found in ``qlow`` (lowercased query)."""
    work = qlow
    hits: List[str] = []
    for phrase in sorted(TOPIC_PHRASE_MAP.keys(), key=len, reverse=True):
        if phrase in work:
            hits.append(phrase)
            work = work.replace(phrase, " ", 1)
    return hits


def extract_semantic_constraints(query: str) -> Dict[str, Any]:
    """
    Lightweight semantic split: topic-ish search terms vs cost/OA constraints.
    Cost language is **never** propagated into ``search_terms`` (OpenAlex/DOAJ filter later).
    """
    raw = (query or "").strip()
    qwork = raw.lower()
    ignore_terms: List[str] = []

    for phrase in sorted(_COST_AND_FEE_PHRASES, key=len, reverse=True):
        if phrase in qwork:
            ignore_terms.append(phrase)
            qwork = qwork.replace(phrase, " ")

    for tok in ("apc", "fee", "fees", "pricing", "price", "cost", "costs", "charge", "charges", "pay", "paid"):
        if re.search(rf"(?<![a-z]){re.escape(tok)}(?![a-z])", qwork):
            if tok not in ignore_terms:
                ignore_terms.append(tok)
            qwork = re.sub(rf"(?<![a-z]){re.escape(tok)}(?![a-z])", " ", qwork)

    qwork = re.sub(r"\s+", " ", qwork).strip()
    qwork = _strip_search_meta_noise(qwork)
    orig_low = raw.lower()

    constraints: Dict[str, Any] = {
        "open_access": _detect_open_access_constraint(orig_low),
        "apc": _detect_apc_constraint(orig_low),
    }
    if constraints["apc"] is None and constraints["open_access"] is True and any(
        w in orig_low for w in ("free", "no fee", "zero", "without fee", "no charge")
    ):
        constraints["apc"] = "low"

    topics = _phrase_hits_in_query(qwork)
    topics.extend(t for t in _token_topic_hits(qwork) if t not in topics)
    if not topics:
        topics = _residual_topic_gloss(qwork)

    ignore_set = {x.lower() for x in ignore_terms} | _APC_LOW | _APC_HIGH | {
        "fee",
        "fees",
        "apc",
        "cost",
        "costs",
        "pricing",
        "price",
        "journal",
        "journals",
    }
    search_terms: List[str] = []
    for t in topics:
        tl = t.lower()
        if tl in ignore_set or len(tl) < 2:
            continue
        if tl not in [x.lower() for x in search_terms]:
            search_terms.append(t.strip())
    if not search_terms:
        search_terms = [x for x in _residual_topic_gloss(qwork) if x.lower() not in ignore_set][:6]

    topics_out = [t for t in topics if t.lower() not in ignore_set and len(t) > 1][:8]

    return {
        "topics": topics_out or search_terms[:4],
        "constraints": constraints,
        "search_terms": search_terms or topics_out or ["research"],
        "ignore_terms": list(dict.fromkeys(ignore_terms)),
    }


def _token_topic_hits(qlow: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", qlow)
    out: List[str] = []
    for w in words:
        if w in TOKEN_SYNONYMS:
            out.append(w)
            continue
        if len(w) <= 2:
            continue
    return list(dict.fromkeys(out))


def _residual_topic_gloss(qlow: str) -> List[str]:
    """Loose topic tokens after stripping boilerplate (not used as sole OpenAlex string)."""
    stop = {
        "journal",
        "journals",
        "list",
        "show",
        "find",
        "top",
        "best",
        "good",
        "leading",
        "give",
        "what",
        "are",
        "the",
        "for",
        "with",
        "about",
        "some",
        "any",
        "which",
        "where",
        "when",
        "how",
        "fee",
        "fees",
        "apc",
        "cost",
        "low",
        "high",
        "open",
        "access",
        "quartile",
        "ranking",
        "rank",
        "q1",
        "q2",
        "q3",
        "q4",
        "compare",
        "versus",
        "between",
        "and",
        "vs",
    }
    keys2 = frozenset(TOKEN_SYNONYMS.keys())
    toks = [
        t
        for t in re.findall(r"[a-z0-9]+", qlow)
        if t not in stop and (len(t) > 2 or t in keys2)
    ]
    return list(dict.fromkeys(toks))[:6]


def normalize_query(query: str) -> Dict[str, Any]:
    """
    Semantic decomposition: topics, constraints, expansion terms, strategy.
    Never pass raw cost language to OpenAlex — use ``search_terms`` + ``build_openalex_queries``.
    """
    raw_input = (query or "").strip()
    raw = sanitize_journal_query(raw_input)
    intent = classify_intent(raw)
    sem = extract_semantic_constraints(raw)

    topics: List[str] = []
    if intent == "compare":
        topics = [_strip_compare_noise(p) for p in _split_compare_query(raw)[:2] if p.strip()]
    else:
        topics = list(sem.get("topics") or [])
        if not topics:
            topics = list(sem.get("search_terms") or [])[:8]

    expansion_terms: List[str] = []
    for t in topics:
        tl = t.lower()
        if tl in TOPIC_PHRASE_MAP:
            expansion_terms.extend(TOPIC_PHRASE_MAP[tl])
        if tl in TOKEN_SYNONYMS:
            expansion_terms.extend(TOKEN_SYNONYMS[tl])
    expansion_terms.extend(sem.get("search_terms") or [])
    expansion_terms.extend(topics)
    expansion_terms = [x for x in expansion_terms if isinstance(x, str) and x.strip()]
    expansion_terms = list(dict.fromkeys(expansion_terms))

    cons = dict(sem.get("constraints") or {})
    cons["quartile"] = _detect_quartile_constraint(raw.lower())

    if len(raw) < 28 and len(topics) <= 2 and topics:
        search_strategy = "strict"
    elif len(raw) > 90 or len(topics) == 0:
        search_strategy = "broad"
    else:
        search_strategy = "balanced"

    journal_name: Optional[str] = None
    m = re.search(r"(?i)journal\s+of\s+the\s+(.{3,80})", raw)
    if m:
        journal_name = m.group(1).strip().strip(".,;")
    m2 = re.search(r"(?i)journal\s+named\s+['\"]?([^'\"]{3,80})['\"]?", raw)
    if m2:
        journal_name = m2.group(1).strip()

    qclean = raw.lower()
    field_terms = [t for t in _residual_topic_gloss(qclean) if t not in (x.lower() for x in topics)]

    return {
        "raw_query": raw_input,
        "sanitized_query": raw,
        "intent": intent,
        "topics": topics,
        "entities": {"journal_name": journal_name, "field": field_terms},
        "constraints": cons,
        "expansion_terms": expansion_terms,
        "search_strategy": search_strategy,
        "semantic": sem,
        "search_terms": list(sem.get("search_terms") or topics),
    }


def build_openalex_queries(normalized: Dict[str, Any]) -> List[str]:
    """
    Build 1–5 OpenAlex ``search`` strings using **topic / field language only**.
    Never inject cost / APC / “affordable” wording (constraints apply after retrieval).
    """
    strat = normalized.get("search_strategy") or "balanced"
    if strat not in ("strict", "balanced", "broad"):
        strat = "balanced"
    n_map = {"strict": 2, "balanced": 3, "broad": 5}
    n = n_map[strat]

    base_terms: List[str] = []
    for t in (normalized.get("search_terms") or []):
        if isinstance(t, str) and t.strip():
            tl = t.strip()
            if tl.lower() not in [x.lower() for x in base_terms]:
                base_terms.append(tl)
    if not base_terms:
        for t in (normalized.get("topics") or []):
            if isinstance(t, str) and t.strip():
                tl = t.strip()
                if tl.lower() not in [x.lower() for x in base_terms]:
                    base_terms.append(tl)
    for t in (normalized.get("expansion_terms") or []):
        if isinstance(t, str) and t.strip():
            tl = t.strip()
            if tl.lower() not in [x.lower() for x in base_terms]:
                base_terms.append(tl)
    if not base_terms:
        base_terms = ["research"]

    primary = base_terms[0]
    secondary = base_terms[1] if len(base_terms) > 1 else primary
    tertiary = base_terms[2] if len(base_terms) > 2 else secondary

    queries: List[str] = []
    # OA / APC / fees are **never** part of the OpenAlex ``search`` string; they are post-filters.
    queries.append(f"{primary} journal")
    queries.append(f"{secondary} research journal")
    queries.append(f"{tertiary} academic journal")
    if strat == "broad":
        queries.append(f"{primary} science journal")
        queries.append(f"{secondary} international journal")

    out: List[str] = []
    for q in queries:
        q = re.sub(r"\s+", " ", q.strip())
        if q and q.lower() not in [x.lower() for x in out]:
            out.append(q)
    pad_i = 0
    while len(out) < n and base_terms:
        bt = base_terms[pad_i % len(base_terms)]
        cand = re.sub(r"\s+", " ", f"{bt} academic journal".strip())
        pad_i += 1
        if cand.lower() not in [x.lower() for x in out]:
            out.append(cand)
    return out[:n]


def _dedupe_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        j = ent.get("journal") if isinstance(ent.get("journal"), dict) else {}
        key = _as_opt_str(j.get("openalex_id")) or _norm_title(_as_opt_str(j.get("name")) or "")
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(ent)
    return out


def retrieve_journals(
    normalized: Dict[str, Any],
    queries: List[str],
    *,
    per_call_limit: int = 8,
    oa_only: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Multi-query OpenAlex retrieval with strategy escalation when empty.
    DOAJ + Scimago enrichment happen later via ``_enrich_parallel`` / ``enrich_journal_entity``.
    """
    meta: Dict[str, Any] = {
        "fallback_used": False,
        "reason": None,
        "expanded_terms_used": [],
        "suggestion": None,
        "queries_tried": [],
    }

    def collect(qs: List[str], *, oa_flag: bool) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        for q in qs:
            if not isinstance(q, str) or not q.strip():
                continue
            q = q.strip()
            if q not in meta["queries_tried"]:
                meta["queries_tried"].append(q)
            merged.extend(search_openalex(q, limit=per_call_limit, oa_only=oa_flag))
        return _dedupe_entities(merged)

    entities = collect(queries, oa_flag=oa_only)
    initial_strat = normalized.get("search_strategy") or "balanced"
    order = ["strict", "balanced", "broad"]
    try:
        start_idx = order.index(initial_strat)
    except ValueError:
        start_idx = 1

    if not entities:
        for strat in order[start_idx + 1 :]:
            n2 = copy.deepcopy(normalized)
            n2["search_strategy"] = strat
            q2 = build_openalex_queries(n2)
            meta["expanded_terms_used"] = list(dict.fromkeys(n2.get("expansion_terms") or []))
            entities = collect(q2, oa_flag=oa_only)
            if entities:
                meta["fallback_used"] = True
                meta["reason"] = (
                    f"OpenAlex returned no hits for {initial_strat} queries; "
                    f"retried with '{strat}' semantic expansion ({len(q2)} queries)."
                )
                break

    if not entities and oa_only:
        entities = collect(queries, oa_flag=False)
        if entities:
            meta["fallback_used"] = True
            meta["openalex_oa_api_filter_relaxed"] = True
            prev = meta.get("reason")
            meta["reason"] = " ".join(
                x
                for x in (
                    prev,
                    "OpenAlex is_oa filter was relaxed for one retry to recover candidates; "
                    "OA is still enforced in post-retrieval filtering when requested.",
                )
                if x
            ).strip()

    if not entities:
        n3 = copy.deepcopy(normalized)
        n3["search_strategy"] = "broad"
        ex = [x for x in (n3.get("expansion_terms") or []) if isinstance(x, str) and x.strip()]
        if ex:
            n3["search_terms"] = ex[:8]
            q3 = build_openalex_queries(n3)
            entities = collect(q3, oa_flag=False)
            if entities:
                meta["fallback_used"] = True
                tail = "Retried using semantic expansion terms only as OpenAlex search drivers."
                meta["reason"] = " ".join(x for x in (meta.get("reason"), tail) if x).strip()

    if not entities:
        meta["fallback_used"] = True
        meta["reason"] = (
            "OpenAlex returned no journal matches after query broadening and optional OA filter relaxation."
        )
        meta["expanded_terms_used"] = list(dict.fromkeys(normalized.get("expansion_terms") or []))
        meta["suggestion"] = (
            "Use broader subject keywords, spell out acronyms, or temporarily relax OA or APC filters."
        )

    return entities, meta


def score_query_match(result: Dict[str, Any], normalized: Dict[str, Any]) -> float:
    """Heuristic relevance: topic overlap, OA/APC constraint agreement, name signal."""
    score = 0.0
    topics = [t.lower() for t in (normalized.get("topics") or []) if isinstance(t, str)]
    exp = [t.lower() for t in (normalized.get("expansion_terms") or []) if isinstance(t, str)]
    blob = " ".join(topics + exp)

    name = (result.get("name") or "").lower()
    subs = " ".join(result.get("subject_areas") or []).lower()
    hay = f"{name} {subs}"

    for term in set(re.findall(r"[a-z]{3,}", blob)):
        if term in hay:
            score += 0.09

    cons = normalized.get("constraints") or {}
    want_oa = cons.get("open_access")
    got_oa = result.get("is_oa")
    if want_oa is True and got_oa is True:
        score += 0.22
    elif want_oa is False and got_oa is False:
        score += 0.12

    apc_w = cons.get("apc")
    dj_amt = result.get("doaj_apc_amount")
    if apc_w == "low":
        if result.get("doaj_verified") and dj_amt is not None and float(dj_amt) <= 3500:
            score += 0.22
        elif result.get("doaj_verified") and dj_amt is None:
            score += 0.08
    elif apc_w == "high" and dj_amt is not None and float(dj_amt) >= 2000:
        score += 0.15

    qwant = cons.get("quartile")
    if qwant and result.get("best_quartile") == qwant:
        score += 0.2

    return round(min(1.0, score), 4)


DOAJ_LOW_APC_USD = 3500.0


def apply_constraints(
    results: List[Dict[str, Any]], constraints: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Post-retrieval OA / APC gating. **APC thresholds use DOAJ amounts only** (not OpenAlex USD).
    """
    meta: Dict[str, Any] = {"dropped_oa": 0, "dropped_apc": 0, "kept": 0}
    oa_c = constraints.get("open_access")
    apc_c = constraints.get("apc")

    if oa_c is None and not apc_c:
        return list(results), meta

    out: List[Dict[str, Any]] = []
    for row in results:
        if oa_c is True and row.get("is_oa") is not True:
            meta["dropped_oa"] += 1
            continue
        if oa_c is False and row.get("is_oa") is True:
            meta["dropped_oa"] += 1
            continue

        if apc_c == "low":
            if row.get("doaj_verified") is True and row.get("doaj_apc_amount") is not None:
                try:
                    if float(row["doaj_apc_amount"]) > DOAJ_LOW_APC_USD:
                        meta["dropped_apc"] += 1
                        continue
                except (TypeError, ValueError):
                    meta["dropped_apc"] += 1
                    continue
            elif row.get("doaj_verified") is True and row.get("doaj_apc_amount") is None:
                pass
            else:
                meta["dropped_apc"] += 1
                continue

        if apc_c == "high":
            dj = row.get("doaj_apc_amount")
            if row.get("doaj_verified") is True and dj is not None:
                try:
                    if float(dj) < 1500:
                        meta["dropped_apc"] += 1
                        continue
                except (TypeError, ValueError):
                    pass
        out.append(row)
    meta["kept"] = len(out)
    return out, meta


def _enrich_filter_maybe_relax(
    normalized: Dict[str, Any],
    journals: List[Dict[str, Any]],
    *,
    include_doaj: bool,
    max_results: int = 8,
    pool: int = 16,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Enrich (with DOAJ when APC must be judged), apply constraints, relax APC if empty."""
    aux: Dict[str, Any] = {}
    if not journals:
        return [], aux
    cons = dict(normalized.get("constraints") or {})
    need_doaj_for_apc = bool(cons.get("apc"))
    enrich_doaj = bool(include_doaj) or need_doaj_for_apc

    enriched = _enrich_parallel(journals[:pool], include_doaj=enrich_doaj)
    active = cons.get("open_access") is not None or bool(cons.get("apc"))
    if not active:
        for row in enriched:
            row["retrieval_relevance_score"] = score_query_match(row, normalized)
        enriched.sort(key=lambda x: -float(x.get("retrieval_relevance_score") or 0.0))
        return enriched[:max_results], aux

    filtered, fmeta = apply_constraints(enriched, cons)
    aux["constraint_filter"] = fmeta
    if filtered:
        for row in filtered:
            row["retrieval_relevance_score"] = score_query_match(row, normalized)
        filtered.sort(key=lambda x: -float(x.get("retrieval_relevance_score") or 0.0))
        return filtered[:max_results], aux

    cons_relaxed = dict(cons)
    cons_relaxed["apc"] = None
    filtered2, _ = apply_constraints(enriched, cons_relaxed)
    aux["fallback_used"] = True
    aux["relaxed_query_used"] = True
    aux["reason"] = (
        "Strict DOAJ-backed APC filtering removed all candidates; "
        "relaxed APC constraint while keeping other filters where possible."
    )
    aux["suggestion"] = (
        "Try spelling out your field, widening the subject, or checking fees on the journal homepage."
    )
    rows = filtered2
    if not rows and cons.get("open_access") is True:
        cons3 = dict(cons_relaxed)
        cons3["open_access"] = None
        rows, _ = apply_constraints(enriched, cons3)
        aux["reason"] += " OA filter also relaxed because no rows remained."
    if not rows:
        rows = enriched
        aux["reason"] = "No rows after constraints; returning unfiltered enrichment pool."

    for row in rows:
        row["retrieval_relevance_score"] = score_query_match(row, normalized)
    rows.sort(key=lambda x: -float(x.get("retrieval_relevance_score") or 0.0))
    return rows[:max_results], aux


def _quartile_search_blob(normalized: Dict[str, Any]) -> str:
    parts = list(normalized.get("search_terms") or normalized.get("topics") or [])
    parts.extend((normalized.get("expansion_terms") or [])[:12])
    return " ".join(p for p in parts if isinstance(p, str) and p.strip()).strip() or normalized.get(
        "raw_query", ""
    )


# ---------------------------------------------------------------------------
# Canonical journal schema + coercion (fault-tolerant fusion)
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "1.0"

_QUALITY_TRACKED_LEAVES: Tuple[str, ...] = (
    "journal.name",
    "journal.issn",
    "journal.homepage",
    "journal.openalex_id",
    "metrics.sjr_score",
    "metrics.h_index",
    "metrics.h_index_scimago",
    "metrics.citation_score_2yr",
    "metrics.total_citations",
    "open_access.is_oa",
    "open_access.doaj_verified",
    "open_access.apc.amount",
    "open_access.apc.currency",
    "open_access.apc.openalex_usd",
    "classification.quartile",
    "classification.publisher",
    "classification.country",
)


def _as_opt_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        return s or None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return str(val)
    if isinstance(val, dict):
        return None
    if isinstance(val, list):
        return None
    s = str(val).strip()
    return s or None


def _as_opt_bool(val: Any) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return bool(val)
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no", ""):
            return False
    return None


def _as_opt_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        t = val.strip().replace(",", ".")
        if not t:
            return None
        try:
            return float(t)
        except ValueError:
            return None
    return None


def _as_opt_int(val: Any) -> Optional[int]:
    f = _as_opt_float(val)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError):
        return None


def _as_dict(val: Any) -> Dict[str, Any]:
    return val if isinstance(val, dict) else {}


def _as_list(val: Any) -> List[Any]:
    return val if isinstance(val, list) else []


def _safe_subject_list(val: Any, limit: int = 12) -> List[str]:
    out: List[str] = []
    for x in _as_list(val)[:limit]:
        s = _as_opt_str(x)
        if s:
            out.append(s)
    return out


def empty_journal_entity() -> Dict[str, Any]:
    """Canonical nested structure returned for every journal row."""
    return {
        "schema_version": SCHEMA_VERSION,
        "journal": {
            "name": None,
            "issn": None,
            "homepage": None,
            "openalex_id": None,
        },
        "metrics": {
            "sjr_score": None,
            "h_index": None,
            "h_index_scimago": None,
            "citation_score_2yr": None,
            "total_citations": None,
            "works_count": None,
            "i10_index": None,
            "scimago_rank": None,
        },
        "open_access": {
            "is_oa": None,
            "doaj_verified": None,
            "apc": {"amount": None, "currency": None, "openalex_usd": None},
            "doaj_license": None,
            "review_process": [],
            "doaj_url": None,
        },
        "classification": {
            "subject_areas": [],
            "quartile": None,
            "all_quartiles": [],
            "country": None,
            "publisher": None,
        },
        "provenance": {
            "scimago_match": None,
            "scimago_note": None,
            "quartile_note": None,
            "doaj_error": None,
            "search_context": None,
            "source_disagreements": [],
        },
        "source_map": {"openalex": None, "scimago": None, "doaj": None},
        "quality": {
            "completeness_score": 0.0,
            "confidence_score": 0.0,
            "missing_fields": [],
        },
    }


def _get_leaf(entity: Dict[str, Any], path: str) -> Any:
    cur: Any = entity
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_leaf(entity: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = entity
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def compute_quality_scores(entity: Dict[str, Any]) -> None:
    """Fill ``quality.*`` from current entity leaves."""
    missing: List[str] = []
    filled = 0
    for path in _QUALITY_TRACKED_LEAVES:
        v = _get_leaf(entity, path)
        if v is None or v == "" or v == []:
            missing.append(path)
        else:
            filled += 1
    total = len(_QUALITY_TRACKED_LEAVES)
    entity["quality"]["completeness_score"] = round(filled / total, 4) if total else 0.0
    entity["quality"]["missing_fields"] = missing

    conf = 0.35
    if entity["source_map"].get("openalex") is not None:
        conf += 0.22
    if entity["source_map"].get("scimago") is not None:
        conf += 0.22
    if entity["source_map"].get("doaj") is not None:
        conf += 0.21

    oa_h = entity["metrics"].get("h_index")
    sg_h = entity["metrics"].get("h_index_scimago")
    if oa_h is not None and sg_h is not None and sg_h > 0:
        rel = abs(float(oa_h) - float(sg_h)) / float(sg_h)
        if rel > 0.35:
            conf *= 0.85
            entity["provenance"]["source_disagreements"].append(
                {"field": "h_index", "openalex": oa_h, "scimago": sg_h}
            )
    oa_usd = entity["open_access"]["apc"].get("openalex_usd")
    dj_amt = entity["open_access"]["apc"].get("amount")
    if (
        oa_usd is not None
        and dj_amt is not None
        and float(oa_usd) > 0
        and float(dj_amt) > 0
        and abs(float(oa_usd) - float(dj_amt)) / max(float(oa_usd), float(dj_amt)) > 0.5
    ):
        conf *= 0.9
        entity["provenance"]["source_disagreements"].append(
            {"field": "apc", "openalex_usd": oa_usd, "doaj_amount": dj_amt}
        )

    entity["quality"]["confidence_score"] = round(min(1.0, conf), 4)


def normalize_openalex_record(r: Any) -> Optional[Dict[str, Any]]:
    """
    Normalize a single OpenAlex ``sources`` hit into a compact, JSON-safe dict.
    Returns ``None`` if the record cannot be interpreted as a dict-like source.
    """
    if not isinstance(r, dict):
        return None
    stats = r.get("summary_stats")
    stats_d = stats if isinstance(stats, dict) else {}

    fee_usd = r.get("apc_usd")
    if fee_usd is None:
        prices = r.get("apc_prices")
        prices_l = prices if isinstance(prices, list) else []
        usd_entries = [p for p in prices_l if isinstance(p, dict) and p.get("currency") == "USD"]
        if usd_entries:
            fee_usd = usd_entries[0].get("price")

    raw_safe = {
        "id": _as_opt_str(r.get("id")),
        "display_name": _as_opt_str(r.get("display_name")),
        "issn_l": _as_opt_str(r.get("issn_l")),
        "is_oa": _as_opt_bool(r.get("is_oa")),
        "cited_by_count": _as_opt_int(r.get("cited_by_count")),
        "works_count": _as_opt_int(r.get("works_count")),
    }
    return {
        "normalized": {
            "display_name": raw_safe["display_name"],
            "issn_l": raw_safe["issn_l"],
            "id": raw_safe["id"],
            "is_oa": raw_safe["is_oa"],
            "homepage_url": _as_opt_str(r.get("homepage_url")),
            "cited_by_count": raw_safe["cited_by_count"],
            "works_count": raw_safe["works_count"],
            "citation_score_2yr": round(float(stats_d.get("2yr_mean_citedness") or 0.0), 3),
            "h_index": _as_opt_int(stats_d.get("h_index")),
            "i10_index": _as_opt_int(stats_d.get("i10_index")),
            "apc_usd": _as_opt_float(fee_usd) if fee_usd is not None else None,
        },
        "raw_subset": raw_safe,
    }


def entity_from_openalex_normalized(norm: Dict[str, Any]) -> Dict[str, Any]:
    """Build a canonical entity from ``normalize_openalex_record`` output."""
    entity = empty_journal_entity()
    n = norm.get("normalized")
    if not isinstance(n, dict):
        entity["provenance"]["quartile_note"] = "openalex_normalize_invalid"
        compute_quality_scores(entity)
        return entity

    name = _as_opt_str(n.get("display_name")) or "Unknown"
    entity["journal"]["name"] = name
    entity["journal"]["issn"] = _as_opt_str(n.get("issn_l"))
    entity["journal"]["homepage"] = _as_opt_str(n.get("homepage_url"))
    entity["journal"]["openalex_id"] = _as_opt_str(n.get("id"))

    entity["metrics"]["citation_score_2yr"] = _as_opt_float(n.get("citation_score_2yr"))
    entity["metrics"]["h_index"] = _as_opt_int(n.get("h_index"))
    entity["metrics"]["i10_index"] = _as_opt_int(n.get("i10_index"))
    entity["metrics"]["total_citations"] = _as_opt_int(n.get("cited_by_count"))
    entity["metrics"]["works_count"] = _as_opt_int(n.get("works_count"))

    entity["open_access"]["is_oa"] = _as_opt_bool(n.get("is_oa"))
    entity["open_access"]["apc"]["openalex_usd"] = _as_opt_float(n.get("apc_usd"))

    entity["source_map"]["openalex"] = norm.get("raw_subset")
    compute_quality_scores(entity)
    return entity


def normalize_scimago_lookup_payload(raw: Any) -> Dict[str, Any]:
    """Normalize Scimago CSV lookup payload (dict or garbage) to a fixed shape."""
    base: Dict[str, Any] = {
        "sjr_score": None,
        "best_quartile": None,
        "all_quartiles": [],
        "subject_areas": [],
        "scimago_rank": None,
        "publisher": None,
        "country": None,
        "h_index_scimago": None,
        "scimago_match": "none",
        "scimago_note": None,
    }
    if not isinstance(raw, dict):
        base["scimago_note"] = "invalid_scimago_payload_type"
        return base
    base["sjr_score"] = _as_opt_float(raw.get("sjr_score"))
    q = _as_opt_str(raw.get("best_quartile"))
    base["best_quartile"] = q if q and q.startswith("Q") else None
    aq = raw.get("all_quartiles")
    if isinstance(aq, list):
        base["all_quartiles"] = [x for x in (_as_opt_str(s) for s in aq) if x and x.startswith("Q")]
    base["subject_areas"] = _safe_subject_list(raw.get("subject_areas"))
    base["scimago_rank"] = _as_opt_int(raw.get("scimago_rank"))
    base["publisher"] = _as_opt_str(raw.get("publisher"))
    base["country"] = _as_opt_str(raw.get("country"))
    base["h_index_scimago"] = _as_opt_int(raw.get("h_index_scimago"))
    sm = _as_opt_str(raw.get("scimago_match"))
    base["scimago_match"] = sm if sm in ("exact", "issn", "fuzzy", "none") else "none"
    base["scimago_note"] = _as_opt_str(raw.get("scimago_note"))
    return base


def merge_scimago_into_entity(entity: Dict[str, Any], scimago_norm: Dict[str, Any]) -> None:
    """Scimago → metrics + classification layers (does not remove OpenAlex discovery)."""
    entity["source_map"]["scimago"] = {k: scimago_norm.get(k) for k in scimago_norm}
    entity["metrics"]["sjr_score"] = scimago_norm.get("sjr_score")
    entity["metrics"]["h_index_scimago"] = scimago_norm.get("h_index_scimago")
    entity["metrics"]["scimago_rank"] = scimago_norm.get("scimago_rank")

    entity["classification"]["quartile"] = scimago_norm.get("best_quartile")
    entity["classification"]["all_quartiles"] = list(scimago_norm.get("all_quartiles") or [])
    subs = scimago_norm.get("subject_areas")
    if isinstance(subs, list) and subs:
        merged = list(dict.fromkeys((entity["classification"]["subject_areas"] or []) + subs))
        entity["classification"]["subject_areas"] = merged

    pub = scimago_norm.get("publisher")
    if pub and not entity["classification"]["publisher"]:
        entity["classification"]["publisher"] = pub
    elif pub and entity["classification"].get("publisher") and entity["classification"]["publisher"] != pub:
        entity["provenance"]["source_disagreements"].append(
            {"field": "publisher", "openalex_classification": entity["classification"]["publisher"], "scimago": pub}
        )
        entity["classification"]["publisher"] = pub

    ctry = scimago_norm.get("country")
    if ctry and not entity["classification"]["country"]:
        entity["classification"]["country"] = ctry
    elif ctry and entity["classification"].get("country") and entity["classification"]["country"] != ctry:
        entity["provenance"]["source_disagreements"].append(
            {"field": "country", "prior": entity["classification"]["country"], "scimago": ctry}
        )

    entity["provenance"]["scimago_match"] = scimago_norm.get("scimago_match")
    if scimago_norm.get("scimago_note"):
        entity["provenance"]["scimago_note"] = scimago_norm.get("scimago_note")
    if not entity["classification"]["quartile"]:
        entity["provenance"]["quartile_note"] = scimago_norm.get("scimago_note") or (
            "Quartile unavailable: no CSV match for this title."
        )


def normalize_doaj_payload(raw: Any) -> Dict[str, Any]:
    """Normalize DOAJ client payload to a fixed shape (errors included)."""
    out: Dict[str, Any] = {
        "doaj_verified": False,
        "apc_has_charges": False,
        "apc_amount": None,
        "apc_currency": "USD",
        "submission_charges": False,
        "license": None,
        "review_process": [],
        "publisher": None,
        "doaj_url": None,
        "doaj_error": None,
    }
    if not isinstance(raw, dict):
        out["doaj_error"] = "invalid_doaj_payload_type"
        return out
    if raw.get("doaj_error"):
        out["doaj_error"] = _as_opt_str(raw.get("doaj_error")) or "doaj_error"
        return out
    out["doaj_verified"] = bool(raw.get("doaj_verified"))
    out["apc_has_charges"] = bool(raw.get("apc_has_charges"))
    out["apc_amount"] = _as_opt_float(raw.get("apc_amount"))
    cur = _as_opt_str(raw.get("apc_currency")) or "USD"
    out["apc_currency"] = cur
    out["submission_charges"] = bool(raw.get("submission_charges"))
    out["license"] = _as_opt_str(raw.get("license"))
    rp = raw.get("review_process")
    if isinstance(rp, list):
        out["review_process"] = [x for x in (_as_opt_str(s) for s in rp) if x]
    elif isinstance(rp, str):
        out["review_process"] = [rp] if rp.strip() else []
    out["publisher"] = _as_opt_str(raw.get("publisher"))
    out["doaj_url"] = _as_opt_str(raw.get("doaj_url"))
    return out


def merge_doaj_into_entity(entity: Dict[str, Any], doaj_norm: Dict[str, Any]) -> None:
    """DOAJ → open_access layer; never drops OpenAlex APC USD."""
    entity["source_map"]["doaj"] = {k: v for k, v in doaj_norm.items() if k != "doaj_error" or v}
    if doaj_norm.get("doaj_error"):
        entity["provenance"]["doaj_error"] = doaj_norm["doaj_error"]
        return

    entity["open_access"]["doaj_verified"] = bool(doaj_norm.get("doaj_verified"))
    entity["open_access"]["doaj_license"] = doaj_norm.get("license")
    entity["open_access"]["review_process"] = list(doaj_norm.get("review_process") or [])
    entity["open_access"]["doaj_url"] = doaj_norm.get("doaj_url")

    if doaj_norm.get("apc_amount") is not None:
        entity["open_access"]["apc"]["amount"] = doaj_norm.get("apc_amount")
        entity["open_access"]["apc"]["currency"] = doaj_norm.get("apc_currency") or "USD"


def entity_to_public_dict(entity: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten canonical entity for JSON clients and legacy formatters.

    Nested canonical fields are preserved; flat mirrors are derived copies.
    """
    j = entity.get("journal") if isinstance(entity.get("journal"), dict) else {}
    m = entity.get("metrics") if isinstance(entity.get("metrics"), dict) else {}
    oa = entity.get("open_access") if isinstance(entity.get("open_access"), dict) else {}
    apc = oa.get("apc") if isinstance(oa.get("apc"), dict) else {}
    cl = entity.get("classification") if isinstance(entity.get("classification"), dict) else {}
    pr = entity.get("provenance") if isinstance(entity.get("provenance"), dict) else {}
    qu = entity.get("quality") if isinstance(entity.get("quality"), dict) else {}

    name = _as_opt_str(j.get("name")) or "Unknown"
    flat: Dict[str, Any] = {
        "schema_version": entity.get("schema_version", SCHEMA_VERSION),
        "journal": j,
        "metrics": m,
        "open_access": oa,
        "classification": cl,
        "provenance": pr,
        "source_map": entity.get("source_map"),
        "quality": qu,
        "name": name,
        "issn": j.get("issn"),
        "homepage": j.get("homepage"),
        "openalex_id": j.get("openalex_id"),
        "publisher": cl.get("publisher"),
        "country": cl.get("country"),
        "subject_areas": list(cl.get("subject_areas") or []),
        "is_oa": oa.get("is_oa"),
        "best_quartile": cl.get("quartile"),
        "all_quartiles": list(cl.get("all_quartiles") or []),
        "sjr_score": m.get("sjr_score"),
        "citation_score_2yr": m.get("citation_score_2yr"),
        "h_index": m.get("h_index"),
        "h_index_scimago": m.get("h_index_scimago"),
        "total_citations": m.get("total_citations"),
        "works_count": m.get("works_count"),
        "i10_index": m.get("i10_index"),
        "scimago_rank": m.get("scimago_rank"),
        "apc_usd": apc.get("openalex_usd"),
        "doaj_verified": oa.get("doaj_verified"),
        "doaj_apc_amount": apc.get("amount"),
        "doaj_apc_currency": apc.get("currency"),
        "doaj_license": oa.get("doaj_license"),
        "review_process": list(oa.get("review_process") or []),
        "doaj_url": oa.get("doaj_url"),
        "scimago_match": pr.get("scimago_match"),
        "scimago_note": pr.get("scimago_note"),
        "quartile_note": pr.get("quartile_note"),
        "doaj_error": pr.get("doaj_error"),
        "search_context": pr.get("search_context"),
        "completeness_score": qu.get("completeness_score"),
        "confidence_score": qu.get("confidence_score"),
        "missing_fields": list(qu.get("missing_fields") or []),
        "source_disagreements": list(pr.get("source_disagreements") or []),
    }
    return flat


def entity_from_scimago_csv_row_only(row: Dict[str, str]) -> Dict[str, Any]:
    """Build entity from a CSV row (quartile_list intent) without OpenAlex."""
    entity = empty_journal_entity()
    title = _cell(row, "Title")
    entity["journal"]["name"] = title or "Unknown"
    entity["journal"]["issn"] = _as_opt_str(_cell(row, "Issn")) or None
    q_raw = _cell(row, "SJR Best Quartile")
    sjr = _parse_sjr(_cell(row, "SJR"))
    payload = {
        "sjr_score": sjr,
        "best_quartile": q_raw if q_raw.startswith("Q") else None,
        "all_quartiles": [q_raw] if q_raw.startswith("Q") else [],
        "subject_areas": _categories_to_subject_areas(_cell(row, "Categories"), limit=2),
        "scimago_rank": _parse_int(_cell(row, "Rank")),
        "publisher": _cell(row, "Publisher") or None,
        "country": _cell(row, "Country") or None,
        "h_index_scimago": _parse_int(_cell(row, "H index")),
        "scimago_match": "csv_row",
        "scimago_note": None,
    }
    merge_scimago_into_entity(entity, normalize_scimago_lookup_payload(payload))
    entity["source_map"]["openalex"] = None
    compute_quality_scores(entity)
    return entity


# ---------------------------------------------------------------------------
# HTTP with exponential backoff
# ---------------------------------------------------------------------------
def _http_get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 15.0,
) -> requests.Response:
    backoff = _HTTP_BACKOFF_BASE
    last_exc: Optional[BaseException] = None
    for attempt in range(_MAX_HTTP_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if resp.status_code in (429, 502, 503, 504):
                time.sleep(backoff + random.uniform(0, 0.15))
                backoff = min(backoff * 2, 8.0)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            time.sleep(backoff + random.uniform(0, 0.15))
            backoff = min(backoff * 2, 8.0)
    assert last_exc is not None
    raise last_exc


def _cache_get(store: Dict[Tuple[Any, ...], Tuple[float, Any]], key: Tuple[Any, ...]) -> Any:
    now = time.monotonic()
    with _cache_lock:
        hit = store.get(key)
        if hit and now < hit[0]:
            return hit[1]
    return None


def _cache_set(store: Dict[Tuple[Any, ...], Tuple[float, Any]], key: Tuple[Any, ...], value: Any) -> None:
    with _cache_lock:
        store[key] = (time.monotonic() + _CACHE_TTL, value)


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------
def search_openalex(domain: str, limit: int = 10, oa_only: bool = False) -> List[Dict[str, Any]]:
    """
    Search OpenAlex for journals in a domain.
    Returns list of **canonical journal entities** (nested schema), never raw API dicts.
    """
    cache_key = (domain.strip().lower(), int(limit), bool(oa_only))
    cached = _cache_get(_openalex_cache, cache_key)
    if cached is not None:
        return cached

    filters = ["type:journal"]
    if oa_only:
        filters.append("is_oa:true")
    params: Dict[str, Any] = {
        "search": domain,
        "filter": ",".join(filters),
        "sort": "cited_by_count:desc",
        "per-page": limit,
        "select": (
            "id,display_name,issn_l,cited_by_count,summary_stats,apc_usd,"
            "apc_prices,is_oa,homepage_url,works_count,type"
        ),
    }

    try:
        resp = _http_get(f"{OPENALEX_BASE}/sources", params=params)
        body = resp.json()
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            results = []
    except Exception as e:
        print(f"[OpenAlex Error] {e}")
        return []

    entities: List[Dict[str, Any]] = []
    for r in results:
        norm = normalize_openalex_record(r)
        if norm is None:
            continue
        entities.append(entity_from_openalex_normalized(norm))

    _cache_set(_openalex_cache, cache_key, entities)
    return entities


# ---------------------------------------------------------------------------
# Scimago — local CSV (official site search returns HTML to requests)
# ---------------------------------------------------------------------------
_scimago_lock = threading.Lock()
_scimago_rows: Optional[List[Dict[str, str]]] = None
_scimago_header_idx: Optional[Dict[str, int]] = None


def _header_first_index(header: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i, h in enumerate(header):
        if h not in out:
            out[h] = i
    return out


def _ensure_scimago_loaded() -> None:
    global _scimago_rows, _scimago_header_idx
    with _scimago_lock:
        if _scimago_rows is not None:
            return
        rows: List[Dict[str, str]] = []
        if not _SCIMAGO_CSV_PATH.is_file():
            print(f"[Scimago CSV missing] {_SCIMAGO_CSV_PATH}")
            _scimago_rows = []
            _scimago_header_idx = {}
            return
        with _SCIMAGO_CSV_PATH.open(newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter=";")
            header = next(reader)
            idx = _header_first_index(header)
            _scimago_header_idx = idx
            for cols in reader:
                if len(cols) < len(header):
                    continue
                rows.append({name: cols[i] if i < len(cols) else "" for name, i in idx.items()})
        _scimago_rows = rows


def _cell(row: Dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip().strip('"')


def _norm_title(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip().strip('"\''))


def _issn_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _row_issn_blob(row: Dict[str, str]) -> str:
    return _issn_digits(_cell(row, "Issn"))


def _parse_sjr(raw: str) -> Optional[float]:
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_int(raw: str) -> Optional[int]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw.replace(",", ".")))
    except ValueError:
        return None


def _categories_to_subject_areas(categories: str, limit: int = 3) -> List[str]:
    parts = re.split(r";+", categories or "")
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(re.sub(r"\s*\([^)]*\)\s*$", "", p).strip())
        if len(out) >= limit:
            break
    return out


def _pick_scimago_row(journal_name: str, issn: Optional[str]) -> Tuple[Dict[str, str], str]:
    _ensure_scimago_loaded()
    rows = _scimago_rows or []
    if not rows:
        return {}, "none"

    want_issn = _issn_digits(issn or "")
    if len(want_issn) >= 7:
        for row in rows:
            blob = _row_issn_blob(row)
            if want_issn and want_issn in blob:
                return row, "issn"

    nt = _norm_title(journal_name)
    if not nt:
        return {}, "none"

    for row in rows:
        if _norm_title(_cell(row, "Title")) == nt:
            return row, "exact"

    first = nt.split()[0] if nt else ""
    pool = [r for r in rows if first and first in _norm_title(_cell(r, "Title"))]
    if not pool:
        pool = rows

    best_row = None
    best_ratio = 0.0
    for row in pool:
        title = _norm_title(_cell(row, "Title"))
        if not title:
            continue
        ratio = difflib.SequenceMatcher(None, nt, title).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_row = row

    if best_row is not None and best_ratio >= 0.55:
        return best_row, "fuzzy"
    return {}, "none"


def _row_to_scimago_payload(row: Dict[str, str], match: str) -> Dict[str, Any]:
    q_raw = _cell(row, "SJR Best Quartile")
    quartiles = [q_raw] if q_raw.startswith("Q") else []
    sjr = _parse_sjr(_cell(row, "SJR"))
    rank = _parse_int(_cell(row, "Rank"))
    h_idx = _parse_int(_cell(row, "H index"))
    return {
        "sjr_score": sjr,
        "best_quartile": q_raw if q_raw.startswith("Q") else None,
        "all_quartiles": list(dict.fromkeys(quartiles)),
        "subject_areas": _categories_to_subject_areas(_cell(row, "Categories")),
        "scimago_rank": rank,
        "publisher": _cell(row, "Publisher") or None,
        "country": _cell(row, "Country") or None,
        "h_index_scimago": h_idx,
        "scimago_match": match,
    }


def get_scimago_data(journal_name: str, issn: Optional[str] = None) -> Dict[str, Any]:
    """Resolve Scimago quartile / SJR from bundled CSV."""
    cache_key = (_norm_title(journal_name), _issn_digits(issn or ""))
    cached = _cache_get(_scimago_lookup_cache, cache_key)
    if cached is not None:
        return cached

    row, match = _pick_scimago_row(journal_name, issn)
    if not row:
        out: Dict[str, Any] = {
            "sjr_score": None,
            "best_quartile": None,
            "all_quartiles": [],
            "subject_areas": [],
            "scimago_rank": None,
            "publisher": None,
            "country": None,
            "h_index_scimago": None,
            "scimago_match": "none",
            "scimago_note": "No Scimago row matched this title/ISSN in local CSV.",
        }
        _cache_set(_scimago_lookup_cache, cache_key, out)
        return out

    out = _row_to_scimago_payload(row, match)
    _cache_set(_scimago_lookup_cache, cache_key, out)
    return out


_QUARTILE_STOP = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "about",
    "your",
    "some",
    "any",
}


def get_quartile_list(
    domain: str, target_quartile: Optional[str] = None, limit: int = 15
) -> List[Dict[str, Any]]:
    """List journals from local Scimago CSV filtered by domain keywords and quartile."""
    _ensure_scimago_loaded()
    rows = _scimago_rows or []
    if not rows:
        return []

    tokens = [
        t
        for t in re.findall(r"[a-z0-9]+", domain.lower())
        if len(t) > 2 and t not in _QUARTILE_STOP
    ][:16]
    scored: List[Tuple[int, float, Dict[str, str]]] = []

    for row in rows:
        title = _cell(row, "Title")
        categories = _cell(row, "Categories")
        areas = _cell(row, "Areas")
        blob = f"{title} {categories} {areas}".lower()
        score = sum(1 for tok in tokens if tok in blob) if tokens else 0
        if score == 0 and tokens:
            continue

        q_raw = _cell(row, "SJR Best Quartile")
        if not q_raw.startswith("Q"):
            continue
        if target_quartile and q_raw != target_quartile:
            continue

        sjr = _parse_sjr(_cell(row, "SJR")) or 0.0
        scored.append((score if tokens else 1, sjr, row))

    scored.sort(key=lambda x: (-x[0], -x[1]))
    results: List[Dict[str, Any]] = []
    for _, _, j in scored[:limit]:
        ent = entity_from_scimago_csv_row_only(j)
        results.append(entity_to_public_dict(ent))
    return results


# ---------------------------------------------------------------------------
# DOAJ
# ---------------------------------------------------------------------------
def get_doaj_data(journal_name: str) -> Dict[str, Any]:
    """
    Query DOAJ for open access fee and policy information.
    Path: ``{DOAJ_SEARCH_BASE}/{url_encoded_query}`` with ``pageSize`` query param.
    Returns a **normalized** dict (``normalize_doaj_payload``-compatible), never raw HTTP JSON.
    """
    if not journal_name.strip():
        return normalize_doaj_payload({})

    path_segment = quote(journal_name.strip(), safe="")
    url = f"{DOAJ_SEARCH_BASE}/{path_segment}"
    try:
        resp = _http_get(url, params={"pageSize": 1})
        data = resp.json()
    except Exception as e:
        print(f"[DOAJ Error for '{journal_name}'] {e}")
        return normalize_doaj_payload({"doaj_error": str(e)})

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or not results:
        return normalize_doaj_payload({"doaj_error": "empty_results"})

    best = None
    journal_name_lower = journal_name.lower()
    for r in results:
        if not isinstance(r, dict):
            continue
        bib = r.get("bibjson")
        bib = bib if isinstance(bib, dict) else {}
        title = str(bib.get("title", "") or "").lower()
        if journal_name_lower in title or title in journal_name_lower:
            best = r
            break
    if not best:
        best = results[0] if isinstance(results[0], dict) else None
    if not isinstance(best, dict):
        return normalize_doaj_payload({"doaj_error": "invalid_result_shape"})

    bib = best.get("bibjson")
    bib = bib if isinstance(bib, dict) else {}
    apc = bib.get("apc")
    apc = apc if isinstance(apc, dict) else {}
    sub = bib.get("submission_charges")
    sub = sub if isinstance(sub, dict) else {}

    lic = bib.get("license")
    lic_first: Dict[str, Any] = {}
    if isinstance(lic, list) and lic:
        lic_first = lic[0] if isinstance(lic[0], dict) else {}
    elif isinstance(lic, dict):
        lic_first = lic

    ed = bib.get("editorial")
    ed = ed if isinstance(ed, dict) else {}
    rp = ed.get("review_process")
    if not isinstance(rp, list):
        rp = [rp] if rp else []

    lang_raw = bib.get("language")
    languages: List[str] = []
    if isinstance(lang_raw, list):
        for l in lang_raw:
            if isinstance(l, dict):
                n = _as_opt_str(l.get("name"))
                if n:
                    languages.append(n)
            else:
                s = _as_opt_str(l)
                if s:
                    languages.append(s)

    pub = bib.get("publisher")
    pub_name = pub.get("name") if isinstance(pub, dict) else None

    max_list = apc.get("max")
    first_price: Dict[str, Any] = {}
    if isinstance(max_list, list) and max_list and isinstance(max_list[0], dict):
        first_price = max_list[0]

    raw_payload = {
        "doaj_verified": True,
        "apc_has_charges": bool(apc.get("has_apc")),
        "apc_amount": first_price.get("price"),
        "apc_currency": first_price.get("currency") or "USD",
        "submission_charges": bool(sub.get("has_charges")),
        "license": lic_first.get("type"),
        "review_process": rp,
        "language": languages,
        "publisher": pub_name,
        "doaj_url": f"https://doaj.org/toc/{bib.get('pissn', '') or ''}",
    }
    return normalize_doaj_payload(raw_payload)


# ---------------------------------------------------------------------------
# Enrichment (canonical entity only)
# ---------------------------------------------------------------------------
def enrich_journal_entity(entity: Dict[str, Any], include_doaj: bool = True) -> Dict[str, Any]:
    """
    Enrich a **canonical** journal entity with Scimago (CSV) and optional DOAJ.
    Mutates ``entity`` in place and returns it.
    """
    jn = entity.get("journal") if isinstance(entity.get("journal"), dict) else {}
    name = _as_opt_str(jn.get("name")) or "Unknown"
    issn = _as_opt_str(jn.get("issn"))

    scimago_raw = get_scimago_data(name, issn=issn)
    scimago_n = normalize_scimago_lookup_payload(scimago_raw)
    merge_scimago_into_entity(entity, scimago_n)

    if include_doaj and entity.get("open_access", {}).get("is_oa"):
        doaj_raw = get_doaj_data(name)
        doaj_n = normalize_doaj_payload(doaj_raw)
        merge_doaj_into_entity(entity, doaj_n)

    compute_quality_scores(entity)
    return entity


def _safe_enrich_one(entity: Any, include_doaj: bool) -> Dict[str, Any]:
    try:
        if not isinstance(entity, dict):
            e = empty_journal_entity()
            e["journal"]["name"] = "invalid_input"
            e["provenance"]["quartile_note"] = "enrichment_skipped_non_dict"
            compute_quality_scores(e)
            return entity_to_public_dict(e)
        work = copy.deepcopy(entity)
        enrich_journal_entity(work, include_doaj=include_doaj)
        return entity_to_public_dict(work)
    except Exception as ex:
        err = empty_journal_entity()
        jn = err["journal"]
        if isinstance(entity, dict) and isinstance(entity.get("journal"), dict):
            jn["name"] = _as_opt_str(entity["journal"].get("name")) or "Unknown"
        else:
            jn["name"] = "enrichment_error"
        err["provenance"]["quartile_note"] = f"enrichment_failed: {ex}"
        err["quality"]["missing_fields"] = ["enrichment_exception"]
        compute_quality_scores(err)
        return entity_to_public_dict(err)


def _enrich_parallel(entities: List[Any], include_doaj: bool) -> List[Dict[str, Any]]:
    if not entities:
        return []
    max_workers = min(8, len(entities))

    if len(entities) == 1:
        return [_safe_enrich_one(entities[0], include_doaj)]

    out: List[Optional[Dict[str, Any]]] = [None] * len(entities)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_safe_enrich_one, j, include_doaj): i for i, j in enumerate(entities)}
        for fut in as_completed(futs):
            out[futs[fut]] = fut.result()
    return [x for x in out if x is not None]


# ---------------------------------------------------------------------------
# Main query handler
# ---------------------------------------------------------------------------
def handle_query(query: str) -> Dict[str, Any]:
    """
    Main entry point. Pass any natural language researcher query.
    Returns structured data ready for display.
    """
    normalized = normalize_query(query)
    intent = str(normalized.get("intent") or "top_journals")
    domain_display = (
        " | ".join(normalized.get("topics") or [])
        if normalized.get("topics")
        else (normalized.get("sanitized_query") or normalized.get("raw_query") or "").strip()
    )

    def _attach_retrieval(enriched: List[Dict[str, Any]], rmeta: Dict[str, Any]) -> None:
        for row in enriched:
            row["retrieval_relevance_score"] = score_query_match(row, normalized)
        enriched.sort(key=lambda x: -float(x.get("retrieval_relevance_score") or 0.0))

    if intent == "top_journals":
        qs = build_openalex_queries(normalized)
        journals, rmeta = retrieve_journals(normalized, qs, per_call_limit=8, oa_only=False)
        if not journals:
            return {
                "intent": intent,
                "domain": domain_display,
                "query": query,
                "results": [],
                "normalized_query": normalized,
                "retrieval": rmeta,
                "fallback_used": rmeta.get("fallback_used", True),
                "reason": rmeta.get("reason"),
                "expanded_terms_used": rmeta.get("expanded_terms_used", []),
                "suggestion": rmeta.get("suggestion"),
                "source_note": rmeta.get("reason") or "No OpenAlex hits after semantic expansion.",
            }
        enriched, filter_meta = _enrich_filter_maybe_relax(
            normalized, journals, include_doaj=False, max_results=8, pool=16
        )
        rmeta = {**rmeta, **filter_meta}
        if not any(k in rmeta for k in ("fallback_used", "relaxed_query_used")):
            _attach_retrieval(enriched, rmeta)
        return {
            "intent": intent,
            "domain": domain_display,
            "query": query,
            "results": enriched[:8],
            "normalized_query": normalized,
            "retrieval": rmeta,
            "source_note": (
                "Citation scores from OpenAlex. Quartiles from local Scimago CSV (SJR). "
                "NOT official Impact Factor."
            ),
        }

    if intent == "quartile_list":
        target_q = normalized.get("constraints", {}).get("quartile")
        blob = _quartile_search_blob(normalized)
        journals = get_quartile_list(blob, target_quartile=target_q, limit=20)
        for row in journals:
            row["retrieval_relevance_score"] = score_query_match(row, normalized)
        journals.sort(key=lambda x: -float(x.get("retrieval_relevance_score") or 0.0))
        rmeta = {
            "fallback_used": not bool(journals),
            "reason": None
            if journals
            else "No Scimago CSV rows matched topic tokens after semantic normalization.",
            "expanded_terms_used": normalized.get("expansion_terms") or [],
            "suggestion": "Broaden or rephrase the subject; spell out acronyms if the CSV has no token match."
            if not journals
            else None,
            "queries_tried": [blob],
        }
        return {
            "intent": intent,
            "domain": domain_display,
            "query": query,
            "filter_quartile": target_q,
            "results": journals,
            "normalized_query": normalized,
            "retrieval": rmeta,
            "source_note": "Quartiles from bundled Scimago CSV (SJR-based).",
        }

    if intent == "oa_journals":
        qs = build_openalex_queries(normalized)
        journals, rmeta = retrieve_journals(normalized, qs, per_call_limit=8, oa_only=False)
        if not journals:
            return {
                "intent": intent,
                "domain": domain_display,
                "query": query,
                "results": [],
                "normalized_query": normalized,
                "retrieval": rmeta,
                "fallback_used": rmeta.get("fallback_used", True),
                "reason": rmeta.get("reason"),
                "expanded_terms_used": rmeta.get("expanded_terms_used", []),
                "suggestion": rmeta.get("suggestion"),
                "source_note": rmeta.get("reason") or "No OA journal hits from OpenAlex after expansion.",
            }
        enriched, filter_meta = _enrich_filter_maybe_relax(
            normalized, journals, include_doaj=True, max_results=8, pool=16
        )
        rmeta = {**rmeta, **filter_meta}
        if not any(k in rmeta for k in ("fallback_used", "relaxed_query_used")):
            _attach_retrieval(enriched, rmeta)
        return {
            "intent": intent,
            "domain": domain_display,
            "query": query,
            "results": enriched[:8],
            "normalized_query": normalized,
            "retrieval": rmeta,
            "source_note": "OA status from OpenAlex. Fees verified via DOAJ where available.",
        }

    if intent == "fee_search":
        qs = build_openalex_queries(normalized)
        journals, rmeta = retrieve_journals(normalized, qs, per_call_limit=8, oa_only=False)
        if not journals:
            return {
                "intent": intent,
                "domain": domain_display,
                "query": query,
                "results": [],
                "normalized_query": normalized,
                "retrieval": rmeta,
                "fallback_used": rmeta.get("fallback_used", True),
                "reason": rmeta.get("reason"),
                "expanded_terms_used": rmeta.get("expanded_terms_used", []),
                "suggestion": rmeta.get("suggestion"),
                "fee_note": rmeta.get("suggestion"),
                "source_note": rmeta.get("reason") or "No journals found for fee-oriented semantic queries.",
            }
        enriched, filter_meta = _enrich_filter_maybe_relax(
            normalized, journals, include_doaj=True, max_results=8, pool=16
        )
        rmeta = {**rmeta, **filter_meta}
        if not any(k in rmeta for k in ("fallback_used", "relaxed_query_used")):
            _attach_retrieval(enriched, rmeta)
        enriched.sort(
            key=lambda x: (
                -float(x.get("retrieval_relevance_score") or 0.0),
                x.get("doaj_apc_amount") is None,
                float(x.get("doaj_apc_amount") or 1e9),
                x.get("apc_usd") is None,
                float(x.get("apc_usd") or 1e9),
            )
        )
        return {
            "intent": intent,
            "domain": domain_display,
            "query": query,
            "results": enriched[:8],
            "normalized_query": normalized,
            "retrieval": rmeta,
            "fee_note": (
                "Fees from OpenAlex APC data + DOAJ verification. "
                "Subscription journal fees not publicly available via any free API."
            ),
            "source_note": "If fee shows 'Unknown', visit the journal homepage directly.",
        }

    if intent == "journal_detail":
        qs = build_openalex_queries(normalized)
        journals, rmeta = retrieve_journals(normalized, qs, per_call_limit=6, oa_only=False)
        if not journals:
            return {
                "intent": intent,
                "domain": domain_display,
                "query": query,
                "results": [],
                "error": "Journal not found.",
                "normalized_query": normalized,
                "retrieval": rmeta,
                "fallback_used": True,
                "reason": rmeta.get("reason"),
                "suggestion": rmeta.get("suggestion"),
            }
        cand_list, fmeta = _enrich_filter_maybe_relax(
            normalized, journals, include_doaj=True, max_results=8, pool=12
        )
        rmeta = {**rmeta, **fmeta}
        if not cand_list:
            return {
                "intent": intent,
                "domain": domain_display,
                "query": query,
                "results": [],
                "error": "Journal not found after constraint filtering.",
                "normalized_query": normalized,
                "retrieval": rmeta,
                "fallback_used": True,
                "reason": fmeta.get("reason"),
                "suggestion": fmeta.get("suggestion"),
            }
        return {
            "intent": intent,
            "domain": domain_display,
            "query": query,
            "results": [cand_list[0]],
            "normalized_query": normalized,
            "retrieval": rmeta,
            "metrics_note": (
                "SJR and quartile from Scimago CSV. Citation score from OpenAlex. "
                "These are NOT the official Clarivate Impact Factor."
            ),
        }

    if intent == "compare":
        parts = _split_compare_query(query)
        results: List[Dict[str, Any]] = []
        rmeta_all: Dict[str, Any] = {"queries_tried": [], "fallback_used": False, "parts": []}
        parent_constraints = (
            normalized.get("constraints") if isinstance(normalized.get("constraints"), dict) else {}
        )
        for part in parts[:2]:
            domain_part = _strip_compare_noise(part)
            if not domain_part:
                continue
            sub_norm = normalize_query(f"find journals in {domain_part}")
            sub_norm["topics"] = [domain_part]
            sub_norm["expansion_terms"] = list(
                dict.fromkeys([domain_part] + (sub_norm.get("expansion_terms") or []))
            )
            if parent_constraints:
                merged = dict(sub_norm.get("constraints") or {})
                for k in ("open_access", "apc", "quartile"):
                    if k in parent_constraints and parent_constraints[k] is not None:
                        merged[k] = parent_constraints[k]
                sub_norm["constraints"] = merged
            qs = build_openalex_queries(sub_norm)
            js, rmeta = retrieve_journals(sub_norm, qs, per_call_limit=5, oa_only=False)
            rmeta_all["queries_tried"].extend(rmeta.get("queries_tried") or [])
            if rmeta.get("fallback_used"):
                rmeta_all["fallback_used"] = True
            tagged: List[Dict[str, Any]] = []
            for j in js:
                if not isinstance(j, dict):
                    continue
                jc = copy.deepcopy(j)
                jc.setdefault("provenance", {})
                if not isinstance(jc["provenance"], dict):
                    jc["provenance"] = {}
                jc["provenance"]["search_context"] = domain_part
                tagged.append(jc)
            part_rows, fmeta = _enrich_filter_maybe_relax(
                sub_norm, tagged, include_doaj=True, max_results=3, pool=10
            )
            for row in part_rows:
                row["retrieval_relevance_score"] = score_query_match(row, sub_norm)
            part_rows.sort(key=lambda x: -float(x.get("retrieval_relevance_score") or 0.0))
            results.extend(part_rows[:3])
            rmeta_all["parts"].append(
                {"context": domain_part, "retrieval": rmeta, "constraint_filter": fmeta}
            )
        return {
            "intent": intent,
            "domain": domain_display,
            "query": query,
            "results": results,
            "normalized_query": normalized,
            "retrieval": rmeta_all,
            "source_note": "Metrics from OpenAlex + Scimago CSV; fees/OA constraints use DOAJ when available.",
        }

    return {
        "intent": intent,
        "domain": domain_display,
        "query": query,
        "results": [],
        "error": "Could not process query.",
        "normalized_query": normalized,
        "retrieval": {"fallback_used": True, "reason": "Unhandled intent branch.", "suggestion": None},
    }


def routing_metadata(intent: str) -> Dict[str, Any]:
    """Routing / provenance hint for HTTP layers (standalone ``api`` and backend ``/pipelines``)."""
    routing_map: Dict[str, Dict[str, Any]] = {
        "top_journals": {
            "used_sources": ["OpenAlex", "Scimago CSV"],
            "path": "openalex_search -> scimago_csv_enrichment",
        },
        "quartile_list": {
            "used_sources": ["Scimago CSV"],
            "path": "scimago_csv_keyword_filter",
        },
        "oa_journals": {
            "used_sources": ["OpenAlex", "Scimago CSV", "DOAJ"],
            "path": "openalex_oa_search -> scimago_csv -> doaj_enrichment",
        },
        "fee_search": {
            "used_sources": ["OpenAlex", "Scimago CSV", "DOAJ"],
            "path": "openalex_search -> scimago_csv -> doaj_fee_verification",
        },
        "journal_detail": {
            "used_sources": ["OpenAlex", "Scimago CSV", "DOAJ"],
            "path": "openalex_single_search -> full_enrichment",
        },
        "compare": {
            "used_sources": ["OpenAlex", "Scimago CSV"],
            "path": "dual_openalex_search -> scimago_csv_enrichment",
        },
    }
    return routing_map.get(intent, {"used_sources": [], "path": "unknown"})


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def format_fee(journal: Dict[str, Any]) -> str:
    """Return a clean fee string."""
    if journal.get("doaj_error"):
        return f"DOAJ lookup issue: {journal['doaj_error']}"
    doaj_amt = journal.get("doaj_apc_amount")
    doaj_curr = journal.get("doaj_apc_currency", "USD")
    openalex = journal.get("apc_usd")

    if doaj_amt:
        return f"{doaj_curr} {doaj_amt} (DOAJ verified)"
    if openalex:
        return f"USD {openalex} (OpenAlex)"
    if journal.get("is_oa") is False:
        return "Subscription journal - fee not publicly available"
    return "Unknown - visit journal homepage"


def format_metrics(journal: Dict[str, Any]) -> str:
    """Return honest, clearly-labelled metrics."""
    parts: List[str] = []
    if journal.get("sjr_score"):
        parts.append(f"SJR Score: {journal['sjr_score']}")
    if journal.get("citation_score_2yr"):
        parts.append(
            f"Citation Score 2yr (OpenAlex): {journal['citation_score_2yr']}"
        )
    if journal.get("h_index") is not None:
        parts.append(f"H-Index (OpenAlex): {journal['h_index']}")
    if journal.get("h_index_scimago") is not None:
        parts.append(f"H-Index (Scimago CSV): {journal['h_index_scimago']}")
    return " | ".join(parts) if parts else "No metrics available"


def print_results(response: Dict[str, Any]) -> None:
    """Pretty-print results to terminal."""
    print(f"\n{'=' * 60}")
    print(f"Query: {response['query']}")
    print(f"Intent: {response['intent']} | Domain: {response['domain']}")
    print(f"{'=' * 60}\n")

    for i, j in enumerate(response.get("results", []), 1):
        print(f"{i}. {j['name']}")
        print(f"   Publisher : {j.get('publisher', 'Unknown')}")
        print(f"   Country   : {j.get('country', 'Unknown')}")
        print(f"   Quartile  : {j.get('best_quartile', 'N/A')} (Scimago CSV)")
        if j.get("quartile_note"):
            print(f"   Note      : {j['quartile_note']}")
        print(f"   Metrics   : {format_metrics(j)}")
        oa = j.get("is_oa")
        oa_label = "Open Access" if oa is True else "Subscription" if oa is False else "Unknown"
        print(f"   OA Status : {oa_label}")
        print(f"   Fee       : {format_fee(j)}")
        if j.get("subject_areas"):
            print(f"   Fields    : {', '.join(j['subject_areas'])}")
        if j.get("homepage"):
            print(f"   Homepage  : {j['homepage']}")
        print()

    note = (
        response.get("source_note")
        or response.get("metrics_note")
        or response.get("fee_note")
    )
    if note:
        print(f"INFO: {note}\n")


if __name__ == "__main__":
    import sys

    test_queries = [a.strip() for a in sys.argv[1:] if a.strip()]
    if not test_queries:
        print("Usage: python -m src.Journel_Research_Assistan.journal_research <query> [...]", file=sys.stderr)
        raise SystemExit(0)

    for q in test_queries:
        result = handle_query(q)
        print_results(result)
