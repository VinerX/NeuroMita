from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRegularExpression, QTimer
from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import QLabel, QFrame, QPlainTextEdit, QVBoxLayout, QWidget

from ui.widgets.launcher_dashboard_helpers import DashboardAction, create_logs_page
from utils import _

_LOG_TAIL_BYTES = 64 * 1024
_LOG_TAIL_LINES = 500


_LOG_LEVEL_COLORS: dict[str, str] = {
    "DEBUG":    "#888888",
    "PROGRESS": "#87CEEB",
    "INFO":     "#E0E0E0",
    "NOTIFY":   "#E8C8F0",
    "WARNING":  "#FFD700",
    "SUCCESS":  "#90EE90",
    "ERROR":    "#FF6B6B",
    "CRITICAL": "#FF4444",
}

_LOG_LEVEL_BOLD: set[str] = {
    "CRITICAL",
}

_LOG_LEVEL_BG: dict[str, str] = {
    "CRITICAL": "#770000",
}


class _LogHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._default_fmt = QTextCharFormat()
        self._default_fmt.setForeground(QColor("#BBBBBB"))
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        for level, color in _LOG_LEVEL_COLORS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if level in _LOG_LEVEL_BOLD:
                fmt.setFontWeight(QFont.Weight.Bold)
            if level in _LOG_LEVEL_BG:
                fmt.setBackground(QColor(_LOG_LEVEL_BG[level]))
            rx = QRegularExpression(f"- +{level}\\b")
            self._rules.append((rx, fmt))

    def highlightBlock(self, text: str) -> None:
        self.setFormat(0, len(text), self._default_fmt)
        for rx, fmt in self._rules:
            m = rx.match(text)
            if m.hasMatch():
                self.setFormat(0, len(text), fmt)
                return


def _append_to_shell_page(page: QWidget, widget: QWidget) -> None:
    content_widget = page.findChild(QWidget, "LauncherShellPage")
    if content_widget is None or content_widget.layout() is None:
        return

    layout = content_widget.layout()
    insert_index = max(0, layout.count() - 1)
    layout.insertWidget(insert_index, widget)


class LogsPage(QWidget):
    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self.setObjectName("LogsPage")

        self._logs_timer = QTimer(self)
        self._logs_timer.setInterval(2000)
        self._logs_timer.timeout.connect(self.refresh_logs)
        self._last_tail = None

        self.logs_window = None
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._sync_host_exports()
        self._build_ui()

    def _sync_host_exports(self):
        self.gui.logs_page = self

    def _is_active(self) -> bool:
        return getattr(self.gui, "current_main_page", None) == "logs"

    def _read_log_tail(self, log_path: Path) -> str:
        with log_path.open("rb") as handle:
            handle.seek(0, 2)
            file_size = handle.tell()
            read_from = max(0, file_size - _LOG_TAIL_BYTES)
            handle.seek(read_from)
            chunk = handle.read()

        text = chunk.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if read_from > 0 and lines:
            lines = lines[1:]
        return "\n".join(lines[-_LOG_TAIL_LINES:])

    def _build_live_stream_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(10)

        title = QLabel(_("Живой поток", "Live stream"))
        title.setObjectName("LauncherShellSectionTitle")
        card_layout.addWidget(title)

        subtitle = QLabel(
            _(
                "Последние строки лог-файла. Обновляются раз в 2 секунды только пока открыта страница логов.",
                "Latest lines from the log file. Refreshed every 2 seconds only while the logs page is open.",
            )
        )
        subtitle.setObjectName("LauncherShellMeta")
        subtitle.setWordWrap(True)
        card_layout.addWidget(subtitle)

        self.logs_window = QPlainTextEdit()
        self.logs_window.setObjectName("DebugWindow")
        self.logs_window.setReadOnly(True)
        self.logs_window.setMinimumHeight(420)
        self._log_highlighter = _LogHighlighter(self.logs_window.document())
        card_layout.addWidget(self.logs_window)

        self.gui.logs_window = self.logs_window
        return card

    def _build_ui(self):
        page = create_logs_page(
            title=_("Системные логи", "System logs"),
            subtitle=_(
                "Хвост файла NeuroMitaLogs.log и быстрые действия для отладки.",
                "Tail of NeuroMitaLogs.log plus quick debug actions.",
            ),
            items=[],
            header_actions=[
                DashboardAction(_("Обновить", "Refresh"), callback=self.refresh_logs, icon_name="fa6s.rotate-right"),
                DashboardAction(_("Открыть папку", "Open folder"), callback=self.gui._open_logs_folder, icon_name="fa6s.folder-open", accent=False),
                DashboardAction(_("Диагностика в песочнице", "Sandbox diagnostics"), callback=self._open_sandbox_debug, icon_name="fa6s.bug", accent=False),
            ],
        )
        _append_to_shell_page(page, self._build_live_stream_card())
        self._root_layout.addWidget(page)

    def _open_sandbox_debug(self):
        if self._logs_timer.isActive():
            self._logs_timer.stop()
        self.gui.switch_main_page("sandbox")
        page = getattr(self.gui, "sandbox_page", None)
        if page is not None and hasattr(page, "show_debug_tab"):
            QTimer.singleShot(0, page.show_debug_tab)

    def refresh_logs(self):
        if self.logs_window is None:
            return
        if not self._is_active():
            if self._logs_timer.isActive():
                self._logs_timer.stop()
            return

        log_path = Path("NeuroMitaLogs.log")
        try:
            if not log_path.exists():
                tail = _("Файл логов пока не создан.", "Log file does not exist yet.")
            else:
                tail = self._read_log_tail(log_path)
        except Exception as exc:
            tail = _("Не удалось прочитать лог: {err}", "Failed to read log: {err}").format(err=exc)

        if tail == self._last_tail:
            return

        scrollbar = self.logs_window.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        self.logs_window.setPlainText(tail)
        self._last_tail = tail
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def on_activated(self):
        if not self._logs_timer.isActive():
            self._logs_timer.start()
        self.gui.update_debug_info()
        self.refresh_logs()

    def on_deactivated(self):
        if self._logs_timer.isActive():
            self._logs_timer.stop()


def build_logs_page(window) -> QWidget:
    return LogsPage(window)
