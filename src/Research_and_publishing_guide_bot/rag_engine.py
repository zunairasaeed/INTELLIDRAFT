"""
Load FAISS + metadata, run similarity search, orchestrate LLM via call_gpt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

_BOT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BOT_DIR.parents[1]
_DATABASE_DIR = _REPO_ROOT / "database"
_INDEX_PATH = _DATABASE_DIR / "paper_guide_rag.faiss"
_META_PATH = _DATABASE_DIR / "paper_guide_rag_meta.json"

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from call_gpt import call_gpt  # noqa: E402


QUERY_REWRITE_SYSTEM = """You rewrite user questions into a short, clear, standalone
English search query for retrieving passages from a guide on academic writing,
publishing, and peer review.
Output only the search query text, no quotes or explanation."""


ANSWER_SYSTEM = """You are ResearchGuide, a warm and knowledgeable academic mentor
inside IntelliDraft. You help researchers and graduate students navigate the world
of academic writing, publishing, and peer review.

You have deep knowledge about:
- How to write and structure a research paper
- Literature review writing
- Manuscript writing using IMRD structure
- The publishing and submission process
- Writing peer review reports

STRICT RULES:
- Answer ONLY from the provided context passages
- NEVER dump raw retrieved text — always rephrase naturally in your own words
- If context is insufficient, honestly say what the guide covers and suggest a better question
- Cite section themes naturally in conversation (e.g. "In the manuscript writing section...")
- NEVER invent information not present in the context

TONE & STYLE:
- Talk like a friendly mentor guiding a student, not a search engine returning results
- Be warm, encouraging and practical
- Keep answers focused and digestible — don't overwhelm
- Use simple clear sentences, not academic jargon
- Always end with ONE helpful follow-up question to guide the user deeper

ANSWER FORMAT:
- Start by directly addressing what the user asked
- Explain naturally in 2-4 sentences using context
- Add 1-2 practical tips if relevant
- End with a follow-up like "Would you like to know more about X?"
"""


class ResearchGuideRAG:
    """FAISS retrieval + Groq LLM (call_gpt)."""

    def __init__(self) -> None:
        self._index: Optional[faiss.Index] = None
        self._chunks: List[Dict[str, Any]] = []
        self._model: Optional[SentenceTransformer] = None
        self._model_name: str = ""

    @property
    def is_ready(self) -> bool:
        return self._index is not None and self._model is not None and bool(self._chunks)

    def index_path(self) -> Path:
        return _INDEX_PATH

    def meta_path(self) -> Path:
        return _META_PATH

    def load(self) -> None:
        if not _INDEX_PATH.is_file() or not _META_PATH.is_file():
            raise FileNotFoundError(
                f"Missing FAISS bundle in database/. "
                f"Run: python -m src.Research_and_publishing_guide_bot.create_embeddings\n"
                f"Expected:\n  {_INDEX_PATH}\n  {_META_PATH}"
            )

        with open(_META_PATH, encoding="utf-8") as f:
            payload = json.load(f)

        self._model_name = payload.get(
            "embedding_model", "sentence-transformers/all-mpnet-base-v2"
        )
        self._chunks = payload.get("chunks") or []
        if not self._chunks:
            raise ValueError("Metadata has no chunks")

        self._index = faiss.read_index(str(_INDEX_PATH))
        if self._index.ntotal != len(self._chunks):
            raise ValueError(
                f"FAISS ntotal={self._index.ntotal} but meta chunks={len(self._chunks)}"
            )

        self._model = SentenceTransformer(self._model_name)

    def ensure_loaded(self) -> None:
        if not self.is_ready:
            self.load()

    def _embed_query(self, query: str) -> np.ndarray:
        assert self._model is not None
        q = self._model.encode(
            [query],
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype("float32")
        q /= np.linalg.norm(q, axis=1, keepdims=True) + 1e-12
        return q

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        self.ensure_loaded()
        assert self._index is not None
        k = min(top_k, self._index.ntotal)
        if k < 1:
            return []

        qv = self._embed_query(query)
        scores, indices = self._index.search(qv, k)
        out: List[Dict[str, Any]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            row = dict(self._chunks[idx])
            row["similarity_score"] = float(score)
            out.append(row)
        return out

    def refine_search_query(self, user_query: str) -> str:
        """LLM: turn conversational question into a compact retrieval query."""
        text = call_gpt(
            system_prompt=QUERY_REWRITE_SYSTEM,
            user_prompt=f"User question:\n{user_query.strip()}",
            max_tokens=120,
            temperature=0.1,
        )
        return (text or "").strip()

    def answer(
        self,
        user_query: str,
        top_k: int = 5,
        use_query_refinement: bool = True,
    ) -> Dict[str, Any]:
        """
        Full RAG: optional query rewrite → retrieve → LLM answer with context.
        """
        self.ensure_loaded()

        search_q = self.refine_search_query(user_query) if use_query_refinement else user_query.strip()
        if not search_q:
            search_q = user_query.strip()

        hits = self.search(search_q, top_k=top_k)
        context_blocks = []
        for i, h in enumerate(hits, start=1):
            loc = f"{h.get('section_title', '')} → {h.get('subsection_title', '')}".strip(" →")
            context_blocks.append(f"[{i}] ({loc})\n{h.get('text', '')}")

        context = "\n\n---\n\n".join(context_blocks) if context_blocks else "(No passages retrieved.)"

        answer_text = call_gpt(
            system_prompt=ANSWER_SYSTEM,
            user_prompt=(
                f"Context from the guide:\n\n{context}\n\n"
                f"User question:\n{user_query.strip()}\n\n"
                "Answer:"
            ),
            max_tokens=1024,
            temperature=0.2,
        )

        return {
            "answer": answer_text or "",
            "retrieval_query": search_q,
            "sources": [
                {
                    "chunk_id": h.get("chunk_id"),
                    "section_title": h.get("section_title"),
                    "subsection_title": h.get("subsection_title"),
                    "similarity_score": h.get("similarity_score"),
                    "text_preview": (h.get("text") or "")[:400],
                }
                for h in hits
            ],
        }


_default_rag: Optional[ResearchGuideRAG] = None


def get_rag() -> ResearchGuideRAG:
    global _default_rag
    if _default_rag is None:
        _default_rag = ResearchGuideRAG()
    return _default_rag
