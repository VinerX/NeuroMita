from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from handlers.embedding_providers.base import EmbeddingRequest
from handlers.embedding_providers.gemini_provider import GeminiEmbeddingProvider, _safe_error_text


class _Response:
    status_code = 200
    headers = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"embeddings": [{"values": [3.0, 4.0]}]}


class _Requests:
    def __init__(self) -> None:
        self.calls = []

    def post(self, url, *, json, headers, timeout):
        self.calls.append((url, json, headers, timeout))
        return _Response()


class GeminiEmbeddingProviderTests(unittest.TestCase):
    def test_key_is_sent_in_header_not_url(self) -> None:
        requests = _Requests()
        provider = GeminiEmbeddingProvider()
        request = EmbeddingRequest(texts=["test"], api_key="secret-key")

        result = provider._embed_batch(
            requests,
            ["secret-key"],
            "https://example.test/v1beta",
            "text-embedding-004",
            "RETRIEVAL_DOCUMENT",
            ["test"],
            request,
        )

        self.assertEqual(len(result), 1)
        url, _payload, headers, _timeout = requests.calls[0]
        self.assertNotIn("secret-key", url)
        self.assertNotIn("?key=", url)
        self.assertEqual(headers["x-goog-api-key"], "secret-key")

    def test_error_text_redacts_known_and_query_string_secrets(self) -> None:
        error = RuntimeError("request failed: https://example.test/?key=other-secret&token=token-secret")

        safe_text = _safe_error_text(error, ["other-secret", "token-secret"])

        self.assertNotIn("other-secret", safe_text)
        self.assertNotIn("token-secret", safe_text)
        self.assertIn("key=<redacted>", safe_text)
        self.assertIn("token=<redacted>", safe_text)


if __name__ == "__main__":
    unittest.main()
