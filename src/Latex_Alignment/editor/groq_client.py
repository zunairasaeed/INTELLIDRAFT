"""Groq client for the LaTeX Editor Agent.

Two modes:

* ``edit``     — the section already has content; rewrite per the instruction.
* ``generate`` — the section is empty; generate appropriate content.

The system prompts are crafted to keep LaTeX commands, citations, labels
and refs intact unless the user explicitly says otherwise.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from groq import Groq
except ImportError:  # pragma: no cover - guard for partial installs
    Groq = None  # type: ignore[assignment]

from ..models.schema import Section
from ..utils.regex_patterns import SECTION_RE

# ────────────────────────────────────────────────────────────────────────────
# Prompts
# ────────────────────────────────────────────────────────────────────────────
EDIT_PROMPT = """You are a precise LaTeX editor for academic papers.
You will receive the BODY of a section (the section header has already been stripped) and an edit instruction.

Rules:
1. Return ONLY valid LaTeX - no markdown, no explanation, no code fences.
2. DO NOT include the section header line (no \\section{}, \\subsection{}, \\subsubsection{}, \\paragraph{}, etc.) in your output. The header is preserved by the surrounding system.
3. Preserve all \\label{}, \\cite{}, \\ref{} commands exactly as-is unless the instruction says to change them.
4. Preserve all LaTeX environments (\\begin{}/\\end{}) unless the instruction says to change them.
5. Match the formality and style of academic writing.
6. Your output replaces the body only - it must start with the first content line and end with the last content line of the section."""

GENERATE_PROMPT = """You are a LaTeX content generator for academic papers.
This section currently has no content - only a header.
Generate appropriate academic content for this section based on the instruction and the paper's metadata.

Rules:
1. Return ONLY valid LaTeX - no markdown, no explanation, no code fences.
2. Use \\cite{KEY} format for citations - only keys provided in the context.
3. Use appropriate LaTeX environments (itemize, equation, figure, table) where relevant.
4. Match ACM academic paper style.
5. Your output is the section body - do NOT repeat the \\section{} header line."""

APPEND_PROMPT = """You are extending a section of a LaTeX academic paper.
You will receive the section's current body and an instruction describing what to ADD.
Generate ONLY the new content to append - do not repeat anything that already exists.

