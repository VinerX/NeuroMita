from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from handlers.embedding_providers.base import EmbeddingRequest
from handlers.embedding_providers.gemini_provider import GeminiEmbeddingProvider, _safe_error_text
from handlers.embedding_providers.registry import build_request
from controllers.embedding_presets_controller import EmbeddingPresetsController


class _Response:
    status_code = 200
    headers = {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"embeddings": [{"values": [3.0, 4.0]}]}


class _HttpClient:
    def __init__(self) -> None:
        self.calls = []

    def post(self, url, *, json, headers, timeout):
        self.calls.append((url, json, headers, timeout))
        return _Response()

    @staticmethod
    def raise_for_status(response):
        return response.raise_for_status()


class GeminiEmbeddingProviderTests(unittest.TestCase):
    def test_key_is_sent_in_header_not_url(self) -> None:
        http_client = _HttpClient()
        provider = GeminiEmbeddingProvider(http_client=http_client)
        request = EmbeddingRequest(texts=["test"], api_key="secret-key")

        result = provider._embed_batch(
            ["secret-key"],
            "https://example.test/v1beta",
            "text-embedding-004",
            "RETRIEVAL_DOCUMENT",
            ["test"],
            request,
        )

        self.assertEqual(len(result), 1)
        url, _payload, headers, _timeout = http_client.calls[0]
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

    def test_distribute_keys_rotates_each_gemini_request(self) -> None:
        provider = GeminiEmbeddingProvider()
        request = EmbeddingRequest(
            texts=["text"] * 101,
            api_key="primary-key",
            reserve_keys=["reserve-key"],
            reserve_keys_distribute=True,
        )

        with patch.object(provider, "_embed_batch", side_effect=[[None] * 100, [None]]) as embed_batch:
            provider.embed(request)

        initial_indexes = [call.kwargs["initial_key_index"] for call in embed_batch.call_args_list]
        self.assertEqual(initial_indexes, [0, 1])

    def test_distribution_flag_is_preserved_in_provider_request(self) -> None:
        request = build_request(
            {
                "provider_name": "gemini",
                "reserve_keys_distribute": True,
            },
            ["text"],
        )

        self.assertTrue(request.reserve_keys_distribute)

    def test_builtin_gemini_keys_and_distribution_are_retained_when_saved(self) -> None:
        controller = EmbeddingPresetsController()
        with patch.object(controller, "_save", return_value=True) as save:
            controller.save(
                {
                    "id": "google_gemini_embed",
                    "key": "primary-key",
                    "reserve_keys": ["reserve-key"],
                    "reserve_keys_distribute": True,
                }
            )
        config = controller.get_full("google_gemini_embed")

        self.assertTrue(save.called)
        self.assertEqual(config["api_key"], "primary-key")
        self.assertEqual(config["reserve_keys"], ["reserve-key"])
        self.assertTrue(config["reserve_keys_distribute"])


if __name__ == "__main__":
    unittest.main()
