# Transcript-Level Merge with Resumable Clone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the semantic-sidecar merge with a transcript-level merge that detects the shared prefix of two sessions, asks Cerebras for one briefing document unifying the divergent branches, and writes a new resumable cloned session with the briefing spliced in as a synthetic `Read` tool cycle.

**Architecture:** `weave.core.merge` linearizes both transcripts, finds the longest common content prefix, and hands (shared distilled, A-branch raw, B-branch raw) to a **pure** merge layer that returns briefing **text**. Core then clones source A in memory, deletes A's branch, splices in a `Read` tool cycle whose `tool_result` holds the briefing, rewrites identity for the local machine, and writes a resumable session JSONL via the connector. The old `MergedContext` schema, validator, JSON parser, and sidecar writer are deleted.

**Tech Stack:** Python 3 (stdlib only in core/transcript/connector; `supabase` only in `weave.remote`, untouched here). Tests are `unittest`-style, run with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q` from the repo root.

## Global Constraints

- **Run the suite with:** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q` (a broken third-party `lapse` pytest plugin must stay disabled). Baseline before this work: `120 passed, 2 skipped, 643 subtests passed`.
- **Stdlib only** in `weave.core`, `weave.transcript`, `weave.connector`. The merge layer may use stdlib HTTP only (already the case).
- **Package-per-module layout:** every module is a directory with an `__init__.py` public surface over impl files. Tests reach module *internals* through the impl submodule (e.g. `from weave.core import core as _core_mod`), and public surface through the package (`from weave import core`).
- **Cerebras / merge layer is pure and read-only:** it takes contexts in and returns text out. No file I/O, no transcript edits — those live only in `weave.core`.
- **Non-destructive:** both source sessions on disk are never mutated; the merged result is a new session id.
- **Merge output shape:** a single plain-text briefing document. No output schema, no JSON validation of the model response.
- **Test framework:** `unittest.TestCase` classes (matches the existing suite), executed via pytest.

---

### Task 1: Shared-prefix detection in core (additive)

Adds pure content-comparison helpers to `core`. Purely additive — no existing behavior changes, suite stays green.

**Files:**
- Modify: `weave/core/core.py` (add helpers near the top, after the imports)
- Test: `tests/test_weave_merge.py` (create)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `_entry_key(entry: dict) -> str` — content identity of a linearized entry, ignoring volatile id/machine fields.
  - `_has_tool_use(entry: dict) -> bool`
  - `_split_at_branch(a: list[dict], b: list[dict]) -> tuple[str | None, list[dict], list[dict]]` — returns `(branch_point_uuid_or_None, a_tail, b_tail)`. `branch_point_uuid` is the uuid of the last shared entry in `a` (None if the shared prefix is empty). Tails are the entries after the shared prefix.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_weave_merge.py`:

```python
"""Tests for weave.core transcript-level merge.

Run (from repo root):  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_weave_merge.py -q
"""

import unittest

from weave.core import core as _core


def _user(uuid, text, *, sid="s", cwd="/a", ts="2026-06-26T10:00:00.000Z"):
    return {
        "parentUuid": None, "type": "user", "uuid": uuid,
        "sessionId": sid, "cwd": cwd, "timestamp": ts,
        "message": {"role": "user", "content": text},
    }


