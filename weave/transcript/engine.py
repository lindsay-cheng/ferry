"""Private linear transcript-editing engine for weave.

A Claude Code transcript is JSONL: one JSON entry per line, entries linked into a
tree by ``parentUuid`` -> ``uuid``. Real transcripts FORK -- a rewind/edit appends
a new branch at the end of the file, so a node gains multiple children. The active
conversation is the branch ending at the LAST-appended entry.

This engine refuses to edit the tree. Instead it works on a single linear branch::

    raw_lines  --_linearize-->  [entry, ...]   # the active branch, root -> leaf
               edit as a plain list            # order is truth; parentUuid ignored
    [entry, ...]  --_serialize-->  raw_lines   # parentUuid recomputed from order

Because ``_serialize`` sets every entry's ``parentUuid`` to the previous entry's
``uuid``, each node has exactly one child -- a fork is unrepresentable in the
output. The only fork-aware code in the system is ``_linearize``.

Everything here is module-private; the public surface is ``weave.transcript``.
"""

import json
import uuid as _uuidlib
from datetime import datetime, timedelta, timezone

_ROLES = ("user", "assistant")


class _NotFoundError(ValueError):
    """A uuid-anchored operation referenced a uuid not on the branch."""


class _SpecError(ValueError):
    """A create/update spec is malformed."""


# --- (de)serialization --------------------------------------------------------
def _split_jsonl(text):
    """JSONL document string -> list of line strings (keeping line endings)."""
    return text.splitlines(keepends=True)


def _join_jsonl(raw_lines):
    """List of line strings -> JSONL document string."""
    return "".join(raw_lines)


def _parse(raw_line):
    stripped = raw_line.strip()
    if not stripped:
        return None
    return json.loads(stripped)


def _dump(entry):
    return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


# --- boundary: linearize / serialize ------------------------------------------
def _linearize(raw_lines):
    """The active branch as a list of entry dicts, root -> leaf.

    The active leaf is the last-appended entry that carries a uuid (this is what
    Claude Code resumes). Walk ``parentUuid`` back to the root with a cycle guard,
    then reverse. Forks and non-chain meta lines (no uuid) are dropped.
    """
    by_uuid, order = {}, []
    for raw in raw_lines:
        entry = _parse(raw)
        if entry is not None and entry.get("uuid"):
            by_uuid.setdefault(entry["uuid"], entry)
            order.append(entry)
    if not order:
        return []
    path, seen = [], set()
    cur = order[-1]
    while cur is not None and cur.get("uuid") not in seen:
        seen.add(cur["uuid"])
        path.append(cur)
        cur = by_uuid.get(cur.get("parentUuid"))
    path.reverse()
    return path


def _serialize(entries):
    """Recompute ``parentUuid`` from list order and return JSONL line strings.

    Head gets ``parentUuid = None``; every other entry points at its predecessor.
    Input dicts are not mutated. The result is always a single linear chain.
    """
    lines, prev = [], None
    for e in entries:
        e = dict(e)
        e["parentUuid"] = prev
        prev = e.get("uuid")
        lines.append(_dump(e) + "\n")
    return lines


def _from_text(text):
    return _linearize(_split_jsonl(text))


def _to_text(entries):
    return _join_jsonl(_serialize(entries))


# --- synthetic entry builders -------------------------------------------------
def _gen_uuid():
    return str(_uuidlib.uuid4())


def _gen_tool_id():
    return "toolu_" + _uuidlib.uuid4().hex[:24]


def _gen_timestamp(base_ts):
    """A timestamp 1s after ``base_ts``, or 'now' if it can't be parsed."""
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    try:
        dt = datetime.strptime(base_ts, fmt).replace(tzinfo=timezone.utc)
        dt += timedelta(seconds=1)
    except (TypeError, ValueError):
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _context(entries):
    """Gather contextual fields from existing entries so new ones blend in."""
    fields = ("sessionId", "cwd", "gitBranch", "version", "userType",
              "entrypoint", "isSidechain")
    tmpl = {}
    for e in entries:
        for k in fields:
            if k in e:
                tmpl.setdefault(k, e[k])
        msg = e.get("message")
        if e.get("type") == "assistant" and isinstance(msg, dict) and msg.get("model"):
            tmpl.setdefault("model", msg["model"])
    return tmpl


def _apply_context(entry, tmpl):
    for k in ("userType", "entrypoint", "cwd", "sessionId", "version", "gitBranch"):
        if k in tmpl:
            entry[k] = tmpl[k]
    return entry


def _user_entry(tmpl, new_uuid, ts, content):
    entry = {"parentUuid": None, "type": "user"}
    if "isSidechain" in tmpl:
        entry["isSidechain"] = tmpl["isSidechain"]
    entry["message"] = {"role": "user", "content": content}
    entry["uuid"] = new_uuid
    entry["timestamp"] = ts
    return _apply_context(entry, tmpl)


