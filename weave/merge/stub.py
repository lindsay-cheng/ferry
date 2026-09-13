"""Deterministic in-memory merger for tests and local development."""

from __future__ import annotations

from weave.context.types import ChatContext


class StubMerger:
    """Deterministic in-memory briefing merger for tests and local dev."""

    def merge(
        self,
        shared_context: ChatContext | None,
        a_branch: list[dict],
        b_branch: list[dict],
    ) -> str:
        shared_line = (
            shared_context.summary if shared_context is not None
            else "no shared history"
        )
        return (
            "MERGED SESSION BRIEFING\n"
            f"Shared background: {shared_line}\n"
            f"Branch A contributed {len(a_branch)} turn(s).\n"
            f"Branch B contributed {len(b_branch)} turn(s)."
        )
