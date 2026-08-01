"""Окно «Мита говорит» — аренды реплик, а не один общий флаг.

Микрофон обязан молчать, пока звучит голос Миты, иначе ASR распознаёт её же
реплику из колонок. Раньше окно было одним булевым флагом на всё приложение:
любой `active=False` открывал микрофон, даже если параллельно говорила другая
Мита или второй клиент мода, а падение мода между `active=True` и `active=False`
глушило микрофон навсегда.

Здесь каждая реплика — отдельная аренда с ключом «клиент + id реплики» и
дедлайном. Микрофон открыт, когда не осталось ни одной живой аренды.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Callable

from main_logger import logger


class SpeakingWindow:
    """Аренды звучащих реплик. Потокобезопасен: события приходят из разных пулов."""

    # Сколько держать окно закрытым после конца реплики: затухание звука плюс
    # задержка VAD, который выдаёт текст уже после паузы.
    DEFAULT_TAIL_SEC = 0.4

    # Аренда без известной длительности: мод мог упасть, не прислав active=False.
    DEFAULT_LEASE_SEC = 60.0

    # Потолок для аренды с известной длительностью — на случай мусора в поле.
    MAX_LEASE_SEC = 180.0

    # Запас поверх заявленной длительности: сеть и старт воспроизведения.
    LEASE_MARGIN_SEC = 5.0

    # Сколько отключившихся клиентов помним, чтобы отбить их запоздавшие события.
    _CLOSED_MEMORY = 64

    def __init__(
        self,
        *,
        tail_sec: float = DEFAULT_TAIL_SEC,
        lease_sec: float = DEFAULT_LEASE_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tail_sec = float(tail_sec)
        self._lease_sec = float(lease_sec)
        self._clock = clock
        self._lock = threading.Lock()
        self._leases: dict[tuple[str, str], float] = {}
        self._closed_sources: list[str] = []
        self._tail_until = 0.0

    def open(self, *, source: str, speech_id: str = "", duration_sec: float = 0.0) -> bool:
        """Реплика зазвучала. False — событие от уже отключившегося клиента.

        Отключение и `active=True` приходят разными событиями шины и обгоняют
        друг друга; без этой проверки запоздавшее «начал говорить» от мёртвого
        соединения глушило микрофон на всю длину аренды.
        """
        key = self._key(source, speech_id)
        with self._lock:
            if key[0] in self._closed_sources:
                logger.debug(
                    f"speaking_window: игнорирую начало реплики от отключённого '{key[0]}'"
                )
                return False
            self._leases[key] = self._clock() + self._lease_for(duration_sec)
            return True

    def close(self, *, source: str, speech_id: str = "") -> None:
        key = self._key(source, speech_id)
        with self._lock:
            if self._leases.pop(key, None) is not None:
                self._start_tail()

    def close_source(self, source: str) -> None:
        """Клиент отключился: все его реплики закончились вместе с соединением."""
        name = str(source or "").strip()
        if not name:
            return
        with self._lock:
            closed = [key for key in self._leases if key[0] == name]
            for key in closed:
                self._leases.pop(key, None)
            if closed:
                self._start_tail()
            self._remember_closed(name)

    def is_active(self) -> bool:
        now = self._clock()
        with self._lock:
            for key, deadline in list(self._leases.items()):
                if deadline <= now:
                    self._leases.pop(key, None)
                    logger.warning(
                        f"speaking_window: реплика {key} не сообщила о конце — "
                        "снимаю блокировку микрофона по дедлайну"
                    )
            return bool(self._leases) or now < self._tail_until

    def _lease_for(self, duration_sec: float) -> float:
        """Длительность аренды по заявленной моду длине реплики.

        NaN обязателен к отсеву: `nan <= 0` — False, `min(nan, MAX)` — тоже nan,
        и дедлайн `nan` не проходит ни одну проверку истечения. Одно битое поле
        от мода глушило бы микрофон до перезапуска приложения.
        """
        try:
            duration = float(duration_sec or 0.0)
        except (TypeError, ValueError):
            return self._lease_sec
        if not math.isfinite(duration) or duration <= 0.0:
            return self._lease_sec
        return min(duration + self.LEASE_MARGIN_SEC, self.MAX_LEASE_SEC)

    def _start_tail(self) -> None:
        self._tail_until = max(self._tail_until, self._clock() + self._tail_sec)

    def _remember_closed(self, source: str) -> None:
        if source in self._closed_sources:
            return
        self._closed_sources.append(source)
        if len(self._closed_sources) > self._CLOSED_MEMORY:
            del self._closed_sources[: -self._CLOSED_MEMORY]

    @staticmethod
    def _key(source: str, speech_id: str) -> tuple[str, str]:
        return str(source or "local").strip() or "local", str(speech_id or "").strip()
