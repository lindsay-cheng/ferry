"""Tests for the private linear transcript engine.

Run:  python3 -m pytest tests/test_transcript.py -v
"""

import json
import unittest
from collections import Counter

from weave.transcript import engine as t


# A FORKED transcript: a1 has two children -- u2 (older, first in file) and u2b
# (newer, appended later). a2b is the last line == the active leaf. Plus a
# non-chain meta line (no uuid) that linearize must drop.
FORKED = (
    '{"parentUuid":null,"type":"user","uuid":"u1","timestamp":"2026-06-26T10:00:00.000Z","message":{"role":"user","content":"hello"}}\n'
    '{"parentUuid":"u1","type":"assistant","uuid":"a1","timestamp":"2026-06-26T10:00:01.000Z","message":{"role":"assistant","content":[{"type":"text","text":"hi"}]}}\n'
    '{"parentUuid":"a1","type":"user","uuid":"u2","timestamp":"2026-06-26T10:00:02.000Z","message":{"role":"user","content":"OLD"}}\n'
    '{"parentUuid":"u2","type":"assistant","uuid":"a2","timestamp":"2026-06-26T10:00:03.000Z","message":{"role":"assistant","content":[{"type":"text","text":"old-ans"}]}}\n'
    '{"type":"mode","mode":"default"}\n'
    '{"parentUuid":"a1","type":"user","uuid":"u2b","timestamp":"2026-06-26T10:00:09.000Z","message":{"role":"user","content":"NEW"}}\n'
    '{"parentUuid":"u2b","type":"assistant","uuid":"a2b","timestamp":"2026-06-26T10:00:10.000Z","message":{"role":"assistant","content":[{"type":"text","text":"new-ans"}]}}\n'
)

# A simple already-linear conversation.
SIMPLE = (
    '{"parentUuid":null,"type":"user","uuid":"u1","timestamp":"2026-06-26T10:00:00.000Z","message":{"role":"user","content":"hello"}}\n'
    '{"parentUuid":"u1","type":"assistant","uuid":"a1","timestamp":"2026-06-26T10:00:01.000Z","message":{"role":"assistant","content":[{"type":"text","text":"hi"}]}}\n'
    '{"parentUuid":"a1","type":"user","uuid":"u2","timestamp":"2026-06-26T10:00:02.000Z","message":{"role":"user","content":"followup"}}\n'
    '{"parentUuid":"u2","type":"assistant","uuid":"a2","timestamp":"2026-06-26T10:00:03.000Z","message":{"role":"assistant","content":[{"type":"text","text":"answer"}]}}\n'
)

# Linear conversation containing one tool cycle (a1 tool_use t1 / u2 tool_result t1).
TOOL = (
    '{"parentUuid":null,"type":"user","uuid":"u1","timestamp":"2026-06-26T10:00:00.000Z","message":{"role":"user","content":"hello"}}\n'
    '{"parentUuid":"u1","type":"assistant","uuid":"a1","timestamp":"2026-06-26T10:00:01.000Z","message":{"role":"assistant","content":[{"type":"text","text":"check"},{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"echo 42"}}]}}\n'
    '{"parentUuid":"a1","type":"user","uuid":"u2","timestamp":"2026-06-26T10:00:02.000Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":"42"}]}}\n'
    '{"parentUuid":"u2","type":"assistant","uuid":"a2","timestamp":"2026-06-26T10:00:03.000Z","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}\n'
)


def ids(entries):
    return [e["uuid"] for e in entries]


def assert_linear(tc, lines):
    """Assert serialized ``lines`` form a single linear chain (no forks)."""
    entries = [json.loads(l) for l in lines if l.strip()]
    if not entries:
        return
    roots = [e for e in entries if e.get("parentUuid") is None]
    tc.assertEqual(len(roots), 1, "exactly one root")
    child_counts = Counter(e.get("parentUuid") for e in entries)
    for parent, n in child_counts.items():
        if parent is not None:
            tc.assertEqual(n, 1, f"node {parent} has {n} children (fork)")
    tc.assertIsNone(entries[0].get("parentUuid"))
    for i in range(1, len(entries)):
        tc.assertEqual(entries[i]["parentUuid"], entries[i - 1]["uuid"])


