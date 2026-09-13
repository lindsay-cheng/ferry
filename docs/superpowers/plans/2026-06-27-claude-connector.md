# Claude Code Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `claude_connector.py` — a dumb local-filesystem I/O boundary that maps a Claude Code session id ↔ a file path on a unix `~/.claude` and moves bytes in and out.

**Architecture:** A single stdlib-only module of pure functions. Path mechanics (`projects_root`, `encode_cwd`, `session_path`) compute where files live; I/O functions (`resolve`, `read_text`, `write_text`, `list_sessions`) read and write bytes. No JSON parsing, no field rewriting, no id generation — those belong to the future `weave` layer. The module has no dependency on the transcript core.

**Tech Stack:** Python 3, stdlib only (`os`, `re`, `tempfile`, `pathlib`). Tests use stdlib `unittest`, matching the existing `test_transcript.py` style.

## Global Constraints

- **Stdlib only.** No third-party dependencies. No import of `transcript`/`transcript_api`.
- **Unix filesystem assumed.** `~` expansion, `/` separators, POSIX `os.replace` atomicity.
- **Storage base:** `$CLAUDE_CONFIG_DIR/projects` if the env var is set, else `~/.claude/projects`. Read the env var at call time (not import time) so tests can redirect it.
- **Errors subclass `ValueError`:** `SessionNotFound`, `AmbiguousSession`.
- **Byte-faithful:** reads return exact file contents (UTF-8); writes persist exactly the string given (no newline/encoding munging).
- **Crash-safe writes:** atomic via a temp file in the same directory + `os.replace`; `mkdir -p` the parent.
- **File layout:** flat repo root — module `claude_connector.py`, tests `test_claude_connector.py` (mirrors the existing `transcript.py` / `test_transcript.py` layout).
- **Tests never touch a real `~/.claude`:** every test redirects `CLAUDE_CONFIG_DIR` to a `tempfile.TemporaryDirectory`.

---

### Task 1: Path mechanics + exceptions

**Files:**
- Create: `claude_connector.py`
- Create: `test_claude_connector.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `projects_root() -> pathlib.Path` — `$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects`.
  - `encode_cwd(cwd: str) -> str` — every non-`[A-Za-z0-9]` char → `-`.
  - `session_path(cwd: str, session_id: str) -> pathlib.Path` — `projects_root()/encode_cwd(cwd)/f"{session_id}.jsonl"`.
  - `SessionNotFound(ValueError)`, `AmbiguousSession(ValueError)` — exception classes used by later tasks.
  - A reusable test base class `_ConnectorBase(unittest.TestCase)` that redirects `CLAUDE_CONFIG_DIR` to a temp dir and exposes `self.config: Path` and `self.root() -> Path`.

- [ ] **Step 1: Write the failing test**

Create `test_claude_connector.py`:

```python
"""Tests for claude_connector — no real ~/.claude is ever touched.

Run:  python3 -m unittest test_claude_connector -v
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import claude_connector as cc


class _ConnectorBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config = Path(self._tmp.name)
        patcher = mock.patch.dict(
            os.environ, {"CLAUDE_CONFIG_DIR": str(self.config)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def root(self):
        return self.config / "projects"

    def make(self, encoded_dir, session_id, text="{}\n"):
        d = self.root() / encoded_dir
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{session_id}.jsonl"
        f.write_text(text, encoding="utf-8")
        return f


class PathTests(_ConnectorBase):
    def test_projects_root_uses_config_dir_env(self):
        self.assertEqual(cc.projects_root(), self.config / "projects")

    def test_projects_root_defaults_to_home_without_env(self):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                cc.projects_root(), Path("~/.claude/projects").expanduser())

    def test_encode_cwd_replaces_non_alphanumeric(self):
        self.assertEqual(cc.encode_cwd("/Users/bob/myapp"), "-Users-bob-myapp")
        self.assertEqual(
            cc.encode_cwd("/Users/me/proj.test_v2"), "-Users-me-proj-test-v2")

    def test_session_path_composition(self):
        self.assertEqual(
            cc.session_path("/Users/bob/myapp", "abc-123"),
            self.config / "projects" / "-Users-bob-myapp" / "abc-123.jsonl")

    def test_errors_subclass_valueerror(self):
        self.assertTrue(issubclass(cc.SessionNotFound, ValueError))
        self.assertTrue(issubclass(cc.AmbiguousSession, ValueError))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_claude_connector.PathTests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_connector'`.

- [ ] **Step 3: Write minimal implementation**

Create `claude_connector.py`:

```python
"""Local-filesystem connector for Claude Code session JSONL.

