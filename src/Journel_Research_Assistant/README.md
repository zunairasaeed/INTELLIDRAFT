# Journal Research Module

Natural-language questions about journals → structured results using **OpenAlex**, **DOAJ**, and a **local Scimago CSV** (no paid keys).

## Files

| File | Role |
|------|------|
| `journal_research.py` | Pipeline: intent, domain string, OpenAlex/DOAJ/CSV, enrichment, caches |
| `api.py` | Optional standalone FastAPI (`/ask`, `/health`) |

Integrated backend (same logic): **`GET /pipelines/journal-research/ask`** and **`GET /pipelines/journal-research/health`** on `backend.main`.

---

## Pipeline review (query → answer)

Use this section to see **where** each step lives and **what to improve**.

### 1. Input

- **Entry:** `handle_query(query: str)` in `journal_research.py`.
- **HTTP:** query string `q` on `GET /ask` or `GET /pipelines/journal-research/ask`.

No separate “keyword extraction” stage before intent: the raw string is passed into the classifier and domain helper as-is (only lowercasing where noted below).

### 2. Intent classification

- **Function:** `classify_intent(query)`.
- **Mechanism:** **Rule-based, first match wins** (order is part of the contract). Substring / phrase checks on `query.lower()`.
- **Outputs:** one of  
  `compare` | `oa_journals` | `fee_search` | `quartile_list` | `journal_detail` | `top_journals` (default).

**Order (summary):** compare → open-access phrases → fee → quartile → metrics/detail → “top/list/find” → default top_journals.

**Improvement areas**

- Replace or augment with a **small classifier** (logreg / lightweight model) or **LLM routing** if you need fuzzy phrasing and fewer false positives.
- **Coverage:** typos, multilingual queries, and journal names mistaken for “domains” are not handled here.
- **Overlap:** words like `rank` / `score` can tug between intents; tuning lists or using scored intents would help.

### 3. Semantic query normalization (retrieval input)

- **Function:** `normalize_query(query)` → structured dict: `topics`, `constraints` (open_access, apc, quartile), `expansion_terms`, `search_strategy` (`strict` | `balanced` | `broad`), `entities`, and `intent` (via `classify_intent`).
- **OpenAlex strings:** `build_openalex_queries(normalized)` produces 2–5 **search** phrases (never the raw user string alone).
- **Retrieval:** `retrieve_journals(normalized, queries)` runs multi-query OpenAlex, dedupes, and **escalates** strategy (`strict` → `balanced` → `broad`) when results are empty; metadata in `retrieval` + optional `fallback_used` / `reason` / `suggestion`.
- **Ranking:** `score_query_match(result, normalized)` sets `retrieval_relevance_score` on rows where applicable.
- **Legacy helper:** `extract_domain()` remains for external callers but **`handle_query` no longer uses it** for OpenAlex retrieval.

**Improvement areas**

- Topic map (`TOPIC_PHRASE_MAP` / `TOKEN_SYNONYMS`) is **hand-curated**; extend or replace with embeddings / LLM expansion for long-tail fields.
- **Constraint detection** is keyword-based; ambiguous “free” (beer vs OA) can mis-fire without context.

### 4. Intent-specific retrieval (the “answer path”)

| Intent | OpenAlex | Scimago CSV | DOAJ | Notes |
|--------|----------|-------------|------|--------|
| `top_journals` | `retrieve_journals` → multi-query `search_openalex` | per-journal enrich | no | Fallback + relevance score |
| `quartile_list` | no | `get_quartile_list(_quartile_search_blob(normalized), …)` | no | Topics + expansion terms drive CSV token match |
| `oa_journals` | `retrieve_journals` … `oa_only=True` | enrich | yes | Same fallback ladder |
| `fee_search` | `retrieve_journals` | enrich | yes | Sort by relevance then APC |
| `journal_detail` | `retrieve_journals` (candidates) → best by `score_query_match` | enrich | yes | No single literal domain string |
| `compare` | per-side `normalize_query('find journals in …')` + `retrieve_journals` | enrich | no | `search_context` on each row |

**OpenAlex:** `filter` merges `type:journal` and optional `is_oa:true`; **TTL cache** on `(domain, limit, oa_only)`.

