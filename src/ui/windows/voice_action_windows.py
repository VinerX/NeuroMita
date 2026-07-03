from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QProgressBar,
    QApplication, QWidget, QPushButton, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QTime
from PyQt6.QtGui import QFont, QTextCursor, QGuiApplication
from utils import getTranslationVariant as _

import re
from html import escape as html_escape
from main_logger import logger
from collections import deque

# Широкий регэксп: чистит и CSI-последовательности (\x1b[...),
# и одиночные ESC-последовательности (\x1bX), и OSC/прочие escape-формы.
ANSI_RE = re.compile(r'\x1b(?:\[.*?[@-~]|\].*?(?:\x1b\\|\x07))')


def strip_ansi(s: str) -> str:
    """Удаляет ANSI escape-коды из строки."""
    if not s:
        return ""
    return ANSI_RE.sub('', s)


class VoiceInstallationWindow(QDialog):
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    log_updated = pyqtSignal(str)
    window_closed = pyqtSignal()
    minimized = pyqtSignal()

    def __init__(self, parent, title, initial_status=None, *, style_variant: str = "default", reopen_hint_text: str | None = None):
        super().__init__(parent)
        # Пока установка идёт, закрытие окна не отменяет её — окно просто
        # прячется (логи сохраняются), и его можно открыть снова. Реальное
        # закрытие происходит только после finalize() (задача завершена).
        self._finished = False
        self.setWindowTitle(title)
        self.setMinimumSize(720, 420)
        self.resize(820, 520)
        self.setModal(True)
        self.setSizeGripEnabled(True)

        self._style_variant = str(style_variant or "default").strip().lower()
        if self._style_variant == "ai_hub":
            self.setObjectName("AIHubInstallDialog")
            self._snapshot_bg = "#0b0c14"
            self._snapshot_border = "#252236"
            self._snapshot_fg = "#d8d2e4"
            # Эталонная сине-серая гамма (#0A0A18 / #252236), розовый — только на
            # заполнении прогресс-бара. Раньше тут был фиолетовый набор бордюров
            # (#3b2748/#4d335c/#5c3b6d), выбивавшийся из остального UI (фидбэк Артёма).
            self.setStyleSheet("""
                QDialog#AIHubInstallDialog {
                    background-color: #0d0e1c;
                    border: 1px solid #252236;
                }
                QLabel {
                    color: #f3edf6;
                }
                QTextEdit {
                    background-color: #07070f;
                    color: #d8d2e4;
                    border: 1px solid #252236;
                    border-radius: 10px;
                    padding: 8px;
                }
                QProgressBar {
                    border: 1px solid #252236;
                    border-radius: 7px;
                    background-color: #14121f;
                    text-align: center;
                }
                QProgressBar::chunk {
                    background-color: #b74b7d;
                    border-radius: 7px;
                }
                QPushButton {
                    background-color: #181826;
                    color: #f3edf6;
                    border: 1px solid #252236;
                    border-radius: 10px;
                    padding: 7px 12px;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: #20202f;
                    border-color: #3a3750;
                }
            """)
        else:
            self._snapshot_bg = "#14161a"
            self._snapshot_border = "#30343a"
            self._snapshot_fg = "#cfe4ff"
            self.setStyleSheet("""
                QDialog { background-color: #1e1e1e; }
                QLabel { color: #ffffff; }
                QTextEdit {
                    background-color: #101010;
                    color: #cccccc;
                    border: 1px solid #333;
                }
                QProgressBar {
                    border: 1px solid #555;
                    border-radius: 5px;
                    background-color: #555555;
                    text-align: center;
                }
                QProgressBar::chunk {
                    background-color: #b74b7d;
                    border-radius: 5px;
                }
                QPushButton {
                    background-color: #333333;
                    color: #ffffff;
                    border: none;
                    padding: 5px 10px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #555555; }
            """)

        self._full_log_lines: list[str] = []
        self._display_lines: deque[str] = deque()
        self._max_display_blocks: int = 200
        self._snapshot_lines: list[str] = []

        self._start_time = QTime.currentTime()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._elapsed_timer.start()

        layout = QVBoxLayout(self)

        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        info_layout = QHBoxLayout()
        self.status_label = QLabel(initial_status or _("Подготовка...", "Preparing..."))
        self.status_label.setFont(QFont("Segoe UI", 9))
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(self.status_label, 2)

        self.progress_value_label = QLabel("0%")
        self.progress_value_label.setFont(QFont("Segoe UI", 9))
        info_layout.addWidget(self.progress_value_label, 0)

        self.eta_label = QLabel("ETA --:--")
        self.eta_label.setFont(QFont("Segoe UI", 9))
        self.eta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(self.eta_label, 0)

        self.elapsed_label = QLabel(_("Прошло 00:00", "Elapsed 00:00"))
        self.elapsed_label.setFont(QFont("Segoe UI", 9))
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        info_layout.addWidget(self.elapsed_label, 0)

        layout.addLayout(info_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        self.progress_value_label.setText("...")

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_text, 1)

        hint_text = reopen_hint_text or _(
            "Это окно можно закрыть — установка продолжится в фоне. "
            "Открыть снова и посмотреть логи: «Логи установки» в боковой панели.",
            "You can close this window — the installation keeps running in the "
            "background. Reopen it and view logs via “Install logs” in the sidebar.",
        )
        hint_label = QLabel(hint_text)
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        layout.addWidget(hint_label)

        actions_layout = QHBoxLayout()
        copy_btn = QPushButton(_("Копировать лог", "Copy Log"))
        copy_btn.clicked.connect(self._copy_log)
        actions_layout.addWidget(copy_btn)

        save_btn = QPushButton(_("Сохранить лог...", "Save Log..."))
        save_btn.clicked.connect(self._save_log)
        actions_layout.addWidget(save_btn)

        clear_btn = QPushButton(_("Очистить", "Clear"))
        clear_btn.setToolTip(_("Очищает только экран, полный лог сохраняется", "Clears screen only, full log remains"))
        clear_btn.clicked.connect(self._clear_log_screen_only)
        actions_layout.addWidget(clear_btn)

        actions_layout.addStretch()

        close_btn = QPushButton(_("Закрыть", "Close"))
        close_btn.clicked.connect(self.close)
        actions_layout.addWidget(close_btn)
        layout.addLayout(actions_layout)

        # ВАЖНО: queued, чтобы UI обновлялся в UI-треде даже если emit из фонового потока
        self.progress_updated.connect(self._on_progress_update, type=Qt.ConnectionType.QueuedConnection)
        self.status_updated.connect(self._on_status_update, type=Qt.ConnectionType.QueuedConnection)
        self.log_updated.connect(self._on_log_update, type=Qt.ConnectionType.QueuedConnection)

        if parent and hasattr(parent, 'geometry'):
            parent_rect = parent.geometry()
            self.move(
                parent_rect.center().x() - self.width() // 2,
                parent_rect.center().y() - self.height() // 2
            )

        self._style_polished = False
        self._polish_styles()
        QTimer.singleShot(0, self._recalc_max_blocks_and_refresh)
        QTimer.singleShot(0, self._polish_styles)

    def get_threadsafe_callbacks(self):
        return (
            self.progress_updated.emit,
            self.status_updated.emit,
            self.log_updated.emit,
        )

    def showEvent(self, event):
        super().showEvent(event)
        if not self._style_polished:
            self._polish_styles()

    def _polish_styles(self):
        widgets = [self, *self.findChildren(QWidget)]
        for widget in widgets:
            try:
                widget.ensurePolished()
                style = widget.style()
                if style is not None:
                    style.unpolish(widget)
                    style.polish(widget)
                widget.update()
            except Exception:
                continue
        self._style_polished = True
     
    def _update_elapsed(self):
        secs = self._start_time.secsTo(QTime.currentTime())
        if secs < 0:
            secs = 0
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        text = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        self.elapsed_label.setText(_("Прошло ", "Elapsed ") + text)

    def _recalc_max_blocks_and_refresh(self):
        fm = self.log_text.fontMetrics()
        line_h = max(1, fm.lineSpacing())
        vp_h = max(1, self.log_text.viewport().height())
        # 90% от видимой высоты в строках, минимум 20
        new_max = max(20, int((vp_h / line_h) * 0.9))
        changed = (new_max != self._max_display_blocks)
        self._max_display_blocks = new_max
        if changed:
            self._rebuild_display_from_full()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalc_max_blocks_and_refresh()

    def _on_progress_update(self, value: int):
        value = max(0, min(100, int(value)))
        if value <= 0:
            if self.progress_bar.minimum() != 0 or self.progress_bar.maximum() != 0:
                self.progress_bar.setRange(0, 0)
            self.progress_value_label.setText("...")
            return
        if self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)
        self.progress_value_label.setText(f"{value}%")

    def _on_status_update(self, message: str):
        message = strip_ansi(message)
        self.status_label.setText(message)
        # Вынимаем ETA из сообщения, если есть
        m = re.search(r'KATEX_INLINE_OPEN\s*ETA\s+([^)]+)KATEX_INLINE_CLOSE', message, flags=re.IGNORECASE)
        if m:
            self.eta_label.setText(f"ETA {m.group(1)}")
        elif any(k in message.lower() for k in ("завершено", "complete", "done")):
            self.eta_label.setText("ETA 00:00")

    def _colorize_line(self, plain: str) -> str:
        """Окраска строки для отображения (HTML). plain уже без ANSI."""
        low = plain.lower()
        if any(w in low for w in ("error", "ошибка", "failed", "traceback", "exception", "critical")):
            return f'<span style="color:#ff5555;">{html_escape(plain)}</span>'
        elif any(w in low for w in ("warning", "предупреж", "warn")):
            return f'<span style="color:#ffb86c;">{html_escape(plain)}</span>'
        else:
            return html_escape(plain)

    def _render_display_lines(self):
        scrollbar = self.log_text.verticalScrollBar()
        old_value = scrollbar.value()
        stick_to_bottom = old_value >= max(0, scrollbar.maximum() - 12)
        # Формируем HTML из текущего окна строк
        snapshot_html = ""
        if self._snapshot_lines:
            snapshot_html = (
                f"<div style='margin:8px 0 0 0; padding:6px; background:{self._snapshot_bg}; "
                f"border:1px solid {self._snapshot_border}; border-radius:6px;'>"
                "<pre style='font-family:Consolas,monospace; font-size:9pt; "
                f"margin:0; color:{self._snapshot_fg};'>"
                + html_escape("\n".join(self._snapshot_lines))
                + "</pre></div>"
            )
        html = (
            "<div style='white-space: pre-wrap; font-family:Consolas,monospace; font-size:9pt; margin:0;'>"
            + "<br/>".join(self._display_lines) +
            "</div>"
            + snapshot_html
        )
        self.log_text.setHtml(html)
        if stick_to_bottom:
            self.log_text.moveCursor(QTextCursor.MoveOperation.End)
            self.log_text.ensureCursorVisible()
        else:
            scrollbar.setValue(min(old_value, scrollbar.maximum()))

    def _render_snapshot(self, lines: list[str]):
        self._snapshot_lines = list(lines)
        self._render_display_lines()

    def _append_log_chunk(self, text: str):
        if not text:
            return
        # Разбиваем на строки, добавляем в full, поддерживаем окно последних строк
        for ln in text.splitlines():
            plain = strip_ansi(ln)
            if not plain.strip():
                continue
            self._full_log_lines.append(plain)
            colored = self._colorize_line(plain)
            self._display_lines.append(colored)
            while len(self._display_lines) > self._max_display_blocks:
                self._display_lines.popleft()
        self._render_display_lines()

    def _rebuild_display_from_full(self):
        # Берём последние N строк из полного лога и пересобираем окно
        if not self._full_log_lines:
            self._display_lines.clear()
            self._render_display_lines()
            return
        last = self._full_log_lines[-self._max_display_blocks:]
        self._display_lines = deque((self._colorize_line(s) for s in last), maxlen=self._max_display_blocks)
        self._render_display_lines()

    def _on_log_update(self, text: str):
        if text.startswith("__SNAPSHOT_START__"):
            in_snapshot = False
            lines: list[str] = []
            for line in text.splitlines():
                if line == "__SNAPSHOT_START__":
                    in_snapshot = True
                    continue
                if line == "__SNAPSHOT_END__":
                    in_snapshot = False
                    continue
                if in_snapshot:
                    clean = strip_ansi(line).replace("\x1b", "")
                    if clean.strip():
                        lines.append(clean)
            self._render_snapshot(lines)
            return
        # Окно показа — только последние строки, но полный лог сохраняем отдельно
        self._append_log_chunk(text)

    def _copy_log(self):
        QGuiApplication.clipboard().setText("\n".join(self._full_log_lines) or "")

    def _save_log(self):
        fname, _selected_filter = QFileDialog.getSaveFileName(self, _("Сохранить лог", "Save Log"), "install_log.txt", "Text Files (*.txt)")
        if fname:
            try:
                with open(fname, "w", encoding="utf-8") as f:
                    f.write("\n".join(self._full_log_lines))
            except Exception as ex:
                logger.error(f"Не удалось сохранить лог: {ex}")

    def _clear_log_screen_only(self):
        # Очистка только видимой области; полный лог остаётся для копирования/сохранения
        self._display_lines.clear()
        self._render_display_lines()

    def finalize(self):
        """Mark the task as finished so the window may actually close."""
        self._finished = True

    def closeEvent(self, event):
        # While the task is still running, closing only hides the window (the
        # install keeps going and the accumulated logs are preserved so the
        # user can reopen it). A real close happens once finalize() was called.
        if not self._finished:
            event.ignore()
            self.hide()
            self.minimized.emit()
            return
        self.window_closed.emit()
        super().closeEvent(event)

    def update_progress(self, value: int):
        self.progress_updated.emit(value)

    def update_status(self, message: str):
        self.status_updated.emit(message)

    def update_log(self, text: str):
        self.log_updated.emit(text)


