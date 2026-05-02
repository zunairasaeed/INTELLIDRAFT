"""
input_processor.py
STEP 1-3: Input validation, sanitization, keyword extraction, query reconstruction.
Pure Python + NLTK. Output in two forms: (1) query string as-is, (2) dict with title, abstract, keywords.
"""

import json
import re
from typing import Any, Dict, List, Optional

from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize

from ..utils.text_utils import is_meaningful_text


def _ensure_nltk() -> None:
    """Ensure NLTK resources exist (runs once)."""
    try:
        stopwords.words("english")
    except LookupError:
        import nltk

        nltk.download("punkt", quiet=True)
        nltk.download("stopwords", quiet=True)


def validate_input(title: str, abstract: str) -> Dict[str, Any]:
    """
    Validate that inputs are non-empty and contain meaningful text.
    Returns Dict with keys: valid (bool), errors (list).
    """
    result: Dict[str, Any] = {"valid": True, "errors": []}

    if not title or not isinstance(title, str):
        result["valid"] = False
        result["errors"].append("Title is required and must be a string")

    if not abstract or not isinstance(abstract, str):
        result["valid"] = False
        result["errors"].append("Abstract is required and must be a string")

    if title and len(title.strip()) < 10:
        result["valid"] = False
        result["errors"].append("Title too short (min 10 characters)")

    if abstract and len(abstract.strip()) < 50:
        result["valid"] = False
        result["errors"].append("Abstract too short (min 50 characters)")

    if title and not is_meaningful_text(title, min_alpha_ratio=0.3, min_length=10):
        result["valid"] = False
        result["errors"].append("Title lacks meaningful text")

    if abstract and not is_meaningful_text(abstract, min_alpha_ratio=0.3, min_length=50):
        result["valid"] = False
        result["errors"].append("Abstract lacks meaningful text")

    return result


def sanitize_text(text: str) -> str:
    """
    Process text: lowercase, remove hyperlinks/emails, remove unwanted symbols, collapse spaces.
    """
    if not text:
        return ""

    # Lowercase
    text = text.lower()

    # Remove hyperlinks and emails
    text = re.sub(r"(?:https?|www\.)\S+", "", text)
    text = re.sub(r"[\w.-]+@[\w.-]+\.\w+", "", text)

    # Keep only letters, numbers, spaces, and basic punctuation; replace rest with space
    text = re.sub(r"[^a-z0-9\s\-/.,;():]+", " ", text)

    # Collapse multiple spaces/newlines/tabs into single space
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def extract_keywords(
    title: str, abstract: str, max_single: int = 30, max_phrases: int = 20
) -> Dict[str, List[str]]:
    """
    Extract keywords using NLTK: single-word keywords and phrase keywords separately.
    Returns Dict with keys: single_word_keywords, phrase_keywords.
    """
    _ensure_nltk()

    # Title weighted 2x
    combined = f"{title} {title} {abstract}"
    tokens = word_tokenize(combined)
    stop_words = set(stopwords.words("english"))

    # Single-word keywords: alpha, length > 2, not stopword
    filtered_tokens = [
        t for t in tokens
        if t.isalpha() and len(t) > 2 and t not in stop_words
    ]
    seen_single: set = set()
    single_word_keywords: List[str] = []
    for w in filtered_tokens:
        if w not in seen_single:
            seen_single.add(w)
            single_word_keywords.append(w)

    # Phrase keywords: consecutive bigrams from original token sequence
    phrases: List[str] = []
    seen_phrase: set = set()
    for i in range(len(filtered_tokens) - 1):
        bigram = f"{filtered_tokens[i]} {filtered_tokens[i+1]}"
        if len(bigram) > 5 and bigram not in seen_phrase:
            seen_phrase.add(bigram)
            phrases.append(bigram)

    return {
        "single_word_keywords": single_word_keywords[:max_single],
        "phrase_keywords": phrases[:max_phrases],
    }


def normalize_query(
    single_word_keywords: List[str],
    phrase_keywords: List[str],
    identified_field: Optional[str] = None,
) -> str:
    """
    Build a single normalized query string for LLM context from keywords.
    """
    # Combine: phrases first (more specific), then single words
    combined = phrase_keywords + single_word_keywords
    core = combined[:15]

    if not core:
        return "general computer science research"

    if identified_field:
        base = f"Research in {identified_field.lower()} focusing on "
    else:
        base = "Research focusing on "

    if len(core) <= 3:
        kw_str = ", ".join(core)
    else:
        primary = ", ".join(core[:3])
        secondary = ", ".join(core[3:8])
        kw_str = f"{primary}, with aspects of {secondary}"

    return base + kw_str + "."


