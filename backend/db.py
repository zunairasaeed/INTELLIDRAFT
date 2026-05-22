import logging
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from supabase import create_client, Client

# Load repo-root `.env` (parent of ``backend/``), not cwd-only `load_dotenv()`.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DOTENV_PATH = _PROJECT_ROOT / ".env"

load_dotenv(_DOTENV_PATH)
_FILE_ENV: dict[str, str | None] = (
    dict(dotenv_values(_DOTENV_PATH)) if _DOTENV_PATH.is_file() else {}
)
log = logging.getLogger(__name__)


def _merged_env(name: str) -> str:
    """Prefer non-empty process env; otherwise value from repo `.env`."""
    from_proc = (os.getenv(name) or "").strip()
    if from_proc:
        return from_proc
    raw = _FILE_ENV.get(name)
    return (raw or "").strip() if isinstance(raw, str) else ""


def _supabase_connect_config() -> tuple[str, str]:
    """
    Server-side client: prefers **service_role** JWT so auth + RPC/storage calls
    work reliably from this process.

    Set `SUPABASE_SERVICE_KEY` from Dashboard → Settings → API → ``service_role``.
    Falls back to ``SUPABASE_KEY`` if the service key is unset.
    """
    url = _merged_env("SUPABASE_URL").rstrip("/")

    key = _merged_env("SUPABASE_SERVICE_KEY") or _merged_env("SUPABASE_KEY")

    missing: list[str] = []
    if not url:
        missing.append("SUPABASE_URL")
    if not key:
        missing.append("SUPABASE_SERVICE_KEY or SUPABASE_KEY")
    if missing:
        raise RuntimeError("Missing required env vars: " + ", ".join(missing))

    if not key.startswith("eyJ"):
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY / SUPABASE_KEY looks wrong — expected a JWT starting "
            f"with 'eyJ'. Got prefix: {key[:16]!r}… "
            "Dashboard → Project Settings → API → copy the full ``service_role`` "
            "(or anon) ``eyJ…`` secret, not an ``sb_…`` publishable-only string."
        )

    log.info("Supabase client initialized (URL=%s)", url)
    return url, key


_URL, _KEY = _supabase_connect_config()
supabase: Client = create_client(_URL, _KEY)
