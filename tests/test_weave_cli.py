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
        self.repo = self.tmp / "proj"
        self.repo.mkdir()
        self.src = self.repo / "src"
        self.src.mkdir()
        self.cfg = self.repo / ".weave" / "config"
        patcher = mock.patch.dict(
            os.environ, {"CLAUDE_CONFIG_DIR": str(self.tmp / "claude")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self._orig_cwd = os.getcwd()
        os.chdir(self.repo)
        self.cwd = os.getcwd()
        self.addCleanup(lambda: os.chdir(self._orig_cwd))


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
        self.assertEqual(len(core.ls()), 1)

    def test_pull_prints_written_folder(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"):
            '{"parentUuid":null,"type":"user","uuid":"u1","cwd":"/a",'
            '"sessionId":"s","timestamp":"2026-06-26T10:00:00.000Z",'
            '"message":{"role":"user","content":"hi"}}\n'})
        expected_folder = str(cc.session_path(self.cwd, "placeholder").parent)
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["pull", "auth"])
        self.assertEqual(rc, 0)
        self.assertIn(f"folder: {expected_folder}", out.getvalue())

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
        self.assertEqual(len(core.ls()), 1)

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
        self.assertNotIn("merge", text)
        self.assertIn("log", text)

    def test_help_shows_command_parameters_and_optional_markers(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["help"])
        self.assertEqual(rc, 0)
        text = _strip_ansi(out.getvalue())
        self.assertIn("usage: weave", text)
        self.assertIn("<name>", text)
        self.assertIn("--session", text)
        self.assertIn("[<remote>]", text)
        self.assertIn("hyphen", text)

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

    def test_push_without_session_with_multiple_local_exits_1(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        cc.write_text(cc.session_path(self.cwd, "old"), '{"uuid":"o"}\n')
        cc.write_text(cc.session_path(self.cwd, "new"), '{"uuid":"n"}\n')
        fake = FakeServer()
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = cli.main(["push", "aname"])
        self.assertEqual(rc, 1)
        msg = err.getvalue()
        self.assertIn("old", msg)
        self.assertIn("new", msg)
        self.assertEqual(fake.store, {})

    def test_push_without_session_with_one_local_pushes_it(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        cc.write_text(cc.session_path(self.cwd, "only"), '{"uuid":"o"}\n')
        fake = FakeServer()
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["push", "aname"])
        self.assertEqual(rc, 0)
        self.assertEqual(fake.store[("u@h:/p", "aname")], '{"uuid":"o"}\n')

    def test_push_with_explicit_session_pushes_that_one(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        cc.write_text(cc.session_path(self.cwd, "old"), '{"uuid":"o"}\n')
        cc.write_text(cc.session_path(self.cwd, "new"), '{"uuid":"n"}\n')
        fake = FakeServer()
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["push", "aname", "--session", "old"])
        self.assertEqual(rc, 0)
        self.assertEqual(fake.store[("u@h:/p", "aname")], '{"uuid":"o"}\n')

    def test_help_does_not_advertise_auto_latest(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["help"])
        text = _strip_ansi(out.getvalue()).lower()
        self.assertNotIn("newest local session", text)
        self.assertNotIn("defaults to the newest", text)

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


class WalkUpCliTests(CliBase):
    def test_nested_cwd_finds_parent_config(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        os.chdir(self.src)
        cc.write_text(cc.session_path(self.cwd, "s1"), '{"uuid":"x"}\n')
        fake = FakeServer()
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["push", "mine", "--session", "s1"])
        self.assertEqual(rc, 0)
        self.assertEqual(fake.store[("u@h:/p", "mine")], '{"uuid":"x"}\n')

    def test_nested_cwd_pull_prints_project_folder(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"):
            '{"parentUuid":null,"type":"user","uuid":"u1","cwd":"/a",'
            '"sessionId":"s","timestamp":"2026-06-26T10:00:00.000Z",'
            '"message":{"role":"user","content":"hi"}}\n'})
        os.chdir(self.src)
        project = str(config.project_dir())
        expected_folder = str(cc.session_path(project, "placeholder").parent)
        with mock.patch.object(_core_mod, "_load_server", return_value=fake):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli.main(["pull", "auth"])
        self.assertEqual(rc, 0)
        self.assertIn(f"folder: {expected_folder}", out.getvalue())

    def test_no_config_push_exits_not_a_project(self):
        os.chdir(self.src)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = cli.main(["push", "n", "--session", "x"])
        self.assertEqual(rc, 1)
        self.assertIn("not a Weave project", err.getvalue())

    def test_remote_add_creates_config_in_cwd(self):
        os.chdir(self.src)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["remote", "add", "origin", "u@h:/p"])
        self.assertEqual(rc, 0)
        self.assertTrue((self.src / ".weave" / "config").is_file())


if __name__ == "__main__":
    unittest.main()