def _assistant(uuid, text, *, sid="s", cwd="/a", ts="2026-06-26T10:00:01.000Z"):
    return {
        "parentUuid": None, "type": "assistant", "uuid": uuid,
        "sessionId": sid, "cwd": cwd, "timestamp": ts,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


class EntryKeyTests(unittest.TestCase):
    def test_same_content_different_identity_matches(self):
        a = _user("uuid-a", "hello", sid="alice", cwd="/Users/alice/p")
        b = _user("uuid-b", "hello", sid="bob", cwd="/Users/bob/p",
                  ts="2026-06-27T00:00:00.000Z")
        self.assertEqual(_core._entry_key(a), _core._entry_key(b))

    def test_different_content_differs(self):
        a = _user("uuid-a", "hello")
        b = _user("uuid-b", "goodbye")
        self.assertNotEqual(_core._entry_key(a), _core._entry_key(b))

    def test_tool_ids_are_ignored(self):
        a = {"type": "assistant", "uuid": "1", "message": {"role": "assistant",
             "content": [{"type": "tool_use", "id": "toolu_AAA", "name": "Read",
                          "input": {"file_path": "x"}}]}}
        b = {"type": "assistant", "uuid": "2", "message": {"role": "assistant",
             "content": [{"type": "tool_use", "id": "toolu_BBB", "name": "Read",
                          "input": {"file_path": "x"}}]}}
        self.assertEqual(_core._entry_key(a), _core._entry_key(b))


class SplitAtBranchTests(unittest.TestCase):
    def test_shared_then_branch(self):
        a = [_user("a1", "shared-1"), _assistant("a2", "shared-2"), _user("a3", "A-only")]
        b = [_user("b1", "shared-1"), _assistant("b2", "shared-2"), _user("b3", "B-only")]
        bp, a_tail, b_tail = _core._split_at_branch(a, b)
        self.assertEqual(bp, "a2")
        self.assertEqual([e["uuid"] for e in a_tail], ["a3"])
        self.assertEqual([e["uuid"] for e in b_tail], ["b3"])

    def test_no_shared_prefix(self):
        a = [_user("a1", "A-start")]
        b = [_user("b1", "B-start")]
        bp, a_tail, b_tail = _core._split_at_branch(a, b)
        self.assertIsNone(bp)
        self.assertEqual(len(a_tail), 1)
        self.assertEqual(len(b_tail), 1)

    def test_a_is_prefix_of_b(self):
        a = [_user("a1", "shared-1")]
        b = [_user("b1", "shared-1"), _user("b2", "B-extra")]
        bp, a_tail, b_tail = _core._split_at_branch(a, b)
        self.assertEqual(bp, "a1")
        self.assertEqual(a_tail, [])
        self.assertEqual([e["uuid"] for e in b_tail], ["b2"])

    def test_identical(self):
        a = [_user("a1", "shared-1"), _assistant("a2", "shared-2")]
        b = [_user("b1", "shared-1"), _assistant("b2", "shared-2")]
        bp, a_tail, b_tail = _core._split_at_branch(a, b)
        self.assertEqual(bp, "a2")
        self.assertEqual(a_tail, [])
        self.assertEqual(b_tail, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_weave_merge.py -q`
Expected: FAIL — `AttributeError: module 'weave.core.core' has no attribute '_entry_key'`.

- [ ] **Step 3: Add the helpers to `weave/core/core.py`**

Insert after the existing imports and before `class WeaveError` (the `json` module is already imported at the top of the file):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_weave_merge.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the full suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`
Expected: `127 passed, 2 skipped` (the prior 120 + 7 new), still green.

- [ ] **Step 6: Commit**

```bash
git add weave/core/core.py tests/test_weave_merge.py
git commit -m "feat(core): shared-prefix detection for transcript merge"
```

---

### Task 2: Briefing merge layer (additive)

Adds the pure text-briefing merger in a new module, leaving the old `MergedContext` merger in place. Additive — suite stays green.

**Files:**
- Create: `weave/merge/briefing.py`
- Modify: `weave/merge/__init__.py` (add new exports alongside the old)
- Test: `tests/test_merge_briefing.py` (create)

**Interfaces:**
- Consumes: `weave.merge.client.CerebrasClient` / `default_cerebras_client`, `weave.merge.env.cerebras_configured`, `weave.merge.exceptions.MergeClientError`/`MergeResponseError`, `weave.context.types.ChatContext`.
- Produces:
  - `build_briefing_prompt(shared_context: ChatContext | None, a_branch: list[dict], b_branch: list[dict]) -> str`
  - `class BriefingMerger` with `merge(self, shared_context, a_branch, b_branch) -> str` (raises `MergeResponseError` on empty output).
  - `class StubBriefingMerger` with the same `merge(...) -> str` signature, deterministic.
  - `default_briefing_merger(*, client: CerebrasClient | None = None) -> BriefingMerger` (raises `MergeClientError` if Cerebras unconfigured).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_merge_briefing.py`:

```python
"""Tests for the pure text-briefing merge layer.

Run (from repo root):  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_merge_briefing.py -q
"""

import unittest

from weave.context.types import ChatContext
from weave.merge.briefing import (
    BriefingMerger,
    StubBriefingMerger,
    build_briefing_prompt,
)
from weave.merge.exceptions import MergeResponseError


def _ctx(summary):
    return ChatContext(
        session_id="s", source_label="shared", leaf_uuid="u",
        git_branch=None, summary=summary,
    )


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.last_prompt = None

    def complete(self, prompt):
        self.last_prompt = prompt
        return self.response


_A_BRANCH = [{"type": "user", "uuid": "a1",
              "message": {"role": "user", "content": "A did this"}}]
_B_BRANCH = [{"type": "user", "uuid": "b1",
              "message": {"role": "user", "content": "B did that"}}]


class StubBriefingMergerTests(unittest.TestCase):
    def test_returns_text_mentioning_branch_sizes(self):
        out = StubBriefingMerger().merge(_ctx("background"), _A_BRANCH, _B_BRANCH)
        self.assertIsInstance(out, str)
        self.assertIn("background", out)
        self.assertIn("1", out)  # one turn per branch

    def test_handles_no_shared_context(self):
        out = StubBriefingMerger().merge(None, _A_BRANCH, _B_BRANCH)
        self.assertIsInstance(out, str)
        self.assertTrue(out.strip())


class BriefingMergerTests(unittest.TestCase):
    def test_returns_stripped_client_text(self):
        client = _FakeClient("  MERGED BRIEFING  ")
        out = BriefingMerger(client=client).merge(_ctx("bg"), _A_BRANCH, _B_BRANCH)
        self.assertEqual(out, "MERGED BRIEFING")

    def test_prompt_includes_branch_content(self):
        client = _FakeClient("ok")
        BriefingMerger(client=client).merge(_ctx("bg"), _A_BRANCH, _B_BRANCH)
        self.assertIn("A did this", client.last_prompt)
        self.assertIn("B did that", client.last_prompt)

    def test_empty_response_raises(self):
        client = _FakeClient("   ")
        with self.assertRaises(MergeResponseError):
            BriefingMerger(client=client).merge(_ctx("bg"), _A_BRANCH, _B_BRANCH)


class BuildBriefingPromptTests(unittest.TestCase):
    def test_no_shared_context_is_labeled(self):
        prompt = build_briefing_prompt(None, _A_BRANCH, _B_BRANCH)
        self.assertIn("none", prompt.lower())
        self.assertIn("A did this", prompt)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_merge_briefing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'weave.merge.briefing'`.

- [ ] **Step 3: Create `weave/merge/briefing.py`**

```python
"""Pure text-briefing merge layer.

Takes the distilled shared background plus the two raw divergent branches and
returns a single briefing document. No I/O, no transcript edits -- those live in
weave.core. This module will become the canonical merge layer once the old
MergedContext path is removed.
"""

from __future__ import annotations

import json

from weave.context.types import ChatContext
from weave.merge.client import CerebrasClient, default_cerebras_client
from weave.merge.env import cerebras_configured
from weave.merge.exceptions import MergeClientError, MergeResponseError


def build_briefing_prompt(
    shared_context: ChatContext | None,
    a_branch: list[dict],
    b_branch: list[dict],
) -> str:
    """Serialize the shared background + both raw branches into a briefing prompt."""
    shared_block = (
        json.dumps(shared_context.to_dict(), indent=2, sort_keys=True)
        if shared_context is not None
        else "(none -- the two sessions share no history)"
    )
    sections = [
        "You are merging two diverged Claude Code session branches into one.",
        "Write a SINGLE briefing document (plain prose / markdown) that a developer",
        "can read to resume the unified work: what each branch did, the decisions",
        "made, how any conflicts reconcile, the files touched, and the current state",
        "with next steps. Output the briefing text only -- no JSON, no code fences.",
        "",
        "Shared background (distilled):",
        shared_block,
        "",
        "Branch A (raw transcript turns):",
        json.dumps(a_branch, indent=2, sort_keys=True),
        "",
        "Branch B (raw transcript turns):",
        json.dumps(b_branch, indent=2, sort_keys=True),
    ]
    return "\n".join(sections)


class BriefingMerger:
    """Merge two branches into a briefing via Cerebras."""

    def __init__(self, client: CerebrasClient | None = None) -> None:
        self._client = client

    def merge(
        self,
        shared_context: ChatContext | None,
        a_branch: list[dict],
        b_branch: list[dict],
    ) -> str:
        client = self._client or default_cerebras_client()
        prompt = build_briefing_prompt(shared_context, a_branch, b_branch)
        text = client.complete(prompt).strip()
        if not text:
            raise MergeResponseError("merge response was empty")
        return text


class StubBriefingMerger:
    """Deterministic in-memory briefing merger for tests and local dev."""

    def merge(
        self,
        shared_context: ChatContext | None,
        a_branch: list[dict],
        b_branch: list[dict],
    ) -> str:
        shared_line = (
            shared_context.summary if shared_context is not None
            else "no shared history"
        )
        return (
            "MERGED SESSION BRIEFING\n"
            f"Shared background: {shared_line}\n"
            f"Branch A contributed {len(a_branch)} turn(s).\n"
            f"Branch B contributed {len(b_branch)} turn(s)."
        )


def default_briefing_merger(*, client: CerebrasClient | None = None) -> BriefingMerger:
    """Return a :class:`BriefingMerger` when Cerebras env vars are configured."""
    if client is None and not cerebras_configured():
        raise MergeClientError(
            "CEREBRAS_API_KEY and CEREBRAS_MODEL are required for merge"
        )
    return BriefingMerger(client=client)
```

- [ ] **Step 4: Add exports to `weave/merge/__init__.py`**

Add these imports and `__all__` entries alongside the existing ones (do not remove anything yet):

```python
from weave.merge.briefing import (
    BriefingMerger,
    StubBriefingMerger,
    build_briefing_prompt,
    default_briefing_merger,
)
```

Append `"BriefingMerger"`, `"StubBriefingMerger"`, `"build_briefing_prompt"`, `"default_briefing_merger"` to the `__all__` list.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_merge_briefing.py -q`
Expected: PASS (6 tests).

- [ ] **Step 6: Run the full suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`
Expected: `133 passed, 2 skipped`, green.

- [ ] **Step 7: Commit**

```bash
git add weave/merge/briefing.py weave/merge/__init__.py tests/test_merge_briefing.py
git commit -m "feat(merge): pure text-briefing merge layer (additive)"
```

---

### Task 3: `core.merge` — resumable cloned session (additive)

Adds the orchestration that ties Task 1 + Task 2 into a resumable JSONL, alongside the still-present `merge_contexts`. Uses the temporary name `MergedSession` for the result (renamed to `MergeResult` in Task 4, where the old `MergeResult` is deleted).

**Files:**
- Modify: `weave/core/core.py` (add `merge`, `_read_source`, `_distill_shared`, `MergedSession`)
- Modify: `weave/core/__init__.py` (export `merge`, `MergedSession`)
- Test: `tests/test_weave_merge.py` (append)

**Interfaces:**
- Consumes: `_split_at_branch` (Task 1); `default_briefing_merger` (Task 2, imported lazily); existing `weave.transcript` (`from_text`, `to_text`, `delete_between`, `create_after`, `create_at_start`), existing `weave.connector` (`read_text`, `session_path`, `write_text`), existing `core._new_id` and `core._rewrite_for_local`, `weave.context.distill.distill_from_jsonl`.
- Produces:
  - `merge(source_a: str, source_b: str, *, cwd: str | None = None, merger=None) -> MergedSession`
  - `@dataclass(frozen=True) class MergedSession` with fields `session_id: str`, `jsonl_path: str`, `branch_point: str | None`, `a_tail_len: int`, `b_tail_len: int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_weave_merge.py` (add imports at the top of the file: `import json`, `import os`, `import tempfile`, `from pathlib import Path`, `from unittest import mock`, `from weave import connector as cc`, `from weave import core`, `from weave.merge.briefing import StubBriefingMerger`):

```python
_VALID_A = (
    '{"parentUuid":null,"type":"user","uuid":"u1","sessionId":"sA","cwd":"/src",'
    '"timestamp":"2026-06-26T10:00:00.000Z",'
    '"message":{"role":"user","content":"shared question"}}\n'
    '{"parentUuid":"u1","type":"assistant","uuid":"u2","sessionId":"sA","cwd":"/src",'
    '"timestamp":"2026-06-26T10:00:01.000Z",'
    '"message":{"role":"assistant","content":[{"type":"text","text":"shared answer"}]}}\n'
    '{"parentUuid":"u2","type":"user","uuid":"u3","sessionId":"sA","cwd":"/src",'
    '"timestamp":"2026-06-26T10:00:02.000Z",'
    '"message":{"role":"user","content":"A branch work"}}\n'
)
_VALID_B = (
    '{"parentUuid":null,"type":"user","uuid":"v1","sessionId":"sB","cwd":"/other",'
    '"timestamp":"2026-06-27T09:00:00.000Z",'
    '"message":{"role":"user","content":"shared question"}}\n'
    '{"parentUuid":"v1","type":"assistant","uuid":"v2","sessionId":"sB","cwd":"/other",'
    '"timestamp":"2026-06-27T09:00:01.000Z",'
    '"message":{"role":"assistant","content":[{"type":"text","text":"shared answer"}]}}\n'
    '{"parentUuid":"v2","type":"user","uuid":"v3","sessionId":"sB","cwd":"/other",'
    '"timestamp":"2026-06-27T09:00:02.000Z",'
    '"message":{"role":"user","content":"B branch work"}}\n'
)


class _MergeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = "/Users/tester/proj"
        self.a_path = Path(self.tmp) / "a.jsonl"
        self.b_path = Path(self.tmp) / "b.jsonl"
        self.a_path.write_text(_VALID_A, encoding="utf-8")
        self.b_path.write_text(_VALID_B, encoding="utf-8")
        # Redirect the connector's ~/.claude root into the temp dir.
        patcher = mock.patch.dict(
            os.environ, {"CLAUDE_CONFIG_DIR": self.tmp}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _written_entries(self, result):
        text = Path(result.jsonl_path).read_text(encoding="utf-8")
        return [json.loads(l) for l in text.splitlines() if l.strip()]


class MergeWritesResumableSessionTests(_MergeBase):
    def test_shared_prefix_preserved_and_read_cycle_spliced(self):
        result = core.merge(str(self.a_path), str(self.b_path),
                            cwd=self.cwd, merger=StubBriefingMerger())
        entries = self._written_entries(result)

        # Shared prefix (2 turns) preserved verbatim by content.
        self.assertEqual(entries[0]["message"]["content"], "shared question")
        self.assertEqual(entries[1]["message"]["content"][0]["text"], "shared answer")

        # Exactly one Read tool_use carrying the stub briefing in its result.
        tool_uses = [b for e in entries
                     for b in (e.get("message", {}).get("content") or [])
                     if isinstance(b, dict) and b.get("type") == "tool_use"]
        self.assertEqual(len(tool_uses), 1)
        self.assertEqual(tool_uses[0]["name"], "Read")
        results = [b for e in entries
                   for b in (e.get("message", {}).get("content") or [])
                   if isinstance(b, dict) and b.get("type") == "tool_result"]
        self.assertIn("MERGED SESSION BRIEFING", results[0]["content"])

        # A's branch turn ("A branch work") is gone from the transcript.
        texts = json.dumps(entries)
        self.assertNotIn("A branch work", texts)
        self.assertNotIn("B branch work", texts)

    def test_identity_rewritten_for_local_machine(self):
        result = core.merge(str(self.a_path), str(self.b_path),
                            cwd=self.cwd, merger=StubBriefingMerger())
        entries = self._written_entries(result)
        for e in entries:
            self.assertEqual(e["cwd"], self.cwd)
            self.assertEqual(e["sessionId"], result.session_id)
        # File lives under the encoded cwd for this machine.
        self.assertEqual(Path(result.jsonl_path).stem, result.session_id)

    def test_result_reports_branch_lengths(self):
        result = core.merge(str(self.a_path), str(self.b_path),
                            cwd=self.cwd, merger=StubBriefingMerger())
        self.assertEqual(result.a_tail_len, 1)
        self.assertEqual(result.b_tail_len, 1)
        self.assertIsNotNone(result.branch_point)


class MergeErrorTests(_MergeBase):
    def test_identical_sessions_raise(self):
        self.b_path.write_text(_VALID_A, encoding="utf-8")
        with self.assertRaises(core.WeaveError):
            core.merge(str(self.a_path), str(self.b_path),
                       cwd=self.cwd, merger=StubBriefingMerger())

    def test_missing_source_raises_weave_error(self):
        with self.assertRaises(core.WeaveError):
            core.merge(str(Path(self.tmp) / "nope.jsonl"), str(self.b_path),
                       cwd=self.cwd, merger=StubBriefingMerger())

    def test_empty_shared_prefix_yields_only_read_cycle(self):
        self.a_path.write_text(
            '{"parentUuid":null,"type":"user","uuid":"x1","sessionId":"sA",'
            '"cwd":"/src","timestamp":"2026-06-26T10:00:00.000Z",'
            '"message":{"role":"user","content":"A unique start"}}\n',
            encoding="utf-8")
        self.b_path.write_text(
            '{"parentUuid":null,"type":"user","uuid":"y1","sessionId":"sB",'
            '"cwd":"/other","timestamp":"2026-06-27T09:00:00.000Z",'
            '"message":{"role":"user","content":"B unique start"}}\n',
            encoding="utf-8")
        result = core.merge(str(self.a_path), str(self.b_path),
                            cwd=self.cwd, merger=StubBriefingMerger())
        self.assertIsNone(result.branch_point)
        entries = self._written_entries(result)
        # Only the Read cycle remains (assistant tool_use + user tool_result).
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["type"], "assistant")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_weave_merge.py -q`
Expected: FAIL — `AttributeError: module 'weave.core.core' has no attribute 'merge'` (the new tests; Task 1 tests still pass).

- [ ] **Step 3: Add `merge` + helpers + `MergedSession` to `weave/core/core.py`**

Add the dataclass near the existing `MergeResult` dataclass:

```python
@dataclass(frozen=True)
class MergedSession:
    session_id: str
    jsonl_path: str
    branch_point: str | None
    a_tail_len: int
    b_tail_len: int
```

Add these functions (place them after the existing `merge_contexts`):

```python
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


def merge(source_a, source_b, *, cwd=None, merger=None):
    """Merge two sessions into a new resumable cloned session.

    Detects the shared content prefix, asks the merge layer for one briefing
    document unifying the divergent branches, then clones source A: drops A's
    branch and splices in a synthetic Read tool cycle whose result holds the
    briefing. Identity is rewritten for the local machine and the clone is
    written under ~/.claude. Both sources are left untouched.
    """
    a = tx.from_text(_read_source(source_a))
    b = tx.from_text(_read_source(source_b))
    if not a and not b:
        raise WeaveError("no chat history in either session")

    branch_point, a_tail, b_tail = _split_at_branch(a, b)
    if not a_tail and not b_tail:
        raise WeaveError("sessions are identical; nothing to merge")

    shared_ctx = _distill_shared(a, branch_point, source_a)

    from weave.merge.briefing import default_briefing_merger
    active = merger or default_briefing_merger()
    briefing = active.merge(shared_ctx, a_tail, b_tail)   # MergeError propagates; nothing written yet

    entries = list(a)
    if a_tail:
        entries, _ = tx.delete_between(entries, a_tail[0]["uuid"], a[-1]["uuid"])
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
    return MergedSession(
        session_id=new_id, jsonl_path=str(path), branch_point=branch_point,
        a_tail_len=len(a_tail), b_tail_len=len(b_tail),
    )
```

- [ ] **Step 4: Export from `weave/core/__init__.py`**

Add `merge` and `MergedSession` to the `from weave.core.core import (...)` list and to `__all__` (keep `merge_contexts`/`MergeResult` for now).

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_weave_merge.py -q`
Expected: PASS (Task 1's 7 + Task 3's 6 = 13).

- [ ] **Step 6: Run the full suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`
Expected: `139 passed, 2 skipped`, green.

- [ ] **Step 7: Commit**

```bash
git add weave/core/core.py weave/core/__init__.py tests/test_weave_merge.py
git commit -m "feat(core): merge writes a resumable cloned session"
```

---

### Task 4: Switch CLI to `core.merge`; delete the sidecar path; canonicalize names

Flips the CLI to the new merge, deletes the `MergedContext` schema/validator/parser/sidecar and the old mergers, and renames the temporary names to their canonical forms. Ends green.

**Files:**
- Modify: `weave/cli/cli.py`
- Modify: `weave/core/core.py` (delete `merge_contexts`, `_write_merge_sidecar`, `_resolve_source_path`, old `MergeResult`, sidecar constants; rename `MergedSession` → `MergeResult`)
- Modify: `weave/core/__init__.py`
- Modify: `weave/merge/protocols.py`, `weave/merge/cerebras.py`, `weave/merge/stub.py`, `weave/merge/prompt.py`, `weave/merge/factory.py`, `weave/merge/__init__.py`, `weave/merge/exceptions.py`
- Delete: `weave/merge/types.py`, `weave/merge/validator.py`, `weave/merge/parse.py`, `weave/merge/briefing.py`
- Modify/Delete tests: `tests/test_weave_cli.py` (modify), `tests/merge_test_fixtures.py` (rewrite), `tests/test_merge_pipeline.py` (reduce to boundary test), `tests/test_merge_briefing.py` (rename classes), delete `tests/test_merge_types.py`, delete `tests/test_merge_e2e.py`

**Interfaces:**
- Consumes: `core.merge` + `MergeResult` (post-rename), `weave.merge` text contract.
- Produces final public surface:
  - `weave.merge`: `ContextMerger.merge(shared, a_branch, b_branch) -> str`, `CerebrasMerger`, `StubMerger`, `build_merge_prompt`, `default_merger`, `MergeError`/`MergeClientError`/`MergeResponseError`.
  - `weave.core`: `merge(...) -> MergeResult`, `MergeResult(session_id, jsonl_path, branch_point, a_tail_len, b_tail_len)`, plus existing `pull`/`push`/`ls`/`remote_add`/`WeaveError`.
  - `weave.cli`: `weave merge <source_a> <source_b>`.

- [ ] **Step 1: Write/adjust the failing CLI test**

In `tests/test_weave_cli.py`, replace the existing `merge` test body so it drives the new signature. Find the merge test (it currently patches `core.merge_contexts` and passes `--output-dir`) and replace it with:

```python
    def test_merge_subcommand_prints_resume_hint(self):
        expected = _core_mod.MergeResult(
            session_id="merged-123", jsonl_path="/tmp/merged-123.jsonl",
            branch_point="bp", a_tail_len=1, b_tail_len=2)
        with mock.patch.object(_core_mod, "merge", return_value=expected) as m:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["merge", "/tmp/a.jsonl", "/tmp/b.jsonl"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with("/tmp/a.jsonl", "/tmp/b.jsonl")
        self.assertIn("merged-123", out.getvalue())
        self.assertIn("claude --resume merged-123", out.getvalue())
```

(`_core_mod` is already imported in this file as `from weave.core import core as _core_mod`.)

- [ ] **Step 2: Run the CLI test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_weave_cli.py -q`
Expected: FAIL — `AttributeError`/`TypeError` (no `core.merge` wired in the CLI yet; old `MergeResult` shape).

- [ ] **Step 3: Update `weave/cli/cli.py` merge subcommand**

Replace the `merge` parser block:

```python
    mg = sub.add_parser("merge", help="merge two session JSONL files via Cerebras")
    mg.add_argument("source_a")
    mg.add_argument("source_b")
    mg.add_argument("--output-dir", default=None)
```

with:

```python
    mg = sub.add_parser("merge", help="merge two sessions into a new resumable session")
    mg.add_argument("source_a")
    mg.add_argument("source_b")
```

Replace the `merge` dispatch branch in `main`:

```python
        elif args.cmd == "merge":
            result = core.merge_contexts(
                args.source_a, args.source_b, output_dir=args.output_dir
            )
            print(result.sidecar_path)
```

with:

```python
        elif args.cmd == "merge":
            result = core.merge(args.source_a, args.source_b)
            print(f"merged into {result.session_id}\n"
                  f"  resume: claude --resume {result.session_id}")
```

- [ ] **Step 4: Delete the sidecar path in `weave/core/core.py` and rename the result**

- Delete `merge_contexts`, `_write_merge_sidecar`, `_resolve_source_path`, the old `MergeResult` dataclass, and the module constants `_DEFAULT_MERGED_DIR`, `_WEAVE_MERGE_VERSION`, `_COMPATIBILITY_NOTE`.
- Remove now-unused imports if they are no longer referenced anywhere in the file: `tempfile`, `json` (check — `json` is still used by `_entry_key`, so keep `json`; `tempfile` and `datetime`/`timezone` were only for the sidecar — remove if unreferenced), `MergedContext`, `default_merger` (old), `ContextMerger`.
- Rename the `MergedSession` dataclass to `MergeResult` and update its use in `merge`.
- Replace the lazy `from weave.merge.briefing import default_briefing_merger` inside `merge` with the canonical `from weave.merge.factory import default_merger` and call `default_merger()` (the factory now returns the text `CerebrasMerger` after Step 6).

- [ ] **Step 5: Update `weave/core/__init__.py`**

Re-export `merge` and `MergeResult`; remove `merge_contexts` and `MergedSession`. Final list: `MergeResult, WeaveError, ls, merge, pull, push, remote_add`.

- [ ] **Step 6: Canonicalize the merge layer (move briefing → canonical files, delete old)**

- `weave/merge/protocols.py`: replace `ContextMerger` with the text contract:

```python
"""Merge-layer plug-in point."""

from __future__ import annotations

from typing import Protocol

from weave.context.types import ChatContext


class ContextMerger(Protocol):
    """Merge a shared background + two raw branches into a briefing document."""

    def merge(
        self,
        shared_context: ChatContext | None,
        a_branch: list[dict],
        b_branch: list[dict],
    ) -> str:
        ...
```

- `weave/merge/prompt.py`: replace its contents with the `build_merge_prompt(shared_context, a_branch, b_branch)` function — identical body to `build_briefing_prompt` from `briefing.py` (copy it verbatim, rename the function to `build_merge_prompt`). Delete the old `_MERGE_OUTPUT_SCHEMA` and the old `build_merge_prompt`.
- `weave/merge/cerebras.py`: replace `CerebrasMerger` with the body of `BriefingMerger` (rename class to `CerebrasMerger`), importing `build_merge_prompt` from `weave.merge.prompt`. Remove the `parse`/`validator`/`MergedContext` imports and the `feedback` handling.
- `weave/merge/stub.py`: replace its contents with `StubMerger` = the body of `StubBriefingMerger` (rename class to `StubMerger`). Delete all the old `MergedContext` helper functions.
- `weave/merge/factory.py`: `default_merger(*, client=None) -> ContextMerger` returns `CerebrasMerger(client=client)` when configured (the existing body already does this; just confirm the return type is the text `CerebrasMerger`).
- `weave/merge/exceptions.py`: update `MergeResponseError` docstring to "Model output was empty or unusable."
- Delete files: `weave/merge/types.py`, `weave/merge/validator.py`, `weave/merge/parse.py`, `weave/merge/briefing.py`.
- `weave/merge/__init__.py`: final exports only:

```python
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
```

- [ ] **Step 7: Update tests to the canonical names and delete dead test files**

- Delete `tests/test_merge_types.py` (the `MergedContext` schema is gone).
- Delete `tests/test_merge_e2e.py` (superseded by `tests/test_weave_merge.py`).
- `tests/test_merge_briefing.py`: rename imports `BriefingMerger → CerebrasMerger`, `StubBriefingMerger → StubMerger`, `build_briefing_prompt → build_merge_prompt`, all from `weave.merge`. Rename the test classes accordingly (e.g. `BriefingMergerTests → CerebrasMergerTests`). Rename the file to `tests/test_merge_layer.py`.
- `tests/test_weave_merge.py`: change `from weave.merge.briefing import StubBriefingMerger` to `from weave.merge import StubMerger` and replace `StubBriefingMerger()` with `StubMerger()`.
- `tests/test_merge_pipeline.py`: reduce to the `WeaveImportBoundaryTests` class only. Replace the top-of-file imports with exactly:

```python
"""Boundary test: weave must reach the private transcript engine only via the
public weave.transcript surface.

Run (from repo root):  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_merge_pipeline.py -q
"""

import ast
import unittest
from pathlib import Path

_WEAVE_ROOT = Path(__file__).resolve().parent.parent / "weave"
```

Keep the `WeaveImportBoundaryTests` class and the `if __name__ == "__main__"` block; delete every other class and any `merge_test_fixtures`/`MergedContext`/`CerebrasMerger` references in the file.
- `tests/merge_test_fixtures.py`: delete everything that references `MergedContext`/`SourceRef`/`MergedDecision` and the `ChatContext` sample/`merged_dict_for_contexts` helpers. Keep only what surviving tests still import. After this task, check usage: `grep -rn "merge_test_fixtures" tests/` — if nothing imports it, delete the file.

- [ ] **Step 8: Run the full suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`
Expected: green. Then confirm no dangling references:

Run: `grep -rn "MergedContext\|merge_contexts\|validate_merged_context\|parse_merged_response\|MergedSession\|BriefingMerger\|sidecar" weave tests`
Expected: no matches.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: switch merge to resumable clone; remove MergedContext sidecar path"
```

---

### Task 5: Real-Cerebras integration test (gated)

Rewrites the one gated integration test to assert briefing text + a resumable merged session, instead of a `MergedContext`.

**Files:**
- Modify: `tests/test_cerebras_integration.py`

**Interfaces:**
- Consumes: `weave.core.merge`, `weave.merge.CerebrasMerger`, `weave.merge.env` gating helpers, `weave.merge.exceptions`.

- [ ] **Step 1: Rewrite the integration test**

Replace the body so the gated test (skipped unless `CEREBRAS_API_KEY` is set) drives a real merge of two fixture JSONLs through `core.merge` with a real `CerebrasMerger`, and asserts:
- the call returns a `MergeResult` with a non-empty `session_id`,
- the written JSONL round-trips through `weave.transcript` as a single linear chain,
- exactly one `Read` tool cycle is present and its `tool_result` content is non-empty text.

Use the existing skip guard pattern:

```python
import os
import unittest

from weave.merge.env import cerebras_configured


@unittest.skipUnless(cerebras_configured(), "CEREBRAS_API_KEY/CEREBRAS_MODEL not set")
class CerebrasMergeIntegrationTests(unittest.TestCase):
    ...
```

Build two minimal fixture JSONL strings inline (a shared prefix + one divergent turn each, like `_VALID_A`/`_VALID_B` in `tests/test_weave_merge.py`), write them to a temp dir, point `CLAUDE_CONFIG_DIR` at the temp dir, call `core.merge(...)` with no `merger=` (real client), and assert as above. Remove all `MergedContext`/`validate_merged_context`/`MERGE_SCHEMA_VERSION` imports and assertions.

- [ ] **Step 2: Run the integration test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_cerebras_integration.py -q`
Expected: `1 skipped` (no API key in CI) — or PASS locally if a key is configured.

- [ ] **Step 3: Run the full suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q`
Expected: green; skip count unchanged from the gated test(s).

- [ ] **Step 4: Commit**

```bash
git add tests/test_cerebras_integration.py
git commit -m "test: gated real-Cerebras integration test for resumable merge"
```

---

## Notes for the implementer

- **Why the temporary names.** `briefing.py`, `BriefingMerger`/`StubBriefingMerger`, and `MergedSession` exist only so Tasks 2–3 can land green alongside the old `MergedContext` path. Task 4 deletes the old path and renames these to their canonical forms (`cerebras.py`/`stub.py`, `CerebrasMerger`/`StubMerger`, `MergeResult`). Don't skip the rename — the spec's public surface uses the canonical names.
- **`CLAUDE_CONFIG_DIR`.** `weave.connector.projects_root()` honors `$CLAUDE_CONFIG_DIR`; tests set it to a temp dir so no real `~/.claude` is touched. This is how the merge write is sandboxed.
- **Order of operations in `core.merge`.** The merge-layer call happens *before* any clone edit or write, so a Cerebras failure (`MergeClientError`/`MergeResponseError`) aborts with nothing written — matching the spec's error-handling guarantees.
- **Known caveat (accepted).** When the shared prefix is empty, the merged transcript begins with an assistant tool cycle rather than a user turn. This is intentional per the spec's "leave it empty" decision.

## Out of scope (follow-up, not this plan)

The README still documents the SSH WeaveHub and the sidecar merge. After this lands, update the README "Merge pipeline"/"Write" stage and error-handling rows to describe the resumable-clone behavior. Tracked separately.
