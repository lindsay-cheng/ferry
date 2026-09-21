"""Remote transport for weave: HTTP hub, files keyed by name.

The "pure byte transport" boundary: move raw session JSONL text to/from a
hub, keyed by ``(url, name)``. It never parses JSON, rewrites fields, or
chooses session ids -- that all lives in ``weave.core``.

``url`` is the hub address from ``.weave/config`` (e.g. ``http://localhost:8080``).
The shared password comes from ``WEAVE_HUB_PASSWORD`` (never from config).

Public surface (the contract ``weave.core`` calls):
    push(url, name, text) -> None
    pull(url, name) -> str      # raises ServerError if absent
    list(url) -> list[str]
    delete(url, name) -> None
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_list_type = list  # builtin; ``list()`` below shadows the name

_ENV = "WEAVE_HUB_PASSWORD"
_TIMEOUT = 60
_dotenv_loaded = False


def ensure_dotenv_loaded():
    """Load KEY=value lines from a `.env` (cwd, or WEAVE_ENV_FILE) once."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    candidates = [Path.cwd() / ".env"]
    env_file = os.environ.get("WEAVE_ENV_FILE")
    if env_file:
        candidates.append(Path(env_file))
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
        return


class ServerError(ValueError):
    """Any remote-transport failure (missing password, absent session, hub error).

    Subclasses ``ValueError`` so ``weave.core``'s ``except ValueError`` catches it.
    """


def _reset_client_cache():
    """Drop cached dotenv state (test seam)."""
    global _dotenv_loaded
    _dotenv_loaded = False


def _password():
    ensure_dotenv_loaded()
    p = os.environ.get(_ENV, "")
    if not p:
        raise ServerError(f"set {_ENV}")
    return p


def _call(method, url, name=None, data=None):
    password = _password()
    base = url.rstrip("/")
    if name is None:
        target = base + "/"
    else:
        target = f"{base}/{urllib.parse.quote(name, safe='')}"
    headers = {"Authorization": f"Bearer {password}"}
    body = None
    if data is not None:
        body = data.encode("utf-8")
        headers["Content-Type"] = "text/plain; charset=utf-8"
    req = urllib.request.Request(target, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace").strip() or str(e.reason)
        raise ServerError(msg) from e
    except urllib.error.URLError:
        raise ServerError(f"hub unreachable at {url}") from None


def push(url, name, text):
    """Upload ``text`` under ``name``. Existing names are an error."""
    _call("PUT", url, name, data=text)


def pull(url, name):
    """Return the transcript stored under ``name``.

    Raises :class:`ServerError` if no such session exists on the hub.
    """
    return _call("GET", url, name)


def delete(url, name):
    """Delete the session stored under ``name``.

    Raises :class:`ServerError` if no such session exists on the hub, so the
    caller can report a miss rather than silently succeeding.
    """
    _call("DELETE", url, name)


def list(url):  # noqa: A001 - name fixed by the transport contract
    """Return the session names stored on the hub at ``url``."""
    raw = _call("GET", url)
    try:
        names = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ServerError("hub returned invalid list") from e
    if type(names) is not _list_type:
        raise ServerError("hub returned invalid list")
    return names
