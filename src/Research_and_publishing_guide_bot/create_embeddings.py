"""
Build FAISS index + metadata for the Research & Publishing Guide bot.

Reads existing chunk texts from (repo root):

    database/paper_guide_rag_meta.json

Writes/overwrites (same folder):

    database/paper_guide_rag.faiss
    database/paper_guide_rag_meta.json  (embedding_model + num_vectors updated)

Run from project root:
    python -m src.Research_and_publishing_guide_bot.create_embeddings
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

# Repo root = parent of src/ — this package dir is repo/src/Research_and_publishing_guide_bot/
_BOT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BOT_DIR.parents[1]
_DATABASE_DIR = _REPO_ROOT / "database"

_SOURCE_META_PATH = _DATABASE_DIR / "paper_guide_rag_meta.json"
_INDEX_PATH = _DATABASE_DIR / "paper_guide_rag.faiss"
_OUTPUT_META_PATH = _DATABASE_DIR / "paper_guide_rag_meta.json"

EMBEDDING_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"


def validate_alignment(texts: List[str], records: List[Dict[str, Any]]) -> None:
    if len(texts) != len(records):
        raise ValueError(f"Alignment error: {len(texts)} texts vs {len(records)} meta rows")
    for i, (t, r) in enumerate(zip(texts, records)):
        if t != r["text"]:
            raise ValueError(f"Mismatch at {i}, chunk_id={r.get('chunk_id')}")


def encode_for_faiss(texts: List[str], model_name: str) -> np.ndarray:
    """
    Encode with L2-normalized vectors for IndexFlatIP (cosine similarity).
    Uses SentenceTransformer.normalize_embeddings=True, then re-normalizes for storage.
    """
    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype("float32")
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-12
    embeddings = embeddings / norms
    if not np.allclose(np.linalg.norm(embeddings, axis=1), 1.0, atol=1e-3):
        raise RuntimeError("Embeddings are not unit-norm before FAISS add")
    return embeddings


def build_faiss_index(embeddings: np.ndarray) -> faiss.Index:
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    return index


def main() -> None:
    if not _SOURCE_META_PATH.is_file():
        raise FileNotFoundError(
            f"Missing chunk metadata: {_SOURCE_META_PATH}\n"
            "Place paper_guide_rag_meta.json (with a `chunks` array) under database/."
        )

    _DATABASE_DIR.mkdir(parents=True, exist_ok=True)

    backup = _OUTPUT_META_PATH.with_suffix(_OUTPUT_META_PATH.suffix + ".bak")
    try:
        shutil.copy2(_OUTPUT_META_PATH, backup)
    except OSError:
        pass

    with open(_SOURCE_META_PATH, encoding="utf-8") as f:
        payload: Dict[str, Any] = json.load(f)

    chunks: List[Dict[str, Any]] = payload.get("chunks") or []
    if not chunks:
        raise ValueError(f"No chunks in {_SOURCE_META_PATH}")

    texts = [str(c["text"]) for c in chunks]
    validate_alignment(texts, chunks)
    print(f"[create_embeddings] Chunks from rag meta: {len(texts)}")

    embeddings = encode_for_faiss(texts, EMBEDDING_MODEL_NAME)
    print(f"[create_embeddings] Embedding shape: {embeddings.shape}")

    index = build_faiss_index(embeddings)
    faiss.write_index(index, str(_INDEX_PATH))

    payload["embedding_model"] = EMBEDDING_MODEL_NAME
    payload["index_type"] = "IndexFlatIP"
    payload["metric"] = "cosine_via_normalized_inner_product"
    payload["num_vectors"] = int(index.ntotal)
    payload["chunks"] = chunks
    payload["embeddings_source"] = "paper_guide_rag_meta.json (chunk texts re-encoded)"

    with open(_OUTPUT_META_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[create_embeddings] Wrote index -> {_INDEX_PATH}")
    print(f"[create_embeddings] Wrote meta  -> {_OUTPUT_META_PATH}")


if __name__ == "__main__":
    main()
