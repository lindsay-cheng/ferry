# Weave core orchestrator (`weave.py`) — design

- **Date:** 2026-06-27
- **Status:** Approved design, ready for implementation planning
- **Scope:** One module — the `weave` orchestrator + CLI implementing **push**, **pull**,
  **merge**, plus the supporting **remote add** and **ls** commands.
- **Out of scope:** The `server` module (byte transport to/from a remote) and the `merge`
  module (Cerebras-backed content merge). This spec *defines the interfaces weave calls*
  on them; those modules are built separately and shaped around these signatures.

---

## 1. Purpose

`weave.py` is the orchestrator that turns the dumb I/O boundary (`claude_connector.py`)
and the pure in-memory transcript engine (`transcript_api.py`) into real user-facing
operations on Claude Code sessions. It owns **all policy**: which local session is
"current", what session id a new file gets, which fields are rewritten for the local
machine, and the accept/refuse decision when a collaborator returns bad data.

## 2. Layering & boundaries

```
weave.py  (CLI + orchestration — THIS spec)
   │   owns ALL logic: id choice, cwd/sessionId rewrite, current-session rule,
   │   config resolution, validation/refuse-to-write
   ├── claude_connector   reads/writes session JSONL bytes by id/path        [built]
   ├── transcript_api     parses bytes ↔ entries, edits the linear chain      [built]
   ├── server  (separate) moves bytes to/from a remote URL by name            [interface only]
   └── merge   (separate) merges two entry-lists into one via Cerebras        [interface only]
```

Design rules carried over from the connector spec:

- `server` never parses JSON — it is pure byte transport keyed by `(url, name)`.
- `merge` never touches `cwd` / `sessionId` / ids / the filesystem — it produces merged
  *content* only; weave does every field rewrite and the write, exactly as it does on a
  `pull`.
- weave never decodes an encoded project dir; it only ever *encodes* a known `cwd`
  (via the connector), so the lossy-path problem cannot arise.

### Interfaces weave calls (so the future modules can be shaped around them)

```python
# server module — pure byte transport keyed by (url, name); no JSONL awareness
server.push(url: str, name: str, text: str) -> None
server.pull(url: str, name: str) -> str            # raises if name absent
server.list(url: str) -> list[str]                 # session names on the remote

# merge module — content-only; weave does all field rewriting & writing afterward
merge.merge(target: list[dict], source: list[dict]) -> list[dict]
```

## 3. Resolved decisions

1. **CLI surface (this pass):** `push`, `pull`, `merge`, `remote add`, `ls`.
2. **Current session:** there is no magic. `push` and `merge`-target require an explicit
   `--session <id>`; `weave ls` is how the user finds the id.
3. **Pull identity:** generate a **fresh local uuid** for the new file, and rewrite every
   entry's `cwd` to the local encoded path **and** `sessionId` to the new id. Re-pulling
   produces a new file each time; no collisions.
4. **Push payload:** raw bytes, sent **as-is** with no rewriting. All machine-specific
   rewriting happens on `pull` (where the README puts it).
5. **Merge inputs:** two **local** session ids — `merge <source-id> --session <target-id>`.
   The remote `pull` is a separate prior step; merge never touches the network.
6. **Merge output:** written to a **fresh local id**; source and target files are **never
   modified**, so no backup/snapshot is required (copy-on-write at the file level).
7. **Remote config:** project-local `.weave/config` (INI), committed to the repo, in the
   README's shape: `[remote "<name>"] url = <url>`.
8. **Local cwd:** the process working directory (`os.getcwd()`); pulled/merged sessions
   land in the project dir for that cwd.

## 4. Internal helpers

- `_read_config() -> ConfigParser` / `_remote_url(name) -> str` — parse `.weave/config`;
  resolve a remote name to its url, raising a clear `ValueError` if the name is unknown.
- `_rewrite_for_local(entries: list[dict], new_id: str) -> list[dict]` — the shared
  "make it mine" step used by both pull and merge-output: set every entry's `cwd` to the
  local encoded `cwd` and every `sessionId` to `new_id`. Pure (returns a new list).
- `_new_id() -> str` — `str(uuid.uuid4())`.

## 5. Operations

All operations validate and fail **before** any local write.

