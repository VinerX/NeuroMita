"""Типизированный реестр сервисов.

Замена sync-RPC поверх EventBus (`emit_and_wait` на GET_*-событиях).

Правила:
- у каждого сервиса ровно один владелец, который регистрирует его один раз;
- потребитель достаёт сервис по контракту (ABC), а не по строке;
- отсутствующий сервис — ошибка (ServiceNotRegistered), а не молчаливый дефолт.

EventBus остаётся только для notification-событий (ON_*, GUI.*, *_CHANGED).
"""
from __future__ import annotations

import threading
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

    def unregister(self, contract: Type[Any]) -> None:
        with self._lock:
            self._services.pop(contract, None)

    def reset(self) -> None:
        with self._lock:
            self._services.clear()


_registry = ServiceRegistry()


def services() -> ServiceRegistry:
    return _registry


def use(contract: Type[T]) -> T:
    """Короткая форма services().get(contract)."""
    return _registry.get(contract)
