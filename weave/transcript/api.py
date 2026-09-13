"""Public CRUD interface for editing Claude Code transcripts.

This is the stable surface other code should import. The editing engine lives in
the private ``weave.transcript.engine`` module and is free to change underneath;
everything here is a thin delegate to it.

A transcript is JSONL: one JSON entry per line, entries linked into a tree by
``parentUuid`` -> ``uuid``. Real transcripts FORK (a rewind/edit appends a new
branch). This API works on the single ACTIVE branch -- the one ending at the
last-appended entry, which is what Claude Code resumes -- and every result it
serializes is a single linear chain: no branches, no forks, ever.

Pipeline::

    from weave import transcript as tx

    entries = tx.from_text(open(path).read())          # linearize to the active branch
    entries, created = tx.create_at_end(
        entries, {"type": "message", "role": "user", "content": "hi"})
    open(path, "w").write(tx.to_text(entries))         # serialize a clean linear chain

Conventions
-----------
- In-memory only: functions take and return data; no file or network I/O.
- Pure: the input list is never mutated; mutators return a NEW list.
- Mutators (``create_*`` / ``update`` / ``delete*``) return ``(entries, uuids)``;
  reads return entry dicts (or ``None`` / ``[]``).
- uuid-anchored ops raise :class:`NotFoundError` if the uuid is not on the branch;
  a malformed spec raises :class:`SpecError`. Both subclass ``ValueError`` -- catch
  ``ValueError`` for "any edit error". ``read_one`` / ``read_all`` are lenient.

The spec grammar (shared by ``create_*`` and :func:`update`)
------------------------------------------------------------
::

    {"type": "message", "role": "user"|"assistant", "content": str | [block, ...]}

    {"type": "tool_call",                       # an assistant tool_use + user tool_result pair
     "tools": [{"name", "input", "result", "is_error"?, "id"?}, ...],
     "text"?: str, "reply"?: str}               # single-tool shorthand: name/input/result at top level

Content block types: ``text`` / ``thinking`` / ``tool_use`` / ``tool_result`` /
``image`` / ``document``; unknown types pass through verbatim. ``tool_use`` ids
are auto-filled. A ``tool_call`` always builds the atomic assistant(tool_use) +
user(tool_result) pair (+ optional ``reply``), handled as one unit by every op.
"""

from weave.transcript.engine import (
    _linearize,
    _serialize,
    _from_text,
    _to_text,
    _split_jsonl,
    _join_jsonl,
    _create_at_start,
    _create_after,
    _create_at_end,
    _read_all,
    _read_from,
    _read_between,
    _read_one,
    _update,
    _delete,
    _delete_between,
    _NotFoundError,
    _SpecError,
)

__all__ = [
    # boundary / serialization
    "linearize", "serialize", "from_text", "to_text", "split_jsonl", "join_jsonl",
    # create
    "create_at_start", "create_after", "create_at_end",
    # read
    "read_all", "read_from", "read_between", "read_one",
    # update / delete
    "update", "delete", "delete_between",
    # exceptions
    "NotFoundError", "SpecError",
]

# Raised on a uuid-anchored op with a uuid that isn't on the branch
# (NotFoundError) or on a malformed spec (SpecError). Both subclass ``ValueError``.
NotFoundError = _NotFoundError
SpecError = _SpecError


# --- boundary -----------------------------------------------------------------
def linearize(raw_lines):
    """The active branch as a list of entry dicts (root -> leaf).

    The active leaf is the last-appended entry with a uuid; its ancestry is walked
    to the root. Forks and non-chain meta lines (no uuid) are dropped.
    """
    return _linearize(raw_lines)


def serialize(entries):
    """Serialize ``entries`` to JSONL line strings, recomputing every
    ``parentUuid`` from list order. The output is always a single linear chain."""
    return _serialize(entries)


def from_text(text):
    """Convenience: a JSONL document string -> the active branch (list of entries)."""
    return _from_text(text)


def to_text(entries):
    """Convenience: a list of entries -> a JSONL document string (linear chain)."""
    return _to_text(entries)


def split_jsonl(text):
    """Split a JSONL document string into a list of line strings (endings kept)."""
    return _split_jsonl(text)


def join_jsonl(lines):
    """Join a list of JSONL line strings back into a single document string."""
    return _join_jsonl(lines)


# --- create -------------------------------------------------------------------
def create_at_start(entries, spec):
    """Insert a new entry/cycle (from ``spec``) as the new root. Returns
    ``(entries, created_uuids)``. See the module docstring for the spec grammar."""
    return _create_at_start(entries, spec)


def create_after(entries, uuid, spec):
    """Insert a new entry/cycle immediately after ``uuid`` (after its whole tool
    cycle, if it is in one). Returns ``(entries, created_uuids)``. Raises
    :class:`NotFoundError` if ``uuid`` is absent; :class:`SpecError` on a bad spec."""
    return _create_after(entries, uuid, spec)


def create_at_end(entries, spec):
    """Append a new entry/cycle as the new leaf. Returns ``(entries, created_uuids)``."""
    return _create_at_end(entries, spec)


# --- read ---------------------------------------------------------------------
def read_all(entries):
    """All entries on the branch, in conversation order."""
    return _read_all(entries)


def read_from(entries, uuid, n=None, reverse=False):
    """``n`` entries starting at ``uuid`` (inclusive). ``reverse=False`` walks
    toward the leaf (newer); ``reverse=True`` toward the root (older). ``n=None``
    means "all the way" in that direction. Output is ALWAYS conversation order
    (ascending). Raises :class:`NotFoundError` if ``uuid`` is absent."""
    return _read_from(entries, uuid, n=n, reverse=reverse)


def read_between(entries, uuid_a, uuid_b):
    """The inclusive range of entries between the two uuids (order-agnostic, ascending
    output). Raises :class:`NotFoundError` if either uuid is absent."""
    return _read_between(entries, uuid_a, uuid_b)


def read_one(entries, uuid):
    """The entry with this uuid, or ``None`` (lenient)."""
    return _read_one(entries, uuid)


# --- update -------------------------------------------------------------------
def update(entries, uuid, spec):
    """Replace the entry at ``uuid`` (or its whole tool cycle) with what ``spec``
    builds, using the same grammar as ``create_*``. The new head keeps the target's
    uuid and timestamp (an identity-preserving edit). Returns
    ``(entries, affected_uuids)``. Raises :class:`NotFoundError` / :class:`SpecError`."""
    return _update(entries, uuid, spec)


# --- delete -------------------------------------------------------------------
def delete(entries, uuid):
    """Delete the entry at ``uuid``. If it is half of a tool_use/tool_result cycle,
    the whole cycle is removed (atomic). Returns ``(entries, deleted_uuids)``.
    Raises :class:`NotFoundError` if ``uuid`` is absent."""
    return _delete(entries, uuid)


def delete_between(entries, uuid_a, uuid_b):
    """Delete the inclusive range between the two uuids (order-agnostic). Endpoints
    expand to their tool cycles so a pair is never split. Returns
    ``(entries, deleted_uuids)``. Raises :class:`NotFoundError` if either is absent."""
    return _delete_between(entries, uuid_a, uuid_b)
