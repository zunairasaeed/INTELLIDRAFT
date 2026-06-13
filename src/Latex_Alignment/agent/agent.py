"""Agent — natural language command → JSON action (Groq or Claude)."""

from __future__ import annotations

import json
import os
import re

import httpx

from ..parser.parser import DocumentTree, to_tree_json

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SYSTEM_PROMPT = """You are a LaTeX editing agent for ACM academic papers.

You will be given the document structure as JSON and a user command.
Output ONLY a single valid JSON action object. No explanation. No markdown. No LaTeX.

=== DOCUMENT STRUCTURE ===
{tree_json}

=== AVAILABLE CITATION KEYS ===
{bib_keys}

=== ACTIONS ===

Add paragraph to a section:
{{"action":"add_paragraph","target":"SECTION_ID","content":"plain text","position":"end"}}
position options: "start" | "end" | {{"after_index": N}}

Add top-level section:
{{"action":"add_section","after":"SECTION_ID","label":"Section Name"}}

Add subsection:
{{"action":"add_subsection","parent":"SECTION_ID","label":"Subsection Name"}}

Add subsubsection:
{{"action":"add_subsubsection","parent":"SUBSECTION_ID","label":"Name"}}

Rename section:
{{"action":"rename","target":"SECTION_ID","new_label":"New Name"}}

Delete section (and all children):
{{"action":"delete","target":"SECTION_ID"}}

Rewrite full content of a section:
{{"action":"rewrite","target":"SECTION_ID","content":"new plain text"}}

Replace a specific paragraph (0-indexed):
{{"action":"replace_paragraph","target":"SECTION_ID","index":0,"content":"new text"}}

Move section:
{{"action":"move","target":"SECTION_ID","after":"SECTION_ID"}}

Change document title:
{{"action":"set_title","content":"New Title"}}

Ask for clarification:
{{"action":"clarify","question":"What did you mean by X?"}}

=== RULES ===
- "target", "parent", "after" must be exact IDs from the section tree above
- "content" is always plain English — never write LaTeX commands in content
- Never touch preamble, CCSXML block, bibliography
- If user says "section 2" map it to the second section ID in the tree
- If user says "the intro" map it to the introduction section ID
- If user says "add a section" and gives no position, add it at the end of body
- If the command is genuinely ambiguous, output clarify
- One action per response, always
- Output raw JSON only — no ```json fences"""


def call_llm(system: str, user_message: str) -> str:
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        return _call_groq(system, user_message, groq_key)

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        return _call_claude(system, user_message, anthropic_key)

    raise RuntimeError(
        "No LLM configured. Set GROQ_API_KEY or ANTHROPIC_API_KEY in your environment or .env file."
    )


def _call_groq(system: str, user_message: str, api_key: str) -> str:
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    response = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.2,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system + "\nReply with a single JSON object only."},
                {"role": "user", "content": user_message},
            ],
        },
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def _call_claude(system: str, user_message: str, api_key: str) -> str:
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            "max_tokens": 512,
            "system": system,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()["content"][0]["text"].strip()


def parse_action_json(raw: str) -> dict:
    raw = re.sub(r"```(?:json)?", "", raw).strip("` \n")
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"No valid JSON found in LLM response: {raw!r}")


def get_action(tree: DocumentTree, command: str, bib_keys: list | None = None) -> dict:
    tree_json = json.dumps(to_tree_json(tree), indent=2)
    bib_keys_str = ", ".join(bib_keys) if bib_keys else "none provided"
    system = SYSTEM_PROMPT.format(tree_json=tree_json, bib_keys=bib_keys_str)

    try:
        raw = call_llm(system, command)
        return parse_action_json(raw)
    except (json.JSONDecodeError, ValueError):
        return {
            "action": "clarify",
            "question": "I couldn't understand that command. Could you rephrase?",
        }
    except RuntimeError as exc:
        return {"action": "clarify", "question": str(exc)}
