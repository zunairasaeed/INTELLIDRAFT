"""Stable hashing helpers used for section IDs and content fingerprints."""

from __future__ import annotations

import hashlib


def hash_text(text: str) -> str:
    """SHA-256 hex digest of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_hash(text: str, *, length: int = 12) -> str:
    """First ``length`` hex chars of SHA-256 — handy as a stable id."""
    return hash_text(text)[:length]
