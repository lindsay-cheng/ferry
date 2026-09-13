"""Remote transport for weave, backed by Supabase.

The "pure byte transport" boundary from the weave architecture: move raw
session JSONL text to/from a remote, keyed by ``(url, name)``. It never parses
JSON, rewrites fields, or chooses session ids -- that all lives in ``weave.core``.

Storage is a single Supabase project (``weave_sessions`` table). The ``url``
argument is the *logical* remote namespace from ``.weave/config`` and is stored
in the ``remote_url`` column, so one project can host many remotes. The actual
connection comes from the ``SUPABASE_URL`` / ``SUPABASE_KEY`` environment
variables (use the service-role key so RLS is bypassed).

Public surface (the contract ``weave.core`` calls):
    push(url, name, text) -> None
    pull(url, name) -> str      # raises ServerError if absent
    list(url) -> list[str]
"""

import os

_TABLE = "weave_sessions"
_client_cache = None


class ServerError(ValueError):
    """Any remote-transport failure (missing creds, absent session, API error).

    Subclasses ``ValueError`` so ``weave.core``'s ``except ValueError`` catches it.
    """


def _client():
    """Return a cached Supabase client built from the environment.

    Raises :class:`ServerError` with an actionable message if the ``supabase``
    package is missing or the credentials are not set.
    """
    global _client_cache
    if _client_cache is not None:
        return _client_cache

    # Pull SUPABASE_* from a `.env` (cwd or repo root) when not already in the
    # environment, mirroring how the merge layer resolves its Cerebras creds.
    from weave.merge.env import ensure_dotenv_loaded
    ensure_dotenv_loaded()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise ServerError(
            "Supabase credentials not configured; set SUPABASE_URL and "
            "SUPABASE_KEY (service-role key) in the environment")

    try:
        from supabase import create_client
    except ImportError as e:  # pragma: no cover - exercised only without the dep
        raise ServerError(
            "the 'supabase' package is required for remote operations; "
            "install it with 'pip install weave-sessions[remote]'") from e

    try:
        _client_cache = create_client(url, key)
    except Exception as e:  # noqa: BLE001 - surface any client init failure uniformly
        raise ServerError(f"could not connect to Supabase: {e}") from e
    return _client_cache


def _reset_client_cache():
    """Drop the cached client (test seam; called after patching credentials)."""
    global _client_cache
    _client_cache = None


def push(url, name, text):
    """Upload ``text`` under ``(url, name)``, overwriting any existing row."""
    client = _client()
    try:
        client.table(_TABLE).upsert(
            {"remote_url": url, "name": name, "transcript": text},
            on_conflict="remote_url,name",
        ).execute()
    except ServerError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ServerError(f"push to {name!r} failed: {e}") from e


def pull(url, name):
    """Return the transcript stored under ``(url, name)``.

    Raises :class:`ServerError` if no such session exists on the remote.
    """
    client = _client()
    try:
        res = (
            client.table(_TABLE)
            .select("transcript")
            .eq("remote_url", url)
            .eq("name", name)
            .limit(1)
            .execute()
        )
    except ServerError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ServerError(f"pull of {name!r} failed: {e}") from e
    rows = res.data or []
    if not rows:
        raise ServerError(f"no session {name!r} on remote")
    return rows[0]["transcript"]


def delete(url, name):
    """Delete the session stored under ``(url, name)``.

    Raises :class:`ServerError` if no such session exists on the remote, so the
    caller can report a miss rather than silently succeeding.
    """
    client = _client()
    try:
        res = (
            client.table(_TABLE)
            .delete()
            .eq("remote_url", url)
            .eq("name", name)
            .execute()
        )
    except ServerError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ServerError(f"delete of {name!r} failed: {e}") from e
    if not (res.data or []):
        raise ServerError(f"no session {name!r} on remote")


def list(url):  # noqa: A001 - name fixed by the transport contract
    """Return the session names stored for the remote ``url``."""
    client = _client()
    try:
        res = (
            client.table(_TABLE)
            .select("name")
            .eq("remote_url", url)
            .execute()
        )
    except ServerError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ServerError(f"list failed: {e}") from e
    return [row["name"] for row in (res.data or [])]
