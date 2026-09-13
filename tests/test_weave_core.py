"""Tests for weave.core -- no real ~/.claude and no real Supabase are touched.

Two layers of coverage:
  * policy branches via an injected in-memory `server` fake (fast, no transport);
  * an end-to-end path that drives core.push/pull/ls through the REAL
    weave.remote, with a fake `supabase` module swapped into sys.modules so the
    Supabase pipeline (core -> weave.remote -> client) runs without a network.

Run (from repo root):  python3 -m pytest tests/test_weave_core.py
"""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from weave import config, connector as cc, core
from weave.core import core as _core_mod
from weave.remote import remote as _remote_server

from fake_supabase import FakeSupabaseClient

_VALID_ENTRY = (
    '{"parentUuid":null,"type":"user","uuid":"u1",'
    '"cwd":"/Users/alice/proj","sessionId":"alice-sess",'
    '"timestamp":"2026-06-26T10:00:00.000Z",'
    '"message":{"role":"user","content":"hi"}}\n')


class _WeaveBase(unittest.TestCase):
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


class ConfigTests(_WeaveBase):
    def test_remote_add_writes_url(self):
        core.remote_add("origin", "user@host:/srv/weave", path=self.cfg)
        self.assertEqual(
            config.get_remote("origin", path=self.cfg), "user@host:/srv/weave")

    def test_remote_add_updates_existing(self):
        core.remote_add("origin", "user@host:/old", path=self.cfg)
        core.remote_add("origin", "user@host:/new", path=self.cfg)
        self.assertEqual(
            config.get_remote("origin", path=self.cfg), "user@host:/new")

    def test_unknown_remote_raises(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        with self.assertRaises(ValueError):
            config.get_remote("missing", path=self.cfg)
        with self.assertRaises(core.WeaveError):
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
        with self.assertRaises(core.WeaveError):
            _core_mod._resolve_remote(None, path=self.cfg)

    def test_resolve_remote_none_with_multiple_raises(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        core.remote_add("backup", "u@h:/b", path=self.cfg)
        with self.assertRaises(core.WeaveError):
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


class PushTests(_WeaveBase):
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
        with self.assertRaises(core.WeaveError):
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
        with self.assertRaises(core.WeaveError):
            core.push(None, "n", "sess-1",
                      server=FakeServer(), config_path=self.cfg)

    def test_push_auto_uses_latest_local_session(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        self._seed_session("old-sess", '{"uuid":"old"}\n')
        self._seed_session("new-sess", '{"uuid":"new"}\n')
        os.utime(cc.session_path(self.cwd, "old-sess"), (1_000, 1_000))
        os.utime(cc.session_path(self.cwd, "new-sess"), (2_000, 2_000))
        fake = FakeServer()
        core.push("origin", "auto-name", "auto",
                  cwd=self.cwd, server=fake, config_path=self.cfg)
        self.assertEqual(
            fake.pushed, [("u@h:/p", "auto-name", '{"uuid":"new"}\n')])

    def test_push_auto_with_no_local_sessions_raises(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        with self.assertRaises(core.WeaveError):
            core.push("origin", "n", "auto",
                      cwd=self.cwd, server=FakeServer(), config_path=self.cfg)


class RmTests(_WeaveBase):
    def test_rm_deletes_and_returns_resolved_remote(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        fake = FakeServer({("u@h:/p", "auth"): "T\n"})
        resolved = core.rm(None, "auth", server=fake, config_path=self.cfg)
        self.assertEqual(resolved, "origin")
        self.assertNotIn(("u@h:/p", "auth"), fake.store)

    def test_rm_absent_session_is_weave_error(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        with self.assertRaises(core.WeaveError):
            core.rm("origin", "ghost", server=FakeServer(), config_path=self.cfg)


class LogTests(_WeaveBase):
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


class RewriteAndPullTests(_WeaveBase):
    def test_rewrite_for_local_sets_cwd_and_sessionid(self):
        entries = [{"uuid": "a", "cwd": "/old", "sessionId": "old"},
                   {"uuid": "b", "cwd": "/old", "sessionId": "old"}]
        out = _core_mod._rewrite_for_local(entries, "new-id", "/Users/me/proj")
        for e in out:
            self.assertEqual(e["cwd"], "/Users/me/proj")
            self.assertEqual(e["sessionId"], "new-id")
        self.assertEqual(entries[0]["cwd"], "/old")  # input not mutated

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
        with self.assertRaises(core.WeaveError):
            core.pull("origin", "empty", cwd=self.cwd,
                      server=fake, config_path=self.cfg)
        self.assertEqual(set(cc.list_sessions()), before)  # nothing written

    def test_pull_absent_remote_session_is_weave_error(self):
        core.remote_add("origin", "u@h:/p", path=self.cfg)
        before = set(cc.list_sessions())
        with self.assertRaises(core.WeaveError):
            core.pull("origin", "ghost", cwd=self.cwd,
                      server=FakeServer(), config_path=self.cfg)
        self.assertEqual(set(cc.list_sessions()), before)


class LsTests(_WeaveBase):
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


class SupabaseEndToEndTests(_WeaveBase):
    """Drive core -> real server.py -> faked supabase client (no `server=`)."""

    def setUp(self):
        super().setUp()
        self.server = _remote_server
        self.client = FakeSupabaseClient()
        fake_mod = types.ModuleType("supabase")
        fake_mod.create_client = lambda url, key: self.client
        self.addCleanup(self.server._reset_client_cache)
        mods = mock.patch.dict(sys.modules, {"supabase": fake_mod})
        mods.start()
        self.addCleanup(mods.stop)
        env = mock.patch.dict(
            os.environ,
            {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "svc"})
        env.start()
        self.addCleanup(env.stop)
        self.server._reset_client_cache()
        core.remote_add("origin", "weave://team", path=self.cfg)

    def _seed_local(self, session_id, text):
        cc.write_text(cc.session_path(self.cwd, session_id), text)

    def test_push_then_pull_roundtrip(self):
        self._seed_local("local-1", _VALID_ENTRY)
        core.push("origin", "auth", "local-1", config_path=self.cfg)
        # the transcript landed in the fake DB under (remote_url, name)
        rows = [r for r in self.client.store
                if r["remote_url"] == "weave://team" and r["name"] == "auth"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["transcript"], _VALID_ENTRY)

        new_id = core.pull("origin", "auth", cwd=self.cwd, config_path=self.cfg)
        path = cc.session_path(self.cwd, new_id)
        self.assertTrue(path.is_file())
        entries = [json.loads(l) for l in
                   path.read_text(encoding="utf-8").splitlines() if l.strip()]
        for e in entries:
            self.assertEqual(e["cwd"], self.cwd)
            self.assertEqual(e["sessionId"], new_id)

    def test_push_overwrites_same_name(self):
        self._seed_local("local-1", _VALID_ENTRY)
        self._seed_local("local-2", _VALID_ENTRY.replace("u1", "u2"))
        core.push("origin", "auth", "local-1", config_path=self.cfg)
        core.push("origin", "auth", "local-2", config_path=self.cfg)
        rows = [r for r in self.client.store
                if r["remote_url"] == "weave://team" and r["name"] == "auth"]
        self.assertEqual(len(rows), 1)
        self.assertIn("u2", rows[0]["transcript"])

    def test_ls_remote_lists_names(self):
        self._seed_local("local-1", _VALID_ENTRY)
        core.push("origin", "auth", "local-1", config_path=self.cfg)
        core.push("origin", "ui", "local-1", config_path=self.cfg)
        self.assertEqual(
            set(core.ls("origin", config_path=self.cfg)), {"auth", "ui"})

    def test_pull_absent_session_raises_weave_error(self):
        with self.assertRaises(core.WeaveError):
            core.pull("origin", "ghost", cwd=self.cwd, config_path=self.cfg)

    def test_rm_removes_via_real_remote_package(self):
        # Drives core.rm through the REAL weave.remote package (no server=),
        # so a missing delete export on the package surface is caught here.
        self._seed_local("local-1", _VALID_ENTRY)
        core.push("origin", "auth", "local-1", config_path=self.cfg)
        core.rm("origin", "auth", config_path=self.cfg)
        rows = [r for r in self.client.store
                if r["remote_url"] == "weave://team" and r["name"] == "auth"]
        self.assertEqual(rows, [])
        with self.assertRaises(core.WeaveError):
            core.pull("origin", "auth", cwd=self.cwd, config_path=self.cfg)


class MissingCredentialsTests(_WeaveBase):
    """No SUPABASE_* env -> server raises -> core surfaces a WeaveError."""

    def setUp(self):
        super().setUp()
        self.server = _remote_server
        self.server._reset_client_cache()
        self.addCleanup(self.server._reset_client_cache)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop("SUPABASE_URL", None)
        os.environ.pop("SUPABASE_KEY", None)
        self.addCleanup(env.stop)
        # Neutralise .env autoload so the creds stay genuinely absent.
        loader = mock.patch("weave.merge.env.ensure_dotenv_loaded",
                            return_value=None)
        loader.start()
        self.addCleanup(loader.stop)
        core.remote_add("origin", "weave://team", path=self.cfg)

    def test_pull_without_creds_is_weave_error(self):
        with self.assertRaises(core.WeaveError):
            core.pull("origin", "auth", cwd=self.cwd, config_path=self.cfg)

    def test_ls_without_creds_is_weave_error(self):
        with self.assertRaises(core.WeaveError):
            core.ls("origin", config_path=self.cfg)


if __name__ == "__main__":
    unittest.main()