A dumb I/O boundary: translate a Claude Code session id <-> a file path on a
unix ~/.claude, and move bytes in and out of those paths. No JSON parsing, no
field rewriting, no session-id generation -- those live in the weave layer.

Storage base honors $CLAUDE_CONFIG_DIR if set, else ~/.claude. Stdlib only.
"""

import os
import re
import tempfile
from pathlib import Path

_ENCODE_RE = re.compile(r"[^A-Za-z0-9]")


class SessionNotFound(ValueError):
    """A read target (session id or path) does not exist."""


class AmbiguousSession(ValueError):
    """A session id matches files in more than one project directory."""


# --- path mechanics (pure, no I/O) -------------------------------------------
def projects_root():
    """`$CLAUDE_CONFIG_DIR/projects` if the env var is set, else
    `~/.claude/projects` (expanded). Read at call time."""
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    root = Path(base) if base else Path("~/.claude")
    return root.expanduser() / "projects"


def encode_cwd(cwd):
    """The Claude Code project-dir encoding: every non-alphanumeric character
    becomes '-' (e.g. '/Users/bob/myapp' -> '-Users-bob-myapp')."""
    return _ENCODE_RE.sub("-", cwd)


def session_path(cwd, session_id):
    """Where a session for `cwd` with id `session_id` lives on this machine."""
    return projects_root() / encode_cwd(cwd) / f"{session_id}.jsonl"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_claude_connector.PathTests -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add claude_connector.py test_claude_connector.py
git commit -m "feat: connector path mechanics + exception types"
```

---

### Task 2: Session resolution + enumeration

**Files:**
- Modify: `claude_connector.py` (append `resolve`, `list_sessions`)
- Modify: `test_claude_connector.py` (append `ResolveTests`)

**Interfaces:**
- Consumes: `projects_root()`, `AmbiguousSession` (Task 1).
- Produces:
  - `resolve(session_id: str) -> pathlib.Path | None` — globs `projects_root()/*/<session_id>.jsonl`; returns the single match, `None` for no match, raises `AmbiguousSession` for >1.
  - `list_sessions() -> list[tuple[str, pathlib.Path]]` — `(session_id, path)` for every `*/*.jsonl` under the root, sorted by path. `session_id` is the filename stem.

- [ ] **Step 1: Write the failing test**

Append to `test_claude_connector.py` (before the `if __name__` block):

```python
class ResolveTests(_ConnectorBase):
    def test_resolve_none_when_absent(self):
        self.assertIsNone(cc.resolve("missing-id"))

    def test_resolve_single_match(self):
        f = self.make("-Users-a-proj", "sess1")
        self.assertEqual(cc.resolve("sess1"), f)

    def test_resolve_ambiguous_raises(self):
        self.make("-Users-a-proj", "dup")
        self.make("-Users-b-proj", "dup")
        with self.assertRaises(cc.AmbiguousSession):
            cc.resolve("dup")

    def test_list_sessions_enumerates_across_dirs(self):
        self.make("-Users-a-proj", "s1")
        self.make("-Users-b-proj", "s2")
        got = dict(cc.list_sessions())
        self.assertEqual(set(got), {"s1", "s2"})

    def test_list_sessions_empty_when_no_root(self):
        self.assertEqual(cc.list_sessions(), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_claude_connector.ResolveTests -v`
Expected: FAIL — `AttributeError: module 'claude_connector' has no attribute 'resolve'`.

- [ ] **Step 3: Write minimal implementation**

Append to `claude_connector.py`:

```python
# --- resolution / enumeration ------------------------------------------------
def resolve(session_id):
    """The path of the session with this id, or None. Raises AmbiguousSession
    if the id exists in more than one project dir (e.g. after a copy)."""
    matches = sorted(projects_root().glob(f"*/{session_id}.jsonl"))
    if not matches:
        return None
    if len(matches) > 1:
        dirs = ", ".join(m.parent.name for m in matches)
        raise AmbiguousSession(
            f"session id {session_id!r} found in {len(matches)} project "
            f"dirs: {dirs}")
    return matches[0]


def list_sessions():
    """(session_id, path) for every session file under the root, sorted by
    path. session_id is the filename stem."""
    return sorted(
        ((p.stem, p) for p in projects_root().glob("*/*.jsonl")),
        key=lambda pair: str(pair[1]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_claude_connector.ResolveTests -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add claude_connector.py test_claude_connector.py
git commit -m "feat: connector resolve + list_sessions"
```

---

### Task 3: Read bytes (id-or-path)

**Files:**
- Modify: `claude_connector.py` (append `read_text`)
- Modify: `test_claude_connector.py` (append `ReadTests`)

**Interfaces:**
- Consumes: `resolve()` (Task 2), `SessionNotFound` (Task 1).
- Produces:
  - `read_text(session: str) -> str` — `session` is a session id **or** a path, disambiguated structurally: if it contains `os.sep` or ends with `.jsonl` it is used directly as a path, otherwise it is treated as a session id and resolved. Returns exact UTF-8 contents. Raises `SessionNotFound` if the id resolves to nothing or the path does not exist. (An ambiguous id propagates `AmbiguousSession` from `resolve`.)

- [ ] **Step 1: Write the failing test**

Append to `test_claude_connector.py`:

```python
class ReadTests(_ConnectorBase):
    def test_read_text_by_id(self):
        self.make("-Users-a-proj", "sid", text='{"a":1}\n')
        self.assertEqual(cc.read_text("sid"), '{"a":1}\n')

    def test_read_text_by_path(self):
        f = self.make("-Users-a-proj", "sid", text="LINE1\nLINE2\n")
        self.assertEqual(cc.read_text(str(f)), "LINE1\nLINE2\n")

    def test_read_text_missing_id_raises(self):
        with self.assertRaises(cc.SessionNotFound):
            cc.read_text("nope")

    def test_read_text_missing_path_raises(self):
        missing = self.root() / "-x" / "no.jsonl"
        with self.assertRaises(cc.SessionNotFound):
            cc.read_text(str(missing))

    def test_read_text_ambiguous_id_propagates(self):
        self.make("-Users-a-proj", "dup")
        self.make("-Users-b-proj", "dup")
        with self.assertRaises(cc.AmbiguousSession):
            cc.read_text("dup")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_claude_connector.ReadTests -v`
Expected: FAIL — `AttributeError: module 'claude_connector' has no attribute 'read_text'`.

- [ ] **Step 3: Write minimal implementation**

Append to `claude_connector.py`:

```python
# --- bytes in ----------------------------------------------------------------
def read_text(session):
    """Read a session's JSONL as text. `session` is a session id OR a path:
    if it contains os.sep or ends with '.jsonl' it is treated as a path,
    otherwise as a session id to resolve. Raises SessionNotFound if absent."""
    if os.sep in session or session.endswith(".jsonl"):
        path = Path(session)
    else:
        path = resolve(session)
        if path is None:
            raise SessionNotFound(f"no session with id {session!r}")
    if not path.is_file():
        raise SessionNotFound(f"no session file at {str(path)!r}")
    return path.read_text(encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_claude_connector.ReadTests -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add claude_connector.py test_claude_connector.py
git commit -m "feat: connector read_text (id-or-path)"
```

---

### Task 4: Write bytes (atomic)

**Files:**
- Modify: `claude_connector.py` (append `write_text`)
- Modify: `test_claude_connector.py` (append `WriteTests`)

**Interfaces:**
- Consumes: nothing beyond stdlib (`os`, `tempfile`, `Path` already imported).
- Produces:
  - `write_text(path: str | pathlib.Path, text: str) -> pathlib.Path` — atomic write (temp file in the same dir + `os.replace`), `mkdir -p` the parent, overwrites unconditionally, writes `text` exactly as given. Returns the written `Path`.

- [ ] **Step 1: Write the failing test**

Append to `test_claude_connector.py`:

```python
class WriteTests(_ConnectorBase):
    def test_write_creates_parents_and_writes(self):
        p = self.root() / "-Users-a-proj" / "new.jsonl"
        ret = cc.write_text(p, "HELLO\n")
        self.assertEqual(ret, Path(p))
        self.assertEqual(p.read_text(encoding="utf-8"), "HELLO\n")

    def test_write_overwrites_unconditionally(self):
        p = self.root() / "-d" / "s.jsonl"
        cc.write_text(p, "first")
        cc.write_text(p, "second")
        self.assertEqual(p.read_text(encoding="utf-8"), "second")

    def test_write_is_byte_faithful_no_trailing_newline(self):
        p = self.root() / "-d" / "s.jsonl"
        cc.write_text(p, "no-newline")
        self.assertEqual(p.read_text(encoding="utf-8"), "no-newline")

    def test_write_leaves_no_temp_files(self):
        p = self.root() / "-d" / "s.jsonl"
        cc.write_text(p, "x")
        self.assertEqual(
            [f.name for f in p.parent.iterdir()], ["s.jsonl"])

    def test_write_accepts_str_path(self):
        p = self.root() / "-d" / "s.jsonl"
        ret = cc.write_text(str(p), "y")
        self.assertEqual(ret, p)
        self.assertEqual(p.read_text(encoding="utf-8"), "y")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_claude_connector.WriteTests -v`
Expected: FAIL — `AttributeError: module 'claude_connector' has no attribute 'write_text'`.

- [ ] **Step 3: Write minimal implementation**

Append to `claude_connector.py`:

```python
# --- bytes out ---------------------------------------------------------------
def write_text(path, text):
    """Atomically write `text` to `path`, creating parent dirs. Overwrites
    unconditionally and writes the string exactly as given. Returns the path.

    Atomic: a temp file in the same directory is written then os.replace()d
    into place, so an interrupted write never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_claude_connector.WriteTests -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest test_claude_connector -v`
Expected: PASS (20 tests total).

- [ ] **Step 6: Commit**

```bash
git add claude_connector.py test_claude_connector.py
git commit -m "feat: connector write_text (atomic, mkdir -p)"
```

---

## Notes for the implementer

- The connector module and tests live at the repo root and are **not** gitignored (the `.gitignore` only ignores `docs/` and build artifacts), so plain `git add` works in every task.
- The module reads `CLAUDE_CONFIG_DIR` at call time inside `projects_root()`, which is what lets the test base class redirect storage to a temp dir.
- Do not import `transcript`/`transcript_api` here — the connector is deliberately decoupled and trades only in strings and paths.

## Self-review (completed)

- **Spec coverage:** `projects_root`/`encode_cwd`/`session_path` → Task 1; `resolve` (incl. `AmbiguousSession`) + `list_sessions` → Task 2; `read_text` (id-or-path disambiguation, `SessionNotFound`) → Task 3; `write_text` (atomic, `mkdir -p`, byte-faithful, overwrite) → Task 4; errors subclass `ValueError` → Task 1; temp-dir testing strategy → `_ConnectorBase` in Task 1; "never decodes the lossy path" is satisfied structurally (resolve globs, write encodes — neither reverses the encoding). All spec §5/§6/§8 items covered.
- **Placeholder scan:** none — every code/test step contains complete code.
- **Type consistency:** `projects_root`/`encode_cwd`/`session_path`/`resolve`/`list_sessions`/`read_text`/`write_text` names and signatures match between their producing task, the consuming tasks, and the spec.