class LinearizeTests(unittest.TestCase):
    def test_active_leaf_not_first_child(self):
        # a1's first child is u2 (abandoned); the active branch goes via u2b.
        self.assertEqual(ids(t._from_text(FORKED)), ["u1", "a1", "u2b", "a2b"])

    def test_drops_forks_and_meta_lines(self):
        got = ids(t._from_text(FORKED))
        self.assertNotIn("u2", got)
        self.assertNotIn("a2", got)
        self.assertTrue(all(e.get("type") != "mode" for e in t._from_text(FORKED)))

    def test_empty(self):
        self.assertEqual(t._linearize([]), [])
        self.assertEqual(t._linearize(["\n", "   \n"]), [])

    def test_serialize_is_linear_and_forkfree(self):
        assert_linear(self, t._serialize(t._from_text(FORKED)))

    def test_roundtrip_stable(self):
        once = t._from_text(FORKED)
        twice = t._from_text(t._to_text(once))
        self.assertEqual(ids(once), ids(twice))

    def test_serialize_does_not_mutate_input(self):
        entries = t._from_text(SIMPLE)
        before = json.dumps(entries, sort_keys=True)
        t._serialize(entries)
        self.assertEqual(json.dumps(entries, sort_keys=True), before)


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.entries = t._from_text(SIMPLE)

    def test_at_end(self):
        out, created = t._create_at_end(
            self.entries, {"type": "message", "role": "user", "content": "END"})
        self.assertEqual(len(created), 1)
        self.assertEqual(out[-1]["message"]["content"], "END")
        self.assertEqual(len(self.entries), 4)  # input untouched
        assert_linear(self, t._serialize(out))

    def test_at_start_new_root(self):
        out, created = t._create_at_start(
            self.entries, {"type": "message", "role": "user", "content": "ROOT"})
        self.assertEqual(out[0]["message"]["content"], "ROOT")
        self.assertEqual(out[0]["uuid"], created[0])
        lines = t._serialize(out)
        self.assertIsNone(json.loads(lines[0])["parentUuid"])
        assert_linear(self, lines)

    def test_after_uuid(self):
        out, created = t._create_after(
            self.entries, "u1", {"type": "message", "role": "assistant", "content": "MID"})
        self.assertEqual(ids(out)[:3], ["u1", created[0], "a1"])
        assert_linear(self, t._serialize(out))

    def test_after_inserts_past_tool_cycle(self):
        entries = t._from_text(TOOL)
        out, created = t._create_after(
            entries, "a1", {"type": "message", "role": "assistant", "content": "AFTER"})
        # a1's cycle is (a1, u2); the new entry lands after u2, before a2.
        self.assertEqual(ids(out), ["u1", "a1", "u2", created[0], "a2"])
        assert_linear(self, t._serialize(out))

    def test_after_missing_raises(self):
        with self.assertRaises(t._NotFoundError):
            t._create_after(self.entries, "nope",
                            {"type": "message", "role": "user", "content": "x"})

    def test_tool_call_builds_atomic_pair(self):
        out, created = t._create_at_end(self.entries, {
            "type": "tool_call", "name": "Read", "input": {"file_path": "/x"},
            "result": "BODY", "text": "reading", "reply": "done"})
        self.assertEqual(len(created), 3)
        uses, results = [], []
        for e in out:
            c = e.get("message", {}).get("content")
            if isinstance(c, list):
                for b in c:
                    if b.get("type") == "tool_use":
                        uses.append(b)
                    if b.get("type") == "tool_result":
                        results.append(b)
        self.assertEqual(len(uses), 1)
        self.assertEqual(uses[0]["id"], results[0]["tool_use_id"])
        assert_linear(self, t._serialize(out))

    def test_bad_spec_raises(self):
        with self.assertRaises(t._SpecError):
            t._create_at_end(self.entries, {"type": "message", "role": "system", "content": "x"})
        with self.assertRaises(t._SpecError):
            t._create_at_end(self.entries, {"type": "raw", "entry": {}})  # raw mode removed


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.entries = t._from_text(SIMPLE)  # [u1, a1, u2, a2]

    def test_all(self):
        self.assertEqual(ids(t._read_all(self.entries)), ["u1", "a1", "u2", "a2"])

    def test_from_forward(self):
        self.assertEqual(ids(t._read_from(self.entries, "a1", 2)), ["a1", "u2"])
        self.assertEqual(ids(t._read_from(self.entries, "u2")), ["u2", "a2"])

    def test_from_backward_is_ascending(self):
        self.assertEqual(ids(t._read_from(self.entries, "a2", 2, reverse=True)), ["u2", "a2"])
        self.assertEqual(ids(t._read_from(self.entries, "a2", 1, reverse=True)), ["a2"])
        self.assertEqual(ids(t._read_from(self.entries, "u2", reverse=True)), ["u1", "a1", "u2"])

    def test_between_order_agnostic(self):
        self.assertEqual(ids(t._read_between(self.entries, "a1", "a2")), ["a1", "u2", "a2"])
        self.assertEqual(ids(t._read_between(self.entries, "a2", "a1")), ["a1", "u2", "a2"])
        self.assertEqual(ids(t._read_between(self.entries, "u2", "u2")), ["u2"])

    def test_one_lenient(self):
        self.assertEqual(t._read_one(self.entries, "a1")["uuid"], "a1")
        self.assertIsNone(t._read_one(self.entries, "nope"))

    def test_anchored_read_missing_raises(self):
        with self.assertRaises(t._NotFoundError):
            t._read_from(self.entries, "nope")
        with self.assertRaises(t._NotFoundError):
            t._read_between(self.entries, "u1", "nope")


