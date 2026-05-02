"""
pipeline_run.py — Publisher mapping pipeline: title + abstract → recommendation.

Runs: InputProcessor (validate, sanitize, keywords, query) → LLM Field Analyzer (field, domain, publisher).
Use from CLI or via run_pipeline(title, abstract).
"""

import json
import sys
from pathlib import Path

# Ensure project root is on path for call_gpt
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from .input_processor import process_input, process_user_query_text
from .llm_field_analyzer import analyze_research_field


def _empty_recommendation() -> dict:
    """Output shape when pipeline fails before recommendation."""
    return {
        "best_publisher": "",
        "why_this_domain": "",
        "why_this_publisher": "",
        "journal_finder_link": "",
        "search_keywords": [],
        "runner_up": {"publisher": "", "portal": ""},
    }


def run_pipeline(title: str = "", abstract: str = "", user_input: str = "") -> dict:
    """
    Run the full publisher-mapping pipeline.

    Input: title (str), abstract (str).
    Output: single dict with keys:
      identified_field, domain_type, application_area,
      publisher_recommendation (best_publisher, why_this_domain, why_this_publisher,
        journal_finder_link, search_keywords, runner_up),
      chatbot_response (str when success),
      success (bool), error (None on success, else str).
    """
    # Step 1: Input processor (structured title/abstract OR messy user input)
    if user_input and user_input.strip():
        step1 = process_user_query_text(user_input)
    else:
        step1 = process_input(title, abstract)
    if not step1.get("success"):
        return {
            "identified_field": "",
            "domain_type": "",
            "application_area": "",
            "publisher_recommendation": _empty_recommendation(),
            "chatbot_response": "",
            "success": False,
            "error": step1.get("error", "Input processing failed"),
        }

    out = step1["output"]
    query = out.get("query", "")
    keywords = out.get("keywords", [])

    # Step 2: LLM field analyzer
    result = analyze_research_field(keywords=keywords, query=query)

    rec = result.get("publisher_recommendation") or _empty_recommendation()
    if rec.get("runner_up"):
        ru = rec["runner_up"]
        rec["runner_up"] = {
            "publisher": ru.get("publisher") or "",
            "portal": ru.get("portal") or "",
        }

    # Normalize to consistent shape (analyzer already returns this shape)
    return {
        "identified_field": result.get("identified_field") or "",
        "domain_type": result.get("domain_type") or "",
        "application_area": result.get("application_area"),
        "publisher_recommendation": rec,
        "chatbot_response": result.get("chatbot_response", ""),
        "success": result.get("success", False),
        "error": None if result.get("success") else (result.get("error") or "Unknown error"),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Publisher mapping pipeline: title + abstract → field + publisher recommendation"
    )
    parser.add_argument("--title", "-t", type=str, required=True, help="Paper title (string)")
    parser.add_argument("--abstract", "-a", type=str, required=True, help="Paper abstract (string)")
    parser.add_argument("--pretty", "-p", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    result = run_pipeline(title=args.title, abstract=args.abstract)
    dump_kw = {"indent": 2} if args.pretty else {}
    print(json.dumps(result, **dump_kw))