class VoiceActionWindow(QDialog):
    status_updated = pyqtSignal(str)
    log_updated = pyqtSignal(str)
    window_closed = pyqtSignal()

    def get_threadsafe_callbacks(self):
        return (
            lambda *_: None,
            self.status_updated.emit,
            self.log_updated.emit
        )

    def __init__(self, parent, title, initial_status=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(700, 380)
        self.resize(780, 460)
        self.setModal(True)
        self.setSizeGripEnabled(True)

        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QLabel { color: #ffffff; }
            QTextEdit {
                background-color: #101010;
                color: #cccccc;
                border: 1px solid #333;
            }
            QPushButton {
                background-color: #333333;
                color: #ffffff;
                border: none;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #555555; }
        """)

        self._full_log_lines: list[str] = []
        self._display_lines: deque[str] = deque()
        self._max_display_blocks: int = 200
        self._snapshot_lines: list[str] = []

        self._start_time = QTime.currentTime()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._elapsed_timer.start()

        layout = QVBoxLayout(self)

        title_label = QLabel(title)
        title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        info_layout = QHBoxLayout()
        self.status_label = QLabel(initial_status or _("Подготовка...", "Preparing..."))
        self.status_label.setFont(QFont("Segoe UI", 9))
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(self.status_label, 2)

        self.eta_label = QLabel("ETA --:--")
        self.eta_label.setFont(QFont("Segoe UI", 9))
        info_layout.addWidget(self.eta_label, 0)

        self.elapsed_label = QLabel(_("Прошло 00:00", "Elapsed 00:00"))
        self.elapsed_label.setFont(QFont("Segoe UI", 9))
        info_layout.addWidget(self.elapsed_label, 0)

        layout.addLayout(info_layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_text, 1)

        actions_layout = QHBoxLayout()
        copy_btn = QPushButton(_("Копировать лог", "Copy Log"))
        copy_btn.clicked.connect(self._copy_log)
        actions_layout.addWidget(copy_btn)

        save_btn = QPushButton(_("Сохранить лог...", "Save Log..."))
        save_btn.clicked.connect(self._save_log)
        actions_layout.addWidget(save_btn)

        clear_btn = QPushButton(_("Очистить", "Clear"))
        clear_btn.setToolTip(_("Очищает только экран, полный лог сохраняется", "Clears screen only, full log remains"))
        clear_btn.clicked.connect(self._clear_log_screen_only)
        actions_layout.addWidget(clear_btn)

        actions_layout.addStretch()

        close_btn = QPushButton(_("Закрыть", "Close"))
        close_btn.clicked.connect(self.close)
        actions_layout.addWidget(close_btn)
        layout.addLayout(actions_layout)

        # ВАЖНО: queued, чтобы UI обновлялся в UI-треде
        self.status_updated.connect(self._on_status_update, type=Qt.ConnectionType.QueuedConnection)
        self.log_updated.connect(self._on_log_update, type=Qt.ConnectionType.QueuedConnection)

        if parent and hasattr(parent, 'geometry'):
            parent_rect = parent.geometry()
            self.move(
                parent_rect.center().x() - self.width() // 2,
                parent_rect.center().y() - self.height() // 2
            )

        QTimer.singleShot(0, self._recalc_max_blocks_and_refresh)
    
    def _update_elapsed(self):
        secs = self._start_time.secsTo(QTime.currentTime())
        if secs < 0:
            secs = 0
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        text = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
        self.elapsed_label.setText(_("Прошло ", "Elapsed ") + text)

    def _recalc_max_blocks_and_refresh(self):
        fm = self.log_text.fontMetrics()
        line_h = max(1, fm.lineSpacing())
        vp_h = max(1, self.log_text.viewport().height())
        new_max = max(20, int((vp_h / line_h) * 0.9))
        changed = (new_max != self._max_display_blocks)
        self._max_display_blocks = new_max
        if changed:
            self._rebuild_display_from_full()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalc_max_blocks_and_refresh()

    def _on_status_update(self, message: str):
        message = strip_ansi(message)
        self.status_label.setText(message)
        m = re.search(r'KATEX_INLINE_OPEN\s*ETA\s+([^)]+)KATEX_INLINE_CLOSE', message, flags=re.IGNORECASE)
        if m:
            self.eta_label.setText(f"ETA {m.group(1)}")
        elif any(k in message.lower() for k in ("завершено", "complete", "done")):
            self.eta_label.setText("ETA 00:00")

    def _colorize_line(self, plain: str) -> str:
        low = plain.lower()
        if any(w in low for w in ("error", "ошибка", "failed", "traceback", "exception", "critical")):
            return f'<span style="color:#ff5555;">{html_escape(plain)}</span>'
        elif any(w in low for w in ("warning", "предупреж", "warn")):
            return f'<span style="color:#ffb86c;">{html_escape(plain)}</span>'
        else:
            return html_escape(plain)

    def _render_display_lines(self):
        scrollbar = self.log_text.verticalScrollBar()
        old_value = scrollbar.value()
        stick_to_bottom = old_value >= max(0, scrollbar.maximum() - 12)
        snapshot_html = ""
        if self._snapshot_lines:
            snapshot_html = (
                "<div style='margin:8px 0 0 0; padding:6px; background:#14161a; "
                "border:1px solid #30343a; border-radius:6px;'>"
                "<pre style='font-family:Consolas,monospace; font-size:9pt; "
                "margin:0; color:#cfe4ff;'>"
                + html_escape("\n".join(self._snapshot_lines))
                + "</pre></div>"
            )
        html = (
            "<div style='white-space: pre-wrap; font-family:Consolas,monospace; font-size:9pt; margin:0;'>"
            + "<br/>".join(self._display_lines) +
            "</div>"
            + snapshot_html
        )
        self.log_text.setHtml(html)
        if stick_to_bottom:
            self.log_text.moveCursor(QTextCursor.MoveOperation.End)
            self.log_text.ensureCursorVisible()
        else:
            scrollbar.setValue(min(old_value, scrollbar.maximum()))

    def _render_snapshot(self, lines: list[str]):
        self._snapshot_lines = list(lines)
        self._render_display_lines()

    def _append_log_chunk(self, text: str):
        if not text:
            return
        for ln in text.splitlines():
            plain = strip_ansi(ln)
            if not plain.strip():
                continue
            self._full_log_lines.append(plain)
            colored = self._colorize_line(plain)
            self._display_lines.append(colored)
            while len(self._display_lines) > self._max_display_blocks:
                self._display_lines.popleft()
        self._render_display_lines()

    def _rebuild_display_from_full(self):
        if not self._full_log_lines:
            self._display_lines.clear()
            self._render_display_lines()
            return
        last = self._full_log_lines[-self._max_display_blocks:]
        self._display_lines = deque((self._colorize_line(s) for s in last), maxlen=self._max_display_blocks)
        self._render_display_lines()

    def _on_log_update(self, text: str):
        if text.startswith("__SNAPSHOT_START__"):
            in_snapshot = False
            lines: list[str] = []
            for line in text.splitlines():
                if line == "__SNAPSHOT_START__":
                    in_snapshot = True
                    continue
                if line == "__SNAPSHOT_END__":
                    in_snapshot = False
                    continue
                if in_snapshot:
                    clean = strip_ansi(line).replace("\x1b", "")
                    if clean.strip():
                        lines.append(clean)
            self._render_snapshot(lines)
            return
        self._append_log_chunk(text)

    def _copy_log(self):
        QGuiApplication.clipboard().setText("\n".join(self._full_log_lines) or "")

    def _save_log(self):
        fname, _selected_filter = QFileDialog.getSaveFileName(self, _("Сохранить лог", "Save Log"), "action_log.txt", "Text Files (*.txt)")
        if fname:
            try:
                with open(fname, "w", encoding="utf-8") as f:
                    f.write("\n".join(self._full_log_lines))
            except Exception as ex:
                logger.error(f"Не удалось сохранить лог: {ex}")

    def _clear_log_screen_only(self):
        self._display_lines.clear()
        self._display_lines = deque()
        self._render_display_lines()

    def closeEvent(self, event):
        self.window_closed.emit()
        super().closeEvent(event)

    def update_status(self, message: str):
        self.status_updated.emit(message)

    def update_log(self, text: str):
        self.log_updated.emit(text)


class VCRedistWarningDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("⚠️ Ошибка загрузки Triton", "⚠️ Triton Load Error"))
        self.setModal(True)
        self.setMinimumSize(500, 250)
        
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QLabel { color: #ffffff; }
            QPushButton {
                background-color: #333333;
                color: #ffffff;
                border: none;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #555555; }
            #RetryButton { background-color: #b74b7d; }
            #RetryButton:hover { background-color: #c04c80; }
        """)
        
        self.choice = 'close'
        
        layout = QVBoxLayout(self)
        
        title_label = QLabel(_("Ошибка импорта Triton (DLL Load Failed)", "Triton Import Error (DLL Load Failed)"))
        title_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title_label.setStyleSheet("color: orange;")
        layout.addWidget(title_label)
        
        info_text = _(
            "Не удалось загрузить библиотеку для Triton (возможно, отсутствует VC++ Redistributable).\n"
            "Установите последнюю версию VC++ Redistributable (x64) с сайта Microsoft\n"
            "или попробуйте импортировать снова, если вы только что его установили.",
            "Failed to load the library for Triton (VC++ Redistributable might be missing).\n"
            "Install the latest VC++ Redistributable (x64) from the Microsoft website\n"
            "or try importing again if you just installed it."
        )
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        layout.addStretch()
        
        button_layout = QHBoxLayout()
        
        docs_button = QPushButton(_("Документация", "Documentation"))
        docs_button.clicked.connect(self._on_docs_clicked)
        button_layout.addWidget(docs_button)
        
        button_layout.addStretch()
        
        close_button = QPushButton(_("Закрыть", "Close"))
        close_button.clicked.connect(lambda: self._set_choice_and_accept('close'))
        button_layout.addWidget(close_button)
        
        retry_button = QPushButton(_("Попробовать снова", "Retry"))
        retry_button.setObjectName("RetryButton")
        retry_button.clicked.connect(lambda: self._set_choice_and_accept('retry'))
        button_layout.addWidget(retry_button)
        
        layout.addLayout(button_layout)
    
    def _on_docs_clicked(self):
        from core.events import get_event_bus, Events
        get_event_bus().emit(Events.VoiceModel.OPEN_DOC, "installation_guide.html#vc_redist")
    
    def _set_choice_and_accept(self, choice):
        self.choice = choice
        self.accept()
    
    def get_choice(self):
        return self.choice


class TritonDependenciesDialog(QDialog):
    def __init__(self, parent=None, dependencies_status=None):
        super().__init__(parent)
        self.setWindowTitle(_("⚠️ Зависимости Triton", "⚠️ Triton Dependencies"))
        self.setModal(True)
        self.setMinimumSize(700, 350)

        # Эталонная сине-серая гамма (как остальной UI), а не старый плоский #1e1e1e
        # (фидбэк Артёма: «окошко не в том оформлении как все»).
        self.setObjectName("TritonDependenciesDialog")
        self.setStyleSheet("""
            QDialog#TritonDependenciesDialog {
                background-color: #0d0e1c;
                border: 1px solid #252236;
            }
            QLabel { color: #f3edf6; }
            QPushButton {
                background-color: #181826;
                color: #f3edf6;
                border: 1px solid #252236;
                border-radius: 10px;
                padding: 7px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #20202f;
                border-color: #3a3750;
            }
            #ContinueButton {
                background-color: #b74b7d;
                border: 1px solid #823858;
            }
            #ContinueButton:hover { background-color: #c04c80; }
        """)
        
        self.choice = 'skip'
        self.dependencies_status = dependencies_status or {}
        
        layout = QVBoxLayout(self)
        
        title_label = QLabel(_("Статус зависимостей Triton:", "Triton Dependency Status:"))
        title_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        self.status_layout = QHBoxLayout()
        self._update_status_display()
        layout.addLayout(self.status_layout)
        
        self.warning_label = QLabel(_("⚠️ Для компиляции ядра Triton нужен MSVC (VC++ Build Tools)!",
                                     "⚠️ Triton kernel compilation requires MSVC (VC++ Build Tools)!"))
        self.warning_label.setStyleSheet("color: orange; font-weight: bold;")
        # CUDA Toolkit больше не является обязательным требованием (фидбэк Артёма):
        # для линковки ядра достаточно MSVC/VC++. Предупреждение зависит только от MSVC.
        msvc_found = self.dependencies_status.get('msvc_found', False)
        self.warning_label.setVisible(not msvc_found)
        layout.addWidget(self.warning_label)
        
        info_text = _(
            "Если компоненты не найдены, установите их согласно документации.\n"
            "Вы также можете попробовать инициализировать модель вручную,\n"
            "запустив `init_triton.bat` в корневой папке программы.",
            "If components are not found, install them according to the documentation.\n"
            "You can also try initializing the model manually\n"
            "by running `init_triton.bat` in the program's root folder."
        )
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        layout.addStretch()
        
        button_layout = QHBoxLayout()
        
        docs_button = QPushButton(_("Открыть документацию", "Open Documentation"))
        docs_button.clicked.connect(self._on_docs_clicked)
        button_layout.addWidget(docs_button)
        
        refresh_button = QPushButton(_("Обновить статус", "Refresh Status"))
        refresh_button.clicked.connect(self._on_refresh_status)
        button_layout.addWidget(refresh_button)
        
        button_layout.addStretch()
        
        skip_button = QPushButton(_("Пропустить инициализацию", "Skip Initialization"))
        skip_button.clicked.connect(lambda: self._set_choice_and_accept('skip'))
        button_layout.addWidget(skip_button)
        
        continue_button = QPushButton(_("Продолжить инициализацию", "Continue Initialization"))
        continue_button.setObjectName("ContinueButton")
        continue_button.clicked.connect(lambda: self._set_choice_and_accept('continue'))
        button_layout.addWidget(continue_button)
        
        layout.addLayout(button_layout)
    
    def _update_status_display(self):
        while self.status_layout.count():
            item = self.status_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # CUDA убран из обязательных требований (фидбэк Артёма) — для компиляции
        # ядра Triton нужен только MSVC/VC++. Windows SDK оставляем как
        # вспомогательную информацию, CUDA больше не показываем.
        items = [
            ("MSVC (VC++):", self.dependencies_status.get('msvc_found', False)),
            ("Windows SDK:", self.dependencies_status.get('winsdk_found', False)),
        ]
        
        for text, found in items:
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(0, 0, 15, 0)
            
            label = QLabel(text)
            label.setFont(QFont("Segoe UI", 9))
            item_layout.addWidget(label)
            
            status_text = _("Найден", "Found") if found else _("Не найден", "Not Found")
            status_color = "#4CAF50" if found else "#F44336"
            status_label = QLabel(status_text)
            status_label.setFont(QFont("Segoe UI", 9))
            status_label.setStyleSheet(f"color: {status_color};")
            item_layout.addWidget(status_label)
            
            self.status_layout.addWidget(item_widget)
        
        self.status_layout.addStretch()
        
        if hasattr(self, 'warning_label'):
            msvc_found = self.dependencies_status.get('msvc_found', False)
            self.warning_label.setVisible(not msvc_found)
    
    def _on_refresh_status(self):
        from core.events import get_event_bus, Events
        event_bus = get_event_bus()
        
        results = event_bus.emit_and_wait(Events.Audio.REFRESH_TRITON_STATUS, timeout=5.0)
        if results and results[0]:
            self.dependencies_status = results[0]
            self._update_status_display()
    
    def _on_docs_clicked(self):
        from core.events import get_event_bus, Events
        get_event_bus().emit(Events.VoiceModel.OPEN_DOC, "installation_guide.html")
    
    def _set_choice_and_accept(self, choice):
        self.choice = choice
        self.accept()
    
    def get_choice(self):
        return self.choice