class UpdateTests(unittest.TestCase):
    def by(self, out):
        return {e["uuid"]: e for e in out}

    def test_in_place_preserves_identity(self):
        entries = t._from_text(SIMPLE)
        out, affected = t._update(
            entries, "a1", {"type": "message", "role": "assistant", "content": "edited"})
        self.assertEqual(affected, ["a1"])
        b = self.by(out)
        self.assertEqual(b["a1"]["message"]["content"][0]["text"], "edited")
        self.assertEqual(b["a1"]["timestamp"], "2026-06-26T10:00:01.000Z")  # invisible
        self.assertEqual(len(out), 4)
        assert_linear(self, t._serialize(out))

    def test_to_tool_call_expands(self):
        entries = t._from_text(SIMPLE)
        out, affected = t._update(entries, "a1", {
            "type": "tool_call", "text": "checking",
            "tools": [{"name": "Bash", "input": {}, "result": "ok"}]})
        self.assertEqual(affected[0], "a1")     # head keeps the uuid
        self.assertEqual(len(affected), 2)      # tool_use + tool_result
        b = self.by(out)
        self.assertTrue(any(blk.get("type") == "tool_use"
                            for blk in b["a1"]["message"]["content"]))
        self.assertEqual(ids(out)[:2], ["u1", "a1"])
        self.assertIn("u2", ids(out))           # original tail still there
        assert_linear(self, t._serialize(out))

    def test_tool_cycle_collapses_without_orphan(self):
        entries = t._from_text(TOOL)            # [u1, a1(tool_use), u2(tool_result), a2]
        out, affected = t._update(
            entries, "a1", {"type": "message", "role": "assistant", "content": "plain"})
        self.assertEqual(affected, ["a1"])
        self.assertEqual(ids(out), ["u1", "a1", "a2"])   # u2 (the tool_result) gone
        for e in out:
            c = e.get("message", {}).get("content")
            if isinstance(c, list):
                self.assertFalse(any(b.get("type") == "tool_result" for b in c))
        assert_linear(self, t._serialize(out))

    def test_missing_and_bad_spec_raise(self):
        entries = t._from_text(SIMPLE)
        with self.assertRaises(t._NotFoundError):
            t._update(entries, "nope", {"type": "message", "role": "user", "content": "x"})
        with self.assertRaises(t._SpecError):
            t._update(entries, "a1", {"type": "message", "role": "assistant",
                                      "content": [{"type": "tool_use", "input": {}}]})


class DeleteTests(unittest.TestCase):
    def test_single(self):
        entries = t._from_text(SIMPLE)
        out, deleted = t._delete(entries, "u2")
        self.assertEqual(deleted, ["u2"])
        self.assertEqual(ids(out), ["u1", "a1", "a2"])
        self.assertEqual(len(entries), 4)  # input untouched
        assert_linear(self, t._serialize(out))

    def test_tool_cycle_atomic_from_either_half(self):
        for target in ("a1", "u2"):
            entries = t._from_text(TOOL)
            out, deleted = t._delete(entries, target)
            self.assertEqual(sorted(deleted), ["a1", "u2"])
            self.assertEqual(ids(out), ["u1", "a2"])
            assert_linear(self, t._serialize(out))

    def test_between(self):
        entries = t._from_text(SIMPLE)
        out, deleted = t._delete_between(entries, "a1", "u2")
        self.assertEqual(sorted(deleted), ["a1", "u2"])
        self.assertEqual(ids(out), ["u1", "a2"])
        out2, _ = t._delete_between(t._from_text(SIMPLE), "u2", "a1")  # order-agnostic
        self.assertEqual(ids(out2), ["u1", "a2"])
        assert_linear(self, t._serialize(out))

    def test_between_expands_tool_cycle(self):
        entries = t._from_text(TOOL)            # [u1, a1(tool_use), u2(tool_result), a2]
        out, deleted = t._delete_between(entries, "u1", "a1")
        self.assertEqual(sorted(deleted), ["a1", "u1", "u2"])
        self.assertEqual(ids(out), ["a2"])
        assert_linear(self, t._serialize(out))

    def test_missing_raises(self):
        with self.assertRaises(t._NotFoundError):
            t._delete(t._from_text(SIMPLE), "nope")


if __name__ == "__main__":
    unittest.main()
