from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from ai_editor import credential_store
from ai_editor.contracts import EditPlanError


class FakeKeyringErrors:
    class PasswordDeleteError(Exception):
        pass


class FakeKeyring:
    errors = FakeKeyringErrors()

    def __init__(self):
        self.values = {}

    def set_password(self, service, account, secret):
        self.values[(service, account)] = secret

    def get_password(self, service, account):
        return self.values.get((service, account))

    def delete_password(self, service, account):
        key = (service, account)
        if key not in self.values:
            raise self.errors.PasswordDeleteError()
        del self.values[key]


class CredentialStoreTests(unittest.TestCase):
    def test_secret_roundtrip_uses_os_keyring(self):
        backend = FakeKeyring()
        with patch.dict(sys.modules, {"keyring": backend}):
            credential_store.store_api_key("openai-compatible", "default", "secret-value")
            self.assertEqual(
                credential_store.load_api_key("openai-compatible", "default"),
                "secret-value",
            )
        self.assertEqual(
            list(backend.values),
            [("ZENITH_DESKTOP_AI:openai-compatible", "default")],
        )

    def test_delete_missing_secret_is_safe(self):
        with patch.dict(sys.modules, {"keyring": FakeKeyring()}):
            credential_store.delete_api_key("provider", "default")

    def test_rejects_invalid_secrets(self):
        for secret in ("", "  ", "x\\ny", "x\\ry", "x" * 8193):
            with self.subTest(secret_length=len(secret)):
                with self.assertRaises(EditPlanError):
                    credential_store.store_api_key("provider", "default", secret)

    def test_rejects_invalid_identity(self):
        with self.assertRaises(EditPlanError):
            credential_store.load_api_key("../bad", "default")


if __name__ == "__main__":
    unittest.main()
