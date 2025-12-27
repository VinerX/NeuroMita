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

    def __init__(self, parent, title, initial_status=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(720, 420)
        self.resize(820, 520)
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
            QProgressBar {
                border: 1px solid #555;
                border-radius: 5px;
                background-color: #555555;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
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
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

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

        QTimer.singleShot(0, self._recalc_max_blocks_and_refresh)

    def get_threadsafe_callbacks(self):
        return (
            self.progress_updated.emit,
            self.status_updated.emit,
            self.log_updated.emit,
        )
    
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
        # Формируем HTML из текущего окна строк
        html = (
            "<div style='white-space: pre-wrap; font-family:Consolas,monospace; font-size:9pt; margin:0;'>"
            + "<br/>".join(self._display_lines) +
            "</div>"
        )
        self.log_text.setHtml(html)
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)
        self.log_text.ensureCursorVisible()

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
        # Окно показа — только последние строки, но полный лог сохраняем отдельно
        self._append_log_chunk(text)

    def _copy_log(self):
        QGuiApplication.clipboard().setText("\n".join(self._full_log_lines) or "")

    def _save_log(self):
        fname, _ = QFileDialog.getSaveFileName(self, _("Сохранить лог", "Save Log"), "install_log.txt", "Text Files (*.txt)")
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

    def closeEvent(self, event):
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
            None,
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
        html = (
            "<div style='white-space: pre-wrap; font-family:Consolas,monospace; font-size:9pt; margin:0;'>"
            + "<br/>".join(self._display_lines) +
            "</div>"
        )
        self.log_text.setHtml(html)
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)
        self.log_text.ensureCursorVisible()

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
        self._append_log_chunk(text)

    def _copy_log(self):
        QGuiApplication.clipboard().setText("\n".join(self._full_log_lines) or "")

    def _save_log(self):
        fname, _ = QFileDialog.getSaveFileName(self, _("Сохранить лог", "Save Log"), "action_log.txt", "Text Files (*.txt)")
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
            #RetryButton { background-color: #4CAF50; }
            #RetryButton:hover { background-color: #45a049; }
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
            #ContinueButton { background-color: #4CAF50; }
            #ContinueButton:hover { background-color: #45a049; }
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
        
        self.warning_label = QLabel(_("⚠️ Модели Fish Speech+ / + RVC требуют всех компонентов!", 
                                     "⚠️ Models Fish Speech+ / + RVC require all components!"))
        self.warning_label.setStyleSheet("color: orange; font-weight: bold;")
        cuda_found = self.dependencies_status.get('cuda_found', False)
        winsdk_found = self.dependencies_status.get('winsdk_found', False)
        msvc_found = self.dependencies_status.get('msvc_found', False)
        self.warning_label.setVisible(not (cuda_found and winsdk_found and msvc_found))
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
        
        items = [
            ("CUDA Toolkit:", self.dependencies_status.get('cuda_found', False)),
            ("Windows SDK:", self.dependencies_status.get('winsdk_found', False)),
            ("MSVC:", self.dependencies_status.get('msvc_found', False))
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
            cuda_found = self.dependencies_status.get('cuda_found', False)
            winsdk_found = self.dependencies_status.get('winsdk_found', False)
            msvc_found = self.dependencies_status.get('msvc_found', False)
            self.warning_label.setVisible(not (cuda_found and winsdk_found and msvc_found))
    
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