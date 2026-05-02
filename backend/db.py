import logging
import os

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
log = logging.getLogger(__name__)


def _supabase_connect_config() -> tuple[str, str]:
    """
    Server-side client: prefers **service_role** JWT so auth + RPC/storage calls
    work reliably from this process.

    Set `SUPABASE_SERVICE_KEY` to the JWT from Dashboard → Settings → API →
    ``service_role`` (must start with ``eyJ``). Falls back to ``SUPABASE_KEY``
    if the service key is unset.

    Note: ``service_role`` bypasses Postgres RLS for API calls made with this
    client unless you deliberately scope with user JWT elsewhere—expected for a
    trusted backend-only client.
    """
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")

    key = (
        (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
        or (os.getenv("SUPABASE_KEY") or "").strip()
    )

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
