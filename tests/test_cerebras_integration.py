"""Gated real-Cerebras integration test for the resumable merge pipeline.

Skipped unless CEREBRAS_API_KEY and CEREBRAS_MODEL are set in the environment
(or a .env file). Runs an end-to-end merge through core.merge with a real
CerebrasMerger and asserts:

- Returns a MergeResult with a non-empty session_id.
- The written JSONL round-trips through weave.transcript as a single linear chain.
- Exactly one Read tool cycle is present and its tool_result content is non-empty text.

Run (from repo root):
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_cerebras_integration.py -q
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from weave import core
from weave import transcript as tx
from weave.merge.env import cerebras_configured


# Two minimal fixture JSONL strings: shared prefix (one user + one assistant turn),
# then one divergent user turn each. Modelled on _VALID_A / _VALID_B in test_weave_merge.py.
_FIXTURE_A = (
    '{"parentUuid":null,"type":"user","uuid":"u1","sessionId":"sA","cwd":"/src",'
    '"timestamp":"2026-06-26T10:00:00.000Z",'
    '"message":{"role":"user","content":"shared question"}}\n'
    '{"parentUuid":"u1","type":"assistant","uuid":"u2","sessionId":"sA","cwd":"/src",'
    '"timestamp":"2026-06-26T10:00:01.000Z",'
    '"message":{"role":"assistant","content":[{"type":"text","text":"shared answer"}]}}\n'
    '{"parentUuid":"u2","type":"user","uuid":"u3","sessionId":"sA","cwd":"/src",'
    '"timestamp":"2026-06-26T10:00:02.000Z",'
    '"message":{"role":"user","content":"A branch work: explore the left side"}}\n'
)

_FIXTURE_B = (
    '{"parentUuid":null,"type":"user","uuid":"v1","sessionId":"sB","cwd":"/other",'
    '"timestamp":"2026-06-27T09:00:00.000Z",'
    '"message":{"role":"user","content":"shared question"}}\n'
    '{"parentUuid":"v1","type":"assistant","uuid":"v2","sessionId":"sB","cwd":"/other",'
    '"timestamp":"2026-06-27T09:00:01.000Z",'
    '"message":{"role":"assistant","content":[{"type":"text","text":"shared answer"}]}}\n'
    '{"parentUuid":"v2","type":"user","uuid":"v3","sessionId":"sB","cwd":"/other",'
    '"timestamp":"2026-06-27T09:00:02.000Z",'
    '"message":{"role":"user","content":"B branch work: explore the right side"}}\n'
)


@unittest.skipUnless(cerebras_configured(), "CEREBRAS_API_KEY/CEREBRAS_MODEL not set")
class CerebrasMergeIntegrationTests(unittest.TestCase):
    """End-to-end merge through a real CerebrasMerger (gated on API key)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = "/Users/tester/proj"
        self.a_path = Path(self.tmp) / "a.jsonl"
        self.b_path = Path(self.tmp) / "b.jsonl"
        self.a_path.write_text(_FIXTURE_A, encoding="utf-8")
        self.b_path.write_text(_FIXTURE_B, encoding="utf-8")
        # Redirect connector's ~/.claude root into the temp dir so no real
        # ~/.claude is touched during the test.
        patcher = mock.patch.dict(
            os.environ, {"CLAUDE_CONFIG_DIR": self.tmp}, clear=False
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_real_cerebras_merge_produces_resumable_session(self):
        # Call core.merge with no merger= so the real CerebrasMerger is used
        # via default_merger().
        result = core.merge(str(self.a_path), str(self.b_path), cwd=self.cwd)

        # 1. Returns a MergeResult with a non-empty session_id.
        self.assertTrue(result.session_id, "session_id should be non-empty")

        # 2. The written JSONL round-trips through weave.transcript as a single
        #    linear chain (no parse error, no empty list).
        jsonl_text = Path(result.jsonl_path).read_text(encoding="utf-8")
        entries = tx.from_text(jsonl_text)
        self.assertGreater(len(entries), 0, "round-tripped entries should be non-empty")

        # 3. Exactly one Read tool cycle is present.
        tool_uses = [
            block
            for entry in entries
            for block in (entry.get("message", {}).get("content") or [])
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        self.assertEqual(len(tool_uses), 1, "expected exactly one tool_use (Read)")
        self.assertEqual(tool_uses[0]["name"], "Read")

        # 4. The corresponding tool_result has non-empty text content.
        tool_results = [
            block
            for entry in entries
            for block in (entry.get("message", {}).get("content") or [])
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]
        self.assertEqual(len(tool_results), 1, "expected exactly one tool_result")
        result_content = tool_results[0].get("content", "")
        if isinstance(result_content, list):
            result_content = "".join(
                b.get("text", "") for b in result_content if isinstance(b, dict)
            )
        self.assertTrue(
            str(result_content).strip(),
            "tool_result content should be non-empty text",
        )


if __name__ == "__main__":
    unittest.main()
