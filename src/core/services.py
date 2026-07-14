"""Типизированный реестр сервисов.

Замена sync-RPC поверх EventBus (синхронных GET_*-запросов через EventBus).

Правила:
- у каждого сервиса ровно один владелец, который регистрирует его один раз;
- потребитель достаёт сервис по контракту (ABC), а не по строке;
- отсутствующий сервис — ошибка (ServiceNotRegistered), а не молчаливый дефолт;
- временные/перезапускаемые владельцы используют owner-safe registration handle,
  чтобы старый lifecycle не мог удалить уже заменивший его сервис.

EventBus остаётся только для notification-событий (ON_*, GUI.*, *_CHANGED).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _ServiceEntry:
    impl: Any
    owner: object | None


class ServiceRegistration:
    """Идемпотентный owner-safe handle регистрации сервиса."""

    def __init__(
        self,
        registry: "ServiceRegistry",
        contract: type,
        owner: object,
        fallback: _ServiceEntry | None,
    ) -> None:
        self._registry = registry
        self._contract = contract
        self._owner = owner
        self._fallback = fallback
        self._lock = threading.Lock()
        self._closed = False

    @property
    def contract(self) -> type:
        return self._contract

    def close(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            self._closed = True
        return self._registry._close_owned(
            self._contract, self._owner, self._fallback
        )

    def __enter__(self) -> "ServiceRegistration":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class ServiceRegistry:
    """Хранит по одному экземпляру на контракт. Ничего не создаёт сам."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._services: Dict[type, _ServiceEntry] = {}

    @staticmethod
    def _validate(contract: Type[T], impl: T) -> None:
        if not isinstance(impl, contract):
            raise TypeError(
                f"{type(impl).__name__} не реализует контракт {contract.__name__}"
            )

    def _register(
        self,
        contract: Type[T],
        impl: T,
        *,
        replace: bool,
        owner: object | None,
    ) -> T:
        self._validate(contract, impl)
        with self._lock:
            if contract in self._services and not replace:
                raise ServiceAlreadyRegistered(contract)
            self._services[contract] = _ServiceEntry(impl=impl, owner=owner)
            self._changed.notify_all()
        return impl

    def register(self, contract: Type[T], impl: T, *, replace: bool = False) -> T:
        """Постоянная регистрация без owner handle.

        Подходит для application-scoped сервисов. Для optional/restartable
        компонентов используйте register_owned().
        """
        return self._register(contract, impl, replace=replace, owner=None)

    def register_owned(
        self,
        contract: Type[T],
        impl: T,
        *,
        replace: bool = False,
    ) -> ServiceRegistration:
        self._validate(contract, impl)
        owner = object()
        with self._lock:
            previous = self._services.get(contract)
            if previous is not None and not replace:
                raise ServiceAlreadyRegistered(contract)
            # Application-scoped fallback (owner=None) may be temporarily
            # overridden by an optional feature and must come back on close.
            # Another temporary owner is deliberately not restored: it may
            # already have completed its lifecycle.
            fallback = (
                previous
                if previous is not None and previous.owner is None
                else None
            )
            self._services[contract] = _ServiceEntry(impl=impl, owner=owner)
            self._changed.notify_all()
        return ServiceRegistration(self, contract, owner, fallback)

    def _close_owned(
        self,
        contract: Type[Any],
        owner: object,
        fallback: _ServiceEntry | None,
    ) -> bool:
        with self._lock:
            entry = self._services.get(contract)
            if entry is None or entry.owner is not owner:
                return False
            if fallback is None:
                del self._services[contract]
            else:
                self._services[contract] = fallback
            self._changed.notify_all()
            return True

    def get(self, contract: Type[T]) -> T:
        with self._lock:
            try:
                return self._services[contract].impl
            except KeyError:
                raise ServiceNotRegistered(contract) from None

    def is_registered(self, contract: Type[Any]) -> bool:
        with self._lock:
            return contract in self._services

    def get_optional(self, contract: Type[T], default: Any = None) -> T | Any:
        with self._lock:
            entry = self._services.get(contract)
            return default if entry is None else entry.impl

    def wait(self, contract: Type[T], timeout: float | None = None) -> T:
        """Дождаться регистрации сервиса без опроса EventBus.

        Используется только на фоновых путях, где feature уже запущена или
        запускается. GUI-поток должен пользоваться snapshot/async feature API.
        """
        deadline = (
            None
            if timeout is None
            else time.monotonic() + max(0.0, float(timeout))
        )
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
            return self._services[contract].impl

    def unregister(self, contract: Type[Any], *, owner: object | None = None) -> bool:
        """Удалить сервис.

        Если указан owner, удаление выполняется только если текущая регистрация
        принадлежит именно ему. Это защищает новый сервис от позднего shutdown
        предыдущего поколения optional feature.
        """
        with self._lock:
            entry = self._services.get(contract)
            if entry is None:
                return False
            if owner is not None and entry.owner is not owner:
                return False
            del self._services[contract]
            self._changed.notify_all()
            return True

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
