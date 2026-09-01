from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping

import httpx

from .errors import NetworkRequestError, classify_network_error


HttpClientFactory = Callable[[], httpx.Client]


@dataclass
class _RegisteredClient:
    client: httpx.Client
    references: int = 0


class ManagedHttpClient:
    """HTTP client handle permanently bound to one application service id."""

    def __init__(self, registry: "HttpClientRegistry", service_id: str) -> None:
        self._registry = registry
        self.service_id = service_id
        self._closed = False

    def request(self, method: str, url: str | httpx.URL, **kwargs) -> httpx.Response:
        self._ensure_open()
        return self._registry.request(self.service_id, method, url, **kwargs)

    def get(self, url: str | httpx.URL, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str | httpx.URL, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str | httpx.URL, **kwargs) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def patch(self, url: str | httpx.URL, **kwargs) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

    def delete(self, url: str | httpx.URL, **kwargs) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str | httpx.URL, **kwargs) -> httpx.Response:
        return self.request("HEAD", url, **kwargs)

    def options(self, url: str | httpx.URL, **kwargs) -> httpx.Response:
        return self.request("OPTIONS", url, **kwargs)

    def build_request(self, method: str, url: str | httpx.URL, **kwargs) -> httpx.Request:
        self._ensure_open()
        return self._registry.build_request(self.service_id, method, url, **kwargs)

    def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        self._ensure_open()
        return self._registry.send(self.service_id, request, **kwargs)

    @contextmanager
    def stream(
        self,
        method: str,
        url: str | httpx.URL,
        **kwargs,
    ) -> Iterator[httpx.Response]:
        self._ensure_open()
        with self._registry.stream(self.service_id, method, url, **kwargs) as response:
            yield response

    def raise_for_status(self, response: httpx.Response) -> httpx.Response:
        self._ensure_open()
        try:
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise classify_network_error(self.service_id, exc) from exc

    def client_for_sdk(self) -> httpx.Client:
        self._ensure_open()
        return self._registry._client(self.service_id)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._registry.release(self.service_id)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError(f"HTTP client handle '{self.service_id}' is closed")


class HttpClientRegistry:
    """Owns reusable httpx clients and exposes service-bound handles."""

    def __init__(self) -> None:
        self._clients: dict[str, _RegisteredClient] = {}
        self._lock = threading.RLock()
        self._closed = False

    def acquire(
        self,
        service_id: str,
        *,
        client: httpx.Client | None = None,
        client_factory: HttpClientFactory | None = None,
        client_options: Mapping[str, Any] | None = None,
    ) -> ManagedHttpClient:
        normalized = self._normalize_service_id(service_id)
        with self._lock:
            if self._closed:
                raise RuntimeError("HTTP client registry is closed")
            registered = self._clients.get(normalized)
            if registered is None:
                if client is not None and client_factory is not None:
                    raise ValueError("Pass either client or client_factory, not both")
                if client is None:
                    client = (
                        client_factory()
                        if client_factory is not None
                        else httpx.Client(**dict(client_options or {}))
                    )
                registered = _RegisteredClient(client=client)
                self._clients[normalized] = registered
            elif client is not None and registered.client is not client:
                raise ValueError(f"HTTP service '{normalized}' is already registered")
            registered.references += 1
        return ManagedHttpClient(self, normalized)

    def request(
        self,
        service_id: str,
        method: str,
        url: str | httpx.URL,
        **kwargs,
    ) -> httpx.Response:
        client = self._client(service_id)
        try:
            return client.request(method, url, **kwargs)
        except NetworkRequestError:
            raise
        except httpx.HTTPError as exc:
            raise classify_network_error(service_id, exc, method=method, url=url) from exc

    def build_request(
        self,
        service_id: str,
        method: str,
        url: str | httpx.URL,
        **kwargs,
    ) -> httpx.Request:
        try:
            return self._client(service_id).build_request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise classify_network_error(service_id, exc, method=method, url=url) from exc

    def send(self, service_id: str, request: httpx.Request, **kwargs) -> httpx.Response:
        try:
            return self._client(service_id).send(request, **kwargs)
        except NetworkRequestError:
            raise
        except httpx.HTTPError as exc:
            raise classify_network_error(
                service_id,
                exc,
                method=request.method,
                url=request.url,
            ) from exc

    @contextmanager
    def stream(
        self,
        service_id: str,
        method: str,
        url: str | httpx.URL,
        **kwargs,
    ) -> Iterator[httpx.Response]:
        client = self._client(service_id)
        try:
            with client.stream(method, url, **kwargs) as response:
                yield response
        except NetworkRequestError:
            raise
        except httpx.HTTPError as exc:
            raise classify_network_error(service_id, exc, method=method, url=url) from exc

    def release(self, service_id: str) -> None:
        normalized = self._normalize_service_id(service_id)
        client: httpx.Client | None = None
        with self._lock:
            registered = self._clients.get(normalized)
            if registered is None:
                return
            registered.references = max(0, registered.references - 1)
            if registered.references == 0:
                client = self._clients.pop(normalized).client
        if client is not None:
            client.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            clients = tuple({id(item.client): item.client for item in self._clients.values()}.values())
            self._clients.clear()
        for client in clients:
            client.close()

    def registered_service_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._clients))

    def _client(self, service_id: str) -> httpx.Client:
        normalized = self._normalize_service_id(service_id)
        with self._lock:
            if self._closed:
                raise RuntimeError("HTTP client registry is closed")
            registered = self._clients.get(normalized)
            if registered is None:
                raise KeyError(f"HTTP service is not registered: {normalized}")
            return registered.client

    @staticmethod
    def _normalize_service_id(service_id: str) -> str:
        normalized = str(service_id or "").strip().lower()
        if not normalized:
            raise ValueError("service_id is required")
        return normalized


_SHARED_REGISTRY = HttpClientRegistry()
atexit.register(_SHARED_REGISTRY.close)


def shared_http_client_registry() -> HttpClientRegistry:
    return _SHARED_REGISTRY


__all__ = [
    "HttpClientRegistry",
    "ManagedHttpClient",
    "shared_http_client_registry",
]