def _assistant_entry(tmpl, new_uuid, ts, blocks, stop_reason="end_turn"):
    entry = {"parentUuid": None, "type": "assistant"}
    if "isSidechain" in tmpl:
        entry["isSidechain"] = tmpl["isSidechain"]
    entry["message"] = {
        "model": tmpl.get("model", "claude-opus-4-8"),
        "id": "msg_synthetic" + new_uuid.replace("-", "")[:20],
        "type": "message",
        "role": "assistant",
        "content": blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0,
                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
    }
    entry["uuid"] = new_uuid
    entry["timestamp"] = ts
    return _apply_context(entry, tmpl)


# --- content-block grammar + validation ---------------------------------------
def _normalize_block(block):
    """Validate/normalize one content block; fill a tool_use id if missing.

    Unknown block types pass through verbatim (forward-compatible).
    """
    if not isinstance(block, dict) or "type" not in block:
        raise _SpecError(f"content block must be an object with a 'type': {block!r}")
    b = dict(block)
    bt = b["type"]
    if bt == "text":
        if not isinstance(b.get("text"), str):
            raise _SpecError("text block needs a string 'text'")
    elif bt == "thinking":
        if not isinstance(b.get("thinking"), str):
            raise _SpecError("thinking block needs a string 'thinking'")
    elif bt == "tool_use":
        if not isinstance(b.get("name"), str):
            raise _SpecError("tool_use block needs a string 'name'")
        b.setdefault("input", {})
        if not b.get("id"):
            b["id"] = _gen_tool_id()
    elif bt == "tool_result":
        if not isinstance(b.get("tool_use_id"), str):
            raise _SpecError("tool_result block needs a string 'tool_use_id'")
        b.setdefault("content", "")
        if isinstance(b["content"], list):
            nested = []
            for x in b["content"]:
                if isinstance(x, dict) and x.get("type") in ("tool_use", "tool_result", "thinking"):
                    raise _SpecError(
                        f"{x['type']} block is not allowed inside tool_result.content")
                nested.append(_normalize_block(x))
            b["content"] = nested
    elif bt in ("image", "document"):
        if "source" not in b:
            raise _SpecError(f"{bt} block needs a 'source'")
    return b


def _normalize_content(role, content):
    """A string is shorthand (kept for user, wrapped in one text block for
    assistant); a list is validated block-by-block."""
    if isinstance(content, str):
        return content if role == "user" else [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [_normalize_block(b) for b in content]
    raise _SpecError("message 'content' must be a string or a list of blocks")


def _unique_tool_ids(blocks):
    ids = [b["id"] for b in blocks
           if isinstance(b, dict) and b.get("type") == "tool_use"]
    if len(ids) != len(set(ids)):
        dups = sorted({i for i in ids if ids.count(i) > 1})
        raise _SpecError("duplicate tool_use id(s): " + ", ".join(dups))


def _coerce_tools(spec):
    """Tool defs for a tool_call spec, accepting the single-tool shorthand."""
    tools = spec.get("tools")
    if tools is None and "name" in spec:
        tools = [{"name": spec["name"], "input": spec.get("input"),
                  "result": spec.get("result", ""),
                  "is_error": spec.get("is_error", False), "id": spec.get("id")}]
    if not tools:
        raise _SpecError(
            "tool_call needs a non-empty 'tools' list (or single-tool name/input/result)")
    for tdef in tools:
        if not isinstance(tdef, dict):
            raise _SpecError(f"each tool must be an object: {tdef!r}")
        if not isinstance(tdef.get("name"), str):
            raise _SpecError("each tool needs a string 'name'")
    return tools


# --- segment construction -----------------------------------------------------
def _build(entries, spec, base_ts):
    """Build the entry/entries for a spec, chained internally by list order only.

    ``message`` -> one entry. ``tool_call`` -> assistant(tool_use)+user(tool_result)
    pair (+ optional reply). parentUuid is irrelevant here -- serialize fixes links.
    """
    tmpl = _context(entries)
    etype = spec.get("type")

    if etype == "message":
        role = spec.get("role")
        if role not in _ROLES:
            raise _SpecError("message 'role' must be 'user' or 'assistant'")
        if "content" not in spec:
            raise _SpecError("message needs 'content'")
        content = _normalize_content(role, spec["content"])
        ts = _gen_timestamp(base_ts)
        u = _gen_uuid()
        if role == "user":
            return [_user_entry(tmpl, u, ts, content)]
        _unique_tool_ids(content)
        stop = "tool_use" if any(
            isinstance(b, dict) and b.get("type") == "tool_use" for b in content
        ) else "end_turn"
        return [_assistant_entry(tmpl, u, ts, content, stop)]

    if etype == "tool_call":
        tools = _coerce_tools(spec)
        ts_a = _gen_timestamp(base_ts)
        ts_b = _gen_timestamp(ts_a)
        use_blocks, result_blocks = [], []
        for tdef in tools:
            tid = tdef.get("id") or _gen_tool_id()
            use_blocks.append({"type": "tool_use", "id": tid, "name": tdef["name"],
                               "input": tdef.get("input") or {}})
            result = tdef.get("result", "")
            if isinstance(result, list):
                result = [_normalize_block(b) for b in result]
            result_blocks.append({"type": "tool_result", "tool_use_id": tid,
                                  "content": result,
                                  "is_error": tdef.get("is_error", False)})
        _unique_tool_ids(use_blocks)
        text = spec.get("text")
        a_content = ([{"type": "text", "text": text}] if text else []) + use_blocks
        out = [
            _assistant_entry(tmpl, _gen_uuid(), ts_a, a_content, "tool_use"),
            _user_entry(tmpl, _gen_uuid(), ts_b, result_blocks),
        ]
        if spec.get("reply") is not None:
            out.append(_assistant_entry(
                tmpl, _gen_uuid(), _gen_timestamp(ts_b),
                [{"type": "text", "text": spec["reply"]}], "end_turn"))
        return out

    raise _SpecError(f"unknown entry type: {etype!r}")


# --- indexing + tool-cycle span -----------------------------------------------
def _index_of(entries, uuid):
    for i, e in enumerate(entries):
        if e.get("uuid") == uuid:
            return i
    raise _NotFoundError(f"uuid not on branch: {uuid}")


def _has_block(entry, block_type):
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == block_type for b in content)


