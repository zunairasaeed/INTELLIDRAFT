import re
from typing import List

_SENTENCE_SPLIT = re.compile(r"[.!?;:\n]+")
_NON_ALPHA = re.compile(r"[^a-z0-9\s\-]")

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "he",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
    "this",
    "these",
    "those",
    "we",
    "our",
    "they",
    "their",
    "using",
    "use",
}


def _split_to_phrases(text: str) -> List[str]:
    phrases: List[str] = []
    sentences = _SENTENCE_SPLIT.split(text)
    for sentence in sentences:
        cleaned = _NON_ALPHA.sub(" ", sentence)
        tokens = [token for token in cleaned.split() if token]
        phrase: List[str] = []
        for token in tokens:
            if token in _STOPWORDS:
                if len(phrase) >= 2:
                    phrases.append(" ".join(phrase))
                phrase = []
            else:
                phrase.append(token)
        if len(phrase) >= 2:
            phrases.append(" ".join(phrase))
    return phrases


def extract_keywords(title: str, abstract: str) -> List[str]:
    text = f"{title} {abstract}".strip()
    phrases = _split_to_phrases(text)

    seen = set()
    unique_phrases = []
    for phrase in phrases:
        if phrase not in seen:
            unique_phrases.append(phrase)
            seen.add(phrase)
    return unique_phrases


def _prompt_text(label: str) -> str:
    return input(f"{label}: ").strip()


if __name__ == "__main__":
    title_input = _prompt_text("Enter title")
    abstract_input = _prompt_text("Enter abstract")
    keywords = extract_keywords(title_input, abstract_input)
    print("Extracted keywords:", keywords)
