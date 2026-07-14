"""Сериализация работы с состоянием одного персонажа.

Персонаж — это разделяемое изменяемое состояние: переменные (attitude/boredom/
stress, custom_params), очередь pending targets, буфер temporary system infos,
слои сводки истории. Пул GENERATION многопоточный, поэтому два запроса к ОДНОЙ
Мите (например реплика игрока и idle-событие из игры) могли:

- украсть друг у друга consume_pending_targets();
- перемешать инкременты attitude/boredom;
- получить промпт, собранный с сводкой «до» и summary_count «после».

Разные персонажи по-прежнему обрабатываются параллельно.

Блокировка реентерабельная: generate_chat держит её и внутри зовёт
prepare_for_prompt, который берёт ту же блокировку в том же потоке.
"""
from __future__ import annotations

import threading
from typing import Dict

_locks: Dict[str, threading.RLock] = {}
_guard = threading.Lock()


def character_lock(character_id: str) -> threading.RLock:
    key = str(character_id or "")
    lock = _locks.get(key)
    if lock is not None:
        return lock
    with _guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock
