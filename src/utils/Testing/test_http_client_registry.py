from __future__ import annotations

import socket
import unittest

import httpx

from core.networking import (
    HttpResponseError,
    HttpClientRegistry,
    NetworkTimeoutError,
    NetworkUnavailableError,
)


class HttpClientRegistryTests(unittest.TestCase):
    def test_service_handle_reuses_registered_client(self):
        seen: list[str] = []
        registry = HttpClientRegistry()
        first = registry.acquire(
            "llm",
            client_factory=lambda: httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: seen.append(str(request.url))
                    or httpx.Response(200, json={"ok": True})
                )
            ),
        )
        second = registry.acquire("llm")

        self.assertEqual(first.get("https://example.test").json(), {"ok": True})
        self.assertEqual(second.get("https://example.test/two").json(), {"ok": True})
        self.assertEqual(len(seen), 2)
        self.assertEqual(registry.registered_service_ids(), ("llm",))

        first.close()
        self.assertEqual(registry.registered_service_ids(), ("llm",))
        second.close()
        self.assertEqual(registry.registered_service_ids(), ())

    def test_dns_failure_is_mapped_with_service_identity(self):
        request = httpx.Request("GET", "https://offline.example")

        def fail(_request):
            error = socket.gaierror(11001, "getaddrinfo failed")
            raise httpx.ConnectError("getaddrinfo failed", request=request) from error

        registry = HttpClientRegistry()
        client = registry.acquire(
            "rag-gemini",
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fail)),
        )

        with self.assertRaises(NetworkUnavailableError) as caught:
            client.get("https://offline.example")

        self.assertEqual(caught.exception.service_id, "rag-gemini")
        self.assertEqual(caught.exception.code, "network.dns")
        self.assertTrue(caught.exception.retryable)

    def test_stream_read_failure_is_mapped_by_context_manager(self):
        class BrokenStream(httpx.SyncByteStream):
            def __iter__(self):
                raise httpx.ReadError("connection lost")
                yield b""

        registry = HttpClientRegistry()
        client = registry.acquire(
            "downloads",
            client_factory=lambda: httpx.Client(
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(200, stream=BrokenStream())
                )
            ),
        )

        with self.assertRaises(Exception) as caught:
            with client.stream("GET", "https://example.test/file") as response:
                list(response.iter_bytes())

        self.assertEqual(getattr(caught.exception, "code", None), "network.read")

    def test_connect_timeout_is_mapped_centrally(self):
        def fail(request):
            raise httpx.ConnectTimeout("connect stalled", request=request)

        registry = HttpClientRegistry()
        client = registry.acquire(
            "llm",
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fail)),
        )

        with self.assertRaises(NetworkTimeoutError) as caught:
            client.post("https://example.test/v1", json={})

        self.assertEqual(caught.exception.code, "network.timeout.connect")
        self.assertEqual(caught.exception.phase, "connect")
        self.assertTrue(caught.exception.retryable)

    def test_http_status_error_redacts_secret_query_parameters(self):
        registry = HttpClientRegistry()
        client = registry.acquire(
            "metadata",
            client_factory=lambda: httpx.Client(
                transport=httpx.MockTransport(lambda _request: httpx.Response(503))
            ),
        )
        response = client.get("https://example.test/data?key=secret&view=short")

        with self.assertRaises(HttpResponseError) as caught:
            client.raise_for_status(response)

        self.assertEqual(caught.exception.status_code, 503)
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("secret", caught.exception.url or "")
        self.assertIn("key=%3Credacted%3E", caught.exception.url or "")


if __name__ == "__main__":
    unittest.main()