**Scimago:** **local CSV** row match (ISSN → exact title → fuzzy title); **not** live HTML/JSON from scimagojr.com.

**DOAJ:** GET `{DOAJ_BASE}/{url_encoded_journal_name}?pageSize=1` with retries/backoff.

**Improvement areas**

- **OpenAlex query quality:** driven by **`normalize_query` / `build_openalex_queries`**; tune maps and templates before changing APIs.
- **Quartile list:** token–substring scoring on CSV text is **coarse**; synonyms, abbreviations (`NLP`), and ranking bias when tokens are empty need work.
- **Journal detail:** best match among a **small candidate set** after enrichment; rare misses if OpenAlex has no close sources.
- **Compare:** only two sides, fixed limits; no alignment of “same tier” journals across sides.
- **DOAJ:** one `pageSize=1` hit may miss the intended journal; could raise page size and re-rank.

### 5. Enrichment and parallelism

- **Function:** `enrich_journal_entity` (Scimago + optional DOAJ on canonical rows); **`_enrich_parallel`** + **`_safe_enrich_one`** (try/except per worker).
- **Fields:** merges quartiles, SJR, publisher, country, optional DOAJ APC, notes on miss (`quartile_note`, `doaj_error`).

**Improvement areas**

- **DOAJ concurrency** can still stress rate limits; global semaphore or lower max workers if 429s appear.
- **Explainability:** surface **which source** filled each field in a structured way for UI.

### 6. Response bundle

- **Function:** `handle_query` returns a **dict**: `intent`, `domain`, `query`, `results`, optional `source_note` / `fee_note` / `metrics_note` / `filter_quartile` / `error`.
- **Routing metadata:** `routing_metadata(intent)` for debug (`used_sources`, `path`) — used by `api.py` and backend `/pipelines/journal-research/ask`.

**Improvement areas**

- Stable **JSON schema** / OpenAPI models for each intent if clients need strict typing.
- **User-facing answer string:** today the “answer” is mostly structured rows + notes; a **template or LLM summarizer** layer could produce prose.

---

## Critical design decisions

### Honest metric labeling

This module does **not** label any metric as “Impact Factor”. It uses SJR (from CSV), OpenAlex 2-year citedness, and h-index style fields where available.

### Quartiles

Quartiles come from the **bundled Scimago CSV** (`SJR Best Quartile`), not from ranking arbitrary OpenAlex result lists.

### Known limitations

- Official Clarivate JIF is not available via these free sources.
- Subscription APCs are often unknown; responses say so explicitly.
- CSV is a **snapshot**; refresh the file to track Scimago’s annual updates.

---

## Setup

**Recommended (with the rest of IntelliDraft):** from repo root

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8080
```

Then: `GET /pipelines/journal-research/ask?q=...`

**Standalone** (this folder only):

```bash
cd src/Journel_Research_Assistan
python api.py
```

Port/host default from `.env`: `JOURNAL_RESEARCH_STANDALONE_PORT` (default `8012`), `JOURNAL_RESEARCH_STANDALONE_HOST`. Or:

```bash
uvicorn api:app --reload --host 127.0.0.1 --port 8012
```

Quick local demo:

```bash
python journal_research.py
```

## Endpoints

**Standalone**

```http
GET /health
GET /ask?q=top+journals+in+machine+learning
GET /ask?q=Q1+journals+in+NLP
GET /ask?q=open+access+journals+in+biology+with+low+fees
GET /ask?q=compare+CV+vs+NLP+journals
```

**Backend (same pipeline)**

```http
GET /pipelines/journal-research/health
GET /pipelines/journal-research/ask?q=...
```

## Environment (see repo root `.env`)

- `JOURNAL_RESEARCH_OPENALEX_BASE_URL`
- `JOURNAL_RESEARCH_DOAJ_SEARCH_JOURNALS_BASE_URL`
- `JOURNAL_RESEARCH_SCIMAGO_CSV_PATH`
- `JOURNAL_RESEARCH_CACHE_TTL_SECONDS`, HTTP retry settings
- `JOURNAL_RESEARCH_STANDALONE_PORT`, `JOURNAL_RESEARCH_STANDALONE_HOST` (standalone app only)
