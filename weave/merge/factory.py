"""Factory for merge-layer implementations."""

from __future__ import annotations

from weave.merge.cerebras import CerebrasMerger
from weave.merge.client import CerebrasClient
from weave.merge.env import cerebras_configured
from weave.merge.exceptions import MergeClientError
from weave.merge.protocols import ContextMerger


def default_merger(*, client: CerebrasClient | None = None) -> ContextMerger:
    """Return :class:`CerebrasMerger` when Cerebras env vars are configured."""
    if not cerebras_configured():
        raise MergeClientError("CEREBRAS_API_KEY is required for merge")
    return CerebrasMerger(client=client)
