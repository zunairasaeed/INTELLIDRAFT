"""
ResearchPal — turn retrieved papers into a conversational answer (Groq via call_gpt).
Session / chat history are handled outside this module; prompts use title + abstract + papers only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from call_gpt import call_gpt

LITERATURE_SEARCH_SYSTEM = """You are ResearchPal, a warm and knowledgeable
academic research assistant inside IntelliDraft. You help researchers find
relevant literature for their research paper.

You will receive:
- The user's paper title
- The user's paper abstract
- A list of retrieved papers relevant to their topic

YOUR JOB:
Present retrieved papers conversationally in a single flowing response.

STRICT RULES:
- NEVER dump raw data or mention "Semantic Scholar", "API", or
  any technical pipeline details
- NEVER mention "Why relevant" as a label
- ALWAYS write the paper description as a natural abstract-style
  summary connecting it to the user's work
- Prioritize papers with higher citation counts
- Skip papers with no abstract
- NEVER invent information not in the provided data

TONE & STYLE:
- Warm and conversational like a helpful research colleague
- Make connections between papers and user's topic feel natural
- Keep paper descriptions concise like a mini abstract

ANSWER FORMAT:

1. ONE sentence acknowledging their topic

2. Present top 5 papers as:

   📄 [Paper Title]
   👥 [Authors] | 📅 [Year] | 📊 [Citation Count] citations
   [2-3 sentences written like a mini abstract explaining what
   this paper covers and how it naturally connects to the
   user's title and abstract — no labels, just flowing text]
   🔗 [URL]

3. 2-3 sentence closing summary of what this literature
   collectively tells us about the user's research area

4. ONE follow-up question to continue the conversation naturally
"""


LITERATURE_SEARCH_USER = """
User's paper:
Title: {title}
Abstract: {abstract}

Retrieved papers:
{papers}

Respond conversationally.
Pick top 5 papers with abstracts and highest citations.
Write each paper description as flowing text like a mini abstract,
naturally connecting it to the user's title and abstract.
No bullet labels like 'Why relevant' — just natural description.
"""


def _format_authors(raw: Any) -> str:
    if not raw:
        return "Unknown"
    if isinstance(raw, str):
        return raw
    parts: List[str] = []
    for a in raw[:20]:
        if isinstance(a, str):
            parts.append(a)
        elif isinstance(a, dict):
            parts.append(str(a.get("name") or a.get("authorId") or ""))
    return ", ".join(p for p in parts if p) or "Unknown"


def _papers_for_prompt(mapped_results: List[Dict[str, Any]], max_candidates: int = 18) -> str:
    pool = [p for p in mapped_results if (p.get("abstract") or "").strip()]
    pool.sort(key=lambda p: int(p.get("citationCount") or 0), reverse=True)
    pool = pool[:max_candidates]
    blobs: List[Dict[str, Any]] = []
    for p in pool:
        blobs.append(
            {
                "title": p.get("title") or "",
                "authors": _format_authors(p.get("authors")),
                "year": p.get("year"),
                "citation_count": int(p.get("citationCount") or 0),
                "abstract": (p.get("abstract") or "")[:2200],
                "url": p.get("url") or "",
            }
        )
    return json.dumps(blobs, ensure_ascii=False, indent=2)


def synthesize_researchpal_answer(
    title: str,
    abstract: str,
    mapped_results: List[Dict[str, Any]],
) -> str:
    """
    Returns conversational markdown-style text from the LLM.
    On failure (missing key / API error), returns a short plaintext fallback.
    """
    papers_block = _papers_for_prompt(mapped_results)
    if papers_block.strip() == "[]":
        return (
            "I retrieved no papers that include an abstract in this batch, so "
            "I can't yet write a ResearchPal-style rundown. Try widening "
            "the search or adjusting your title or abstract slightly."
        )
    user_prompt = LITERATURE_SEARCH_USER.format(
        title=title.strip() or "(not provided)",
        abstract=abstract.strip() or "(not provided)",
        papers=papers_block,
    )
    try:
        text = call_gpt(
            system_prompt=LITERATURE_SEARCH_SYSTEM.strip(),
            user_prompt=user_prompt.strip(),
            max_tokens=2048,
            temperature=0.25,
        )
        out = (text or "").strip()
        return out or "I couldn't synthesize a response just now — please try again."
    except Exception:
        return (
            "ResearchPal summary is temporarily unavailable (check GROQ_API_KEY "
            "in .env). The structured paper list is still available in "
            '`results`.'
        )