def _cycle_span(entries, i):
    """Index range (start, end) of the atomic tool cycle containing index ``i``.

    A tool cycle is an assistant entry with a ``tool_use`` block immediately
    followed by the user entry with the ``tool_result``. Any other entry is its
    own span ``(i, i)``.
    """
    e = entries[i]
    if _has_block(e, "tool_use"):
        if i + 1 < len(entries) and _has_block(entries[i + 1], "tool_result"):
            return (i, i + 1)
        return (i, i)
    if _has_block(e, "tool_result"):
        if i - 1 >= 0 and _has_block(entries[i - 1], "tool_use"):
            return (i - 1, i)
        return (i, i)
    return (i, i)


# --- create -------------------------------------------------------------------
def _create_at_start(entries, spec):
    base_ts = entries[0].get("timestamp") if entries else None
    seg = _build(entries, spec, base_ts)
    return seg + list(entries), [e["uuid"] for e in seg]


def _create_at_end(entries, spec):
    base_ts = entries[-1].get("timestamp") if entries else None
    seg = _build(entries, spec, base_ts)
    return list(entries) + seg, [e["uuid"] for e in seg]


def _create_after(entries, uuid, spec):
    end = _cycle_span(entries, _index_of(entries, uuid))[1]
    seg = _build(entries, spec, entries[end].get("timestamp"))
    out = list(entries[:end + 1]) + seg + list(entries[end + 1:])
    return out, [e["uuid"] for e in seg]


# --- read ---------------------------------------------------------------------
def _read_all(entries):
    return list(entries)


def _read_from(entries, uuid, n=None, reverse=False):
    """``n`` entries from ``uuid`` (inclusive), forward toward the leaf or, with
    ``reverse=True``, backward toward the root. Output is always ascending."""
    i = _index_of(entries, uuid)
    if reverse:
        lo = 0 if n is None else max(0, i - n + 1)
        return list(entries[lo:i + 1])
    hi = len(entries) if n is None else min(len(entries), i + n)
    return list(entries[i:hi])


def _read_between(entries, uuid_a, uuid_b):
    i, j = _index_of(entries, uuid_a), _index_of(entries, uuid_b)
    if i > j:
        i, j = j, i
    return list(entries[i:j + 1])


def _read_one(entries, uuid):
    for e in entries:
        if e.get("uuid") == uuid:
            return e
    return None


# --- update -------------------------------------------------------------------
def _update(entries, uuid, spec):
    """Replace the entry (or tool cycle) at ``uuid`` with what ``spec`` builds.
    The new head keeps the target's uuid and timestamp (an identity-preserving
    edit). Returns ``(entries, affected_uuids)``."""
    start, end = _cycle_span(entries, _index_of(entries, uuid))
    seg = _build(entries, spec, entries[start].get("timestamp"))
    head = dict(seg[0])
    head["uuid"] = entries[start].get("uuid")
    if entries[start].get("timestamp") is not None:
        head["timestamp"] = entries[start]["timestamp"]
    seg = [head] + seg[1:]
    out = list(entries[:start]) + seg + list(entries[end + 1:])
    return out, [e["uuid"] for e in seg]


# --- delete -------------------------------------------------------------------
def _delete(entries, uuid):
    """Delete the entry (or its whole tool cycle) at ``uuid``. The chain closes up
    by list order. Returns ``(entries, deleted_uuids)``."""
    start, end = _cycle_span(entries, _index_of(entries, uuid))
    removed = [e["uuid"] for e in entries[start:end + 1]]
    return list(entries[:start]) + list(entries[end + 1:]), removed


def _delete_between(entries, uuid_a, uuid_b):
    """Delete an inclusive range; endpoints expand to their tool cycles so a pair
    is never split. Order-agnostic. Returns ``(entries, deleted_uuids)``."""
    i, j = _index_of(entries, uuid_a), _index_of(entries, uuid_b)
    if i > j:
        i, j = j, i
    start = _cycle_span(entries, i)[0]
    end = _cycle_span(entries, j)[1]
    removed = [e["uuid"] for e in entries[start:end + 1]]
    return list(entries[:start]) + list(entries[end + 1:]), removed
