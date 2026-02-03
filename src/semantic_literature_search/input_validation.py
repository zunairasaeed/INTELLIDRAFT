from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationError(Exception):
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


def validate_input(title: str, abstract: str) -> tuple[str, str]:
    if title is None or not isinstance(title, str):
        raise ValidationError("title", "title must be a string")
    if abstract is None or not isinstance(abstract, str):
        raise ValidationError("abstract", "abstract must be a string")

    cleaned_title = title.strip()
    if len(cleaned_title) < 10:
        raise ValidationError("title", "title must be at least 10 characters")

    abstract_words = [word for word in abstract.strip().split() if word]
    if len(abstract_words) < 20:
        raise ValidationError("abstract", "abstract must be at least 20 words")

    return cleaned_title, abstract.strip()


def _prompt_text(label: str) -> str:
    return input(f"{label}: ").strip()


if __name__ == "__main__":
    try:
        title_input = _prompt_text("Enter title")
        abstract_input = _prompt_text("Enter abstract")
        result = validate_input(title_input, abstract_input)
        print("Validated output:", result)
    except ValidationError as exc:
        print(f"Validation error: {exc}")
