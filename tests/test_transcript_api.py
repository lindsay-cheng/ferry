"""Tests for the public façade.

Run:  python3 -m pytest tests/test_transcript_api.py -v
"""

import json
import unittest
from collections import Counter

from weave import transcript as tx

FORKED = (
    '{"parentUuid":null,"type":"user","uuid":"u1","timestamp":"2026-06-26T10:00:00.000Z","message":{"role":"user","content":"hello"}}\n'
    '{"parentUuid":"u1","type":"assistant","uuid":"a1","timestamp":"2026-06-26T10:00:01.000Z","message":{"role":"assistant","content":[{"type":"text","text":"hi"}]}}\n'
    '{"parentUuid":"a1","type":"user","uuid":"u2","timestamp":"2026-06-26T10:00:02.000Z","message":{"role":"user","content":"OLD"}}\n'
    '{"parentUuid":"a1","type":"user","uuid":"u2b","timestamp":"2026-06-26T10:00:09.000Z","message":{"role":"user","content":"NEW"}}\n'
    '{"parentUuid":"u2b","type":"assistant","uuid":"a2b","timestamp":"2026-06-26T10:00:10.000Z","message":{"role":"assistant","content":[{"type":"text","text":"new-ans"}]}}\n'
)


def assert_no_forks(tc, text):
    entries = [json.loads(l) for l in text.splitlines() if l.strip()]
    counts = Counter(e.get("parentUuid") for e in entries)
    for parent, n in counts.items():
        if parent is not None:
            tc.assertEqual(n, 1, f"fork at {parent}")
    tc.assertEqual(sum(1 for e in entries if e.get("parentUuid") is None), 1)


class ApiSurfaceTests(unittest.TestCase):
    def test_all_public_names_present(self):
        for name in tx.__all__:
            self.assertTrue(hasattr(tx, name), name)

    def test_exceptions_subclass_valueerror(self):
        self.assertTrue(issubclass(tx.NotFoundError, ValueError))
        self.assertTrue(issubclass(tx.SpecError, ValueError))

    def test_pipeline_roundtrip_is_linear(self):
        entries = tx.from_text(FORKED)
        self.assertEqual([e["uuid"] for e in entries], ["u1", "a1", "u2b", "a2b"])
        entries, created = tx.create_at_end(
            entries, {"type": "message", "role": "user", "content": "hi again"})
        self.assertEqual(len(created), 1)
        assert_no_forks(self, tx.to_text(entries))

    def test_edit_forked_input_yields_forkfree_output(self):
        entries = tx.from_text(FORKED)
        entries, _ = tx.update(entries, "a1",
                               {"type": "message", "role": "assistant", "content": "edited"})
        entries, _ = tx.delete(entries, "u2b")
        assert_no_forks(self, tx.to_text(entries))

    def test_read_one_lenient_via_api(self):
        entries = tx.from_text(FORKED)
        self.assertIsNone(tx.read_one(entries, "nope"))
        self.assertEqual(tx.read_one(entries, "a1")["uuid"], "a1")

    def test_missing_uuid_raises_notfound(self):
        entries = tx.from_text(FORKED)
        with self.assertRaises(tx.NotFoundError):
            tx.delete(entries, "nope")


if __name__ == "__main__":
    unittest.main()
