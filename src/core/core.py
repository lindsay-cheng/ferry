"""Ferry orchestrator core: push/pull Claude Code sessions, plus remote/ls.

Owns ALL policy (id choice, cwd/sessionId rewrite, config resolution,
validation). Delegates mechanics to ferry.connector (byte I/O),
ferry.config (remote resolution), and the `ferry.remote` collaborator (byte
transport to an HTTP folder hub). Stdlib only here; HTTP lives behind
`ferry.remote`.

Data pipeline for the remote operations:

    hub folder <--HTTP--> ferry.remote --text--> ferry.core

`ferry.remote` moves raw transcript text keyed by (url, name); this
module applies every machine-specific policy (fresh id, cwd/sessionId rewrite)
before writing anything locally.
"""

import importlib
import json
import os
import subprocess
import sys
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

from ferry import config
from ferry import connector as cc
from ferry.hub import normalize_name


class FerryError(ValueError):
    """Any ferry-layer error (unknown remote, empty history, remote transport)."""


# --- config ------------------------------------------------------------------
def remote_add(name, url, *, path=None):
    config.add_remote(name, url, path=path)


def _project_cwd(cwd, config_path):
    """Chat folder when caller omits ``cwd``: the Ferry project root."""
    if cwd is not None:
        return cwd
    try:
        return str(config.project_dir(path=config_path))
    except ValueError as e:
        raise FerryError(str(e)) from e


def _find_ferry_config():
    d = Path(os.getcwd())
    while True:
        candidate = d / ".ferry" / "config"
        if candidate.is_file():
            return candidate
        parent = d.parent
        if parent == d:
            return None
        d = parent


def _chat_cwd():
    """Chat folder for export/import: project root when ``.ferry`` exists, else cwd."""
    found = _find_ferry_config()
    if found is not None:
        return str(found.parent.parent.resolve())
    return str(Path.cwd().resolve())


def _resolve_remote(remote, *, path=None):
    """Resolve which remote to act on, defaulting to the sole configured one.

    When ``remote`` is given it is returned as-is. When it is ``None`` (caller
    omitted it) and exactly one remote is configured, that remote's name is used
    -- so a single-remote setup never has to name it. Zero or many configured
    remotes make the choice ambiguous, which is a ``FerryError``.
    """
    if remote is not None:
        return remote
    try:
        names = [name for name, _ in config.list_remotes(path=path)]
    except ValueError as e:
        raise FerryError(str(e)) from e
    if len(names) == 1:
        return names[0]
    if not names:
        raise FerryError("no remote configured — run: ferry remote add <name> <url>")
    raise FerryError(
        f"multiple remotes configured ({', '.join(sorted(names))}); specify one")


def _remote_url(remote, *, path=None):
    """Resolve a remote name to its url, as a FerryError on failure.

    Thin orchestrator-level adapter over :func:`ferry.config.get_remote` so
    every ferry-layer error shares the ``FerryError`` (``ValueError``) base.
    """
    try:
        return config.get_remote(remote, path=path)
    except ValueError as e:
        raise FerryError(str(e)) from e


def _load_server():
    return importlib.import_module("ferry.remote")


def _remote_call(fn, *args, action, target):
    """Invoke a `ferry.remote` transport call, mapping any failure to FerryError.

    Keeps the original (actionable) message from the transport layer -- e.g.
    missing credentials or an absent remote session -- while tagging it with
    what was being attempted so the CLI surfaces a clear `ferry: ...` line.
    """
    try:
        return fn(*args)
    except FerryError:
        raise
    except ValueError as e:
        raise FerryError(f"{action} {target}: {e}") from e


# --- session / log helpers ---------------------------------------------------
def _local_sessions(cwd):
    """Session ids for `cwd`, using the same filter as :func:`ls`."""
    enc = cc.encode_cwd(cwd or os.getcwd())
    return sorted(sid for sid, path in cc.list_sessions()
                   if path.parent.name == enc)


