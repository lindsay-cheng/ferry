"""Load merge-layer config from environment and optional `.env` files."""

from __future__ import annotations

import os
from pathlib import Path

from weave import __version__

_DEFAULT_BASE_URL = "https://api.cerebras.ai/v1"
_DEFAULT_MODEL = "zai-glm-4.7"
USER_AGENT = f"weave/{__version__}"

_dotenv_loaded = False


def repo_root() -> Path:
    """Weave repository root (parent of the ``weave`` package)."""
    return Path(__file__).resolve().parents[2]


def load_dotenv_file(path: Path, *, override: bool = False) -> bool:
    """Load simple ``KEY=value`` lines from ``path`` into ``os.environ``."""
    if not path.is_file():
        return False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = value
    return True


def _dotenv_candidates() -> list[Path]:
    candidates = [Path.cwd() / ".env"]
    env_file = os.environ.get("WEAVE_ENV_FILE")
    if env_file:
        candidates.append(Path(env_file))
    if os.environ.get("WEAVE_ENV") == "development":
        candidates.append(repo_root() / ".env")
    return candidates


def ensure_dotenv_loaded() -> Path | None:
    """Load the first ``.env`` found in cwd or ``WEAVE_ENV_FILE`` (once per process)."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return _loaded_dotenv_path()

    for candidate in _dotenv_candidates():
        if load_dotenv_file(candidate):
            _dotenv_loaded = True
            return candidate

    _dotenv_loaded = True
    return None


def _loaded_dotenv_path() -> Path | None:
    for candidate in _dotenv_candidates():
        if candidate.is_file():
            return candidate
    return None


def normalize_base_url(base_url: str) -> str:
    """Strip trailing slashes; avoid duplicate ``/v1`` segments."""
    url = base_url.strip().rstrip("/")
    while url.endswith("/v1/v1"):
        url = url[: -len("/v1")]
    return url


def chat_completions_url(base_url: str) -> str:
    """Build the Cerebras chat-completions endpoint URL."""
    normalized = normalize_base_url(base_url)
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def cerebras_configured() -> bool:
    """Return True when Cerebras is usable.

    Only the API key is required; the model falls back to ``_DEFAULT_MODEL``
    (see :func:`get_default_model`).
    """
    ensure_dotenv_loaded()
    return bool(os.environ.get("CEREBRAS_API_KEY"))


def describe_cerebras_config() -> str:
    """Safe config summary for debugging (never prints full API key)."""
    ensure_dotenv_loaded()
    lines: list[str] = []

    api_key = os.environ.get("CEREBRAS_API_KEY")
    if api_key:
        suffix = api_key[-4:] if len(api_key) >= 4 else "****"
        lines.append(f"CEREBRAS_API_KEY present=True length={len(api_key)} suffix=...{suffix}")
    else:
        lines.append("CEREBRAS_API_KEY present=False")

    model = os.environ.get("CEREBRAS_MODEL")
    if model:
        lines.append(f"CEREBRAS_MODEL={model}")
    else:
        lines.append(f"CEREBRAS_MODEL=(not set, default {_DEFAULT_MODEL})")

    base_url = os.environ.get("CEREBRAS_BASE_URL", _DEFAULT_BASE_URL)
    lines.append(f"CEREBRAS_BASE_URL={base_url}")
    lines.append(f"chat_completions_url={chat_completions_url(base_url)}")

    timeout = os.environ.get("WEAVE_MERGE_TIMEOUT_SECONDS")
    lines.append(f"WEAVE_MERGE_TIMEOUT_SECONDS={timeout or '(not set)'}")

    dotenv = _loaded_dotenv_path()
    lines.append(f"dotenv_file={dotenv or '(not found)'}")

    return "\n".join(lines)


def get_default_base_url() -> str:
    ensure_dotenv_loaded()
    return normalize_base_url(os.environ.get("CEREBRAS_BASE_URL", _DEFAULT_BASE_URL))


def get_default_model() -> str:
    """Resolve the Cerebras model, defaulting to ``_DEFAULT_MODEL`` when unset."""
    ensure_dotenv_loaded()
    return os.environ.get("CEREBRAS_MODEL") or _DEFAULT_MODEL
