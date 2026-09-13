"""Weave orchestrator core: push/pull/merge Claude Code sessions, plus remote/ls.

Owns ALL policy (id choice, cwd/sessionId rewrite, config resolution,
validation). Delegates mechanics to weave.connector (byte I/O),
weave.transcript (entry editing), weave.config (remote resolution), the
`weave.remote` collaborator (byte transport backed by Supabase), and the merge
layer (distill + Cerebras). Stdlib only here; the Supabase dependency lives
entirely behind `weave.remote`.

Data pipeline for the remote operations:

    Supabase (weave_sessions) <--API--> weave.remote --text--> weave.core

`weave.remote` moves raw transcript text keyed by (remote_url, name); this
module applies every machine-specific policy (fresh id, cwd/sessionId rewrite)
before writing anything locally.
"""

import importlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from weave import config
from weave import connector as cc
from weave import transcript as tx
from weave.context.distill import distill_from_jsonl

_VOLATILE_BLOCK_KEYS = ("id", "tool_use_id")


def _strip_volatile(value):
    """Recursively drop volatile id fields so content compares across machines."""
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in value.items()
                if k not in _VOLATILE_BLOCK_KEYS}
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    return value


def _entry_key(entry):
    """Content identity of a linearized entry.

    Ignores uuid/parentUuid/sessionId/cwd/timestamp and the per-call tool ids,
    so the same logical turn captured on two machines compares equal.
    """
    msg = entry.get("message") or {}
    payload = [entry.get("type"), msg.get("role"), _strip_volatile(msg.get("content"))]
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _has_tool_use(entry):
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_use" for b in content)


def _split_at_branch(a, b):
    """Longest common content prefix of two linear transcripts.

    Returns ``(branch_point_uuid_or_None, a_tail, b_tail)``. The prefix never ends
    on a dangling ``tool_use`` (whose ``tool_result`` would land in the tail).
    """
    n = 0
    for ea, eb in zip(a, b):
        if _entry_key(ea) != _entry_key(eb):
            break
        n += 1
    if n > 0 and _has_tool_use(a[n - 1]):
        n -= 1
    branch_point = a[n - 1]["uuid"] if n > 0 else None
    return branch_point, a[n:], b[n:]


class WeaveError(ValueError):
    """Any weave-layer error (unknown remote, empty history, remote transport)."""


@dataclass(frozen=True)
class MergeResult:
    session_id: str
    jsonl_path: str
    branch_point: str | None
    a_tail_len: int
    b_tail_len: int


# --- config ------------------------------------------------------------------
def remote_add(name, url, *, path=None):
    config.add_remote(name, url, path=path)


def _resolve_remote(remote, *, path=None):
    """Resolve which remote to act on, defaulting to the sole configured one.

    When ``remote`` is given it is returned as-is. When it is ``None`` (caller
    omitted it) and exactly one remote is configured, that remote's name is used
    -- so a single-remote setup never has to name it. Zero or many configured
    remotes make the choice ambiguous, which is a ``WeaveError``.
    """
    if remote is not None:
        return remote
    names = [name for name, _ in config.list_remotes(path=path)]
    if len(names) == 1:
        return names[0]
    if not names:
        raise WeaveError("no remote configured — run: weave remote add <name> <url>")
    raise WeaveError(
        f"multiple remotes configured ({', '.join(sorted(names))}); specify one")


def _remote_url(remote, *, path=None):
    """Resolve a remote name to its url, as a WeaveError on failure.

    Thin orchestrator-level adapter over :func:`weave.config.get_remote` so
    every weave-layer error shares the ``WeaveError`` (``ValueError``) base.
    """
    try:
        return config.get_remote(remote, path=path)
    except ValueError as e:
        raise WeaveError(str(e)) from e


def _load_server():
    return importlib.import_module("weave.remote")


