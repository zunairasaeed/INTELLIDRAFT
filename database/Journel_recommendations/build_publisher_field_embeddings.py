import json
import os
import copy
from typing import List, Dict, Any, Tuple

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING_PATH = os.path.join(BASE_DIR, "publisher_field_mapping.json")
INDEX_PATH = os.path.join(BASE_DIR, "publisher_fields_faiss.index")
META_PATH = os.path.join(BASE_DIR, "publisher_fields_meta.json")

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def load_field_mapping(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_publisher_texts(
    publishers: Dict[str, Any]
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Build one rich embedding text PER PUBLISHER from the 'publishers' block.

    Each text captures:
      - Publisher full name
      - Core strength description
      - All best_for_fields (the most important semantic signal)
      - NOT ideal for fields (helps avoid false matches)
      - Example conferences/journals

    Returns:
      index_order : list of publisher short names  e.g. ["ACM","IEEE",...]
      meta_records: list of dicts, one per publisher, stored in meta JSON
      texts       : one embedding string per publisher
    """
    index_order: List[str] = []
    meta_records: List[Dict[str, Any]] = []
    texts: List[str] = []

    for pub_key, info in publishers.items():
        info = copy.deepcopy(info)  # never mutate original
        index_order.append(pub_key)

        full_name    = info.get("full_name", pub_key)
        core_strength = info.get("core_strength", "")
        best_for     = info.get("best_for_fields", [])
        not_ideal    = info.get("not_ideal_for", [])
        examples     = (
            info.get("example_conferences", []) +
            info.get("example_journals", []) +
            info.get("example_series", [])
        )

        parts: List[str] = []

        # 1. Publisher identity
        parts.append(f"Publisher: {full_name} ({pub_key})")

        # 2. Core strength — high signal sentence
        if core_strength:
            parts.append(f"Core strength: {core_strength}")

        # 3. Best-for fields — THE primary semantic signal
        if best_for:
            parts.append(
                f"Best suited for: {', '.join(best_for)}"
            )

        # 4. Not ideal for — negative signal helps cosine distance
        if not_ideal:
            parts.append(
                f"Not suitable for: {', '.join(not_ideal)}"
            )

        # 5. Example venues — extra keyword coverage
        if examples:
            parts.append(
                f"Example venues: {', '.join(examples)}"
            )

        text = ". ".join(p for p in parts if p.strip())
        texts.append(text)

        meta_records.append({
            "publisher_key":  pub_key,
            "full_name":      full_name,
            "core_strength":  core_strength,
            "best_for_fields": best_for,
            "not_ideal_for":  not_ideal,
            "official_portal": info.get(
                "official_journal_portal",
                info.get("official_portal", "")
            ),
        })

    return index_order, meta_records, texts


def create_embeddings(texts: List[str], model_name: str) -> np.ndarray:
    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=True,
        batch_size=32,
    )
    # Normalize → cosine similarity == inner product in IndexFlatIP
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-12
    embeddings = embeddings / norms
    return embeddings.astype("float32")


def build_faiss_index(embeddings: np.ndarray) -> faiss.Index:
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    return index


def validate_meta(
    index_order: List[str],
    meta_records: List[Dict[str, Any]]
) -> None:
    if len(index_order) != len(meta_records):
        raise ValueError(
            f"ALIGNMENT ERROR: index_order has {len(index_order)} entries "
            f"but meta_records has {len(meta_records)}."
        )
    for i, (key, rec) in enumerate(zip(index_order, meta_records)):
        if key != rec["publisher_key"]:
            raise ValueError(
                f"MISMATCH at position {i}: "
                f"index_order='{key}' vs meta_record key='{rec['publisher_key']}'"
            )
    print(f"[validate_meta] OK — {len(index_order)} publishers aligned correctly.")


def main() -> None:
    if not os.path.exists(MAPPING_PATH):
        raise FileNotFoundError(f"Mapping file not found: {MAPPING_PATH}")

    mapping  = load_field_mapping(MAPPING_PATH)
    publishers: Dict[str, Any] = copy.deepcopy(mapping.get("publishers", {}))

    if not publishers:
        raise RuntimeError("No 'publishers' block found in mapping file.")

    index_order, meta_records, texts = build_publisher_texts(publishers)

    # ── Debug: show exactly what gets embedded ──────────────────────────────
    print("\n[DEBUG] Embedding texts per publisher:")
    for i, (pub, text) in enumerate(zip(index_order, texts)):
        print(f"\n  [{i}] {pub}")
        for line in text.split(". "):
            print(f"       {line}.")
    print()
    # ────────────────────────────────────────────────────────────────────────

    embeddings = create_embeddings(texts, EMBEDDING_MODEL_NAME)

    print(f"\n[INFO] Embeddings shape : {embeddings.shape}")
    print(f"[INFO] All norms ≈ 1.0  : "
          f"{np.allclose(np.linalg.norm(embeddings, axis=1), 1.0)}")

    index = build_faiss_index(embeddings)
    faiss.write_index(index, INDEX_PATH)
    print(f"\n[OK] Saved FAISS index  → {INDEX_PATH}")

    validate_meta(index_order, meta_records)

    meta = {
        "model_name":   EMBEDDING_MODEL_NAME,
        "index_order":  index_order,          # ["ACM", "IEEE", "Springer", "Elsevier"]
        "publishers":   meta_records,         # full detail per publisher, same order
    }

    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[OK] Saved metadata     → {META_PATH}")
    print(f"\n[SUMMARY] {len(index_order)} publishers indexed:")
    for i, pub in enumerate(index_order):
        fields = meta_records[i]["best_for_fields"]
        print(f"  {i}. {pub:10s} → {len(fields)} fields: {', '.join(fields[:3])}...")


if __name__ == "__main__":
    main()