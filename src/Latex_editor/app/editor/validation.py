from __future__ import annotations

from dataclasses import dataclass
import re


BEGIN_RE = re.compile(r"\\begin\{([^\}]+)\}")
END_RE = re.compile(r"\\end\{([^\}]+)\}")
CITE_RE = re.compile(r"\\cite\{[^\}]+\}")
LABEL_RE = re.compile(r"\\label\{[^\}]+\}")


@dataclass
class ValidationResult:
    ok: bool
    error: str | None = None


def braces_balanced(text: str) -> bool:
    count = 0
    for ch in text:
        if ch == "{":
            count += 1
        elif ch == "}":
            count -= 1
            if count < 0:
                return False
    return count == 0


def envs_balanced(text: str) -> bool:
    stack: list[str] = []
    for line in text.splitlines():
        for b in BEGIN_RE.finditer(line):
            stack.append(b.group(1))
        for e in END_RE.finditer(line):
            if not stack or stack[-1] != e.group(1):
                return False
            stack.pop()
    return not stack


def validate_latex_block(text: str, require_citations: list[str] | None = None, require_labels: list[str] | None = None) -> ValidationResult:
    if not braces_balanced(text):
        return ValidationResult(False, "Unbalanced braces")

    if not envs_balanced(text):
        return ValidationResult(False, "Unbalanced environments")

    if require_citations:
        for cite in require_citations:
            if cite not in text:
                return ValidationResult(False, f"Missing citation: {cite}")

    if require_labels:
        for label in require_labels:
            if label not in text:
                return ValidationResult(False, f"Missing label: {label}")

    return ValidationResult(True)
