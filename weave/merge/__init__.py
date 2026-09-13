"""Merge layer: text-briefing mergers implementing :class:`ContextMerger`."""

from weave.merge.cerebras import CerebrasMerger
from weave.merge.exceptions import MergeClientError, MergeError, MergeResponseError
from weave.merge.factory import default_merger
from weave.merge.prompt import build_merge_prompt
from weave.merge.protocols import ContextMerger
from weave.merge.stub import StubMerger

__all__ = [
    "CerebrasMerger",
    "ContextMerger",
    "MergeClientError",
    "MergeError",
    "MergeResponseError",
    "StubMerger",
    "build_merge_prompt",
    "default_merger",
]
