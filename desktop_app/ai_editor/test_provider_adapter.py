"""Tests for the opt-in HTTPS JSON provider adapter."""
import json
import os
import unittest
from unittest.mock import patch

from ai_editor.contracts import EditPlanError
from ai_editor.provider_adapter import (
    MAX_REQUEST_BYTES, OpenAICompatibleConfig, OpenAICompatibleJSONProvider,
)


class ProviderAdapterTests(unittest.TestCase):
    def setUp(self):
        self.config = OpenAICompatibleConfig(model="test-model")
        self.response = json.dumps({
            "choices": [{"message": {"content": '{"ok": true}'}}]
        }).encode()

    def test_config_requires_https_and_model(self):
        with self.assertRaisesRegex(EditPlanError, "HTTPS"):
            OpenAICompatibleConfig(endpoint="http://example.com", model="m").validate()
        with self.assertRaisesRegex(EditPlanError, "model"):
            OpenAICompatibleConfig(model="").validate()

    def test_missing_secret_fails_before_transport(self):
        called = []
        provider = OpenAICompatibleJSONProvider(self.config, transport=lambda *a: called.append(a))
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(EditPlanError, "ZENITH_AI_API_KEY"):
                provider.generate_story_blueprint({"system_instructions": "test"})
        self.assertEqual(called, [])

    def test_uses_env_secret_and_json_only_request(self):
        captured = {}
        def transport(url, headers, body, timeout, limit):
            captured.update(url=url, headers=dict(headers), body=json.loads(body),
                            timeout=timeout, limit=limit)
            return self.response
        provider = OpenAICompatibleJSONProvider(self.config, transport=transport)
        with patch.dict(os.environ, {"ZENITH_AI_API_KEY": "secret-value"}):
            result = provider.generate_story_blueprint({
                "system_instructions": "Return JSON",
                "assets": [{"asset_id": "safe-id"}],
                "privacy": {"local_paths_included": False, "media_bytes_included": False},
            })
        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(captured["headers"]["Authorization"], "Bearer secret-value")
        self.assertEqual(captured["body"]["response_format"], {"type": "json_object"})
        self.assertNotIn("secret-value", json.dumps(captured["body"]))

    def test_oversized_request_rejected_before_transport(self):
        called = []
        provider = OpenAICompatibleJSONProvider(self.config, transport=lambda *a: called.append(a))
        with patch.dict(os.environ, {"ZENITH_AI_API_KEY": "secret-value"}):
            with self.assertRaisesRegex(EditPlanError, "2 MB"):
                provider.generate_edit_plan({
                    "system_instructions": "x",
                    "payload": "x" * (MAX_REQUEST_BYTES + 1),
                })
        self.assertEqual(called, [])

    def test_oversized_response_rejected(self):
        provider = OpenAICompatibleJSONProvider(
            self.config, transport=lambda *a: b"x" * (self.config.max_response_bytes + 1)
        )
        with patch.dict(os.environ, {"ZENITH_AI_API_KEY": "secret-value"}):
            with self.assertRaisesRegex(EditPlanError, "too large"):
                provider.generate_story_blueprint({"system_instructions": "test"})

    def test_invalid_provider_envelope_rejected(self):
        provider = OpenAICompatibleJSONProvider(self.config, transport=lambda *a: b'{}')
        with patch.dict(os.environ, {"ZENITH_AI_API_KEY": "secret-value"}):
            with self.assertRaisesRegex(EditPlanError, "invalid chat-completions"):
                provider.generate_story_blueprint({"system_instructions": "test"})

    def test_provider_is_explicitly_remote(self):
        provider = OpenAICompatibleJSONProvider(self.config, transport=lambda *a: self.response)
        self.assertIs(provider.is_remote, True)


if __name__ == "__main__":
    unittest.main()
