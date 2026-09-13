"""Transcript editing: linear CRUD over a Claude Code JSONL active branch.

The public CRUD surface lives in :mod:`weave.transcript.api`; the private
linearize/serialize engine lives in :mod:`weave.transcript.engine`. Import from
this package (``from weave import transcript``) for the stable surface.
"""

from weave.transcript.api import (
    NotFoundError,
    SpecError,
    create_after,
    create_at_end,
    create_at_start,
    delete,
    delete_between,
    from_text,
    join_jsonl,
    linearize,
    read_all,
    read_between,
    read_from,
    read_one,
    serialize,
    split_jsonl,
    to_text,
    update,
)

__all__ = [
    "NotFoundError",
    "SpecError",
    "create_after",
    "create_at_end",
    "create_at_start",
    "delete",
    "delete_between",
    "from_text",
    "join_jsonl",
    "linearize",
    "read_all",
    "read_between",
    "read_from",
    "read_one",
    "serialize",
    "split_jsonl",
    "to_text",
    "update",
]
