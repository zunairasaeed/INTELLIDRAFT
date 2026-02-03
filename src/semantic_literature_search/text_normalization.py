import re

_URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
_INLINE_YEAR_PAREN = re.compile(r"\(\s*\d{4}[a-z]?\s*\)")
_INLINE_BRACKET_CITE = re.compile(r"\[[0-9,\s\-]+\]")
_MULTI_SPACE = re.compile(r"\s+")


def _normalize_quotes(text: str) -> str:
    return (
        text.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )


def normalize_text(title: str, abstract: str) -> tuple[str, str]:
    cleaned_title = _normalize_quotes(title)
    cleaned_abstract = _normalize_quotes(abstract)

    cleaned_title = _URL_PATTERN.sub("", cleaned_title)
    cleaned_abstract = _URL_PATTERN.sub("", cleaned_abstract)

    cleaned_title = _INLINE_YEAR_PAREN.sub("", cleaned_title)
    cleaned_abstract = _INLINE_YEAR_PAREN.sub("", cleaned_abstract)

    cleaned_title = _INLINE_BRACKET_CITE.sub("", cleaned_title)
    cleaned_abstract = _INLINE_BRACKET_CITE.sub("", cleaned_abstract)

    cleaned_title = cleaned_title.lower()
    cleaned_abstract = cleaned_abstract.lower()

    cleaned_title = _MULTI_SPACE.sub(" ", cleaned_title).strip()
    cleaned_abstract = _MULTI_SPACE.sub(" ", cleaned_abstract).strip()

    return cleaned_title, cleaned_abstract


def _prompt_text(label: str) -> str:
    return input(f"{label}: ").strip()


if __name__ == "__main__":
    title_input = _prompt_text("Enter title")
    abstract_input = _prompt_text("Enter abstract")
    normalized = normalize_text(title_input, abstract_input)
    print("Normalized output:", normalized)
