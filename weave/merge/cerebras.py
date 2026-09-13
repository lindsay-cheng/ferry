"""Cerebras text-briefing merge implementation."""

from __future__ import annotations

from weave.context.types import ChatContext
from weave.merge.client import CerebrasClient, default_cerebras_client
from weave.merge.exceptions import MergeResponseError
from weave.merge.prompt import build_merge_prompt


class CerebrasMerger:
    """Merge two branches into a briefing via Cerebras."""

    def __init__(self, client: CerebrasClient | None = None) -> None:
        self._client = client

    def merge(
        self,
        shared_context: ChatContext | None,
        a_branch: list[dict],
        b_branch: list[dict],
    ) -> str:
        client = self._client or default_cerebras_client()
        prompt = build_merge_prompt(shared_context, a_branch, b_branch)
        text = client.complete(prompt).strip()
        if not text:
            raise MergeResponseError("merge response was empty")
        return text
