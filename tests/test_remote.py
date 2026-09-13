"""Tests for weave.remote (the Supabase-backed remote transport).

A fake `supabase` module is injected into sys.modules so the real
`from supabase import create_client` path runs against an in-memory client --
no network, no real project. weave.remote is otherwise exercised verbatim.

Run (from repo root):  python3 -m pytest tests/test_remote.py
"""

import os
import sys
import types
import unittest
from unittest import mock

from weave.remote import remote as server
from fake_supabase import FakeSupabaseClient


class _ServerBase(unittest.TestCase):
    def setUp(self):
        self.client = FakeSupabaseClient()
        fake_mod = types.ModuleType("supabase")
        fake_mod.create_client = lambda url, key: self.client
        mods = mock.patch.dict(sys.modules, {"supabase": fake_mod})
        mods.start()
        self.addCleanup(mods.stop)
        env = mock.patch.dict(
            os.environ,
            {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "svc"})
        env.start()
        self.addCleanup(env.stop)
        server._reset_client_cache()
        self.addCleanup(server._reset_client_cache)


class PushPullTests(_ServerBase):
    def test_push_then_pull(self):
        server.push("weave://team", "auth", "TRANSCRIPT\n")
        self.assertEqual(server.pull("weave://team", "auth"), "TRANSCRIPT\n")

    def test_push_stores_expected_row(self):
        server.push("weave://team", "auth", "T\n")
        rows = self.client.store
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["remote_url"], "weave://team")
        self.assertEqual(rows[0]["name"], "auth")
        self.assertEqual(rows[0]["transcript"], "T\n")

    def test_push_overwrites_on_conflict(self):
        server.push("weave://team", "auth", "first\n")
        server.push("weave://team", "auth", "second\n")
        self.assertEqual(len(self.client.store), 1)
        self.assertEqual(server.pull("weave://team", "auth"), "second\n")

    def test_pull_missing_raises(self):
        with self.assertRaises(server.ServerError):
            server.pull("weave://team", "ghost")

    def test_pull_scoped_by_remote_url(self):
        server.push("weave://team-a", "auth", "A\n")
        with self.assertRaises(server.ServerError):
            server.pull("weave://team-b", "auth")


class DeleteTests(_ServerBase):
    def test_delete_removes_only_the_named_session(self):
        server.push("weave://team", "auth", "A\n")
        server.push("weave://team", "ui", "B\n")
        server.delete("weave://team", "auth")
        self.assertEqual(server.list("weave://team"), ["ui"])
        with self.assertRaises(server.ServerError):
            server.pull("weave://team", "auth")

    def test_delete_scoped_by_remote_url(self):
        server.push("weave://team-a", "auth", "A\n")
        with self.assertRaises(server.ServerError):
            server.delete("weave://team-b", "auth")
        self.assertEqual(server.list("weave://team-a"), ["auth"])  # untouched

    def test_delete_absent_raises(self):
        with self.assertRaises(server.ServerError):
            server.delete("weave://team", "ghost")


class ListTests(_ServerBase):
    def test_list_returns_names_for_remote(self):
        server.push("weave://team", "auth", "1\n")
        server.push("weave://team", "ui", "2\n")
        server.push("weave://other", "infra", "3\n")
        self.assertEqual(set(server.list("weave://team")), {"auth", "ui"})

    def test_list_empty_remote(self):
        self.assertEqual(server.list("weave://nobody"), [])


class CredentialTests(unittest.TestCase):
    def setUp(self):
        server._reset_client_cache()
        self.addCleanup(server._reset_client_cache)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop("SUPABASE_URL", None)
        os.environ.pop("SUPABASE_KEY", None)
        self.addCleanup(env.stop)
        # Neutralise .env autoload so "missing" means missing from the
        # environment AND from any real .env on disk.
        loader = mock.patch("weave.merge.env.ensure_dotenv_loaded",
                            return_value=None)
        loader.start()
        self.addCleanup(loader.stop)

    def test_missing_creds_raises_server_error(self):
        with self.assertRaises(server.ServerError):
            server.push("weave://team", "auth", "T\n")

    def test_credentials_loaded_from_dotenv(self):
        """_client consults the .env loader; creds it sets are picked up."""
        def fake_loader():
            os.environ["SUPABASE_URL"] = "https://from-dotenv.supabase.co"
            os.environ["SUPABASE_KEY"] = "dotenv-svc-key"

        fake_mod = types.ModuleType("supabase")
        seen = {}
        fake_mod.create_client = lambda url, key: seen.update(url=url, key=key) or object()
        with mock.patch.dict(sys.modules, {"supabase": fake_mod}):
            with mock.patch("weave.merge.env.ensure_dotenv_loaded",
                            side_effect=fake_loader):
                client = server._client()
        self.assertIsNotNone(client)
        self.assertEqual(seen["url"], "https://from-dotenv.supabase.co")
        self.assertEqual(seen["key"], "dotenv-svc-key")


if __name__ == "__main__":
    unittest.main()
