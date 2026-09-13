"""Tests for the pure text-briefing merge layer.

Run (from repo root):  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_merge_layer.py -q
"""

import unittest

from weave.context.types import ChatContext
from weave.merge import (
    CerebrasMerger,
    StubMerger,
    build_merge_prompt,
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


class StubMergerTests(unittest.TestCase):
    def test_returns_text_mentioning_branch_sizes(self):
        out = StubMerger().merge(_ctx("background"), _A_BRANCH, _B_BRANCH)
        self.assertIsInstance(out, str)
        self.assertIn("background", out)
        self.assertIn("1", out)  # one turn per branch

    def test_handles_no_shared_context(self):
        out = StubMerger().merge(None, _A_BRANCH, _B_BRANCH)
        self.assertIsInstance(out, str)
        self.assertTrue(out.strip())


class CerebrasMergerTests(unittest.TestCase):
    def test_returns_stripped_client_text(self):
        client = _FakeClient("  MERGED BRIEFING  ")
        out = CerebrasMerger(client=client).merge(_ctx("bg"), _A_BRANCH, _B_BRANCH)
        self.assertEqual(out, "MERGED BRIEFING")

    def test_prompt_includes_branch_content(self):
        client = _FakeClient("ok")
        CerebrasMerger(client=client).merge(_ctx("bg"), _A_BRANCH, _B_BRANCH)
        self.assertIn("A did this", client.last_prompt)
        self.assertIn("B did that", client.last_prompt)

    def test_empty_response_raises(self):
        client = _FakeClient("   ")
        with self.assertRaises(MergeResponseError):
            CerebrasMerger(client=client).merge(_ctx("bg"), _A_BRANCH, _B_BRANCH)


class BuildMergePromptTests(unittest.TestCase):
    def test_no_shared_context_is_labeled(self):
        prompt = build_merge_prompt(None, _A_BRANCH, _B_BRANCH)
        self.assertIn("none", prompt.lower())
        self.assertIn("A did this", prompt)

    def test_drops_jsonl_envelope_metadata(self):
        entries = [{
            "type": "assistant", "uuid": "envelope-uuid-1",
            "parentUuid": "envelope-uuid-0", "sessionId": "sess-xyz",
            "cwd": "/some/where", "timestamp": "2026-06-27T00:00:00Z",
            "message": {"role": "assistant", "content": [
                {"type": "text", "text": "did the thing"},
                {"type": "tool_use", "name": "Edit", "input": {"file": "a.py"}},
            ]},
        }]
        prompt = build_merge_prompt(None, entries, [])
        self.assertIn("assistant: did the thing", prompt)
        self.assertIn("Edit", prompt)
        # The heavy envelope fields must not leak into the prompt.
        for leaked in ("envelope-uuid-1", "sessionId", "parentUuid",
                       "timestamp", "/some/where"):
            self.assertNotIn(leaked, prompt)

    def test_tool_result_is_truncated(self):
        big = "X" * 5000
        entries = [{"message": {"role": "user", "content": [
            {"type": "tool_result", "content": big}]}}]
        prompt = build_merge_prompt(None, entries, [])
        self.assertIn("elided", prompt)
        self.assertNotIn("X" * 1000, prompt)  # full payload not sent

    def test_lean_render_far_smaller_than_raw_dump(self):
        import json
        entries = [{
            "type": "assistant", "uuid": "u", "sessionId": "s",
            "timestamp": "t", "cwd": "/p",
            "message": {"role": "assistant", "content": [
                {"type": "tool_result", "content": "Y" * 16000}]},
        }]
        prompt = build_merge_prompt(None, entries, [])
        raw = json.dumps(entries, indent=2)
        self.assertLess(len(prompt), len(raw) // 4)


if __name__ == "__main__":
    unittest.main()
