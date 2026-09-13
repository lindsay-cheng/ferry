# Claude Code connector (`claude_connector_api.py`) — design

**Date:** 2026-06-27
**Status:** Approved design, ready for implementation planning
**Scope:** One module — the local filesystem I/O boundary for Claude Code session JSONL.

---

## 1. Purpose

Translate a Claude Code **session id ↔ a file path** on a unix `~/.claude`, and move
**bytes** in and out of those paths. Nothing else.

This is the missing I/O layer beneath the existing pure, in-memory transcript core
(`transcript_api.py` / `transcript.py`), which is deliberately "no file or network I/O."
The connector is what lets higher layers act on *real* sessions.

## 2. Layering

```
weave (orchestrator — NOT in this spec)
   │   owns ALL logic: cwd/sessionId rewrite, session-id choice,
   │   fork / merge / handoff semantics
   ├── claude_connector_api   ── dumb I/O: session-id ↔ path, read bytes, write bytes
   └── transcript core     ── pure in-memory entry editing (already built)
```

The connector **never** parses JSON, **never** rewrites fields, and **never** chooses a
session id. weave reads via the connector, edits via the core, and writes back via the
connector.

## 3. Non-goals (explicitly out of scope)

- No JSON / entry parsing (callers use `transcript_api.from_text` / `to_text`).
- No field rewriting (`cwd`, `sessionId`, `gitBranch`, `version`, …) — that is weave's job.
- No session-id generation — weave decides ids and builds the destination path via
  `session_path(...)`.
- No resume-correctness guarantees about *content* — only that a write is not left
  half-finished on disk (see §6, atomic writes).
- No network / SSH / WeaveHub (a separate future module).

## 4. Platform assumptions

- Unix filesystem: `~` expansion, `/` separators, POSIX `os.replace` atomicity within a
  single filesystem.
- Stdlib only (`os`, `pathlib`, `glob`, `tempfile`). No third-party dependencies. No
  dependency on `transcript_api` (the connector trades in plain strings).
- Storage base honors `$CLAUDE_CONFIG_DIR` if set, else `~/.claude`.

## 5. Public surface

### Path mechanics (pure, no I/O)

| Function | Behavior |
|----------|----------|
| `projects_root() -> Path` | `$CLAUDE_CONFIG_DIR/projects` if the env var is set, else `~/.claude/projects` (expanded). |
| `encode_cwd(cwd: str) -> str` | The directory-name encoding Claude Code uses: every **non-alphanumeric** character is replaced with `-`. Example: `/Users/bob/myapp` → `-Users-bob-myapp`. |
| `session_path(cwd: str, session_id: str) -> Path` | `projects_root() / encode_cwd(cwd) / f"{session_id}.jsonl"`. |

### I/O

| Function | Behavior |
|----------|----------|
| `resolve(session_id: str) -> Path \| None` | Glob `projects_root()/*/<session_id>.jsonl`. Returns the single match, `None` if there are no matches, and **raises `AmbiguousSession`** if more than one project dir contains that id (possible after a copy/handoff). |
| `read_text(session: str) -> str` | `session` is a **session id or a path**, disambiguated structurally: if it contains an `os.sep` or ends with `.jsonl` it is used directly as a path; otherwise it is treated as a session id and resolved via `resolve()`. Returns the file's exact contents (UTF-8). Raises `SessionNotFound` if the id resolves to nothing or the path does not exist. |
| `write_text(path: str \| Path, text: str) -> Path` | Atomic write (temp file in the **same directory** + `os.replace`), creating parent dirs (`mkdir -p`). **Overwrites unconditionally** — this is also how "rewrite a JSONL in place" works. Writes `text` **exactly** as given (no newline or encoding munging). Returns the written path. |
| `list_sessions() -> list[tuple[str, Path]]` | `(session_id, path)` for every `*/<uuid>.jsonl` under the root, where `session_id` is the filename stem. |

### Errors

- `SessionNotFound(ValueError)` — a read target (id or path) does not exist.
- `AmbiguousSession(ValueError)` — a session id matches files in more than one project dir.

Both subclass `ValueError`, mirroring the core's `NotFoundError` / `SpecError` convention,
so callers can `except ValueError` for "any connector error."

## 6. Key properties

- **Byte-faithful and dumb.** Reads return the file's exact contents; writes persist exactly
  the string handed in. The connector imposes no structure and is unaware of JSONL semantics.
- **Never decodes an encoded directory.** Reads resolve by *globbing the id*; writes *encode*
  a known `cwd`. Because the module only ever encodes (and never tries to reverse the lossy
  `-` encoding), the well-known lossy-path problem cannot arise here.
- **Crash-safe writes.** Atomic `os.replace` means an interrupted write never leaves a
  half-written / corrupt session on disk, even though resume-correctness logic lives in weave.

## 7. How weave composes it (illustrative; not implemented here)

```python
text    = claude_connector_api.read_text(src_id)              # connector
entries = transcript_api.from_text(text)                  # core
# ... weave rewrites cwd / sessionId, picks a new id ...
out     = transcript_api.to_text(entries)                 # core
path    = claude_connector_api.session_path(local_cwd, new_id)  # connector
claude_connector_api.write_text(path, out)                    # connector
```

## 8. Testing strategy

All tests point `$CLAUDE_CONFIG_DIR` at a temporary directory — a fake `~/.claude` — so **no
real session is ever read or written**. No network. Stdlib `unittest`, matching the existing
test style.

- `encode_cwd` against known vectors (incl. leading `/`, dots, mixed punctuation).
- `session_path` composition.
- `resolve`: zero matches → `None`; one match → that path; two matches in different project
  dirs → `AmbiguousSession`.
- `read_text`: missing id → `SessionNotFound`; missing path → `SessionNotFound`; id form and
  path form both succeed; exact-content round-trip.
- `write_text`: creates missing parent dirs; atomic replace over an existing file; exact byte
  round-trip (including trailing-newline preservation); returns the path.
- `list_sessions`: enumerates ids across multiple project dirs.

## 9. Resolved decisions

1. **Addressing:** session id, resolved by global glob over `projects_root()/*/<id>.jsonl`.
2. **Responsibility:** connector is dumb I/O; all field-rewriting / id-choice / handoff logic
   lives in weave.
3. **Currency:** raw text + paths (no dependency on the transcript core).
4. **Duplicate id on `resolve`:** raise `AmbiguousSession` (do not silently pick one).
5. **Module name:** `claude_connector_api.py`.

## 10. Future considerations (not now)

- A `remote` module (SSH push/pull, WeaveHub) reuses the same path mechanics.
- If callers frequently want entries rather than text, a thin convenience wrapper can live in
  weave — not in the connector, to keep it decoupled.
