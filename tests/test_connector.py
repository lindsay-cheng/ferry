"""Tests for weave.connector — no real ~/.claude is ever touched.

Run:  python3 -m pytest tests/test_connector.py -v
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from weave import connector as cc


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
        f1 = self.make("-Users-a-proj", "s1")
        f2 = self.make("-Users-b-proj", "s2")
        result = cc.list_sessions()
        self.assertIsInstance(result, list)
        self.assertEqual(result, sorted([("s1", f1), ("s2", f2)],
                                        key=lambda pair: str(pair[1])))

    def test_list_sessions_empty_when_no_root(self):
        self.assertEqual(cc.list_sessions(), [])


class LatestSessionTests(_ConnectorBase):
    def test_returns_most_recently_modified_in_project(self):
        cwd = "/Users/me/proj"
        enc = cc.encode_cwd(cwd)
        old = self.make(enc, "old")
        new = self.make(enc, "new")
        # Make `old` clearly older than `new` by mtime.
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (2_000_000, 2_000_000))
        self.assertEqual(cc.latest_session(cwd), "new")

    def test_scoped_to_cwd_project_only(self):
        cwd = "/Users/me/proj"
        self.make(cc.encode_cwd(cwd), "mine")
        # A newer session in a different project must not be chosen.
        other = self.make(cc.encode_cwd("/Users/me/other"), "theirs")
        os.utime(other, (9_000_000, 9_000_000))
        self.assertEqual(cc.latest_session(cwd), "mine")

    def test_raises_when_project_has_no_sessions(self):
        with self.assertRaises(cc.SessionNotFound):
            cc.latest_session("/Users/me/empty")


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


if __name__ == "__main__":
    unittest.main()
