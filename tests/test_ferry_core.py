"""Tests for ferry.core -- no real ~/.claude is touched.

Two layers of coverage:
  * policy branches via an injected in-memory `server` fake (fast, no transport);
  * an end-to-end path that drives core.push/pull/ls through the REAL
    ferry.remote against a localhost hub writing a temp folder.

Run (from repo root):  python3 -m pytest tests/test_ferry_core.py
"""

import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
import warnings
from pathlib import Path
from unittest import mock

from ferry import config, connector as cc, core
from ferry.core import core as _core_mod
from ferry.hub import make_server
from ferry.remote import remote as _remote_server

_VALID_ENTRY = (
    '{"parentUuid":null,"type":"user","uuid":"u1",'
    '"cwd":"/Users/alice/proj","sessionId":"alice-sess",'
    '"timestamp":"2026-06-26T10:00:00.000Z",'
    '"message":{"role":"user","content":"hi"}}\n')

_EXTRA_TYPES_TEXT = (
    '{"type":"ai-title","title":"My chat"}\n'
    '{"type":"file-history-snapshot","files":[]}\n'
    '{"type":"mode","mode":"default"}\n'
    '{"type":"permission-mode","mode":"default"}\n'
    + _VALID_ENTRY
)


class _FerryBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        patcher = mock.patch.dict(
            os.environ, {"CLAUDE_CONFIG_DIR": str(self.tmp / "claude")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = self.tmp / ".ferry" / "config"
        self.cwd = "/Users/tester/proj"


class ConfigTests(_FerryBase):
    def test_remote_add_writes_url(self):
        core.remote_add("origin", "user@host:/srv/ferry", path=self.cfg)
        self.assertEqual(
            config.get_remote("origin", path=self.cfg), "user@host:/srv/ferry")

    def test_remote_add_duplicate_name_raises(self):
        core.remote_add("origin", "user@host:/old", path=self.cfg)
        with self.assertRaises(ValueError) as ctx:
            core.remote_add("origin", "user@host:/new", path=self.cfg)
        self.assertIn("already exists", str(ctx.exception))
        self.assertEqual(
            config.get_remote("origin", path=self.cfg), "user@host:/old")

    def test_remote_add_second_name_still_works(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        core.remote_add("backup", "u@h:/b", path=self.cfg)
        self.assertEqual(config.get_remote("backup", path=self.cfg), "u@h:/b")

    def test_unknown_remote_raises(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        with self.assertRaises(ValueError):
            config.get_remote("missing", path=self.cfg)
        with self.assertRaises(core.FerryError):
            _core_mod._remote_url("missing", path=self.cfg)

    def test_resolve_remote_defaults_to_sole_remote(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        self.assertEqual(
            _core_mod._resolve_remote(None, path=self.cfg), "origin")

    def test_resolve_remote_passthrough_when_named(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        core.remote_add("backup", "u@h:/b", path=self.cfg)
        self.assertEqual(
            _core_mod._resolve_remote("backup", path=self.cfg), "backup")

    def test_resolve_remote_none_with_no_remotes_raises(self):
        with self.assertRaises(core.FerryError):
            _core_mod._resolve_remote(None, path=self.cfg)

    def test_resolve_remote_none_with_multiple_raises(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        core.remote_add("backup", "u@h:/b", path=self.cfg)
        with self.assertRaises(core.FerryError):
            _core_mod._resolve_remote(None, path=self.cfg)


class FakeServer:
    """In-memory stand-in for the `server` module, injected via `server=`."""
    def __init__(self, store=None):
        self.store = dict(store or {})
        self.pushed = []  # (url, name, text)

    def push(self, url, name, text):
        self.pushed.append((url, name, text))
        self.store[(url, name)] = text

    def pull(self, url, name):
        if (url, name) not in self.store:
            raise ValueError(f"no session {name!r} on remote")
        return self.store[(url, name)]

    def list(self, url):
        return [n for (u, n) in self.store if u == url]

    def delete(self, url, name):
        if (url, name) not in self.store:
            raise ValueError(f"no session {name!r} on remote")
        del self.store[(url, name)]


class PushTests(_FerryBase):
    def _seed_session(self, session_id, text):
        cc.write_text(cc.session_path(self.cwd, session_id), text)

    def test_push_sends_exact_bytes(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        self._seed_session("sess-1", '{"uuid":"x"}\n')
        fake = FakeServer()
        core.push("origin", "auth-refactor", "sess-1",
                  server=fake, config_path=self.cfg)
        self.assertEqual(
            fake.pushed, [("u@h:/p", "auth-refactor", '{"uuid":"x"}\n')])

    def test_push_unknown_session_raises(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        with self.assertRaises(ValueError):
            core.push("origin", "n", "missing-id",
                      server=FakeServer(), config_path=self.cfg)

    def test_push_unknown_remote_raises(self):
        self._seed_session("sess-1", '{"uuid":"x"}\n')
        with self.assertRaises(core.FerryError):
            core.push("nope", "n", "sess-1",
                      server=FakeServer(), config_path=self.cfg)

    def test_push_defaults_to_sole_remote(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        self._seed_session("sess-1", '{"uuid":"x"}\n')
        fake = FakeServer()
        resolved = core.push(None, "auth-refactor", "sess-1",
                             server=fake, config_path=self.cfg)
        self.assertEqual(
            fake.pushed, [("u@h:/p", "auth-refactor", '{"uuid":"x"}\n')])
        self.assertEqual(resolved, "origin")  # returns the remote it resolved to

    def test_push_no_remote_arg_with_no_remotes_raises(self):
        self._seed_session("sess-1", '{"uuid":"x"}\n')
        with self.assertRaises(core.FerryError):
            core.push(None, "n", "sess-1",
                      server=FakeServer(), config_path=self.cfg)

    def test_push_omitted_session_with_multiple_local_raises(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        self._seed_session("old-sess", '{"uuid":"old"}\n')
        self._seed_session("new-sess", '{"uuid":"new"}\n')
        with self.assertRaises(core.FerryError) as ctx:
            core.push("origin", "ambig-name", None,
                      cwd=self.cwd, server=FakeServer(), config_path=self.cfg)
        msg = str(ctx.exception)
        self.assertIn(self.cwd, msg)
        self.assertIn("old-sess", msg)
        self.assertIn("new-sess", msg)
        self.assertIn("--session", msg)

    def test_push_omitted_session_with_one_local_pushes_it(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        self._seed_session("only-sess", '{"uuid":"only"}\n')
        fake = FakeServer()
        core.push("origin", "solo-name", None,
                  cwd=self.cwd, server=fake, config_path=self.cfg)
        self.assertEqual(
            fake.pushed, [("u@h:/p", "solo-name", '{"uuid":"only"}\n')])

    def test_push_omitted_session_with_no_local_raises(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        with self.assertRaises(core.FerryError) as ctx:
            core.push("origin", "n", None,
                      cwd=self.cwd, server=FakeServer(), config_path=self.cfg)
        self.assertIn(self.cwd, str(ctx.exception))

    def test_push_truncated_last_line_warns(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        text = '{"uuid":"x"}\n{"truncated":'
        self._seed_session("sess-1", text)
        fake = FakeServer()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            core.push("origin", "auth-refactor", "sess-1",
                      server=fake, config_path=self.cfg)
        self.assertEqual(len(caught), 1)
        self.assertEqual(
            fake.pushed, [("u@h:/p", "auth-refactor", '{"uuid":"x"}\n')])


class RmTests(_FerryBase):
    def test_rm_deletes_and_returns_resolved_remote(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"): "T\n"})
        resolved = core.rm(None, "auth", server=fake, config_path=self.cfg)
        self.assertEqual(resolved, "origin")
        self.assertNotIn(("u@h:/p", "auth"), fake.store)

    def test_rm_absent_session_is_ferry_error(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        with self.assertRaises(core.FerryError):
            core.rm("origin", "ghost", server=FakeServer(), config_path=self.cfg)


class LogTests(_FerryBase):
    def _seed_session(self, session_id, text):
        cc.write_text(cc.session_path(self.cwd, session_id), text)

    def test_log_empty_when_no_ops(self):
        self.assertEqual(core.log(config_path=self.cfg), [])

    def test_push_ops_logged_newest_first(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        self._seed_session("s1", '{"uuid":"x"}\n')
        fake = FakeServer()
        core.push("origin", "first", "s1", server=fake, config_path=self.cfg)
        core.push("origin", "second", "s1", server=fake, config_path=self.cfg)
        entries = core.log(config_path=self.cfg)
        self.assertEqual([e["name"] for e in entries], ["second", "first"])
        self.assertEqual([e["op"] for e in entries], ["push", "push"])
        self.assertTrue(all(e.get("ts") for e in entries))

    def test_pull_logs_new_id_and_rm_logged(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"): _VALID_ENTRY})
        new_id = core.pull("origin", "auth", cwd=self.cwd,
                           server=fake, config_path=self.cfg)
        core.rm("origin", "auth", server=fake, config_path=self.cfg)
        entries = core.log(config_path=self.cfg)
        self.assertEqual(entries[0]["op"], "rm")       # newest first
        self.assertIsNone(entries[0]["id"])
        self.assertEqual(entries[1]["op"], "pull")
        self.assertEqual(entries[1]["id"], new_id)


class RewriteAndPullTests(_FerryBase):
    def test_pull_filename_matches_new_id(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"): _VALID_ENTRY})
        new_id = core.pull("origin", "auth", cwd=self.cwd,
                           server=fake, config_path=self.cfg)
        path = cc.session_path(self.cwd, new_id)
        self.assertEqual(path.name, f"{new_id}.jsonl")

    def test_pull_rewrites_cwd_and_sessionid(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"): _VALID_ENTRY})
        new_id = core.pull("origin", "auth", cwd=self.cwd,
                           server=fake, config_path=self.cfg)
        path = cc.session_path(self.cwd, new_id)
        entries = [json.loads(l) for l in
                   path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertTrue(entries)
        for e in entries:
            if "cwd" in e or "sessionId" in e:
                self.assertEqual(e["cwd"], self.cwd)
                self.assertEqual(e["sessionId"], new_id)

    def test_pull_preserves_extra_line_types(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"): _EXTRA_TYPES_TEXT})
        new_id = core.pull("origin", "auth", cwd=self.cwd,
                           server=fake, config_path=self.cfg)
        types = [json.loads(l)["type"]
                 for l in cc.session_path(self.cwd, new_id)
                 .read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(types, [
            "ai-title", "file-history-snapshot", "mode", "permission-mode",
            "user"])

    def test_pull_truncated_last_line_warns(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        text = _VALID_ENTRY + '{"truncated":'
        fake = FakeServer({("u@h:/p", "auth"): text})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            new_id = core.pull("origin", "auth", cwd=self.cwd,
                               server=fake, config_path=self.cfg)
        skipped = [w for w in caught
                   if "skipping invalid JSON" in str(w.message)]
        self.assertEqual(len(skipped), 1)
        path = cc.session_path(self.cwd, new_id)
        self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_pull_writes_fresh_local_session(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"): _VALID_ENTRY})
        new_id = core.pull("origin", "auth", cwd=self.cwd,
                           server=fake, config_path=self.cfg)
        path = cc.session_path(self.cwd, new_id)
        self.assertTrue(path.is_file())
        entries = [json.loads(l) for l in
                   path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertTrue(entries)
        for e in entries:
            self.assertEqual(e["cwd"], self.cwd)
            self.assertEqual(e["sessionId"], new_id)

    def test_pull_defaults_to_sole_remote(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"): _VALID_ENTRY})
        new_id = core.pull(None, "auth", cwd=self.cwd,
                           server=fake, config_path=self.cfg)
        self.assertTrue(cc.session_path(self.cwd, new_id).is_file())

    def test_pull_empty_history_raises_before_writing(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "empty"): "\n"})
        before = set(cc.list_sessions())
        with self.assertRaises(core.FerryError):
            core.pull("origin", "empty", cwd=self.cwd,
                      server=fake, config_path=self.cfg)
        self.assertEqual(set(cc.list_sessions()), before)  # nothing written

    def test_pull_absent_remote_session_is_ferry_error(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        before = set(cc.list_sessions())
        with self.assertRaises(core.FerryError):
            core.pull("origin", "ghost", cwd=self.cwd,
                      server=FakeServer(), config_path=self.cfg)
        self.assertEqual(set(cc.list_sessions()), before)


class LsTests(_FerryBase):
    def test_ls_local_filters_to_cwd(self):
        cc.write_text(cc.session_path(self.cwd, "mine-1"), "{}\n")
        cc.write_text(cc.session_path(self.cwd, "mine-2"), "{}\n")
        cc.write_text(cc.session_path("/Users/tester/other", "elsewhere"),
                      "{}\n")
        ids = core.ls(cwd=self.cwd)
        self.assertEqual(set(ids), {"mine-1", "mine-2"})

    def test_ls_remote_delegates_to_server(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "a"): "x", ("u@h:/p", "b"): "y"})
        self.assertEqual(
            set(core.ls("origin", server=fake, config_path=self.cfg)),
            {"a", "b"})


class HubEndToEndTests(_FerryBase):
    """Drive core -> real ferry.remote -> localhost hub folder (no `server=`)."""

    def setUp(self):
        super().setUp()
        self.server = _remote_server
        self.hub_dir = self.tmp / "hub"
        self.hub_dir.mkdir()
        self.password = "test-secret"
        env = mock.patch.dict(os.environ, {"FERRY_HUB_PASSWORD": self.password})
        env.start()
        self.addCleanup(env.stop)
        self.server._reset_client_cache()
        self.addCleanup(self.server._reset_client_cache)
        httpd = make_server(self.hub_dir, self.password, "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.url = f"http://127.0.0.1:{httpd.server_port}"
        core.remote_add("origin", self.url, path=self.cfg)

    def _seed_local(self, session_id, text):
        cc.write_text(cc.session_path(self.cwd, session_id), text)

    def test_push_then_pull_roundtrip(self):
        self._seed_local("local-1", _VALID_ENTRY)
        core.push("origin", "auth", "local-1", config_path=self.cfg)
        self.assertEqual(
            (self.hub_dir / "auth.jsonl").read_text(encoding="utf-8"),
            _VALID_ENTRY)

        new_id = core.pull("origin", "auth", cwd=self.cwd, config_path=self.cfg)
        path = cc.session_path(self.cwd, new_id)
        self.assertTrue(path.is_file())
        entries = [json.loads(l) for l in
                   path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for e in entries:
            self.assertEqual(e["cwd"], self.cwd)
            self.assertEqual(e["sessionId"], new_id)

    def test_push_same_name_raises(self):
        self._seed_local("local-1", _VALID_ENTRY)
        self._seed_local("local-2", _VALID_ENTRY.replace("u1", "u2"))
        core.push("origin", "auth", "local-1", config_path=self.cfg)
        with self.assertRaises(core.FerryError) as ctx:
            core.push("origin", "auth", "local-2", config_path=self.cfg)
        self.assertIn("already exists", str(ctx.exception))
        self.assertIn("u1", (self.hub_dir / "auth.jsonl").read_text(encoding="utf-8"))

    def test_ls_remote_lists_names(self):
        self._seed_local("local-1", _VALID_ENTRY)
        core.push("origin", "auth", "local-1", config_path=self.cfg)
        core.push("origin", "ui", "local-1", config_path=self.cfg)
        self.assertEqual(
            set(core.ls("origin", config_path=self.cfg)), {"auth", "ui"})

    def test_pull_absent_session_raises_ferry_error(self):
        with self.assertRaises(core.FerryError):
            core.pull("origin", "ghost", cwd=self.cwd, config_path=self.cfg)

    def test_rm_removes_via_real_remote_package(self):
        # Drives core.rm through the REAL ferry.remote package (no server=),
        # so a missing delete export on the package surface is caught here.
        self._seed_local("local-1", _VALID_ENTRY)
        core.push("origin", "auth", "local-1", config_path=self.cfg)
        core.rm("origin", "auth", config_path=self.cfg)
        self.assertFalse((self.hub_dir / "auth.jsonl").exists())
        with self.assertRaises(core.FerryError):
            core.pull("origin", "auth", cwd=self.cwd, config_path=self.cfg)


class WalkUpTests(_FerryBase):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.src = self.repo / "src"
        self.src.mkdir()
        self.repo_cfg = self.repo / ".ferry" / "config"
        self._orig_cwd = os.getcwd()
        self.addCleanup(lambda: os.chdir(self._orig_cwd))

    def test_nested_cwd_finds_parent_config(self):
        core.remote_add("origin", "u@h:/p", path=self.repo_cfg)
        os.chdir(self.src)
        self.assertEqual(config.get_remote("origin"), "u@h:/p")

    def test_nested_cwd_ls_uses_project(self):
        core.remote_add("origin", "u@h:/p", path=self.repo_cfg)
        os.chdir(self.src)
        project = str(config.project_dir())
        cc.write_text(cc.session_path(project, "mine-1"), "{}\n")
        cc.write_text(cc.session_path(os.getcwd(), "wrong"), "{}\n")
        self.assertEqual(set(core.ls()), {"mine-1"})

    def test_nested_cwd_push_resolves_project_sessions(self):
        core.remote_add("origin", "u@h:/p", path=self.repo_cfg)
        os.chdir(self.src)
        project = str(config.project_dir())
        cc.write_text(cc.session_path(project, "only"), '{"uuid":"o"}\n')
        fake = FakeServer()
        core.push(None, "aname", None, server=fake)
        self.assertEqual(fake.pushed, [("u@h:/p", "aname", '{"uuid":"o"}\n')])

    def test_nested_cwd_pull_writes_to_project(self):
        core.remote_add("origin", "u@h:/p", path=self.repo_cfg)
        fake = FakeServer({("u@h:/p", "auth"): _VALID_ENTRY})
        os.chdir(self.src)
        project = str(config.project_dir())
        new_id = core.pull(None, "auth", server=fake)
        self.assertTrue(cc.session_path(project, new_id).is_file())

    def test_nested_cwd_no_sessions_names_project(self):
        core.remote_add("origin", "u@h:/p", path=self.repo_cfg)
        os.chdir(self.src)
        project = str(config.project_dir())
        with self.assertRaises(core.FerryError) as ctx:
            core.push(None, "n", None, server=FakeServer())
        self.assertIn(project, str(ctx.exception))
        self.assertNotIn(os.getcwd(), str(ctx.exception))

    def test_no_config_raises_not_a_project(self):
        os.chdir(self.src)
        with self.assertRaises(core.FerryError) as ctx:
            core.push(None, "n", "s", server=FakeServer())
        self.assertIn("not a Ferry project", str(ctx.exception))

    def test_remote_add_creates_config_in_cwd(self):
        os.chdir(self.src)
        core.remote_add("origin", "u@h:/p")
        self.assertTrue((self.src / ".ferry" / "config").is_file())
        self.assertEqual(config.get_remote("origin"), "u@h:/p")


class ExportImportTests(_FerryBase):
    def setUp(self):
        super().setUp()
        self.home_patcher = mock.patch.dict(
            os.environ, {"HOME": str(self.tmp)})
        self.home_patcher.start()
        self.addCleanup(self.home_patcher.stop)
        (self.tmp / "Downloads").mkdir()
        self._orig_cwd = os.getcwd()
        self.addCleanup(lambda: os.chdir(self._orig_cwd))

    def _seed_session(self, cwd, session_id, text):
        cc.write_text(cc.session_path(cwd, session_id), text)

    def test_export_writes_named_file_and_skips_truncated_last_line(self):
        os.chdir(self.tmp)
        chat = str(self.tmp.resolve())
        text = '{"uuid":"x"}\n{"truncated":'
        self._seed_session(chat, "sess-1", text)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            path = core.export("My-Chat", "sess-1")
        self.assertEqual(Path(path), (self.tmp / "my-chat.jsonl").resolve())
        self.assertEqual((self.tmp / "my-chat.jsonl").read_text(encoding="utf-8"),
                         '{"uuid":"x"}\n')
        self.assertEqual(len(caught), 1)

    def test_export_two_local_chats_without_session_raises(self):
        os.chdir(self.tmp)
        chat = str(self.tmp.resolve())
        self._seed_session(chat, "old-sess", '{"uuid":"old"}\n')
        self._seed_session(chat, "new-sess", '{"uuid":"new"}\n')
        with self.assertRaises(core.FerryError) as ctx:
            core.export("chat", None)
        msg = str(ctx.exception)
        self.assertIn(chat, msg)
        self.assertIn("old-sess", msg)
        self.assertIn("new-sess", msg)

    def test_export_without_ferry_uses_cwd(self):
        os.chdir(self.tmp)
        chat = str(self.tmp.resolve())
        self._seed_session(chat, "only", '{"uuid":"o"}\n')
        path = core.export("solo", None)
        self.assertEqual((self.tmp / "solo.jsonl").read_text(encoding="utf-8"),
                         '{"uuid":"o"}\n')
        self.assertTrue(path.endswith("solo.jsonl"))

    def test_export_from_nested_dir_uses_project_root(self):
        repo = self.tmp / "repo"
        src = repo / "app" / "src"
        src.mkdir(parents=True)
        cfg = repo / ".ferry" / "config"
        core.remote_add("origin", "u@h:/p", path=cfg)
        project = str(repo.resolve())
        self._seed_session(project, "only", '{"uuid":"o"}\n')
        os.chdir(src)
        path = core.export("nested", None)
        self.assertEqual((src / "nested.jsonl").read_text(encoding="utf-8"),
                         '{"uuid":"o"}\n')
        self.assertTrue(path.endswith("nested.jsonl"))

    def test_export_existing_file_raises(self):
        os.chdir(self.tmp)
        self._seed_session(str(self.tmp.resolve()), "s1", '{"uuid":"x"}\n')
        (self.tmp / "chat.jsonl").write_text("old\n", encoding="utf-8")
        with self.assertRaises(core.FerryError):
            core.export("chat", "s1")

    def test_import_with_path_rewrites_and_keeps_extra_types(self):
        os.chdir(self.tmp)
        (self.tmp / "in.jsonl").write_text(_EXTRA_TYPES_TEXT, encoding="utf-8")
        new_id, cwd = core.import_session(str(self.tmp / "in.jsonl"))
        path = cc.session_path(cwd, new_id)
        types = [json.loads(l)["type"]
                 for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(types, [
            "ai-title", "file-history-snapshot", "mode", "permission-mode",
            "user"])
        for e in [json.loads(l) for l in
                  path.read_text(encoding="utf-8").splitlines() if l.strip()]:
            if "cwd" in e or "sessionId" in e:
                self.assertEqual(e["cwd"], cwd)
                self.assertEqual(e["sessionId"], new_id)

    def test_import_no_path_one_file_in_cwd(self):
        os.chdir(self.tmp)
        (self.tmp / "solo.jsonl").write_text(_VALID_ENTRY, encoding="utf-8")
        new_id, _ = core.import_session(None, stdin_is_tty=False)
        self.assertTrue(cc.session_path(str(self.tmp.resolve()), new_id).is_file())

    def test_import_no_path_one_file_in_downloads(self):
        (self.tmp / "empty").mkdir(exist_ok=True)
        os.chdir(self.tmp / "empty")
        (self.tmp / "Downloads" / "solo.jsonl").write_text(
            _VALID_ENTRY, encoding="utf-8")
        new_id, cwd = core.import_session(None, stdin_is_tty=False)
        self.assertEqual(cwd, str((self.tmp / "empty").resolve()))
        self.assertTrue(cc.session_path(cwd, new_id).is_file())

    def test_import_no_path_two_files_non_tty_lists_and_raises(self):
        os.chdir(self.tmp)
        a = self.tmp / "a.jsonl"
        b = self.tmp / "b.jsonl"
        a.write_text(_VALID_ENTRY, encoding="utf-8")
        b.write_text(_VALID_ENTRY, encoding="utf-8")
        os.utime(a, (1, 1))
        os.utime(b, (2, 2))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(core.FerryError) as ctx:
                core.import_session(None, stdin_is_tty=False)
        text = out.getvalue()
        self.assertIn("1.", text)
        self.assertIn("2.", text)
        self.assertIn("a.jsonl", text)
        self.assertIn("b.jsonl", text)
        self.assertIn("pass a path or a number", str(ctx.exception))

    def test_import_no_path_tty_empty_choice_picks_first(self):
        os.chdir(self.tmp)
        a = self.tmp / "a.jsonl"
        b = self.tmp / "b.jsonl"
        a.write_text(_VALID_ENTRY, encoding="utf-8")
        b.write_text('{"uuid":"b"}\n', encoding="utf-8")
        os.utime(a, (2, 2))
        os.utime(b, (1, 1))
        with mock.patch("builtins.input", return_value=""):
            new_id, _ = core.import_session(None, stdin_is_tty=True)
        self.assertTrue(cc.session_path(str(self.tmp.resolve()), new_id).is_file())

    def test_import_without_ferry_config(self):
        os.chdir(self.tmp)
        (self.tmp / "in.jsonl").write_text(_VALID_ENTRY, encoding="utf-8")
        new_id, cwd = core.import_session(str(self.tmp / "in.jsonl"))
        self.assertEqual(cwd, str(self.tmp.resolve()))
        self.assertTrue(cc.session_path(cwd, new_id).is_file())

    def test_export_import_roundtrip(self):
        os.chdir(self.tmp)
        chat = str(self.tmp.resolve())
        self._seed_session(chat, "sess-1", _VALID_ENTRY)
        export_path = core.export("trip", "sess-1")
        other = self.tmp / "other"
        other.mkdir()
        os.chdir(other)
        new_id, cwd = core.import_session(export_path)
        self.assertEqual(cwd, str(other.resolve()))
        path = cc.session_path(cwd, new_id)
        self.assertTrue(path.is_file())
        entry = json.loads(path.read_text(encoding="utf-8").strip())
        self.assertEqual(entry["cwd"], cwd)
        self.assertEqual(entry["sessionId"], new_id)

    def test_export_clipboard_failure_still_writes(self):
        os.chdir(self.tmp)
        self._seed_session(str(self.tmp.resolve()), "s1", '{"uuid":"x"}\n')
        with mock.patch.object(_core_mod, "copy_file_to_clipboard",
                               side_effect=OSError("nope")), \
                mock.patch("ferry.core.core.sys.platform", "darwin"):
            path = core.export("chat", "s1")
        self.assertTrue(Path(path).is_file())


class MissingCredentialsTests(_FerryBase):
    """No FERRY_HUB_PASSWORD -> server raises -> core surfaces a FerryError."""

    def setUp(self):
        super().setUp()
        self.server = _remote_server
        self.server._reset_client_cache()
        self.addCleanup(self.server._reset_client_cache)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop("FERRY_HUB_PASSWORD", None)
        self.addCleanup(env.stop)
        # Neutralise .env autoload so the password stays genuinely absent.
        loader = mock.patch("ferry.remote.remote.ensure_dotenv_loaded",
                            return_value=None)
        loader.start()
        self.addCleanup(loader.stop)
        core.remote_add("origin", "http://127.0.0.1:8080", path=self.cfg)

    def test_pull_without_creds_is_ferry_error(self):
        with self.assertRaises(core.FerryError):
            core.pull("origin", "auth", cwd=self.cwd, config_path=self.cfg)

    def test_ls_without_creds_is_ferry_error(self):
        with self.assertRaises(core.FerryError):
            core.ls("origin", config_path=self.cfg)


if __name__ == "__main__":
    unittest.main()
