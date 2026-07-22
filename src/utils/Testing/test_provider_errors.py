import importlib.util
from pathlib import Path
import sys
import unittest


_ERRORS_PATH = Path(__file__).resolve().parents[2] / "handlers" / "llm_providers" / "errors.py"
_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
_SPEC = importlib.util.spec_from_file_location("test_provider_errors_module", _ERRORS_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

build_provider_error = _MODULE.build_provider_error


class ProviderErrorMappingTests(unittest.TestCase):
    def test_readable_provider_message_is_appended_for_user(self):
        err = build_provider_error(
            "common",
            status_code=400,
            payload={"error": {"message": "Reasoning is mandatory for this endpoint and cannot be disabled."}},
            url="https://openrouter.ai/api/v1/chat/completions",
        )

        rendered = err.to_user_message()
        self.assertIn("Ошибка 400", rendered)
        self.assertIn("Reasoning is mandatory for this endpoint and cannot be disabled.", rendered)

    def test_401_invalid_key_is_user_friendly(self):
        err = build_provider_error(
            "common",
            status_code=401,
            payload={"error": {"message": "Invalid API key"}},
            url="https://api.example.test/v1/chat/completions",
        )

        self.assertIn("401", err.friendly_message)
        self.assertIn("API", err.friendly_message)
        self.assertFalse(err.retryable)

    def test_403_access_denied_is_user_friendly(self):
        err = build_provider_error(
            "common",
            status_code=403,
            payload={"error": {"message": "Forbidden"}},
            url="https://api.example.test/v1/chat/completions",
        )

        self.assertIn("403", err.friendly_message)
        self.assertFalse(err.retryable)

    def test_404_endpoint_error_is_user_friendly(self):
        err = build_provider_error(
            "common",
            status_code=404,
            payload={"error": {"message": "Unknown request URL: POST /openai/v1/chat/completions"}},
            url="https://api.example.test/openai/v1",
        )

        self.assertIn("404", err.friendly_message)
        self.assertIn("Endpoint", err.friendly_message)
        self.assertFalse(err.retryable)

    def test_429_rate_limit_is_retryable(self):
        err = build_provider_error(
            "common",
            status_code=429,
            payload={"error": {"message": "Rate limit exceeded"}},
            url="https://api.example.test/v1/chat/completions",
        )

        self.assertIn("429", err.friendly_message)
        self.assertTrue(err.retryable)

    def test_retry_after_is_extracted_from_headers(self):
        err = build_provider_error(
            "common",
            status_code=429,
            payload={"error": {"message": "Rate limit exceeded"}},
            response_headers={"Retry-After": "7"},
            url="https://api.example.test/v1/chat/completions",
        )

        self.assertEqual(err.retry_after_seconds, 7.0)

    def test_structured_provider_message_is_not_appended_for_user(self):
        err = build_provider_error(
            "common",
            status_code=400,
            payload={"error": {"message": "{\"detail\": [{\"type\": \"extra_forbidden\"}]}" }},
            url="https://api.example.test/v1/chat/completions",
        )

        rendered = err.to_user_message()
        self.assertIn("Ошибка 400", rendered)
        self.assertNotIn("extra_forbidden", rendered)

    def test_422_thinking_error_explains_how_to_fix_preset(self):
        err = build_provider_error(
            "common",
            status_code=422,
            payload={
                "error": {
                    "message": (
                        "{'detail': [{'type': 'extra_forbidden', 'loc': ['body', 'thinking'], "
                        "'msg': 'Extra inputs are not permitted'}]}"
                    )
                }
            },
            url="https://api.example.test/openai/v1",
        )

        self.assertIn("thinking", err.friendly_message.lower())
        self.assertIn("Отключите режим мышления", err.friendly_message)
        self.assertFalse(err.retryable)

    def test_nested_openrouter_raw_error_is_extracted(self):
        err = build_provider_error(
            "common",
            status_code=400,
            payload={
                "error": {
                    "message": "Provider returned error",
                    "code": 400,
                    "metadata": {
                        "raw": "{\"error\":{\"message\":\"User location is not supported for the API use.\"}}"
                    },
                }
            },
            url="https://openrouter.ai/api/v1/chat/completions",
        )

        self.assertIn("регион", err.friendly_message.lower())
        self.assertIn("User location is not supported for the API use.", err.provider_message)

    def test_provider_error_payload_is_safe_and_serializable(self):
        err = build_provider_error(
            "gemini",
            status_code=503,
            payload={"error": {"message": "Service temporarily unavailable"}},
            url="https://example.test/generate?key=secret-key",
        )

        payload = err.to_payload()

        self.assertEqual(payload["kind"], "provider_error")
        self.assertEqual(payload["provider"], "gemini")
        self.assertEqual(payload["reason"], "Service temporarily unavailable")
        self.assertTrue(payload["retryable"])
        self.assertNotIn("secret-key", payload["url"])


if __name__ == "__main__":
    unittest.main()
