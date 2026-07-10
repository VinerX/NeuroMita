"""Типизированный реестр сервисов.

Замена sync-RPC поверх EventBus (синхронных GET_*-запросов через EventBus).

Правила:
- у каждого сервиса ровно один владелец, который регистрирует его один раз;
- потребитель достаёт сервис по контракту (ABC), а не по строке;
- отсутствующий сервис — ошибка (ServiceNotRegistered), а не молчаливый дефолт.

EventBus остаётся только для notification-событий (ON_*, GUI.*, *_CHANGED).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Type, TypeVar

T = TypeVar("T")


class ServiceNotRegistered(RuntimeError):
    def __init__(self, contract: type):
        super().__init__(
            f"Сервис '{contract.__name__}' не зарегистрирован. "
            f"Его владелец должен вызвать services().register({contract.__name__}, impl) до первого использования."
        )
        self.contract = contract


class ServiceAlreadyRegistered(RuntimeError):
    def __init__(self, contract: type):
        super().__init__(
            f"Сервис '{contract.__name__}' уже зарегистрирован. "
            f"У сервиса один владелец; для замены используйте register(..., replace=True)."
        )
        self.contract = contract


class ServiceRegistry:
    """Хранит по одному экземпляру на контракт. Ничего не создаёт сам."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._services: Dict[type, Any] = {}

    def register(self, contract: Type[T], impl: T, *, replace: bool = False) -> T:
        if not isinstance(impl, contract):
            raise TypeError(
                f"{type(impl).__name__} не реализует контракт {contract.__name__}"
            )
        with self._lock:
            if contract in self._services and not replace:
                raise ServiceAlreadyRegistered(contract)
            self._services[contract] = impl
            self._changed.notify_all()
        return impl

    def get(self, contract: Type[T]) -> T:
        with self._lock:
            try:
                return self._services[contract]
            except KeyError:
                raise ServiceNotRegistered(contract) from None

    def is_registered(self, contract: Type[Any]) -> bool:
        with self._lock:
            return contract in self._services

    def get_optional(self, contract: Type[T], default: Any = None) -> T | Any:
        with self._lock:
            return self._services.get(contract, default)

    def wait(self, contract: Type[T], timeout: float | None = None) -> T:
        """Дождаться регистрации сервиса без опроса EventBus.

        Используется только на фоновых путях, где feature уже запущена или
        запускается. GUI-поток должен пользоваться snapshot/async feature API.
        """
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        with self._changed:
            while contract not in self._services:
                if deadline is None:
                    self._changed.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Сервис '{contract.__name__}' не зарегистрирован за {float(timeout):.3f}s"
                    )
                self._changed.wait(remaining)
            return self._services[contract]

    def unregister(self, contract: Type[Any]) -> None:
        with self._lock:
            self._services.pop(contract, None)
            self._changed.notify_all()

    def reset(self) -> None:
        with self._lock:
            self._services.clear()
            self._changed.notify_all()


_registry = ServiceRegistry()


def services() -> ServiceRegistry:
    return _registry


def use(contract: Type[T]) -> T:
    """Короткая форма services().get(contract)."""
    return _registry.get(contract)