def build_single_output_dict(
    clean_title: str,
    clean_abstract: str,
    single_word_keywords: List[str],
    phrase_keywords: List[str],
    query: str,
) -> Dict[str, Any]:
    """
    One output: single dictionary with normalized query and a flat keyword list.

    Example:
    {
      "query": "...",
      "keywords": ["intrusion detection", "deep learning", "cybersecurity", ...]
    }
    """
    # Combine single-word and phrase keywords into one list, preserving order and uniqueness
    combined = single_word_keywords + phrase_keywords
    seen: set[str] = set()
    keywords: List[str] = []
    for kw in combined:
        if kw not in seen:
            seen.add(kw)
            keywords.append(kw)

    return {
        "query": query,
        "keywords": keywords,
    }


def process_input(title: str, abstract: str) -> Dict[str, Any]:
    """
    Run full pipeline: validate -> sanitize -> extract keywords -> normalize query.
    Returns one dictionary: success, error (if failed), and a single "output" dict with all info.
    """
    validation = validate_input(title, abstract)
    if not validation["valid"]:
        error_msg = "; ".join(validation["errors"])
        return {
            "success": False,
            "error": error_msg,
            "output": {"error": error_msg},
        }

    clean_title = sanitize_text(title)
    clean_abstract = sanitize_text(abstract)
    kw_result = extract_keywords(clean_title, clean_abstract)
    single_word_keywords = kw_result["single_word_keywords"]
    phrase_keywords = kw_result["phrase_keywords"]
    query = normalize_query(single_word_keywords, phrase_keywords)

    output = build_single_output_dict(
        clean_title, clean_abstract, single_word_keywords, phrase_keywords, query
    )

    return {
        "success": True,
        "output": output,
    }


def _split_user_text(user_text: str) -> Dict[str, str]:
    """
    Heuristic parser for messy human input.
    Tries labeled patterns first, then falls back to first-line title + rest abstract.
    """
    raw = (user_text or "").strip()
    if not raw:
        return {"title": "", "abstract": ""}

    # Normalize line endings and trim noisy spacing.
    text = re.sub(r"\r\n?", "\n", raw)

    title_match = re.search(r"(?:^|\n)\s*title\s*:\s*(.+)", text, flags=re.IGNORECASE)
    abs_match = re.search(
        r"(?:^|\n)\s*(?:abstract|summary|problem|description)\s*:\s*(.+)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    title = title_match.group(1).strip() if title_match else ""
    abstract = abs_match.group(1).strip() if abs_match else ""

    # If only one labeled part exists, infer the missing piece.
    if title and not abstract:
        abstract = text
    elif abstract and not title:
        title = abstract.split("\n", 1)[0][:140].strip()

    # No labels: first line as title, remaining text as abstract.
    if not title and not abstract:
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if not lines:
            return {"title": "", "abstract": ""}
        if len(lines) == 1:
            one = lines[0]
            mid = max(20, min(len(one) // 3, 90))
            title = one[:mid].strip()
            abstract = one
        else:
            title = lines[0]
            abstract = " ".join(lines[1:]).strip()

    # Strengthen minimal length for downstream validator.
    if len(title) < 10:
        title = (title + " " + abstract[:80]).strip()[:140]
    if len(abstract) < 50:
        abstract = f"{title}. {abstract}".strip()

    return {"title": title, "abstract": abstract}


def process_user_query_text(user_text: str) -> Dict[str, Any]:
    """
    New layer for chatbot-style raw text input.
    Converts messy user text into title/abstract, then reuses existing process_input().
    """
    parsed = _split_user_text(user_text)
    title = parsed["title"]
    abstract = parsed["abstract"]

    result = process_input(title, abstract)
    if not result.get("success"):
        return result

    # Preserve parsed fields so API/debug can inspect what was inferred.
    out = result.get("output", {})
    out["parsed_title"] = title
    out["parsed_abstract"] = abstract
    return {
        "success": True,
        "output": out,
    }


if __name__ == "__main__":
    title_in = input("Enter title: ").strip()
    abstract_in = input("Enter abstract: ").strip()
    result = process_input(title_in, abstract_in)
    print(json.dumps(result["output"], indent=2))
