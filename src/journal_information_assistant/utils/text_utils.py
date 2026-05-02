"""Shared text helpers for journal information assistant."""


def is_meaningful_text(text: str, min_alpha_ratio: float = 0.3, min_length: int = 10) -> bool:
    """
    Check if text has meaningful content (not just symbols, whitespace, or repeated chars).
    Returns True if text passes basic content checks.
    """
    if not text or not isinstance(text, str):
        return False
    stripped = text.strip()
    if len(stripped) < min_length:
        return False
    alpha_count = sum(1 for c in stripped if c.isalpha())
    if alpha_count / len(stripped) < min_alpha_ratio:
        return False
    return True