def _resolve_session(session, cwd):
    """Return an explicit session id, or pick the sole local session for `cwd`.

    When ``session`` is ``None`` (caller omitted it): one local chat for
    ``cwd`` is used; zero or many are ``FerryError``s that name the folder
    and list ids when ambiguous.
    """
    if session is not None:
        return session
    ids = _local_sessions(cwd)
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise FerryError(
            f"no local Claude sessions for {cwd!r} — "
            f"run Claude Code from that folder first")
    listed = ", ".join(ids)
    raise FerryError(
        f"multiple local sessions for {cwd!r} ({listed}); pass --session <id>")


def _prepare_push_text(text, session_id):
    """Return push bytes, dropping a truncated last line with a warning."""
    if not text:
        return text
    lines = text.splitlines(keepends=True)
    if not lines:
        return text
    last_body = lines[-1].rstrip("\r\n")
    if not last_body:
        return text
    try:
        json.loads(last_body)
        return text
    except json.JSONDecodeError:
        warnings.warn(
            f"skipping invalid JSON on last line of session {session_id!r}")
        return "".join(lines[:-1])


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
    try:
        entries = config.read_log(path=config_path)
    except ValueError as e:
        raise FerryError(str(e)) from e
    return list(reversed(entries))


# --- operations --------------------------------------------------------------
def _new_id():
    return str(uuid.uuid4())


def _normalize_export_name(name):
    """Validate and normalize an export basename (no ``.jsonl`` suffix)."""
    if not name:
        raise FerryError("name required")
    base = name
    if base.lower().endswith(".jsonl"):
        base = base[:-6]
    base = base.lower()
    if not base or base in (".", "..") or "/" in base:
        raise FerryError("name must be letters, numbers, and hyphen")
    try:
        return normalize_name(base)
    except ValueError as e:
        raise FerryError(str(e)) from e


def copy_file_to_clipboard(path):
    """Copy a file onto the clipboard (Darwin). Raises on failure."""
    resolved = str(Path(path).resolve())
    escaped = resolved.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e", f'set the clipboard to (POSIX file "{escaped}")'],
        check=True,
        capture_output=True,
    )


def _write_imported_text(text, cwd, *, source="import"):
    """Rewrite ``text`` into a fresh local session under ``cwd``; return new id."""
    new_id = _new_id()
    lines = text.splitlines(keepends=True)
    if not lines and text:
        lines = [text]
    out = []
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        if not line:
            continue
        rewritten = _rewrite_pull_line(line, new_id, cwd)
        if rewritten is None:
            if i == len(lines) - 1:
                warnings.warn(
                    f"skipping invalid JSON on last line of {source}")
            continue
        out.append(rewritten)
    if not out:
        raise FerryError("file has no chat history")
    cc.write_text(cc.session_path(cwd, new_id), "".join(out))
    return new_id


def _jsonl_import_candidates():
    """``*.jsonl`` files in cwd and ``~/Downloads``, newest mtime first."""
    found = []
    for folder in (Path.cwd(), Path.home() / "Downloads"):
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if path.is_file() and path.suffix == ".jsonl":
                if path.name.endswith(".crdownload"):
                    continue
                found.append(path)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


def _format_import_candidate(index, path):
    return f"{index}. {path.parent} {path.name}"


def _resolve_import_path(file=None, *, stdin_is_tty=None):
    """Pick a jsonl path from ``file`` or cwd/Downloads discovery."""
    if file is not None:
        path = Path(file)
        if not path.is_file():
            raise FerryError(f"file not found: {file}")
        return path
    candidates = _jsonl_import_candidates()
    if not candidates:
        raise FerryError(
            "no .jsonl file in current folder or Downloads — pass a path")
    if len(candidates) == 1:
        return candidates[0]
    lines = [_format_import_candidate(i, p)
             for i, p in enumerate(candidates, 1)]
    listing = "\n".join(lines)
    print(listing)
    is_tty = stdin_is_tty if stdin_is_tty is not None else sys.stdin.isatty()
    if not is_tty:
        raise FerryError(
            "multiple .jsonl files — pass a path or a number")
    choice = input("Choice [1]: ").strip()
    if not choice:
        return candidates[0]
    try:
        n = int(choice)
    except ValueError:
        raise FerryError(f"invalid choice: {choice!r}")
    if n < 1 or n > len(candidates):
        raise FerryError(f"invalid choice: {n}")
    return candidates[n - 1]


