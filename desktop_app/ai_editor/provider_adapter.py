"""Secure OpenAI-compatible JSON provider adapter.

The adapter is opt-in, remote by definition, reads credentials from the OS
credential vault (with an environment-variable fallback for headless use), and
accepts only bounded JSON requests/responses. It never reads project files or
performs media uploads.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ai_editor.contracts import EditPlanError


MAX_REQUEST_BYTES = 2_000_000
MAX_RESPONSE_BYTES = 1_000_000


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    model: str = ""
    api_key_env: str = "ZENITH_AI_API_KEY"
    credential_account: str = "default"
    timeout_seconds: float = 45.0
    max_response_bytes: int = MAX_RESPONSE_BYTES

    def validate(self) -> None:
        from urllib.parse import urlsplit
        parsed = urlsplit(self.endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise EditPlanError("AI provider endpoint must use HTTPS.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise EditPlanError("AI provider endpoint cannot contain credentials, query, or fragment.")
        if not self.model or len(self.model) > 200:
            raise EditPlanError("A valid AI model name is required.")
        if not self.api_key_env.isidentifier() or len(self.api_key_env) > 100:
            raise EditPlanError("API key environment-variable name is invalid.")
        if not isinstance(self.credential_account, str) or not self.credential_account.strip() or len(self.credential_account) > 120:
            raise EditPlanError("AI credential account name is invalid.")
        if not 1 <= self.timeout_seconds <= 120:
            raise EditPlanError("AI request timeout must be between 1 and 120 seconds.")
        if not 1 <= self.max_response_bytes <= MAX_RESPONSE_BYTES:
            raise EditPlanError("AI response limit must be between 1 byte and 1 MB.")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _https_post_json(url: str, headers: Mapping[str, str], body: bytes,
                     timeout: float, max_response_bytes: int) -> bytes:
    request = Request(url, data=body, headers=dict(headers), method="POST")
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read(max_response_bytes + 1)
    except HTTPError as exc:
        # Do not include provider response bodies or request headers in errors.
        raise EditPlanError(f"AI provider returned HTTP status {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise EditPlanError("Could not reach the configured AI provider.") from exc
    if len(payload) > max_response_bytes:
        raise EditPlanError("AI provider response exceeded the configured size limit.")
    return payload


class OpenAICompatibleJSONProvider:
    """Remote JSON-only adapter for providers implementing chat-completions."""

    is_remote = True

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        transport: Callable[[str, Mapping[str, str], bytes, float, int], bytes] | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self._transport = transport or _https_post_json

    def _generate(self, request: Mapping[str, object]) -> str:
        if not isinstance(request, Mapping):
            raise EditPlanError("AI request must be a JSON object.")
        try:
            user_content = json.dumps(request, ensure_ascii=False, allow_nan=False,
                                      separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise EditPlanError("AI request contains non-JSON data.") from exc
        if len(user_content) > MAX_REQUEST_BYTES:
            raise EditPlanError("AI request exceeds the 2 MB safety limit.")
        api_key = ""
        try:
            from ai_editor.credential_store import load_api_key
            api_key = load_api_key("openai-compatible", self.config.credential_account) or ""
        except EditPlanError:
            # Environment-variable fallback remains available for headless use.
            api_key = ""
        if not api_key:
            api_key = os.environ.get(self.config.api_key_env, "")
        if not api_key or len(api_key) > 8_192 or "\n" in api_key or "\r" in api_key:
            raise EditPlanError(
                f"Set a valid credential in the {self.config.api_key_env} environment variable."
            )
        system = request.get("system_instructions")
        if not isinstance(system, str) or not system.strip():
            raise EditPlanError("AI request is missing system instructions.")
        payload = {
            "model": self.config.model,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content.decode("utf-8")},
            ],
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        raw = self._transport(
            self.config.endpoint, headers, body,
            self.config.timeout_seconds, self.config.max_response_bytes,
        )
        if not isinstance(raw, bytes) or len(raw) > self.config.max_response_bytes:
            raise EditPlanError("AI provider response is invalid or too large.")
        try:
            envelope = json.loads(raw.decode("utf-8"))
            content = envelope["choices"][0]["message"]["content"]
        except (UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise EditPlanError("AI provider returned an invalid chat-completions response.") from exc
        if not isinstance(content, str) or not content.strip():
            raise EditPlanError("AI provider returned an empty JSON response.")
        if len(content.encode("utf-8")) > self.config.max_response_bytes:
            raise EditPlanError("AI provider JSON content exceeded the response limit.")
        return content

    def generate_story_blueprint(self, request: Mapping[str, object]) -> str:
        return self._generate(request)

    def generate_edit_plan(self, request: Mapping[str, object]) -> str:
        return self._generate(request)
