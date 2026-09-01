"""Per-character synchronization primitives.

``character_lock`` protects short mutations/snapshots of character state.
``character_generation_lock`` serializes complete generation workflows for the
same character without blocking unrelated state maintenance while the provider
is producing a response.
"""
from __future__ import annotations

import threading
from typing import Dict

_state_locks: Dict[str, threading.RLock] = {}
_generation_locks: Dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock_key(character_id: str) -> str:
    return str(character_id or "")


def character_lock(character_id: str) -> threading.RLock:
    key = _lock_key(character_id)
    lock = _state_locks.get(key)
    if lock is not None:
        return lock
    with _guard:
        lock = _state_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _state_locks[key] = lock
        return lock


def character_generation_lock(character_id: str) -> threading.Lock:
    key = _lock_key(character_id)
    lock = _generation_locks.get(key)
    if lock is not None:
        return lock
    with _guard:
        lock = _generation_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _generation_locks[key] = lock
        return lock


__all__ = ["character_lock", "character_generation_lock"]
