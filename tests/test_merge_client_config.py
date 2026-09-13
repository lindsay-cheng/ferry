"""Tests for Cerebras env loading and HTTP client config."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from weave.merge.client import HttpCerebrasClient, default_cerebras_client
from weave.merge.env import (
    cerebras_configured,
    chat_completions_url,
    describe_cerebras_config,
    get_default_model,
    load_dotenv_file,
    normalize_base_url,
    repo_root,
)
from weave.merge.exceptions import MergeClientError


class DotenvLoaderTests(unittest.TestCase):
    def test_loads_values_from_temp_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "CEREBRAS_API_KEY=from-dotenv-key\n"
                "CEREBRAS_MODEL=test-model\n"
                "# comment\n"
                "\n"
                "CEREBRAS_BASE_URL=https://example.test/v1\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                self.assertTrue(load_dotenv_file(env_path))
                self.assertEqual(os.environ["CEREBRAS_API_KEY"], "from-dotenv-key")
                self.assertEqual(os.environ["CEREBRAS_MODEL"], "test-model")
                self.assertEqual(os.environ["CEREBRAS_BASE_URL"], "https://example.test/v1")

    def test_does_not_override_existing_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("CEREBRAS_API_KEY=from-dotenv-key\n", encoding="utf-8")
            with patch.dict(os.environ, {"CEREBRAS_API_KEY": "from-shell"}, clear=True):
                load_dotenv_file(env_path)
                self.assertEqual(os.environ["CEREBRAS_API_KEY"], "from-shell")


class HttpCerebrasClientConfigTests(unittest.TestCase):
    def test_build_request_includes_required_headers(self):
        client = HttpCerebrasClient(
            api_key="secret-key-value",
            base_url="https://api.cerebras.ai/v1",
            model="test-model",
        )
        request = client.build_request("merge prompt")

        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key-value")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_header("User-agent"), "weave/0.1.0")
        self.assertEqual(request.full_url, "https://api.cerebras.ai/v1/chat/completions")

    def test_chat_completions_url_avoids_double_v1(self):
        url = chat_completions_url("https://api.cerebras.ai/v1/v1")
        self.assertEqual(url, "https://api.cerebras.ai/v1/chat/completions")

    def test_describe_config_never_prints_full_api_key(self):
        with patch.dict(
            os.environ,
            {"CEREBRAS_API_KEY": "csk-abcdefghijklmnop", "CEREBRAS_MODEL": "m"},
            clear=True,
        ):
            with patch("weave.merge.env.ensure_dotenv_loaded", return_value=None):
                summary = describe_cerebras_config()
        self.assertIn("present=True", summary)
        self.assertIn("length=20", summary)
        self.assertIn("...mnop", summary)
        self.assertNotIn("csk-abcdefghijklmnop", summary)

    def test_complete_surfaces_http_errors_without_leaking_key(self):
        client = HttpCerebrasClient(
            api_key="secret-key-value",
            base_url="https://api.cerebras.ai/v1",
            model="test-model",
        )

        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url,
                403,
                "Forbidden",
                hdrs=None,
                fp=io.BytesIO(b'{"message":"Forbidden"}'),
            )

        with patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(MergeClientError) as ctx:
                client.complete("prompt")
        self.assertIn("HTTP 403", str(ctx.exception))
        self.assertNotIn("secret-key-value", str(ctx.exception))


class DefaultModelTests(unittest.TestCase):
    def test_defaults_to_zai_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("weave.merge.env.ensure_dotenv_loaded", return_value=None):
                self.assertEqual(get_default_model(), "zai-glm-4.7")

    def test_respects_env_override(self):
        with patch.dict(os.environ, {"CEREBRAS_MODEL": "custom-model"}, clear=True):
            with patch("weave.merge.env.ensure_dotenv_loaded", return_value=None):
                self.assertEqual(get_default_model(), "custom-model")

    def test_cerebras_configured_needs_only_api_key(self):
        with patch.dict(os.environ, {"CEREBRAS_API_KEY": "k"}, clear=True):
            with patch("weave.merge.env.ensure_dotenv_loaded", return_value=None):
                self.assertTrue(cerebras_configured())

    def test_default_client_uses_default_model_when_unset(self):
        with patch.dict(os.environ, {"CEREBRAS_API_KEY": "k"}, clear=True):
            with patch(
                "weave.merge.client.ensure_dotenv_loaded", return_value=None
            ):
                client = default_cerebras_client()
        self.assertEqual(client._model, "zai-glm-4.7")


class RepoRootTests(unittest.TestCase):
    def test_repo_root_contains_weave_package(self):
        root = repo_root()
        self.assertTrue((root / "weave" / "merge" / "client.py").is_file())


if __name__ == "__main__":
    unittest.main()
