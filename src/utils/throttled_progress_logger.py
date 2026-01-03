from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class ThrottledProgressLogger:
    """
    Логгер прогресса с троттлингом:
    - логируем не чаще, чем раз в log_interval_sec секунд
      ИЛИ каждые log_every элементов
      ИЛИ на завершении.
    """
    info: Callable[[str], None]
    op: str
    total: int
    meta: str = ""
    log_every: int = 50
    log_interval_sec: float = 5.0

    _t0: float = 0.0
    _last_t: float = 0.0
    _last_processed: int = 0
    _started: bool = False

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._last_t = self._t0
        self._last_processed = 0
        self._started = True
        suffix = f" | {self.meta}" if self.meta else ""
        self.info(f"{self.op} start | total={int(self.total)}{suffix}")

    def tick(self, processed: int, updated: Optional[int] = None, stage: str = "") -> None:
        if not self._started:
            self.start()

        if self.total <= 0:
            return

        now = time.monotonic()

        # кроме финального состояния не логируем слишком часто
        if processed != self.total:
            if (processed - self._last_processed) < int(self.log_every) and (now - self._last_t) < float(self.log_interval_sec):
                return

        pct = (processed / self.total * 100.0) if self.total else 0.0
        elapsed = now - self._t0

        st = f" | stage={stage}" if stage else ""
        upd = f" | updated={int(updated)}" if updated is not None else ""
        suffix = f" | {self.meta}" if self.meta else ""

        self.info(
            f"{self.op}{st} | {int(processed)}/{int(self.total)} ({pct:.1f}%)"
            f"{upd} | elapsed={elapsed:.1f}s{suffix}"
        )

        self._last_processed = int(processed)
        self._last_t = now

    def done(self, processed: int, updated: Optional[int] = None) -> None:
        # финальный лог всегда
        if not self._started:
            self.start()
        self.tick(processed=processed, updated=updated, stage="done")
