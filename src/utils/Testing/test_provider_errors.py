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


if __name__ == "__main__":
    unittest.main()
