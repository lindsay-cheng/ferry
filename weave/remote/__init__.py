"""Remote transport: move raw session JSONL text to/from a Supabase-backed remote.

The pure byte-transport boundary keyed by ``(url, name)``. Implementation lives
in :mod:`weave.remote.remote`; import from this package for the stable surface
(the contract ``weave.core`` calls: ``push`` / ``pull`` / ``list`` / ``delete``).
"""

from weave.remote.remote import (
    ServerError,
    delete,
    list,
    pull,
    push,
)

__all__ = [
    "ServerError",
    "delete",
    "list",
    "pull",
    "push",
]