def _remote_call(fn, *args, action, target):
    """Invoke a `weave.remote` transport call, mapping any failure to WeaveError.

    Keeps the original (actionable) message from the transport layer -- e.g.
    missing credentials or an absent remote session -- while tagging it with
    what was being attempted so the CLI surfaces a clear `weave: ...` line.
    """
    try:
        return fn(*args)
    except WeaveError:
        raise
    except ValueError as e:
        raise WeaveError(f"{action} {target}: {e}") from e


# --- auto / log helpers ------------------------------------------------------
def _resolve_session(session, cwd):
    """Map the literal ``"auto"`` to the newest local session for `cwd`.

    Any other value (an id or a path) passes through untouched. Connector
    errors (e.g. no local sessions) surface as a ``WeaveError``.
    """
    if session != "auto":
        return session
    try:
        return cc.latest_session(cwd or os.getcwd())
    except ValueError as e:
        raise WeaveError(str(e)) from e


def _resolve_local_id(source, *, config_path=None):
    """Map a logical *name* (the alias a prior push/pull recorded for a session)
    to the local session id it stands for.

    Sources that already name a file path or resolve directly as a local session
    id pass through unchanged. Otherwise the operation log is consulted and the
    most recent entry whose ``name`` matches yields its local ``id``. When no
    alias matches, the original string is returned so the caller's reader can
    raise the usual "no session" error.
    """
    if os.sep in source or source.endswith(".jsonl"):
        return source
    try:
        if cc.resolve(source) is not None:
            return source
    except ValueError:
        return source            # ambiguous id -- let the reader report it
    for entry in reversed(config.read_log(path=config_path)):
        if entry.get("name") == source and entry.get("id"):
            return entry["id"]
    return source


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_op(op, remote, name, id_, *, path):
    """Append one remote-operation record to the local log (best-effort)."""
    config.append_log(
        {"ts": _now_iso(), "op": op, "remote": remote, "name": name, "id": id_},
        path=path,
    )


def log(*, config_path=None):
    """Return logged remote operations, newest first."""
    return list(reversed(config.read_log(path=config_path)))


# --- operations --------------------------------------------------------------
def _new_id():
    return str(uuid.uuid4())


def _rewrite_for_local(entries, new_id, cwd):
    return [{**e, "cwd": cwd, "sessionId": new_id} for e in entries]


def pull(remote, name, *, cwd=None, server=None, config_path=None):
    """Download `name` from `remote` (Supabase) into a fresh local session.

    `remote` may be ``None`` to use the sole configured remote. Pipeline:
    weave.remote.pull -> weave.transcript parse -> local id/cwd rewrite ->
    connector write. Validates (unknown/ambiguous remote, transport failure,
    empty history) and fails before any local write.
    """
    remote = _resolve_remote(remote, path=config_path)
    url = _remote_url(remote, path=config_path)
    svr = server or _load_server()
    text = _remote_call(svr.pull, url, name, action="pull", target=f"{remote}/{name}")
    entries = tx.from_text(text)
    if not entries:
        raise WeaveError(f"session {name!r} has no chat history")
    cwd = cwd or os.getcwd()
    new_id = _new_id()
    entries = _rewrite_for_local(entries, new_id, cwd)
    cc.write_text(cc.session_path(cwd, new_id), tx.to_text(entries))
    _log_op("pull", remote, name, new_id, path=config_path)
    return new_id


def push(remote, name, session_id, *, cwd=None, server=None, config_path=None):
    """Upload the local `session_id` to `remote` (Supabase) under `name`.

    `remote` may be ``None`` to use the sole configured remote, and `session_id`
    may be ``"auto"`` to use the newest local session for `cwd`. Returns the
    resolved remote name so callers can report where the push landed. Bytes are
    sent as-is; all machine-specific rewriting happens on `pull`.
    """
    session_id = _resolve_session(session_id, cwd)
    text = cc.read_text(session_id)            # SessionNotFound/Ambiguous propagate
    remote = _resolve_remote(remote, path=config_path)
    url = _remote_url(remote, path=config_path)
    svr = server or _load_server()
    _remote_call(svr.push, url, name, text, action="push", target=f"{remote}/{name}")
    _log_op("push", remote, name, session_id, path=config_path)
    return remote


