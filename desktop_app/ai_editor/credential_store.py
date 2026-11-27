"""OS-backed credential storage for ZENITH Desktop AI providers.

Secrets are delegated to the operating system keyring (Windows Credential
Manager on Windows). Provider settings must never serialize API keys.
"""
from __future__ import annotations

from ai_editor.contracts import EditPlanError

SERVICE_NAME = "ZENITH_DESKTOP_AI"


def _validate_identity(provider_id: str, account: str) -> None:
    if not isinstance(provider_id, str) or not provider_id.strip() or len(provider_id) > 120:
        raise EditPlanError("AI provider credential identifier is invalid.")
    if not isinstance(account, str) or not account.strip() or len(account) > 120:
        raise EditPlanError("AI credential account name is invalid.")


def store_api_key(provider_id: str, account: str, secret: str) -> None:
    """Store a provider key in the OS credential vault, never in project files."""
    _validate_identity(provider_id, account)
    if not isinstance(secret, str) or not secret.strip() or len(secret) > 8192:
        raise EditPlanError("API key must contain between 1 and 8192 characters.")
    if "\n" in secret or "\r" in secret:
        raise EditPlanError("API key cannot contain newline characters.")
    try:
        import keyring
        keyring.set_password(f"{SERVICE_NAME}:{provider_id}", account, secret)
    except Exception as exc:
        raise EditPlanError(
            "The operating-system credential vault is unavailable; the API key was not saved."
        ) from exc


def load_api_key(provider_id: str, account: str) -> str | None:
    _validate_identity(provider_id, account)
    try:
        import keyring
        return keyring.get_password(f"{SERVICE_NAME}:{provider_id}", account)
    except Exception as exc:
        raise EditPlanError("The operating-system credential vault is unavailable.") from exc


def delete_api_key(provider_id: str, account: str) -> None:
    _validate_identity(provider_id, account)
    try:
        import keyring
        try:
            keyring.delete_password(f"{SERVICE_NAME}:{provider_id}", account)
        except keyring.errors.PasswordDeleteError:
            pass
    except Exception as exc:
        raise EditPlanError("The operating-system credential vault is unavailable.") from exc