### `weave push <remote> <name> --session <id>`
1. `connector.read_text(id)` → raw text (propagates `SessionNotFound` / `AmbiguousSession`).
2. `server.push(_remote_url(remote), name, text)` — bytes unchanged.
3. Print confirmation (`pushed <id> → <remote>/<name>`).

### `weave pull <remote> <name>`
1. `text = server.pull(_remote_url(remote), name)`.
2. `entries = transcript_api.from_text(text)`; if empty → warn and **exit before writing**.
3. `new_id = _new_id()`; `entries = _rewrite_for_local(entries, new_id)`.
4. `out = transcript_api.to_text(entries)`;
   `path = connector.session_path(os.getcwd(), new_id)`;
   `connector.write_text(path, out)`.
5. Print the new local id and the `claude --resume <new_id>` hint.

### `weave merge <source-id> --session <target-id>`
1. Read both locally via `connector.read_text` → `transcript_api.from_text` each.
   Empty either side → warn and **exit before writing**.
2. `merged = merge.merge(target_entries, source_entries)`.
3. Validate `merged` is a non-empty entry list; otherwise refuse to write and surface it.
4. `new_id = _new_id()`; `merged = _rewrite_for_local(merged, new_id)` (merged content may
   carry either machine's `cwd`, so normalize unconditionally).
5. `connector.write_text(connector.session_path(os.getcwd(), new_id), to_text(merged))`.
   **Source and target files are never touched.**
6. Print the new id and the resume hint.

### `weave remote add <name> <url>`
- `mkdir -p .weave/`; write/update `[remote "<name>"] url = <url>` in `.weave/config`.
  A second add for the same name updates the url.

### `weave ls [remote]`
- No remote → local sessions for the current cwd: filter `connector.list_sessions()` to the
  encoded-cwd project dir, print each id with a cheap summary (turn count and/or mtime).
- With a remote → `server.list(_remote_url(remote))`.

## 6. CLI structure

- Stdlib `argparse` with subparsers (no third-party deps, matching the codebase).
- One `main(argv=None) -> int` entry point. Each subcommand is a thin
  `cmd_*(args)` function that marshals arguments and calls a corresponding **library
  function** (`push()`, `pull()`, `merge()`, `remote_add()`, `ls()`).
- Library functions take plain arguments and are unit-testable without spawning a process.
- `main` catches `ValueError` (the shared base across connector, transcript, and weave
  errors), prints `weave: <message>` to stderr, and returns exit code `1`.

## 7. Error handling

All cases fail **before** local writes.

| Case | Behavior |
|------|----------|
| Unknown remote name | `ValueError` → `no remote '<name>'; add it with 'weave remote add'`. |
| Local session id not found / ambiguous | propagate connector's `SessionNotFound` / `AmbiguousSession`. |
| Empty / no chat history (pull or merge input) | warn and exit before writing anything. |
| Server unreachable / remote name absent | `server` raises; weave surfaces it; nothing written locally. |
| Merge returns empty / non-list | weave refuses to write, surfaces the bad output. |

## 8. Testing strategy

Stdlib `unittest`, matching the existing test style. `$CLAUDE_CONFIG_DIR` points at a
temporary fake `~/.claude` so no real session is read or written. The `server` and `merge`
collaborators are replaced with in-test fakes (no network, no Cerebras).

- **push:** reads the correct local bytes and hands the *exact* text to the fake server
  (byte-faithful, no rewrite).
- **pull:** fake server returns fixture text → assert a fresh id, `cwd` + `sessionId`
  rewritten to local on every entry, file written at `session_path(cwd, new_id)`;
  empty-history input exits without writing.
- **merge:** fake merge module → result written under a fresh id; both input files are
  byte-unchanged on disk afterward; empty/garbage merge output refuses to write.
- **remote add / `_read_config`:** INI round-trip; a second add updates the url.
- **ls:** local enumeration filtered to the cwd; remote form delegates to the fake server.
- **main / CLI:** arg parsing per subcommand; a raised `ValueError` → exit code 1 and a
  `weave: …` stderr message.

## 9. Future considerations (not now)

- `fork`, `resume`, `show`, and multi-session `--into` disambiguation from the README.
- The merge **reprompt loop** (re-run with user feedback on reject) — orchestrated by the
  weave CLI around `merge.merge` once interactive UX is in scope.
- Remote **snapshot-before-merge** safety, if merge ever overwrites in place instead of
  writing a fresh id.
