from __future__ import annotations

import socket
import ssl
import sys
import unittest
from pathlib import Path

import httpx

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.networking.errors import classify_network_error


class NetworkErrorClassificationTests(unittest.TestCase):
    def _connect_error(self, cause: BaseException) -> httpx.ConnectError:
        error = httpx.ConnectError("connection failed", request=httpx.Request("GET", "https://example.test"))
        error.__cause__ = cause
        return error

    def test_certificate_verification_is_non_retryable_tls_error(self) -> None:
        error = self._connect_error(ssl.SSLCertVerificationError("certificate verify failed"))

        result = classify_network_error("test", error)

        self.assertEqual(result.code, "network.tls.certificate")
        self.assertEqual(result.phase, "connect")
        self.assertFalse(result.retryable)

    def test_generic_ssl_error_is_non_retryable_handshake_error(self) -> None:
        result = classify_network_error("test", self._connect_error(ssl.SSLError("WRONG_VERSION_NUMBER")))

        self.assertEqual(result.code, "network.tls.handshake")
        self.assertFalse(result.retryable)
        self.assertIn("WRONG_VERSION_NUMBER", result.detail)

    def test_tls_detail_redacts_secret_parameters(self) -> None:
        cause = ssl.SSLError("handshake failed for key=secret-value")
        result = classify_network_error("test", self._connect_error(cause))

        self.assertIn("key=<redacted>", result.detail)
        self.assertNotIn("secret-value", result.detail)

    def test_dns_connect_error_remains_retryable(self) -> None:
        result = classify_network_error("test", self._connect_error(socket.gaierror("getaddrinfo failed")))

        self.assertEqual(result.code, "network.dns")
        self.assertTrue(result.retryable)

    def test_plain_connect_error_remains_retryable(self) -> None:
        result = classify_network_error("test", self._connect_error(OSError("connection refused")))

        self.assertEqual(result.code, "network.connect")
        self.assertTrue(result.retryable)

    def test_secret_query_parameter_is_redacted(self) -> None:
        error = httpx.ConnectError("failed", request=httpx.Request("GET", "https://example.test/?key=secret-value"))

        result = classify_network_error("test", error)

        self.assertNotIn("secret-value", result.url or "")
        self.assertIn("redacted", result.url or "")

    def test_http_status_detail_redacts_secret_query_parameter(self) -> None:
        request = httpx.Request("GET", "https://example.test/?key=secret-value&mode=full")
        response = httpx.Response(401, request=request)
        error = httpx.HTTPStatusError(
            f"Client error '401 Unauthorized' for url '{request.url}'",
            request=request,
            response=response,
        )

        result = classify_network_error("test", error)

        self.assertNotIn("secret-value", result.url or "")
        self.assertNotIn("secret-value", result.detail)
        self.assertIn("key=<redacted>", result.detail)


if __name__ == "__main__":
    unittest.main()
