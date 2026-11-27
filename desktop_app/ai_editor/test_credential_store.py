from __future__ import annotations

import pytest

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


def test_secret_roundtrip_uses_os_keyring_not_project_config(monkeypatch):
    backend = FakeKeyring()
    monkeypatch.setitem(__import__("sys").modules, "keyring", backend)
    credential_store.store_api_key("openai-compatible", "default", "secret-value")
    assert credential_store.load_api_key("openai-compatible", "default") == "secret-value"
    assert list(backend.values) == [("ZENITH_DESKTOP_AI:openai-compatible", "default")]


def test_delete_missing_secret_is_safe(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring())
    credential_store.delete_api_key("provider", "default")


@pytest.mark.parametrize("secret", ["", "  ", "x\ny", "x\ry", "x" * 8193])
def test_rejects_invalid_secret(secret):
    with pytest.raises(EditPlanError):
        credential_store.store_api_key("provider", "default", secret)


def test_rejects_invalid_identity():
    with pytest.raises(EditPlanError):
        credential_store.load_api_key("../bad", "default")
