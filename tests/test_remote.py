"""Tests for ferry.remote against a real localhost hub (temp folder, no Docker).

Run (from repo root):  python3 -m pytest tests/test_remote.py
"""

import contextlib
import io
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from ferry.hub import main as hub_main
from ferry.hub import make_server
from ferry.remote import remote as server


def _start_hub(test, data_dir, password):
    httpd = make_server(data_dir, password, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    test.addCleanup(httpd.server_close)
    test.addCleanup(httpd.shutdown)
    return f"http://127.0.0.1:{httpd.server_port}"


class _HubBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "chats"
        self.dir.mkdir()
        self.password = "test-secret"
        env = mock.patch.dict(os.environ, {"FERRY_HUB_PASSWORD": self.password})
        env.start()
        self.addCleanup(env.stop)
        server._reset_client_cache()
        self.addCleanup(server._reset_client_cache)
        self.url = _start_hub(self, self.dir, self.password)


class PushPullTests(_HubBase):
    def test_push_then_pull(self):
        server.push(self.url, "auth", "TRANSCRIPT\n")
        self.assertEqual(server.pull(self.url, "auth"), "TRANSCRIPT\n")

    def test_push_writes_file_in_hub_dir(self):
        server.push(self.url, "auth", "T\n")
        path = self.dir / "auth.jsonl"
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_text(encoding="utf-8"), "T\n")

    def test_push_stores_lowercase_name(self):
        server.push(self.url, "Auth-Refactor", "T\n")
        self.assertTrue((self.dir / "auth-refactor.jsonl").is_file())
        self.assertEqual(server.pull(self.url, "AUTH-REFACTOR"), "T\n")
        self.assertEqual(server.list(self.url), ["auth-refactor"])

    def test_push_same_name_raises(self):
        server.push(self.url, "auth", "first\n")
        with self.assertRaises(server.ServerError) as ctx:
            server.push(self.url, "auth", "second\n")
        self.assertIn("already exists", str(ctx.exception))
        self.assertEqual(server.pull(self.url, "auth"), "first\n")

    def test_pull_missing_raises(self):
        with self.assertRaises(server.ServerError) as ctx:
            server.pull(self.url, "ghost")
        self.assertIn("ghost", str(ctx.exception))

    def test_bad_names_raise(self):
        for bad in ("", ".", "..", "foo/bar", "foo_bar", "foo bar"):
            with self.subTest(bad=bad):
                with self.assertRaises(server.ServerError) as ctx:
                    server.push(self.url, bad, "x")
                self.assertIn("letters, numbers, and hyphen", str(ctx.exception))

    def test_two_hubs_do_not_share_names(self):
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        url2 = _start_hub(self, other, self.password)
        server.push(self.url, "auth", "A\n")
        with self.assertRaises(server.ServerError):
            server.pull(url2, "auth")
        self.assertEqual(server.list(url2), [])


class DeleteTests(_HubBase):
    def test_delete_removes_only_the_named_session(self):
        server.push(self.url, "auth", "A\n")
        server.push(self.url, "ui", "B\n")
        server.delete(self.url, "auth")
        self.assertEqual(server.list(self.url), ["ui"])
        with self.assertRaises(server.ServerError):
            server.pull(self.url, "auth")

    def test_delete_absent_raises(self):
        with self.assertRaises(server.ServerError):
            server.delete(self.url, "ghost")


class ListTests(_HubBase):
    def test_list_returns_names_for_remote(self):
        server.push(self.url, "auth", "1\n")
        server.push(self.url, "ui", "2\n")
        self.assertEqual(set(server.list(self.url)), {"auth", "ui"})

    def test_list_empty_remote(self):
        self.assertEqual(server.list(self.url), [])


class AuthAndReachabilityTests(_HubBase):
    def test_bad_password(self):
        with mock.patch.dict(os.environ, {"FERRY_HUB_PASSWORD": "wrong"}):
            server._reset_client_cache()
            with self.assertRaises(server.ServerError) as ctx:
                server.list(self.url)
        self.assertIn("bad password", str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))

    def test_unreachable_is_one_line(self):
        with self.assertRaises(server.ServerError) as ctx:
            server.pull("http://127.0.0.1:1", "auth")
        self.assertIn("unreachable", str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))


class CredentialTests(unittest.TestCase):
    def setUp(self):
        server._reset_client_cache()
        self.addCleanup(server._reset_client_cache)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        os.environ.pop("FERRY_HUB_PASSWORD", None)
        self.addCleanup(env.stop)
        loader = mock.patch("ferry.remote.remote.ensure_dotenv_loaded",
                            return_value=None)
        loader.start()
        self.addCleanup(loader.stop)

    def test_missing_password_raises_server_error(self):
        with self.assertRaises(server.ServerError) as ctx:
            server.push("http://127.0.0.1:8080", "auth", "T\n")
        self.assertIn("FERRY_HUB_PASSWORD", str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))


class DotenvTests(unittest.TestCase):
    def test_password_loaded_from_cwd_dotenv(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / ".env").write_text("FERRY_HUB_PASSWORD=from-file\n", encoding="utf-8")
        chats = root / "chats"
        chats.mkdir()
        orig = os.getcwd()
        os.chdir(root)
        self.addCleanup(lambda: os.chdir(orig))
        server._reset_client_cache()
        self.addCleanup(server._reset_client_cache)
        os.environ.pop("FERRY_HUB_PASSWORD", None)
        url = _start_hub(self, chats, "from-file")
        server.push(url, "auth", "T\n")
        self.assertEqual(server.pull(url, "auth"), "T\n")


class HubMainTests(unittest.TestCase):
    def test_missing_password_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("FERRY_HUB_PASSWORD", None)
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = hub_main(["--dir", d])
        self.assertEqual(rc, 1)
        self.assertIn("FERRY_HUB_PASSWORD", err.getvalue())


if __name__ == "__main__":
    unittest.main()
