import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

try:
    from .keyword_extraction import extract_keywords
except ImportError:  # pragma: no cover - supports running as a script
    project_root = Path(__file__).resolve().parents[2]
    sys.path.append(str(project_root))
    from src.semantic_literature_search.keyword_extraction import extract_keywords

_WORD_BOUNDARY = r"(?<!\w){phrase}(?!\w)"

_GENERIC_PHRASES = {
    "this study",
    "this paper",
    "our study",
    "our paper",
    "results show",
    "experimental results",
    "method",
    "approach",
    "analysis",
    "data",
    "model",
    "framework",
    "system",
}


def _count_phrase(text: str, phrase: str) -> int:
    pattern = _WORD_BOUNDARY.format(phrase=re.escape(phrase))
    return len(re.findall(pattern, text))


def _phrase_length(phrase: str) -> int:
    return len([token for token in phrase.split() if token])


def score_keywords(
    title: str, abstract: str, phrases: List[str], max_phrases: int = 8
) -> Dict[str, float]:
    scored: List[Tuple[str, float]] = []
    for phrase in phrases:
        phrase_len = _phrase_length(phrase)
        if phrase_len == 0:
            continue

        abstract_freq = _count_phrase(abstract, phrase)
        title_freq = _count_phrase(title, phrase)
        title_boost = 1.5 if title_freq > 0 else 1.0
        noise_penalty = 0.6 if phrase in _GENERIC_PHRASES else 1.0

        score = (abstract_freq + title_freq * 2 + phrase_len) * title_boost * noise_penalty
        scored.append((phrase, float(score)))

    scored.sort(key=lambda item: item[1], reverse=True)
    top = scored[:max_phrases]
    return {phrase: score for phrase, score in top}


def _prompt_text(label: str) -> str:
    return input(f"{label}: ").strip()


if __name__ == "__main__":
    title_input = _prompt_text("Enter title")
    abstract_input = _prompt_text("Enter abstract")
    extracted_phrases = extract_keywords(title_input, abstract_input)
    scores = score_keywords(title_input, abstract_input, extracted_phrases)
    print("Keyword scores:", scores)
