from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel, QFrame, QPlainTextEdit, QVBoxLayout, QWidget

from ui.widgets.launcher_dashboard_helpers import DashboardAction, create_logs_page
from utils import _


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
        self._logs_timer.start()

        self.logs_window = None
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._sync_host_exports()
        self._build_ui()
        QTimer.singleShot(0, self.refresh_logs)

    def _sync_host_exports(self):
        self.gui.logs_page = self

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
                "Последние строки лог-файла, обновляются раз в 2 секунды и при переходе на страницу.",
                "Latest lines from the log file, refreshed every 2 seconds and when the page opens.",
            )
        )
        subtitle.setObjectName("LauncherShellMeta")
        subtitle.setWordWrap(True)
        card_layout.addWidget(subtitle)

        self.logs_window = QPlainTextEdit()
        self.logs_window.setObjectName("DebugWindow")
        self.logs_window.setReadOnly(True)
        self.logs_window.setMinimumHeight(420)
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
        self.gui.switch_main_page("sandbox")
        page = getattr(self.gui, "sandbox_page", None)
        if page is not None and hasattr(page, "show_debug_tab"):
            QTimer.singleShot(0, page.show_debug_tab)

    def refresh_logs(self):
        if self.logs_window is None:
            return

        log_path = Path("NeuroMitaLogs.log")
        try:
            if not log_path.exists():
                self.logs_window.setPlainText(_("Файл логов пока не создан.", "Log file does not exist yet."))
                return
            text = log_path.read_text(encoding="utf-8", errors="replace")
            tail = "\n".join(text.splitlines()[-500:])
        except Exception as exc:
            tail = _("Не удалось прочитать лог: {err}", "Failed to read log: {err}").format(err=exc)

        scrollbar = self.logs_window.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        self.logs_window.setPlainText(tail)
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def on_activated(self):
        self.gui.update_debug_info()
        self.refresh_logs()


def build_logs_page(window) -> QWidget:
    return LogsPage(window)
