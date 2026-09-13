"""Tests for ChatContext and nested evidence types."""

import json
import unittest

from weave.context.types import (
    SCHEMA_VERSION,
    ChatContext,
    CommandRef,
    Decision,
    FailedAttempt,
    FileRef,
    TestRef,
    TodoItem,
)


def _sample_context() -> ChatContext:
    return ChatContext(
        session_id="sess-001",
        source_label="session-a",
        leaf_uuid="a2b",
        git_branch="feature-auth",
        summary="Implemented auth middleware and fixed login redirect.",
        decisions=[
            Decision(id="d1", text="Use JWT in httpOnly cookies", evidence_uuids=["a1"])
        ],
        file_refs=[FileRef(path="src/auth.py", action="edit", note="added middleware")],
        commands=[CommandRef(command="pytest tests/test_auth.py", outcome="pass")],
        tests=[TestRef(name="test_auth", command="pytest tests/test_auth.py", outcome="pass")],
        failed_attempts=[FailedAttempt(summary="Session cookie in localStorage", reason="XSS risk")],
        todos=[TodoItem(text="Add refresh token rotation", status="open")],
        cwd="-Users-alice-myapp",
        goal="Ship auth refactor",
        entry_count=42,
    )


class ChatContextSerializationTests(unittest.TestCase):
    def test_to_dict_from_dict_roundtrip(self):
        original = _sample_context()
        restored = ChatContext.from_dict(original.to_dict())
        self.assertEqual(restored, original)

    def test_json_roundtrip(self):
        original = _sample_context()
        payload = json.dumps(original.to_dict())
        restored = ChatContext.from_dict(json.loads(payload))
        self.assertEqual(restored, original)

    def test_required_fields_present_in_dict(self):
        d = _sample_context().to_dict()
        for key in (
            "schema_version",
            "session_id",
            "source_label",
            "leaf_uuid",
            "git_branch",
            "summary",
            "decisions",
            "file_refs",
            "commands",
            "tests",
            "failed_attempts",
            "todos",
        ):
            self.assertIn(key, d)

    def test_schema_version_default(self):
        ctx = ChatContext(
            session_id="s",
            source_label="lbl",
            leaf_uuid="u",
            git_branch=None,
            summary="x",
        )
        self.assertEqual(ctx.schema_version, SCHEMA_VERSION)

    def test_git_branch_null_explicit(self):
        d = ChatContext(
            session_id="s",
            source_label="lbl",
            leaf_uuid="u",
            git_branch=None,
            summary="x",
        ).to_dict()
        self.assertIn("git_branch", d)
        self.assertIsNone(d["git_branch"])

    def test_empty_lists_serialized(self):
        ctx = ChatContext(
            session_id="s",
            source_label="lbl",
            leaf_uuid="u",
            git_branch="main",
            summary="x",
        )
        d = ctx.to_dict()
        self.assertEqual(d["decisions"], [])
        self.assertEqual(d["file_refs"], [])


if __name__ == "__main__":
    unittest.main()
