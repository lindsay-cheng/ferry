"""Tests for weave.cli — no real ~/.claude is ever touched.

Run (from repo root):  python3 -m pytest tests/test_weave_cli.py -v
"""

import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from weave import cli, config, connector as cc, core
from weave.config import config as _config_mod
from weave.core import core as _core_mod


def _strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


class FakeServer:
    def __init__(self, store=None):
        self.store = dict(store or {})

    def push(self, url, name, text):
        self.store[(url, name)] = text

    def pull(self, url, name):
        return self.store[(url, name)]

    def list(self, url):
        return [n for (u, n) in self.store if u == url]

    def delete(self, url, name):
        if (url, name) not in self.store:
            raise ValueError(f"no session {name!r} on remote")
        del self.store[(url, name)]


class CliBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        patcher = mock.patch.dict(
            os.environ, {"CLAUDE_CONFIG_DIR": str(self.tmp / "claude")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = self.tmp / ".weave" / "config"
        self.cwd = "/Users/tester/proj"
        # Redirect core defaults at their definition site.
        for p in (mock.patch.object(_config_mod, "DEFAULT_PATH", str(self.cfg)),
                  mock.patch.object(_core_mod.os, "getcwd", return_value=self.cwd)):
            p.start()
            self.addCleanup(p.stop)


class CliTests(CliBase):
    def test_pull_subcommand_writes_and_returns_zero(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"):
            '{"parentUuid":null,"type":"user","uuid":"u1","cwd":"/a",'
            '"sessionId":"s","timestamp":"2026-06-26T10:00:00.000Z",'
            '"message":{"role":"user","content":"hi"}}\n'})
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["pull", "origin", "auth"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(core.ls(cwd=self.cwd)), 1)

    def test_pull_without_remote_uses_sole_remote(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"):
            '{"parentUuid":null,"type":"user","uuid":"u1","cwd":"/a",'
            '"sessionId":"s","timestamp":"2026-06-26T10:00:00.000Z",'
            '"message":{"role":"user","content":"hi"}}\n'})
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["pull", "auth"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(core.ls(cwd=self.cwd)), 1)

    def test_unknown_remote_exits_1_with_message(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli.main(["pull", "nope", "x"])
        self.assertEqual(rc, 1)
        self.assertIn("weave:", err.getvalue())

    def test_rm_subcommand_deletes_from_remote(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"): "T\n"})
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["rm", "auth"])
        self.assertEqual(rc, 0)
        self.assertIn("removed origin/auth", out.getvalue())
        self.assertNotIn(("u@h:/p", "auth"), fake.store)

    def test_help_subcommand_prints_usage(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["help"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("push", text)
        self.assertIn("merge", text)
        self.assertIn("log", text)

    def test_help_shows_command_parameters_and_optional_markers(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["help"])
        self.assertEqual(rc, 0)
        text = _strip_ansi(out.getvalue())
        self.assertIn("usage: weave", text)
        self.assertIn("<name>", text)
        self.assertIn("<source-a>", text)
        self.assertIn("--session", text)
        self.assertIn("[<remote>]", text)

    def test_help_flags_match_help_subcommand(self):
        rendered = {}
        for arg in ("help", "--help", "-h"):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = cli.main([arg])
            self.assertEqual(rc, 0)
            rendered[arg] = buf.getvalue()
        self.assertTrue(rendered["help"].strip())
        self.assertEqual(rendered["help"], rendered["--help"])
        self.assertEqual(rendered["help"], rendered["-h"])

    def test_version_flag_prints_version(self):
        from weave import __version__
        for arg in ("--version", "-V"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main([arg])
            self.assertEqual(rc, 0)
            self.assertIn(__version__, out.getvalue())
            self.assertIn("weave", out.getvalue())

    def test_no_args_prints_help(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main([])
        self.assertEqual(rc, 0)
        self.assertIn("usage: weave", _strip_ansi(out.getvalue()))

    def test_push_session_auto_uses_latest_local(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        cc.write_text(cc.session_path(self.cwd, "old"), '{"uuid":"o"}\n')
        cc.write_text(cc.session_path(self.cwd, "new"), '{"uuid":"n"}\n')
        os.utime(cc.session_path(self.cwd, "old"), (1_000, 1_000))
        os.utime(cc.session_path(self.cwd, "new"), (2_000, 2_000))
        fake = FakeServer()
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["push", "aname", "--session", "auto"])
        self.assertEqual(rc, 0)
        self.assertEqual(fake.store[("u@h:/p", "aname")], '{"uuid":"n"}\n')

    def test_push_without_session_defaults_to_latest_local(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        cc.write_text(cc.session_path(self.cwd, "old"), '{"uuid":"o"}\n')
        cc.write_text(cc.session_path(self.cwd, "new"), '{"uuid":"n"}\n')
        os.utime(cc.session_path(self.cwd, "old"), (1_000, 1_000))
        os.utime(cc.session_path(self.cwd, "new"), (2_000, 2_000))
        fake = FakeServer()
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["push", "aname"])
        self.assertEqual(rc, 0)
        self.assertEqual(fake.store[("u@h:/p", "aname")], '{"uuid":"n"}\n')

    def test_log_subcommand_lists_recorded_ops(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        cc.write_text(cc.session_path(self.cwd, "s1"), '{"uuid":"x"}\n')
        fake = FakeServer()
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["push", "mine", "--session", "s1"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["log"])
        self.assertEqual(rc, 0)
        self.assertIn("push", out.getvalue())
        self.assertIn("origin/mine", out.getvalue())

    def test_remote_add_subcommand(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["remote", "add", "origin", "u@h:/p"])
        self.assertEqual(rc, 0)
        self.assertEqual(config.get_remote("origin", path=self.cfg), "u@h:/p")

    def test_remote_add_accepts_custom_name(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["remote", "add", "backup", "u@h:/b"])
        self.assertEqual(rc, 0)
        self.assertEqual(config.get_remote("backup", path=self.cfg), "u@h:/b")

    def test_pull_open_flag_resumes_session(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"):
            '{"parentUuid":null,"type":"user","uuid":"u1","cwd":"/a",'
            '"sessionId":"s","timestamp":"2026-06-26T10:00:00.000Z",'
            '"message":{"role":"user","content":"hi"}}\n'})
        with mock.patch.object(_core_mod, "_load_server", return_value=fake), \
                mock.patch.object(cli.cli, "_open_session") as opened:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["pull", "auth", "-o"])
        self.assertEqual(rc, 0)
        opened.assert_called_once()

    def test_pull_without_open_flag_does_not_resume(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"):
            '{"parentUuid":null,"type":"user","uuid":"u1","cwd":"/a",'
            '"sessionId":"s","timestamp":"2026-06-26T10:00:00.000Z",'
            '"message":{"role":"user","content":"hi"}}\n'})
        with mock.patch.object(_core_mod, "_load_server", return_value=fake), \
                mock.patch.object(cli.cli, "_open_session") as opened:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["pull", "auth"])
        self.assertEqual(rc, 0)
        opened.assert_not_called()

    def test_merge_open_flag_resumes_session(self):
        expected = _core_mod.MergeResult(
            session_id="merged-123", jsonl_path="/tmp/merged-123.jsonl",
            branch_point="bp", a_tail_len=1, b_tail_len=2)
        with mock.patch.object(core, "merge", return_value=expected), \
                mock.patch.object(cli.cli, "_open_session") as opened:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["merge", "/tmp/a.jsonl", "/tmp/b.jsonl", "--open"])
        self.assertEqual(rc, 0)
        opened.assert_called_once_with("merged-123")

    def test_merge_subcommand_prints_resume_hint(self):
        expected = _core_mod.MergeResult(
            session_id="merged-123", jsonl_path="/tmp/merged-123.jsonl",
            branch_point="bp", a_tail_len=1, b_tail_len=2)
        with mock.patch.object(core, "merge", return_value=expected) as m:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["merge", "/tmp/a.jsonl", "/tmp/b.jsonl"])
        self.assertEqual(rc, 0)
        m.assert_called_once_with("/tmp/a.jsonl", "/tmp/b.jsonl")
        self.assertIn("merged-123", out.getvalue())
        self.assertIn("claude --resume merged-123", out.getvalue())


if __name__ == "__main__":
    unittest.main()
