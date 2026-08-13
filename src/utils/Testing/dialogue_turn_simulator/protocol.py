from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable


MessageCallback = Callable[[dict[str, Any]], None]
StateCallback = Callable[[bool, str], None]


@dataclass(frozen=True, slots=True)
class UnityClientEndpoint:
    host: str = "127.0.0.1"
    port: int = 12345
    reconnect_delay_seconds: float = 1.0
    connect_timeout_seconds: float = 1.0
    max_message_bytes: int = 8 * 1024 * 1024


class UnityProtocolClient:
    """Persistent newline-delimited JSON client matching Unity's game connection."""

    def __init__(
        self,
        endpoint: UnityClientEndpoint,
        *,
        on_message: MessageCallback,
        on_state: StateCallback,
    ) -> None:
        self.endpoint = endpoint
        self._on_message = on_message
        self._on_state = on_state
        self._socket: socket.socket | None = None
        self._socket_lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self._connected_event.is_set()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._connection_loop,
            name="unity-protocol-client",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._close_socket()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None

    def send(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(encoded) > self.endpoint.max_message_bytes:
            raise ValueError("Сообщение превышает лимит Unity-протокола")
        with self._send_lock:
            with self._socket_lock:
                connection = self._socket
            if connection is None or not self.connected:
                raise ConnectionError("NeuroMita не подключена")
            connection.sendall(encoded)

    def _connection_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                connection = socket.create_connection(
                    (self.endpoint.host, self.endpoint.port),
                    timeout=self.endpoint.connect_timeout_seconds,
                )
                connection.settimeout(None)
                with self._socket_lock:
                    self._socket = connection
                self._connected_event.set()
                self._emit_state(True, f"Подключено к {self.endpoint.host}:{self.endpoint.port}")
                self.send({"action": "hello", "client_role": "game"})
                self.send({"action": "get_settings", "client_role": "game", "context": {}})
                self._receive_loop(connection)
            except (ConnectionError, OSError, ValueError) as exc:
                if not self._stop_event.is_set():
                    self._emit_state(False, f"Нет соединения: {exc}")
            finally:
                self._close_socket()
            if not self._stop_event.wait(max(0.1, self.endpoint.reconnect_delay_seconds)):
                continue
        self._emit_state(False, "Отключено")

    def _receive_loop(self, connection: socket.socket) -> None:
        buffer = bytearray()
        while not self._stop_event.is_set():
            chunk = connection.recv(65536)
            if not chunk:
                raise ConnectionError("сервер закрыл соединение")
            buffer.extend(chunk)
            if len(buffer) > self.endpoint.max_message_bytes:
                raise ValueError("Сервер прислал слишком большое сообщение")
            while b"\n" in buffer:
                raw, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                raw = raw.rstrip(b"\r").strip()
                if not raw:
                    continue
                message = json.loads(raw.decode("utf-8"))
                if isinstance(message, dict):
                    self._on_message(message)

    def _close_socket(self) -> None:
        self._connected_event.clear()
        with self._socket_lock:
            connection = self._socket
            self._socket = None
        if connection is None:
            return
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            connection.close()
        except OSError:
            pass

    def _emit_state(self, connected: bool, message: str) -> None:
        try:
            self._on_state(connected, message)
        except Exception:
            pass


def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())
