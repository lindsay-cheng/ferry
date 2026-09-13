"""Merge-layer plug-in point."""

from __future__ import annotations

from typing import Protocol

from weave.context.types import ChatContext


class ContextMerger(Protocol):
    """Merge a shared background + two raw branches into a briefing document."""

    def merge(
        self,
        shared_context: ChatContext | None,
        a_branch: list[dict],
        b_branch: list[dict],
    ) -> str:
        ...