def _rewrite_pull_line(line, new_id, cwd):
    """Rewrite cwd/sessionId on one jsonl line when present; None if invalid JSON."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and ("cwd" in obj or "sessionId" in obj):
        if "cwd" in obj:
            obj["cwd"] = cwd
        if "sessionId" in obj:
            obj["sessionId"] = new_id
        return json.dumps(obj, ensure_ascii=False) + "\n"
    return line if line.endswith("\n") else line + "\n"


def pull(remote, name, *, cwd=None, server=None, config_path=None):
    """Download `name` from `remote` into a fresh local session.

    `remote` may be ``None`` to use the sole configured remote. Pipeline:
    ferry.remote.pull -> per-line cwd/sessionId rewrite -> connector write.
    Validates (unknown/ambiguous remote, transport failure, empty history) and
    fails before any local write.
    """
    remote = _resolve_remote(remote, path=config_path)
    url = _remote_url(remote, path=config_path)
    svr = server or _load_server()
    text = _remote_call(svr.pull, url, name, action="pull", target=f"{remote}/{name}")
    cwd = _project_cwd(cwd, config_path)
    new_id = _write_imported_text(text, cwd, source=f"session {name!r}")
    _log_op("pull", remote, name, new_id, path=config_path)
    return new_id


def push(remote, name, session_id, *, cwd=None, server=None, config_path=None):
    """Upload the local `session_id` to `remote` under `name`.

    `remote` may be ``None`` to use the sole configured remote. Omit
    `session_id` (pass ``None``) when exactly one local session exists for
    `cwd`; otherwise pass an explicit id. Returns the resolved remote name so
    callers can report where the push landed. Valid files are sent byte-for-byte;
    a truncated last line is dropped with a warning.
    """
    session_id = _resolve_session(session_id, _project_cwd(cwd, config_path))
    text = cc.read_text(session_id)            # SessionNotFound/Ambiguous propagate
    text = _prepare_push_text(text, session_id)
    remote = _resolve_remote(remote, path=config_path)
    url = _remote_url(remote, path=config_path)
    svr = server or _load_server()
    _remote_call(svr.push, url, name, text, action="push", target=f"{remote}/{name}")
    _log_op("push", remote, name, session_id, path=config_path)
    return remote


def rm(remote, name, *, server=None, config_path=None):
    """Delete the session stored as `name` on `remote`.

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
        enc = cc.encode_cwd(_project_cwd(cwd, config_path))
        return [sid for sid, path in cc.list_sessions()
                if path.parent.name == enc]
    url = _remote_url(remote, path=config_path)
    svr = server or _load_server()
    return _remote_call(svr.list, url, action="ls", target=remote)


def export(name, session_id=None):
    """Write a local session to ``<name>.jsonl`` in the current directory."""
    norm = _normalize_export_name(name)
    chat_cwd = _chat_cwd()
    session_id = _resolve_session(session_id, chat_cwd)
    text = cc.read_text(session_id)
    text = _prepare_push_text(text, session_id)
    out_path = Path.cwd() / f"{norm}.jsonl"
    if out_path.exists():
        raise FerryError(f"{out_path.name} already exists")
    out_path.write_text(text, encoding="utf-8")
    if sys.platform == "darwin":
        try:
            copy_file_to_clipboard(out_path)
        except (OSError, subprocess.CalledProcessError):
            pass
    return str(out_path)


def import_session(file=None, *, stdin_is_tty=None):
    """Import a jsonl file into a fresh local session; return ``(new_id, cwd)``."""
    path = _resolve_import_path(file, stdin_is_tty=stdin_is_tty)
    text = path.read_text(encoding="utf-8")
    cwd = _chat_cwd()
    new_id = _write_imported_text(text, cwd)
    return new_id, cwd
