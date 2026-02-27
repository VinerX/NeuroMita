import time
from collections import defaultdict, deque
from typing import Any

from main_logger import logger
from core.events import get_event_bus, Events, Event


class InstallEventsController:
    """
    Глобальный подписчик на install-события.

    Задачи:
    - не терять install_task_log даже если UI-окно не создано/не подписано
    - показывать ошибки установки (TASK_FAILED) через GUI.SHOW_ERROR_MESSAGE
    """

    def __init__(self, *, max_lines_per_task: int = 300):
        self.event_bus = get_event_bus()
        self._max_lines = int(max(50, max_lines_per_task))

        self._logs = defaultdict(lambda: deque(maxlen=self._max_lines))
        self._last_failed_ts = 0.0

        self._subscribe()

    def _subscribe(self):
        eb = self.event_bus
        eb.subscribe(Events.Install.TASK_LOG, self._on_task_log, weak=False)
        eb.subscribe(Events.Install.TASK_FAILED, self._on_task_failed, weak=False)

    def _on_task_log(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        task_id = str(data.get("task_id") or data.get("id") or data.get("uid") or "").strip()

        msg = data.get("message")
        if msg is None:
            msg = data.get("log")
        if msg is None:
            msg = data.get("text")
        if msg is None:
            msg = ""

        if isinstance(msg, (list, tuple)):
            lines = [str(x) for x in msg if x is not None]
        else:
            lines = [str(msg)]

        level = str(data.get("level") or "info").strip().lower()

        for line in lines:
            line = str(line).rstrip("\n")
            if not line.strip():
                continue

            if task_id:
                self._logs[task_id].append(line)

            prefix = f"[INSTALL {task_id}] " if task_id else "[INSTALL] "
            text = prefix + line

            if level in ("error", "exception", "critical"):
                logger.error(text)
            elif level in ("warn", "warning"):
                logger.warning(text)
            elif level in ("success",):
                logger.success(text)
            else:
                logger.info(text)

    def _on_task_failed(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        task_id = str(data.get("task_id") or data.get("id") or "").strip()
        title = str(data.get("title") or "Install failed")

        err = data.get("error")
        if err is None:
            err = data.get("message")
        err = str(err or "").strip()

        # анти-спам (на случай нескольких TASK_FAILED подряд)
        now = time.time()
        if (now - float(self._last_failed_ts or 0.0)) < 0.4:
            return
        self._last_failed_ts = now

        tail = ""
        if task_id and self._logs.get(task_id):
            last_lines = list(self._logs[task_id])[-20:]
            tail = "\n".join(last_lines).strip()

        message = ""
        if err:
            message += err
        if tail:
            message += ("\n\n--- LOG ---\n" + tail) if message else ("--- LOG ---\n" + tail)
        if not message:
            message = "Unknown install error"

        self.event_bus.emit(Events.GUI.SHOW_ERROR_MESSAGE, {
            "title": title,
            "message": message
        })