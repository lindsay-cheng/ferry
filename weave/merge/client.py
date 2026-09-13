"""Cerebras HTTP client boundary (injectable in tests)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol

from weave.merge.env import (
    USER_AGENT,
    chat_completions_url,
    ensure_dotenv_loaded,
    get_default_base_url,
    get_default_model,
    normalize_base_url,
)
from weave.merge.exceptions import MergeClientError


class CerebrasClient(Protocol):
    """Return raw model text from a merge prompt."""

    def complete(self, prompt: str) -> str: ...


class HttpCerebrasClient:
    """POST to Cerebras chat-completions using stdlib HTTP."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        model: str,
        timeout_seconds: float | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = (
            normalize_base_url(base_url) if base_url is not None else get_default_base_url()
        )
        self._model = model
        self._timeout_seconds = timeout_seconds

    @property
    def base_url(self) -> str:
        return self._base_url

    def build_request(self, prompt: str) -> urllib.request.Request:
        """Build the HTTP request (test hook; no network I/O)."""
        body = json.dumps(
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        return urllib.request.Request(
            chat_completions_url(self._base_url),
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )

    def complete(self, prompt: str) -> str:
        request = self.build_request(prompt)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as resp:
                response_body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            finally:
                exc.close()
            raise MergeClientError(
                f"Cerebras API HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise MergeClientError(f"Cerebras API request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(response_body)
            return parsed["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise MergeClientError(
                f"Cerebras API returned unexpected response shape: {exc}"
            ) from exc


def default_cerebras_client() -> CerebrasClient:
    """Build :class:`HttpCerebrasClient` from environment variables."""
    ensure_dotenv_loaded()

    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        raise MergeClientError("CEREBRAS_API_KEY is not set")

    model = get_default_model()

    timeout_raw = os.environ.get("WEAVE_MERGE_TIMEOUT_SECONDS")
    timeout_seconds: float | None = None
    if timeout_raw:
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise MergeClientError(
                f"WEAVE_MERGE_TIMEOUT_SECONDS must be a number, got {timeout_raw!r}"
            ) from exc

    return HttpCerebrasClient(
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )
