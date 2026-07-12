from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from ui.pages.logs_presentation import (
    LogsPageState,
    LogsShowError,
    OpenLogsFolder,
    RefreshLogs,
)
from utils import getTranslationVariant as _


_LOG_TAIL_BYTES = 64 * 1024
_LOG_TAIL_LINES = 500


class LogsPageViewModel(IntentViewModel[LogsPageState]):
    def __init__(self, parent=None) -> None:
        super().__init__(LogsPageState(), parent)

    def dispatch(self, intent: Any) -> None:
        if self.is_closed:
            return
        if isinstance(intent, RefreshLogs):
            self._refresh()
        elif isinstance(intent, OpenLogsFolder):
            self._open_folder()

    def _refresh(self) -> None:
        self.update_state(loading=True)
        self.run_coalesced(
            "logs-tail",
            self._read_tail,
            lambda text: self.set_state(LogsPageState(text=str(text), loading=False)),
            self._on_read_error,
        )

    @staticmethod
    def _read_tail() -> str:
        path = Path("NeuroMitaLogs.log")
        if not path.exists():
            return _("Файл логов пока не создан.", "Log file does not exist yet.")
        with path.open("rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            read_from = max(0, file_size - _LOG_TAIL_BYTES)
            handle.seek(read_from)
            chunk = handle.read(_LOG_TAIL_BYTES)
        text = chunk.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if read_from > 0 and lines:
            lines = lines[1:]
        return "\n".join(lines[-_LOG_TAIL_LINES:])

    def _on_read_error(self, exc: Exception) -> None:
        self.set_state(
            LogsPageState(
                text=_(
                    "Не удалось прочитать лог: {err}",
                    "Failed to read log: {err}",
                ).format(err=exc),
                loading=False,
            )
        )

    def _open_folder(self) -> None:
        path = Path("NeuroMitaLogs.log")
        target = path.resolve().parent if path.exists() else Path.cwd()
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]  # Windows-only
        except Exception as exc:
            self.emit_effect(
                LogsShowError(
                    _("Ошибка", "Error"),
                    str(exc),
                )
            )