import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

try:
    from .input_validation import validate_input
    from .text_normalization import normalize_text
    from .keyword_extraction import extract_keywords
    from .keyword_scoring import score_keywords
    from .query_reconstruction import reconstruct_query
    from .data_fetching import fetch_papers
    from .response_mapping import map_response
    from .workflow_logging import append_session_record
except ImportError:  # pragma: no cover - supports running as a script
    project_root = Path(__file__).resolve().parents[2]
    sys.path.append(str(project_root))
    from src.semantic_literature_search.input_validation import validate_input
    from src.semantic_literature_search.text_normalization import normalize_text
    from src.semantic_literature_search.keyword_extraction import extract_keywords
    from src.semantic_literature_search.keyword_scoring import score_keywords
    from src.semantic_literature_search.query_reconstruction import reconstruct_query
    from src.semantic_literature_search.data_fetching import fetch_papers
    from src.semantic_literature_search.response_mapping import map_response
    from src.semantic_literature_search.workflow_logging import append_session_record


async def run_pipeline(
    title: str,
    abstract: str,
    limit: int = 10,
    offset: int = 0,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_session_id = session_id or str(uuid4())

    validated_title, validated_abstract = validate_input(title, abstract)
    normalized_title, normalized_abstract = normalize_text(
        validated_title, validated_abstract
    )
    phrases = extract_keywords(normalized_title, normalized_abstract)
    keyword_scores = score_keywords(normalized_title, normalized_abstract, phrases)
    query = reconstruct_query(normalized_title, keyword_scores)
    raw_payload = await fetch_papers(query=query, limit=limit, offset=offset)
    mapped_results = map_response(raw_payload)

    append_session_record(
        resolved_session_id,
        {
            "title": validated_title,
            "abstract": validated_abstract,
            "normalized_title": normalized_title,
            "normalized_abstract": normalized_abstract,
            "keywords": phrases,
            "keyword_scores": keyword_scores,
            "query": query,
            "response": mapped_results,
        },
    )

    return {"session_id": resolved_session_id, "results": mapped_results}


def _prompt_text(label: str) -> str:
    return input(f"{label}: ").strip()


if __name__ == "__main__":
    title_input = _prompt_text("Enter title")
    abstract_input = _prompt_text("Enter abstract")
    limit_input = _prompt_text("Enter limit (default 10)")
    offset_input = _prompt_text("Enter offset (default 0)")
    session_input = _prompt_text("Enter session id (optional)")

    limit_value = int(limit_input) if limit_input else 10
    offset_value = int(offset_input) if offset_input else 0

    async def _run() -> None:
        result = await run_pipeline(
            title=title_input,
            abstract=abstract_input,
            limit=limit_value,
            offset=offset_value,
            session_id=session_input or None,
        )
        print(result)

    asyncio.run(_run())
