from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any, Iterator
import threading


@dataclass(frozen=True)
class CharacterScope:
    character_id: str
    character_name: str
    prompt_set_path: str = ""

    @property
    def storage_key(self) -> str:
        return self.character_id or self.character_name


class BoundCharacterService:
    """Lightweight character-bound view over one application-scoped service."""

    __slots__ = ("_service", "_character_id")

    def __init__(self, service: "CharacterScopedService", scope: CharacterScope) -> None:
        object.__setattr__(self, "_service", service)
        object.__setattr__(self, "_character_id", scope.character_id)

    def _scope(self) -> CharacterScope:
        service = object.__getattribute__(self, "_service")
        return service.scope_for(object.__getattribute__(self, "_character_id"))

    @property
    def character_id(self) -> str:
        return self._scope().character_id

    @property
    def character_name(self) -> str:
        return self._scope().character_name

    @property
    def storage_key(self) -> str:
        return self._scope().storage_key

    def __getattr__(self, name: str) -> Any:
        service = object.__getattribute__(self, "_service")
        scope = self._scope()
        with service.operation(scope):
            value = getattr(service, name)
        if not callable(value):
            return value

        @wraps(value)
        def bound_call(*args: Any, **kwargs: Any) -> Any:
            current_scope = self._scope()
            with service.operation(current_scope):
                return getattr(service, name)(*args, **kwargs)

        return bound_call

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__slots__:
            object.__setattr__(self, name, value)
            return
        service = object.__getattribute__(self, "_service")
        scope = self._scope()
        with service.operation(scope):
            setattr(service, name, value)


class CharacterScopedService:
    """Base for one service instance operating on explicit character scopes."""

    def __init__(
        self,
        *,
        default_character_id: str = "",
        default_character_name: str = "",
        default_prompt_set_path: str = "",
    ) -> None:
        self._scope_lock = threading.RLock()
        self._active_scope: ContextVar[CharacterScope | None] = ContextVar(
            f"{type(self).__name__}.active_scope",
            default=None,
        )
        self._scopes: dict[str, CharacterScope] = {}
        self._operation_locks: dict[str, threading.RLock] = {}
        self._default_scope: CharacterScope | None = None

        character_id = str(default_character_id or "").strip()
        character_name = str(default_character_name or character_id or "").strip()
        if character_id or character_name:
            self._default_scope = self.register_scope(
                character_id or character_name,
                character_name or character_id,
                default_prompt_set_path,
            )

    @staticmethod
    def _normalize_id(character_id: str) -> str:
        value = str(character_id or "").strip()
        if not value:
            raise ValueError("character_id is required")
        return value

    def register_scope(
        self,
        character_id: str,
        character_name: str = "",
        prompt_set_path: str = "",
    ) -> CharacterScope:
        key = self._normalize_id(character_id)
        with self._scope_lock:
            current = self._scopes.get(key)
            name = str(character_name or (current.character_name if current else key) or key)
            path = str(prompt_set_path or (current.prompt_set_path if current else "") or "")
            scope = CharacterScope(key, name, path)
            self._scopes[key] = scope
            if self._default_scope is not None and self._default_scope.character_id == key:
                self._default_scope = scope
            return scope

    def bind(
        self,
        character_id: str,
        character_name: str = "",
        prompt_set_path: str = "",
    ) -> BoundCharacterService:
        return BoundCharacterService(
            self,
            self.register_scope(character_id, character_name, prompt_set_path),
        )

    def scope_for(self, character_id: str) -> CharacterScope:
        key = self._normalize_id(character_id)
        with self._scope_lock:
            scope = self._scopes.get(key)
        if scope is None:
            scope = self.register_scope(key, key)
        return scope

    def current_scope(self) -> CharacterScope:
        scope = self._active_scope.get() or self._default_scope
        if scope is None:
            raise RuntimeError(
                f"{type(self).__name__} operation requires a character scope"
            )
        return scope

    def _operation_lock_for(self, character_id: str) -> threading.RLock:
        key = self._normalize_id(character_id)
        with self._scope_lock:
            lock = self._operation_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._operation_locks[key] = lock
            return lock

    @contextmanager
    def activate(self, scope: CharacterScope) -> Iterator[None]:
        token = self._active_scope.set(scope)
        try:
            yield
        finally:
            self._active_scope.reset(token)

    @contextmanager
    def operation(self, scope: CharacterScope) -> Iterator[None]:
        lock = self._operation_lock_for(scope.character_id)
        with lock:
            with self.activate(scope):
                yield

    @property
    def character_id(self) -> str:
        return self.current_scope().character_id

    @property
    def character_name(self) -> str:
        return self.current_scope().character_name

    @property
    def storage_key(self) -> str:
        return self.current_scope().storage_key

    @property
    def prompt_set_path(self) -> str:
        return self.current_scope().prompt_set_path

    @prompt_set_path.setter
    def prompt_set_path(self, value: str) -> None:
        scope = self.current_scope()
        self.register_scope(scope.character_id, scope.character_name, str(value or ""))