def rm(remote, name, *, server=None, config_path=None):
    """Delete the session stored as `name` on `remote` (Supabase).

    `remote` may be ``None`` to use the sole configured remote. Local sessions
    are never touched. Returns the resolved remote name.
    """
    remote = _resolve_remote(remote, path=config_path)
    url = _remote_url(remote, path=config_path)
    svr = server or _load_server()
    _remote_call(svr.delete, url, name, action="rm", target=f"{remote}/{name}")
    _log_op("rm", remote, name, None, path=config_path)
    return remote


def ls(remote=None, *, cwd=None, server=None, config_path=None):
    if remote is None:
        enc = cc.encode_cwd(cwd or os.getcwd())
        return [sid for sid, path in cc.list_sessions()
                if path.parent.name == enc]
    url = _remote_url(remote, path=config_path)
    svr = server or _load_server()
    return _remote_call(svr.list, url, action="ls", target=remote)


# --- merge -------------------------------------------------------------------
def _read_source(source):
    """Read a session's JSONL by id or path, mapping connector errors to WeaveError."""
    try:
        return cc.read_text(source)
    except ValueError as exc:
        raise WeaveError(str(exc)) from exc


def _distill_shared(a_entries, branch_point, source_path):
    """Distill the shared-prefix sub-document into a ChatContext (None if empty)."""
    if branch_point is None:
        return None
    idx = next(i for i, e in enumerate(a_entries) if e.get("uuid") == branch_point)
    shared_text = tx.to_text(a_entries[: idx + 1])
    try:
        return distill_from_jsonl(
            shared_text, source_label="shared", source_path=str(source_path)
        ).context
    except ValueError as exc:
        raise WeaveError(str(exc)) from exc


def merge(source_a, source_b, *, cwd=None, merger=None, config_path=None):
    """Merge two sessions into a new resumable cloned session.

    Detects the shared content prefix, asks the merge layer for one briefing
    document unifying the divergent branches, then clones source A: drops A's
    branch and splices in a synthetic Read tool cycle whose result holds the
    briefing. Identity is rewritten for the local machine and the clone is
    written under ~/.claude. Both sources are left untouched.

    Either source may be ``"auto"`` to use the newest local session for `cwd`,
    a raw local session id, a path, or the logical *name* a prior push/pull
    recorded for the session (resolved via the operation log).
    """
    source_a = _resolve_local_id(_resolve_session(source_a, cwd), config_path=config_path)
    source_b = _resolve_local_id(_resolve_session(source_b, cwd), config_path=config_path)
    a = tx.from_text(_read_source(source_a))
    b = tx.from_text(_read_source(source_b))
    if not a and not b:
        raise WeaveError("no chat history in either session")

    branch_point, a_tail, b_tail = _split_at_branch(a, b)
    if not a_tail and not b_tail:
        raise WeaveError("sessions are identical; nothing to merge")

    shared_ctx = _distill_shared(a, branch_point, source_a)

    from weave.merge.factory import default_merger
    active = merger or default_merger()
    briefing = active.merge(shared_ctx, a_tail, b_tail)   # MergeError propagates; nothing written yet

    entries = list(a)
    if a_tail:
        entries, _ = tx.delete_between(entries, a_tail[0]["uuid"], a_tail[-1]["uuid"])
    spec = {
        "type": "tool_call", "name": "Read",
        "input": {"file_path": "weave-merged-context"},
        "result": briefing,
    }
    if branch_point is None:
        entries, _ = tx.create_at_start(entries, spec)
    else:
        entries, _ = tx.create_after(entries, branch_point, spec)

    new_id = _new_id()
    cwd = cwd or os.getcwd()
    entries = _rewrite_for_local(entries, new_id, cwd)
    path = cc.session_path(cwd, new_id)
    cc.write_text(path, tx.to_text(entries))
    return MergeResult(
        session_id=new_id, jsonl_path=str(path), branch_point=branch_point,
        a_tail_len=len(a_tail), b_tail_len=len(b_tail),
    )
