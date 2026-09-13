"""Tests for weave.core transcript-level merge.

Run (from repo root):  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_weave_merge.py -q
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from weave import connector as cc
from weave import core
from weave.core import core as _core
from weave.merge import StubMerger


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

    def test_tool_result_ids_are_ignored(self):
        a = {"type": "user", "uuid": "1", "message": {"role": "user",
             "content": [{"type": "tool_result", "tool_use_id": "toolu_AAA",
                          "content": "same output"}]}}
        b = {"type": "user", "uuid": "2", "message": {"role": "user",
             "content": [{"type": "tool_result", "tool_use_id": "toolu_BBB",
                          "content": "same output"}]}}
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

    def test_no_dangling_tool_use_at_branch_point(self):
        tool_a = {"type": "assistant", "uuid": "a2", "message": {"role": "assistant",
                  "content": [{"type": "tool_use", "id": "toolu_X", "name": "Read",
                               "input": {"file_path": "x"}}]}}
        tool_b = {"type": "assistant", "uuid": "b2", "message": {"role": "assistant",
                  "content": [{"type": "tool_use", "id": "toolu_Y", "name": "Read",
                               "input": {"file_path": "x"}}]}}
        a = [_user("a1", "shared"), tool_a, _user("a3", "A-only")]
        b = [_user("b1", "shared"), tool_b, _user("b3", "B-only")]
        bp, a_tail, b_tail = _core._split_at_branch(a, b)
        self.assertEqual(bp, "a1")
        self.assertEqual([e["uuid"] for e in a_tail], ["a2", "a3"])
        self.assertEqual([e["uuid"] for e in b_tail], ["b2", "b3"])


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
                            cwd=self.cwd, merger=StubMerger())
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
                            cwd=self.cwd, merger=StubMerger())
        entries = self._written_entries(result)
        for e in entries:
            self.assertEqual(e["cwd"], self.cwd)
            self.assertEqual(e["sessionId"], result.session_id)
        # File lives under the encoded cwd for this machine.
        self.assertEqual(Path(result.jsonl_path).stem, result.session_id)

    def test_result_reports_branch_lengths(self):
        result = core.merge(str(self.a_path), str(self.b_path),
                            cwd=self.cwd, merger=StubMerger())
        self.assertEqual(result.a_tail_len, 1)
        self.assertEqual(result.b_tail_len, 1)
        self.assertIsNotNone(result.branch_point)


class MergeResolvesAliasTests(_MergeBase):
    """`weave merge` accepts the logical name an op log recorded for a session,
    not only the raw local session id."""

    def _seed_local(self, sid, text):
        cc.write_text(cc.session_path(self.cwd, sid), text)
        return sid

    def test_merge_accepts_logged_name_alias_for_source(self):
        from weave import config
        a_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        b_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        self._seed_local(a_id, _VALID_A)
        self._seed_local(b_id, _VALID_B)
        cfg = Path(self.tmp) / ".weave" / "config"
        # A prior pull recorded the alias "alice-feature" -> a_id.
        config.append_log(
            {"ts": "t", "op": "pull", "remote": "origin",
             "name": "alice-feature", "id": a_id}, path=cfg)

        result = core.merge("alice-feature", b_id, cwd=self.cwd,
                            merger=StubMerger(), config_path=cfg)

        self.assertTrue(Path(result.jsonl_path).is_file())
        self.assertEqual(result.a_tail_len, 1)
        self.assertEqual(result.b_tail_len, 1)

    def test_most_recent_alias_entry_wins(self):
        from weave import config
        old_id = "11111111-1111-1111-1111-111111111111"
        new_id = "22222222-2222-2222-2222-222222222222"
        b_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        self._seed_local(new_id, _VALID_A)
        self._seed_local(b_id, _VALID_B)
        cfg = Path(self.tmp) / ".weave" / "config"
        # Same name reused; the newest log entry points at the live session.
        config.append_log({"op": "pull", "name": "feature", "id": old_id}, path=cfg)
        config.append_log({"op": "pull", "name": "feature", "id": new_id}, path=cfg)

        result = core.merge("feature", b_id, cwd=self.cwd,
                            merger=StubMerger(), config_path=cfg)
        self.assertTrue(Path(result.jsonl_path).is_file())

    def test_raw_session_id_still_works(self):
        a_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        b_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        self._seed_local(a_id, _VALID_A)
        self._seed_local(b_id, _VALID_B)
        result = core.merge(a_id, b_id, cwd=self.cwd, merger=StubMerger())
        self.assertTrue(Path(result.jsonl_path).is_file())


class MergeErrorTests(_MergeBase):
    def test_identical_sessions_raise(self):
        self.b_path.write_text(_VALID_A, encoding="utf-8")
        with self.assertRaises(core.WeaveError):
            core.merge(str(self.a_path), str(self.b_path),
                       cwd=self.cwd, merger=StubMerger())

    def test_missing_source_raises_weave_error(self):
        with self.assertRaises(core.WeaveError):
            core.merge(str(Path(self.tmp) / "nope.jsonl"), str(self.b_path),
                       cwd=self.cwd, merger=StubMerger())

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
                            cwd=self.cwd, merger=StubMerger())
        self.assertIsNone(result.branch_point)
        entries = self._written_entries(result)
        # Only the Read cycle remains (assistant tool_use + user tool_result).
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["type"], "assistant")


if __name__ == "__main__":
    unittest.main()
