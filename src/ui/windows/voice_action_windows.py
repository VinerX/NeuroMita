from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPlainTextEdit, QProgressBar,
    QApplication, QWidget, QPushButton, QFileDialog, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QTime
from PyQt6.QtGui import QFont, QTextCursor, QGuiApplication
from utils import getTranslationVariant as _

import re
import os
import json
import shutil
from html import escape as html_escape
from main_logger import logger
from collections import deque

# Широкий регэксп: чистит и CSI-последовательности (\x1b[...),
# и одиночные ESC-последовательности (\x1bX), и OSC/прочие escape-формы.
ANSI_RE = re.compile(r'\x1b(?:\[.*?[@-~]|\].*?(?:\x1b\\|\x07))')

# Незавершённая ANSI-последовательность в конце чанка (ESC без финального байта):
# её нельзя стрипать сразу — финальный байт придёт со следующим PTY-чтением.
TRAILING_ANSI_RE = re.compile(r'\x1b(?:\][^\x07\x1b]*|\[[0-9;?]*)?$')


def strip_ansi(s: str) -> str:
    """Удаляет ANSI escape-коды из строки."""
    if not s:
        return ""
    return ANSI_RE.sub('', s)


class VoiceInstallationWindow(QDialog):
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    log_updated = pyqtSignal(str)
    raw_log_updated = pyqtSignal(str)
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
                QTextEdit, QPlainTextEdit {
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
                QTextEdit, QPlainTextEdit {
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
        self._raw_log_chunks: list[str] = []
        self._raw_pending_chunks: deque[str] = deque()
        # Хвост незакрытой ANSI-последовательности, разорванной на границе
        # PTY-чтения: держим до следующего чанка, иначе strip_ansi её пропустит
        # и в Raw log посыплются «□[32m»-артефакты (выглядит как сломанная кодировка).
        self._raw_ansi_carry: str = ""
        self._display_lines: deque[str] = deque()
        self._max_display_blocks: int = 200
        self._snapshot_lines: list[str] = []
        self._overview_lines: deque[str] = deque(maxlen=16)
        self._last_overview_line = ""

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

        # Второй ряд метрик: счётчик пакетов, скорость+скачано, стадия, ошибки,
        # свободное место на диске. Заполняется из структурного маркера __STATS__.
        stats_layout = QHBoxLayout()
        self.packages_label = QLabel("")
        self.packages_label.setFont(QFont("Segoe UI", 9))
        stats_layout.addWidget(self.packages_label, 0)

        self.speed_label = QLabel("")
        self.speed_label.setFont(QFont("Segoe UI", 9))
        stats_layout.addWidget(self.speed_label, 0)

        self.issues_label = QLabel("")
        self.issues_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        stats_layout.addWidget(self.issues_label, 0)

        stats_layout.addStretch(1)

        self.stage_badge = QLabel("")
        self.stage_badge.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        stats_layout.addWidget(self.stage_badge, 0)

        self.disk_label = QLabel("")
        self.disk_label.setFont(QFont("Segoe UI", 9))
        self.disk_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        stats_layout.addWidget(self.disk_label, 0)
        layout.addLayout(stats_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        self.progress_value_label.setText("...")

        # Целевая папка установки — для показа свободного места. Обновляем по таймеру.
        self._install_target_dir = os.path.abspath(os.environ.get("NEUROMITA_LIB_DIR", "Lib"))
        self._disk_timer = QTimer(self)
        self._disk_timer.setInterval(3000)
        self._disk_timer.timeout.connect(self._update_disk_free)
        self._disk_timer.start()
        self._update_disk_free()

        self.install_tabs = QTabWidget()
        self.install_tabs.setDocumentMode(True)

        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        self.overview_text = QTextEdit()
        self.overview_text.setReadOnly(True)
        self.overview_text.setFont(QFont("Segoe UI", 9))
        overview_layout.addWidget(self.overview_text, 1)
        self.install_tabs.addTab(overview_page, _("Ход установки", "Installation"))

        raw_page = QWidget()
        raw_layout = QVBoxLayout(raw_page)
        raw_layout.setContentsMargins(0, 0, 0, 0)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setUndoRedoEnabled(False)
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_text.setFont(QFont("Consolas", 9))
        raw_layout.addWidget(self.log_text, 1)
        self.install_tabs.addTab(raw_page, _("Raw log", "Raw log"))
        self.install_tabs.currentChanged.connect(self._on_install_tab_changed)
        layout.addWidget(self.install_tabs, 1)

        # pip/uv may emit hundreds of lines in a short burst. Rebuilding the
        # QTextEdit HTML for every line made the installer UI itself expensive.
        # Keep the complete raw stream in memory and repaint it in short batches.
        self._raw_flush_timer = QTimer(self)
        self._raw_flush_timer.setSingleShot(True)
        self._raw_flush_timer.setInterval(80)
        self._raw_flush_timer.timeout.connect(self._flush_raw_log)
        self._append_overview_line(initial_status or _("Подготовка...", "Preparing..."))

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
        self.raw_log_updated.connect(self._on_raw_log_update, type=Qt.ConnectionType.QueuedConnection)

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
            self.raw_log_updated.emit,
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

    @staticmethod
    def _fmt_bytes(n) -> str:
        try:
            n = float(n)
        except Exception:
            return "?"
        for unit, mul in (("Б", 1), ("КБ", 1024), ("МБ", 1024 ** 2), ("ГБ", 1024 ** 3), ("ТБ", 1024 ** 4)):
            if n < mul * 1024 or unit == "ТБ":
                return f"{n / mul:.1f} {unit}"
        return f"{n:.0f} Б"

    @classmethod
    def _fmt_speed(cls, bps) -> str:
        try:
            bps = float(bps)
        except Exception:
            return ""
        return f"{cls._fmt_bytes(bps)}/с" if bps > 0 else ""

    def _update_disk_free(self):
        """Свободное место на диске установки; краснеет при нехватке."""
        target = getattr(self, "_install_target_dir", None) or "."
        probe = target
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        try:
            free = shutil.disk_usage(probe or ".").free
        except Exception:
            self.disk_label.setText("")
            return
        low = free < 3 * 1024 ** 3       # < 3 ГБ — критично для torch-стека
        warn = free < 8 * 1024 ** 3      # < 8 ГБ — предупреждение
        color = "#ff5555" if low else ("#ffb86c" if warn else "#9aa0a6")
        self.disk_label.setStyleSheet(f"color: {color};")
        self.disk_label.setText(_("Диск: ", "Disk: ") + self._fmt_bytes(free))

    def _apply_stats(self, stats: dict):
        """Обновляет ряд метрик из структурного маркера __STATS__."""
        pkg_done = stats.get("packages_done")
        pkg_total = stats.get("packages_total")
        if pkg_total:
            done = pkg_done if isinstance(pkg_done, int) else 0
            self.packages_label.setText(_("📦 Пакеты: ", "📦 Packages: ") + f"{done} / {pkg_total}")
        else:
            self.packages_label.setText("")

        speed = stats.get("speed_bps") or 0
        dl_done = stats.get("downloaded_bytes") or 0
        dl_total = stats.get("total_bytes") or 0
        parts = []
        speed_txt = self._fmt_speed(speed)
        if speed_txt:
            parts.append("↓ " + speed_txt)
        if dl_total > 0:
            parts.append(f"{self._fmt_bytes(dl_done)} / {self._fmt_bytes(dl_total)}")
        self.speed_label.setStyleSheet("color: #9aa0a6;")
        self.speed_label.setText("   " + " · ".join(parts) if parts else "")

        errors = int(stats.get("errors") or 0)
        warnings = int(stats.get("warnings") or 0)
        issues = []
        if errors:
            issues.append(f"✖ {errors}")
        if warnings:
            issues.append(f"⚠ {warnings}")
        self.issues_label.setStyleSheet("color: #ff5555;" if errors else "color: #ffb86c;")
        self.issues_label.setText("   " + "  ".join(issues) if issues else "")
        if errors:
            self._show_raw_log()

        stage = str(stats.get("stage") or "")
        badge = {
            "resolving": (_("Резолв", "Resolving"), "#3a6ea5"),
            "preparing": (_("Скачивание", "Downloading"), "#b06bd0"),
            "installing": (_("Установка", "Installing"), "#4a9d6a"),
            "done": (_("Готово", "Done"), "#4a9d6a"),
        }.get(stage)
        if badge:
            text, bg = badge
            self.stage_badge.setStyleSheet(
                f"color: #ffffff; background: {bg}; border-radius: 7px; padding: 1px 8px;"
            )
            self.stage_badge.setText(text)
        else:
            self.stage_badge.setText("")

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
        self._append_overview_line(message)
        if self._is_error_line(message):
            self._show_raw_log()
        # Вынимаем ETA из сообщения, если есть
        m = re.search(r'\(\s*ETA\s+([^)]+)\)', message, flags=re.IGNORECASE)
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
        # Raw output has its own exact subprocess stream. Never reconstruct it
        # from the parsed/normalized semantic log.
        self._flush_raw_log()

    def _render_overview(self):
        activity_html = "".join(
            f"<div style='margin:0 0 6px 0;'>{self._colorize_line(line)}</div>"
            for line in self._overview_lines
        )
        snapshot_html = ""
        if self._snapshot_lines:
            snapshot_html = (
                f"<div style='margin:10px 0 0 0; padding:8px; background:{self._snapshot_bg}; "
                f"border:1px solid {self._snapshot_border}; border-radius:7px;'>"
                "<div style='font-weight:600; margin-bottom:5px;'>"
                + html_escape(_("Текущие операции", "Current operations"))
                + "</div><pre style='font-family:Consolas,monospace; font-size:9pt; margin:0; "
                f"color:{self._snapshot_fg};'>"
                + html_escape("\n".join(self._snapshot_lines))
                + "</pre></div>"
            )
        self.overview_text.setHtml(activity_html + snapshot_html)
        self.overview_text.moveCursor(QTextCursor.MoveOperation.End)

    def _append_overview_line(self, text: str):
        clean = strip_ansi(str(text or "")).strip()
        if not clean or clean == self._last_overview_line:
            return
        self._last_overview_line = clean
        self._overview_lines.append(clean)
        self._render_overview()

    @staticmethod
    def _is_error_line(text: str) -> bool:
        low = str(text or "").lower()
        return any(token in low for token in (
            "error", "ошибка", "failed", "traceback", "exception", "critical",
            "no solution found", "не пройдена",
        ))

    def _show_raw_log(self):
        self.install_tabs.setCurrentIndex(1)
        self._flush_raw_log()

    def _on_install_tab_changed(self, index: int):
        if index == 1:
            self._flush_raw_log()

    def _schedule_raw_flush(self, *, immediate: bool = False):
        if immediate:
            self._raw_flush_timer.stop()
            self._flush_raw_log()
            return
        if not self._raw_flush_timer.isActive():
            self._raw_flush_timer.start()

    def _flush_raw_log(self):
        # The raw tab is a literal decoded subprocess stream. It is intentionally
        # not colorized, normalized, line-split or mixed with __STATS__ protocol
        # frames used by the visual tab.
        if self.install_tabs.currentIndex() != 1 or not self._raw_pending_chunks:
            return
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        while self._raw_pending_chunks:
            cursor.insertText(self._raw_pending_chunks.popleft())
        self.log_text.setTextCursor(cursor)
        self.log_text.ensureCursorVisible()

    def _render_snapshot(self, lines: list[str]):
        self._snapshot_lines = list(lines)
        self._render_overview()

    def _append_log_chunk(self, text: str):
        if not text:
            return
        # Разбиваем на строки, добавляем в full, поддерживаем окно последних строк
        contains_error = False
        for ln in text.splitlines():
            plain = strip_ansi(ln)
            if not plain.strip():
                continue
            self._full_log_lines.append(plain)
            colored = self._colorize_line(plain)
            self._display_lines.append(colored)
            while len(self._display_lines) > self._max_display_blocks:
                self._display_lines.popleft()
            if self._is_error_line(plain):
                contains_error = True
            elif any(marker in plain.lower() for marker in (
                "installing:", "resolved ", "prepared ", "installed ",
                "successfully installed", "download", "using cached",
            )):
                self._append_overview_line(plain)
        if contains_error:
            self._show_raw_log()

    def _rebuild_display_from_full(self):
        # Parsed lines belong to the visual overview only. Raw output is retained
        # independently in _raw_log_chunks and is never reconstructed here.
        return

    def _on_log_update(self, text: str):
        if text.startswith("__STATS__"):
            try:
                self._apply_stats(json.loads(text[len("__STATS__"):]))
            except Exception:
                pass
            return
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

    def _on_raw_log_update(self, text: str):
        if text is None:
            return
        chunk = str(text)
        if not chunk:
            return
        # PTY-поток UV/pip приходит с ANSI-кодами цвета и живой перерисовки
        # прогресса. QPlainTextEdit их не интерпретирует, поэтому raw ESC-байты
        # рендерились как «□[32m» — пользователь видит «сломанную кодировку».
        # Чистим ANSI (и одиночные ESC), но держим хвост незакрытой
        # последовательности, разорванной на границе чтения, до следующего чанка.
        buffered = self._raw_ansi_carry + chunk
        self._raw_ansi_carry = ""
        m = TRAILING_ANSI_RE.search(buffered)
        if m:
            self._raw_ansi_carry = buffered[m.start():]
            buffered = buffered[:m.start()]
        clean = strip_ansi(buffered).replace("\x1b", "")
        if not clean:
            return
        self._raw_log_chunks.append(clean)
        self._raw_pending_chunks.append(clean)
        self._schedule_raw_flush()

    def _raw_log_text(self) -> str:
        return "".join(self._raw_log_chunks)

    def _copy_log(self):
        QGuiApplication.clipboard().setText(self._raw_log_text() or "\n".join(self._full_log_lines) or "")

    def _save_log(self):
        fname, _selected_filter = QFileDialog.getSaveFileName(self, _("Сохранить лог", "Save Log"), "install_log.txt", "Text Files (*.txt)")
        if fname:
            try:
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(self._raw_log_text() or "\n".join(self._full_log_lines))
            except Exception as ex:
                logger.error(f"Не удалось сохранить лог: {ex}")

    def _clear_log_screen_only(self):
        # Очистка только видимой области; полный лог остаётся для копирования/сохранения
        self._display_lines.clear()
        self.log_text.clear()

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

    def update_raw_log(self, text: str):
        self.raw_log_updated.emit(text)


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
            QTextEdit, QPlainTextEdit {
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
        m = re.search(r'\(\s*ETA\s+([^)]+)\)', message, flags=re.IGNORECASE)
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
        if text.startswith("__STATS__"):
            # Это окно не показывает метрики — просто игнорируем структурный маркер.
            return
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
    def __init__(self, open_documentation, parent=None):
        super().__init__(parent)
        self._open_documentation = open_documentation
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
        self._open_documentation("installation_guide.html#vc_redist")

    def _set_choice_and_accept(self, choice):
        self.choice = choice
        self.accept()

    def get_choice(self):
        return self.choice


class TritonDependenciesDialog(QDialog):
    def __init__(
        self,
        *,
        open_documentation,
        refresh_status,
        parent=None,
        dependencies_status=None,
    ):
        super().__init__(parent)
        self._open_documentation = open_documentation
        self._refresh_status = refresh_status
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
            "Для Fish Speech+ нужен только Microsoft VC++ Build Tools.\n"
            "Triton Windows уже содержит TinyCC и не требует Windows SDK или CUDA Toolkit.\n"
            "Установите VC++ Build Tools, затем обновите статус. Если компиляция всё равно не сработает,\n"
            "попробуйте ручную инициализацию через `init_triton.bat` в корне программы.",
            "Fish Speech+ only requires Microsoft VC++ Build Tools.\n"
            "Triton Windows already includes TinyCC and does not require the Windows SDK or CUDA Toolkit.\n"
            "Install VC++ Build Tools, then refresh the status. If compilation still fails,\n"
            "try manual initialization with `init_triton.bat` in the program's root folder."
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
            ("MSVC (VC++):", self.dependencies_status.get('msvc_found', False)),
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
        self.dependencies_status = dict(self._refresh_status() or {})
        self._update_status_display()

    def _on_docs_clicked(self):
        self._open_documentation("installation_guide.html")

    def _set_choice_and_accept(self, choice):
        self.choice = choice
        self.accept()

    def get_choice(self):
        return self.choice