Rules:
1. Return ONLY valid LaTeX - no markdown, no explanation, no code fences.
2. DO NOT include the section header line (\\section{}, \\subsection{}, etc.).
3. DO NOT repeat existing sentences or paragraphs from the current body.
4. Preserve \\label{}, \\cite{}, \\ref{} commands exactly.
5. Use \\cite{KEY} only with keys provided in the context.
6. Match the formality and style of the existing prose."""

_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_MAX_BIB_KEYS = 30
_VALID_MODES = {"edit", "generate", "append"}


# ────────────────────────────────────────────────────────────────────────────
# Payload builder
# ────────────────────────────────────────────────────────────────────────────
def build_groq_payload(
    section: Section,
    instruction: str,
    bib_keys: list[str],
    metadata: dict[str, Any],
    mode: str = "auto",
) -> dict[str, Any]:
    """Build the ``{system, user, mode}`` triple sent to Groq.

    ``mode`` is one of ``edit``, ``generate``, ``append`` or ``auto``
    (auto-selects between edit and generate based on ``section.is_empty``).
    """

    if mode == "auto":
        mode = "generate" if section.is_empty else "edit"
    if mode not in _VALID_MODES:
        raise ValueError(f"Unknown mode '{mode}'. Expected one of {_VALID_MODES}.")

    if mode == "generate":
        system_prompt = GENERATE_PROMPT
    elif mode == "append":
        system_prompt = APPEND_PROMPT
    else:
        system_prompt = EDIT_PROMPT

    # ── Empty-section fallback ─────────────────────────────────────────────
    # When the section's body is empty the LLM otherwise tends to echo the
    # placeholder "(no content yet)" string back or produce a one-line stub.
    # We append an explicit "generate from scratch" directive so the same
    # prompt works for both implicit zones (abstract/acks where the body was
    # narrowed past \begin{}/\end{}) and explicit empty headers.
    if section.is_empty and mode != "append":
        system_prompt += (
            "\n\nThis section is EMPTY. Generate complete, publication-ready content "
            "from scratch based on the instruction. Do not echo placeholder text like "
            "'(no content yet)' and do not emit a section header."
        )

    title = metadata.get("title", "Unknown")
    capped_bib = ", ".join(bib_keys[:_MAX_BIB_KEYS])

    if mode == "generate" or (section.is_empty and mode != "append"):
        current_block = "(no content yet)"
        current_label = "Section is currently empty."
    else:
        body_lines = _strip_header_line(section.raw_lines)
        current_block = "".join(body_lines).rstrip("\n") or "(no content yet)"
        current_label = (
            "Current body (header excluded):"
            if mode == "edit"
            else "Existing content (DO NOT repeat):"
        )

    user_message = (
        f"Paper title: {title}\n"
        f"Available citation keys: {capped_bib}\n\n"
        f"Section: {section.title}\n"
        f"Depth: {section.cmd} (depth {section.depth})\n\n"
        f"{current_label}\n"
        f"---\n"
        f"{current_block}\n"
        f"---\n\n"
        f"Instruction: {instruction}\n"
    )

    return {"system": system_prompt, "user": user_message, "mode": mode}


# ────────────────────────────────────────────────────────────────────────────
# Groq invocation
# ────────────────────────────────────────────────────────────────────────────
_client: "Groq | None" = None


def _get_client() -> "Groq":
    if Groq is None:
        raise RuntimeError(
            "The 'groq' package is not installed. Add it to requirements.txt "
            "and run 'pip install groq'."
        )
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set in the environment. The LaTeX Editor "
                "Agent requires it to call Groq."
            )
        _client = Groq(api_key=api_key)
    return _client


def call_groq_edit(
    section: Section,
    instruction: str,
    bib_keys: list[str],
    metadata: dict[str, Any],
    mode: str = "auto",
    model: str = _DEFAULT_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> str:
    """Run the edit/generate/append call and return the raw LaTeX from Groq."""

    payload = build_groq_payload(section, instruction, bib_keys, metadata, mode=mode)

    response = _get_client().chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": payload["system"]},
            {"role": "user",   "content": payload["user"]},
        ],
    )
    raw = response.choices[0].message.content or ""
    cleaned = _strip_code_fences(raw)
    cleaned = _strip_leading_section_header(cleaned)
    return cleaned


# ────────────────────────────────────────────────────────────────────────────
# Output sanitisers
# Groq sometimes (a) wraps responses in ```latex ... ``` blocks and
# (b) re-emits the section header line even when told not to. Strip both.
# ────────────────────────────────────────────────────────────────────────────
def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1 :]
        else:
            cleaned = cleaned[3:]
    if cleaned.rstrip().endswith("```"):
        cleaned = cleaned.rstrip()
        cleaned = cleaned[: -3].rstrip()
    return cleaned


def _strip_leading_section_header(text: str) -> str:
    """Drop a leading ``\\section{...}`` / ``\\subsection{...}`` / ... line if present.

    The agent always preserves the original header line on disk, so a header
    in the response would create a duplicate.
    """

    if not text:
        return text
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and SECTION_RE.match(lines[0]):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines)


def _strip_header_line(raw_lines: list[str]) -> list[str]:
    """Return ``raw_lines`` with any leading ``\\section{...}`` style header removed."""

    if not raw_lines:
        return raw_lines
    body = list(raw_lines)
    if SECTION_RE.match(body[0]):
        body = body[1:]
    return body


__all__ = [
    "EDIT_PROMPT",
    "GENERATE_PROMPT",
    "build_groq_payload",
    "call_groq_edit",
]
