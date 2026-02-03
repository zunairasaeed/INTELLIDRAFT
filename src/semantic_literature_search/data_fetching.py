import asyncio
import os
from typing import Any, Dict

import httpx

DEFAULT_FIELDS = (
    "title,abstract,authors,year,venue,citationCount,externalIds,url,openAccessPdf"
)
DEFAULT_TIMEOUT_SECONDS = 15.0


def _load_env_file() -> Dict[str, str]:
    env_data: Dict[str, str] = {}
    env_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    )
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                env_data[key.strip()] = value.strip()
                os.environ.setdefault(key.strip(), value.strip())
    return env_data


def _get_env(key: str, default: str | None = None) -> str | None:
    if os.getenv(key):
        return os.getenv(key)
    return _load_env_file().get(key, default)


async def fetch_papers(
    query: str,
    limit: int = 10,
    offset: int = 0,
    fields: str = DEFAULT_FIELDS,
    min_interval_seconds: float = 1.0,
    max_retries: int = 3,
) -> Dict[str, Any]:
    api_key = _get_env("SEMANTIC_SCHOLAR_API_KEY") or _get_env(
        "SEMANTICSCHOLAR_API_KEY"
    )
    if not api_key:
        raise RuntimeError("SEMANTIC_SCHOLAR_API_KEY is required.")

    base_url = _get_env(
        "SEMANTIC_SCHOLAR_BASE_URL", "https://api.semanticscholar.org/graph/v1"
    )
    search_url = f"{base_url.rstrip('/')}/paper/search"

    params = {
        "query": query,
        "limit": limit,
        "offset": offset,
        "fields": fields,
    }

    headers = {"x-api-key": api_key}

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
        for attempt in range(1, max_retries + 1):
            await asyncio.sleep(min_interval_seconds)
            response = await client.get(search_url, params=params, headers=headers)
            if response.status_code in {429, 504}:
                if attempt == max_retries:
                    raise RuntimeError("Semantic Scholar rate limit or timeout.")
                continue
            response.raise_for_status()
            return response.json()

    raise RuntimeError("Semantic Scholar request failed.")


def _prompt_text(label: str) -> str:
    return input(f"{label}: ").strip()


if __name__ == "__main__":
    query_input = _prompt_text("Enter query")
    limit_input = _prompt_text("Enter limit (default 10)")
    offset_input = _prompt_text("Enter offset (default 0)")

    limit_value = int(limit_input) if limit_input else 10
    offset_value = int(offset_input) if offset_input else 0

    async def _run() -> None:
        payload = await fetch_papers(
            query=query_input,
            limit=limit_value,
            offset=offset_value,
        )
        print(payload)

    asyncio.run(_run())
