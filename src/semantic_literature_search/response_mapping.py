import json
from typing import Any, Dict, List


def _resolve_url(paper: Dict[str, Any]) -> str:
    open_access = paper.get("openAccessPdf") or {}
    if open_access.get("url"):
        return open_access["url"]

    external_ids = paper.get("externalIds") or {}
    arxiv_id = external_ids.get("ArXiv")
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"

    return paper.get("url") or ""


def map_response(raw_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for paper in raw_payload.get("data", []):
        results.append(
            {
                "title": paper.get("title") or "",
                "abstract": paper.get("abstract") or "",
                "authors": paper.get("authors") or [],
                "year": paper.get("year"),
                "venue": paper.get("venue") or "",
                "citationCount": paper.get("citationCount") or 0,
                "url": _resolve_url(paper),
                "source": "SemanticScholar",
            }
        )
    return results


def _prompt_text(label: str) -> str:
    return input(f"{label}: ").strip()


if __name__ == "__main__":
    raw_json = _prompt_text("Enter raw Semantic Scholar JSON payload")
    if not raw_json:
        print("No payload provided.")
    else:
        parsed = json.loads(raw_json)
        mapped = map_response(parsed)
        print(mapped)
