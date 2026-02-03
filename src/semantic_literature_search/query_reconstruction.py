import sys
from pathlib import Path
from typing import Dict, List

try:
    from .keyword_extraction import extract_keywords
    from .keyword_scoring import score_keywords
except ImportError:  # pragma: no cover - supports running as a script
    project_root = Path(__file__).resolve().parents[2]
    sys.path.append(str(project_root))
    from src.semantic_literature_search.keyword_extraction import extract_keywords
    from src.semantic_literature_search.keyword_scoring import score_keywords


def _format_phrase(phrase: str) -> str:
    if " " in phrase:
        return f'"{phrase}"'
    return phrase


def reconstruct_query(title: str, keyword_scores: Dict[str, float]) -> str:
    ranked_keywords = sorted(
        keyword_scores.items(), key=lambda item: item[1], reverse=True
    )
    top_keywords: List[str] = [key for key, _ in ranked_keywords]

    primary = top_keywords[:3]
    secondary = top_keywords[3:5]

    parts = [title.strip()]
    parts.extend(_format_phrase(phrase) for phrase in primary)
    parts.extend(_format_phrase(phrase) for phrase in secondary)

    return " ".join([part for part in parts if part]).strip()


def _prompt_text(label: str) -> str:
    return input(f"{label}: ").strip()


if __name__ == "__main__":
    title_input = _prompt_text("Enter title")
    abstract_input = _prompt_text("Enter abstract")
    phrases = extract_keywords(title_input, abstract_input)
    scores = score_keywords(title_input, abstract_input, phrases)
    query = reconstruct_query(title_input, scores)
    print("Reconstructed query:", query)
