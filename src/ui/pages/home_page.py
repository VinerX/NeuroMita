from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import qtawesome as qta
from PyQt6.QtCore import QPoint, QRectF, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Минимальный интервал между фоновыми проверками обновлений (сек), чтобы не
# дёргать GitHub на каждой активации главной страницы.
_UPDATE_CHECK_THROTTLE_SEC = 600

from core.events import Events
from main_logger import logger
from ui.pages.news_support import build_release_news_items, get_news_content, parse_news_items
from ui.widgets.launcher_dashboard_helpers import NewsItem
from utils import _


def _strip_v(version: str) -> str:
    """Срезать единственный ведущий 'v', чтобы подписи не давали 'vv2026...'.

    Версия Unity из _version.txt хранится с префиксом 'v', а подпись добавляет
    свой. Срез опционален: если префикса нет (Python-часть), строка не меняется.
    """
    text = str(version or "").strip()
    if text[:1] in ("v", "V"):
        return text[1:]
    return text


class LauncherHomeBackground(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LauncherHomeBackground")
        self._bg = QPixmap(str(Path("assets/launcher_ui/bg.jpg")))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = QRectF(self.rect())
        if not self._bg.isNull():
            source = QRectF(self._bg.rect())
            target_ratio = rect.width() / max(1.0, rect.height())
            source_ratio = source.width() / max(1.0, source.height())

            if source_ratio > target_ratio:
                new_width = source.height() * target_ratio
                source.setLeft(source.left() + (source.width() - new_width) * 0.68)
                source.setWidth(new_width)
            else:
                new_height = source.width() / target_ratio
                source.setTop(source.top() + (source.height() - new_height) * 0.5)
                source.setHeight(new_height)

            painter.drawPixmap(rect, self._bg, source)
        else:
            painter.fillRect(rect, QColor("#09050f"))

        horizontal = QLinearGradient(rect.topLeft(), rect.topRight())
        horizontal.setColorAt(0.0, QColor(10, 4, 8, 245))
        horizontal.setColorAt(0.42, QColor(10, 4, 8, 170))
        horizontal.setColorAt(0.74, QColor(10, 4, 8, 70))
        horizontal.setColorAt(1.0, QColor(10, 4, 8, 10))
        painter.fillRect(rect, horizontal)

        vertical = QLinearGradient(rect.bottomLeft(), rect.topLeft())
        vertical.setColorAt(0.0, QColor(10, 4, 8, 220))
        vertical.setColorAt(0.38, QColor(10, 4, 8, 55))
        vertical.setColorAt(1.0, QColor(10, 4, 8, 0))
        painter.fillRect(rect, vertical)


class HomePage(LauncherHomeBackground):
    _ui_call_requested = pyqtSignal(object)

    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui

        self._home_install_thread_running = False
        self._update_chip_label = None
        self._backend_status_value = None
        self._unity_status_value = None
        self._status_line_label = None
        self._news_items_layout = None
        self._news_panel_placeholder = None

        # Выборочное обновление: чекбоксы на карточках + баннер-обнова.
        self._py_update_check = None
        self._unity_update_check = None
        self._update_banner = None
        self._update_banner_label = None
        self._update_info_py = None
        self._update_info_unity = None
        self._update_check_inflight = False
        self.primary_button = None
        self.progress_bar = None
        self.progress_label = None
        self._cancel_button = None
        self._cancel_event: threading.Event | None = None

        self._ui_call_requested.connect(self._execute_ui_call)
        self._sync_host_exports()
        self._build_ui()
        self._connect_install_signals()
        self.on_activated()

    def _sync_host_exports(self):
        self.gui.home_page = self

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(44, 42, 36, 32)
        layout.setSpacing(0)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(24)

        left_column = QVBoxLayout()
        left_column.setSpacing(14)

        title = QLabel(_("Добро пожаловать!", "Welcome!"))
        title.setObjectName("LauncherHomeTitle")
        left_column.addWidget(title)

        subtitle = QLabel(
            _(
                'Погрузись Miside по-новому с NeuroMita.',
                "Experience Miside in a new way with NeuroMita.",
            )
        )
        subtitle.setObjectName("LauncherHomeSubtitle")
        left_column.addWidget(subtitle)
        # left_column.addWidget(self._build_home_update_chip())

        logo_wrap = QWidget()
        logo_wrap.setObjectName("LauncherHomeLogoZone")
        logo_layout = QVBoxLayout(logo_wrap)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.setSpacing(0)
        logo_layout.addStretch(1)

        logo = QLabel()
        logo.setObjectName("LauncherHomeLogo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_path = Path("assets/launcher_ui/logo.png")
        if logo_path.exists():
            logo.setPixmap(
                QPixmap(str(logo_path)).scaled(
                    420,
                    270,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            logo.setText("NeuroMita")
        logo_layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        logo_layout.addStretch(1)
        left_column.addWidget(logo_wrap, 1)

        backend_row = QHBoxLayout()
        backend_row.setSpacing(12)
        backend_card, self._backend_status_value, self._py_update_check = self._build_home_status_card(
            "fa6b.python",
            _("Python-бэкенд", "Python backend"),
            "",
            "#ffd86b",
        )
        backend_row.addWidget(backend_card)

        unity_card, self._unity_status_value, self._unity_update_check = self._build_home_status_card(
            "mdi.unity",
            "Unity",
            "",
            "#f0f0f0",
        )
        backend_row.addWidget(unity_card)
        left_column.addLayout(backend_row)

        self._update_banner = self._build_update_banner()
        left_column.addWidget(self._update_banner)

        button_row = QHBoxLayout()
        button_row.setSpacing(0)

        self.primary_button = QPushButton("")
        self.primary_button.setObjectName("LauncherHomePrimaryButton")
        self.primary_button.clicked.connect(self.run_primary_action)
        button_row.addWidget(self.primary_button, 1)

        menu_button = QPushButton("")
        menu_button.setObjectName("LauncherHomeMenuButton")
        menu_button.setIcon(qta.icon("fa6s.chevron-down", color="#ffd2ec"))
        menu_button.setIconSize(QSize(14, 14))
        menu_button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        menu_button.clicked.connect(lambda: self.show_extra_menu(menu_button))
        button_row.addWidget(menu_button)
        left_column.addLayout(button_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("LauncherHomeProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setVisible(False)
        left_column.addWidget(self.progress_bar)

        _progress_row = QHBoxLayout()
        _progress_row.setSpacing(8)
        _progress_row.setContentsMargins(0, 0, 0, 0)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("LauncherHomeProgressLabel")
        self.progress_label.setVisible(False)
        _progress_row.addWidget(self.progress_label, 1)

        self._cancel_button = QPushButton(_("✕ Отменить", "✕ Cancel"))
        self._cancel_button.setObjectName("LauncherHomeCancelButton")
        self._cancel_button.setVisible(False)
        self._cancel_button.clicked.connect(self._cancel_installation)
        _progress_row.addWidget(self._cancel_button)

        left_column.addLayout(_progress_row)

        self._status_line_label = QLabel("")
        self._status_line_label.setObjectName("LauncherHomeFootnote")
        self._status_line_label.setWordWrap(True)
        left_column.addWidget(self._status_line_label)

        right_column = QVBoxLayout()
        right_column.setContentsMargins(0, 0, 0, 8)
        right_column.addStretch(1)
        right_column.addWidget(self._build_home_news_panel())

        content.addLayout(left_column, 5)
        content.addLayout(right_column, 2)
        layout.addLayout(content)

        self.gui.home_primary_button = self.primary_button
        self.gui.home_progress_bar = self.progress_bar
        self.gui.home_progress_label = self.progress_label

    def _connect_install_signals(self):
        if getattr(self.gui, "_home_install_signals_connected", False):
            return
        try:
            self.gui.event_bus.subscribe(Events.Install.TASK_STARTED, self._on_install_started, weak=False)
            self.gui.event_bus.subscribe(Events.Install.TASK_PROGRESS, self._on_install_progress, weak=False)
            self.gui.event_bus.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
            self.gui.event_bus.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)
            self.gui._home_install_signals_connected = True
        except Exception as exc:
            logger.info(f"Install signals subscribe skipped: {exc}")

    def _get_current_news_items(self) -> list[NewsItem]:
        return parse_news_items(get_news_content(self.gui))

    def _get_release_news_items(self, limit: int = 3) -> list[NewsItem]:
        return build_release_news_items(self.gui, limit=limit)

    def _build_home_update_chip(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherHomeUpdateChip")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        dot = QLabel()
        dot.setObjectName("LauncherHomeUpdateDot")
        dot.setFixedSize(10, 10)
        layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._update_chip_label = QLabel("")
        self._update_chip_label.setObjectName("LauncherHomeUpdateText")
        layout.addWidget(self._update_chip_label)
        layout.addStretch(1)

        link = QPushButton(_("Что нового?", "What's new?"))
        link.setObjectName("LauncherHomeLinkButton")
        link.clicked.connect(lambda: self.gui.switch_main_page("news"))
        layout.addWidget(link)
        return card

    def _build_update_banner(self) -> QFrame:
        """Тонкий баннер «доступно обновление». Скрыт, пока обнов нет.

        Только информация о версиях. Само обновление запускает центральная
        кнопка (она же показывает, что нужен код тестера); выбор частей — на
        чекбоксах карточек. Код тестера спрашивается всплывающим окном.
        """
        banner = QFrame()
        banner.setObjectName("LauncherHomeUpdateChip")
        banner.setVisible(False)
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        dot = QLabel()
        dot.setObjectName("LauncherHomeUpdateDot")
        dot.setFixedSize(10, 10)
        layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._update_banner_label = QLabel("")
        self._update_banner_label.setObjectName("LauncherHomeUpdateText")
        self._update_banner_label.setWordWrap(True)
        layout.addWidget(self._update_banner_label, 1)
        return banner

    def _effective_tester_code(self) -> str:
        return str(self.gui.settings.get("TESTER_CODE", "") or "").strip()

    def _prompt_tester_code(self) -> str | None:
        """Запросить код тестера модалкой. None — пользователь отменил."""
        from PyQt6.QtWidgets import QInputDialog

        code, ok = QInputDialog.getText(
            self,
            _("Код тестера", "Tester code"),
            _(
                "Введите код тестера для установки релизных архивов.",
                "Enter the tester code required to install release archives.",
            ),
            QLineEdit.EchoMode.Password,
            "",
        )
        if not ok:
            return None
        code = str(code or "").strip()
        if not code:
            return None
        try:
            self.gui._save_setting("TESTER_CODE", code)
        except Exception:
            pass
        return code

    def _refresh_update_state(self, force: bool = False):
        """Фоновая проверка обновлений → обновляет чекбоксы и баннер.

        По умолчанию проверка идёт не чаще _UPDATE_CHECK_THROTTLE_SEC и только
        если включена настройка UPDATE_CHECK_ON_STARTUP. force=True (кнопка из
        меню) игнорирует и троттлинг, и настройку.
        """
        if not force:
            if not bool(self.gui.settings.get("UPDATE_CHECK_ON_STARTUP", True)):
                return
            last = float(getattr(self.gui, "_home_update_check_ts", 0.0) or 0.0)
            if (time.monotonic() - last) < _UPDATE_CHECK_THROTTLE_SEC:
                return
        if self._update_check_inflight:
            return
        self._update_check_inflight = True
        self.gui._home_update_check_ts = time.monotonic()

        def worker():
            try:
                from updater import get_python_update_info, get_unity_update_info
                channel = self.gui.settings.get("UPDATE_CHANNEL", "stable")
                base_dir = os.environ.get("NEUROMITA_BASE_DIR") or None
                unity_dir = self.gui.settings.get("UNITY_INSTALL_DIR") or None

                py_info = get_python_update_info(base_dir=base_dir, channel=channel)
                unity_info = get_unity_update_info(base_dir=base_dir, unity_dir=unity_dir, channel=channel)
                self._queue_ui_call(lambda: self._apply_update_state(py_info, unity_info))
            except Exception as exc:
                logger.warning(f"[home_update] background check failed: {exc}")
            finally:
                self._update_check_inflight = False

        threading.Thread(target=worker, daemon=True).start()

    def _apply_update_state(self, py_info: dict | None, unity_info: dict | None):
        """Применить результат проверки к UI (вызывается на GUI-потоке)."""
        self._update_info_py = py_info
        self._update_info_unity = unity_info

        py_avail = bool((py_info or {}).get("available"))
        unity_avail = bool((unity_info or {}).get("available"))
        if self._has_pending_python_restart():
            py_avail = False

        if self._py_update_check is not None:
            self._py_update_check.setVisible(py_avail)
            if py_avail:
                self._py_update_check.setChecked(True)
            else:
                self._py_update_check.setChecked(False)
        if self._unity_update_check is not None:
            self._unity_update_check.setVisible(unity_avail)
            if unity_avail:
                self._unity_update_check.setChecked(True)
            else:
                self._unity_update_check.setChecked(False)

        if not py_avail and not unity_avail:
            if self._update_banner is not None:
                self._update_banner.setVisible(False)
            self.refresh_primary_label()
            return

        parts = []
        if py_avail:
            parts.append(_("Python {ver}", "Python {ver}").format(ver=_strip_v(str((py_info or {}).get("latest_version", "")))))
        if unity_avail:
            parts.append(_("Unity {ver}", "Unity {ver}").format(ver=_strip_v(str((unity_info or {}).get("latest_version", "")))))
        text = _("Доступно обновление: {p}", "Update available: {p}").format(p=" • ".join(parts))
        if self._update_banner_label is not None:
            self._update_banner_label.setText(text)

        if self._update_banner is not None:
            self._update_banner.setVisible(True)

        # Центральная кнопка берёт роль «Обновить» — обновляем её подпись.
        self.refresh_primary_label()

    def _build_home_status_card(self, icon_name: str, title_text: str, value_text: str, color: str) -> tuple[QFrame, QLabel, QCheckBox]:
        card = QFrame()
        card.setObjectName("LauncherHomeStatusCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        icon = QLabel()
        icon.setPixmap(qta.icon(icon_name, color=color).pixmap(34, 34))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        title = QLabel(title_text.upper())
        title.setObjectName("LauncherHomeStatusEyebrow")
        text_column.addWidget(title)

        value = QLabel(value_text)
        value.setObjectName("LauncherHomeStatusValue")
        text_column.addWidget(value)

        layout.addLayout(text_column, 1)

        # Чекбокс «включить в обновление». Виден только когда по этой части есть
        # обнова — в обычном состоянии карточка выглядит как раньше.
        update_check = QCheckBox()
        update_check.setObjectName("LauncherHomeStatusCheck")
        update_check.setChecked(True)
        update_check.setVisible(False)
        update_check.setToolTip(_("Включить в обновление", "Include in update"))
        layout.addWidget(update_check, 0, Qt.AlignmentFlag.AlignTop)
        return card, value, update_check

    def _build_home_news_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("LauncherHomeNewsPanel")
        panel.setMinimumWidth(280)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = QLabel(_("Последние релизы", "Latest releases").upper())
        title.setObjectName("LauncherHomeNewsTitle")
        header.addWidget(title)
        header.addStretch(1)

        all_news = QPushButton(_("Все релизы", "All releases"))
        all_news.setObjectName("LauncherHomeLinkButton")
        all_news.clicked.connect(lambda: self.gui.switch_main_page("news"))
        header.addWidget(all_news)
        layout.addLayout(header)

        divider = QFrame()
        divider.setObjectName("LauncherHomeDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        self._news_panel_placeholder = QWidget()
        self._news_panel_placeholder.setObjectName("LauncherHomeNewsItems")
        self._news_items_layout = QVBoxLayout(self._news_panel_placeholder)
        self._news_items_layout.setContentsMargins(0, 0, 0, 0)
        self._news_items_layout.setSpacing(8)
        layout.addWidget(self._news_panel_placeholder)
        return panel

    def _build_home_news_item(self, item: NewsItem, *, is_fresh: bool = False) -> QFrame:
        row = QFrame()
        row.setObjectName("LauncherHomeNewsItem")
        if item.item_id:
            row.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)

        top = QHBoxLayout()
        title = QLabel(item.title)
        title.setObjectName("LauncherHomeNewsItemTitle")
        top.addWidget(title)

        top.addStretch(1)
        text_column.addLayout(top)

        tooltip_text = str(item.full_text or item.summary or "").strip()
        if tooltip_text:
            row.setToolTip(tooltip_text)
            title.setToolTip(tooltip_text)
        layout.addLayout(text_column, 1)

        if item.timestamp:
            stamp = QLabel(self._format_news_date(item.timestamp))
            stamp.setObjectName("LauncherHomeNewsDate")
            layout.addWidget(stamp, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        if item.item_id:
            def _open_release(_event, release_id=item.item_id):
                if hasattr(self.gui, "open_release_page"):
                    self.gui.open_release_page(release_id)
                else:
                    self.gui.switch_main_page("news")
            row.mousePressEvent = _open_release

        return row

    @staticmethod
    def _format_news_date(value: str) -> str:
        if not value:
            return ""
        date_part = value[:10]
        parts = date_part.split("-")
        if len(parts) == 3:
            year, month, day = parts
            return f"{day}.{month}.{year}"
        return value

    def _get_backend_status(self) -> str:
        if self._has_pending_python_restart():
            version = self._get_pending_python_restart_version()
            if version:
                return _("Установлен v{ver} • нужен перезапуск", "Installed v{ver} • restart required").format(
                    ver=_strip_v(version)
                )
            return _("Обновление установлено • нужен перезапуск", "Update installed • restart required")
        try:
            from _version import __version__ as version

            return _("Установлен v{ver}", "Installed v{ver}").format(ver=_strip_v(version))
        except Exception:
            return _("Установлен", "Installed")

    def _get_unity_install_dir(self) -> Path:
        unity_dir_setting = str(self.gui.settings.get("UNITY_INSTALL_DIR", "") or "")
        if unity_dir_setting:
            return Path(unity_dir_setting)

        base_dir = os.environ.get("NEUROMITA_BASE_DIR", "")
        if base_dir:
            return Path(base_dir) / "NeuroMita-Unity"
        return Path(sys.argv[0]).resolve().parent / "NeuroMita-Unity"

    def find_unity_executable(self) -> Path | None:
        unity_dir = self._get_unity_install_dir()
        if not unity_dir.exists() or not unity_dir.is_dir():
            return None

        # Ищем в корне и на один уровень вглубь (например UnityBuild/).
        exe_files = list(unity_dir.glob("*.exe")) + list(unity_dir.glob("*/*.exe"))
        if not exe_files:
            return None

        preferred = ("NeuroMita.exe", "NeuroMita-Unity.exe", "Unity.exe")
        lower_map = {path.name.lower(): path for path in exe_files}
        for name in preferred:
            hit = lower_map.get(name.lower())
            if hit is not None:
                return hit

        for path in exe_files:
            low = path.name.lower()
            if "neuromita" in low or "unity" in low:
                return path
        return exe_files[0]

    def _get_unity_status(self) -> str:
        exe = self.find_unity_executable()
        if exe is None:
            return _("Не установлен", "Not installed")

        try:
            version_file = self._get_unity_install_dir() / "_version.txt"
            if version_file.exists():
                version = version_file.read_text(encoding="utf-8").strip()
                if version:
                    return _("Установлен v{ver}", "Installed v{ver}").format(ver=_strip_v(version))
        except Exception:
            pass
        return _("Установлен", "Installed")

    def _has_py_update(self) -> bool:
        if self._has_pending_python_restart():
            return False
        return bool((self._update_info_py or {}).get("available"))

    def _has_unity_update(self) -> bool:
        return bool((self._update_info_unity or {}).get("available"))

    def _has_any_update(self) -> bool:
        return self._has_py_update() or self._has_unity_update()

    def _has_selectable_update(self) -> bool:
        for control in (self._py_update_check, self._unity_update_check):
            if control is not None and control.isVisible():
                return True
        return False

    def _lock_suffix(self) -> str:
        # Подсказка про код тестера, когда действие потянет зашифрованный архив.
        if not self._effective_tester_code():
            return _(" (🔒 нужен код тестера)", " (🔒 tester code needed)")
        return ""

    def _has_pending_python_restart(self) -> bool:
        return bool(self._get_pending_python_restart_version())

    def _get_pending_python_restart_version(self) -> str:
        return str(getattr(self.gui, "_pending_python_restart_version", "") or "").strip()

    def _mark_python_restart_required(self, version: str | None) -> None:
        self.gui._pending_python_restart_version = str(version or "").strip() or None
        if self._py_update_check is not None:
            self._py_update_check.setVisible(False)
            self._py_update_check.setChecked(False)
        sidebar = getattr(self.gui, "shell_sidebar", None)
        if sidebar is not None and hasattr(sidebar, "refresh_version_label"):
            try:
                sidebar.refresh_version_label()
            except Exception:
                logger.warning("[home_update] Failed to refresh sidebar version label", exc_info=True)

    def _get_primary_action_label(self) -> str:
        if self._has_pending_python_restart():
            return _("↻ Перезапустить", "↻ Restart")
        # Unity ещё нет — это «Установить», даже если по нему «доступна обнова»
        # (фоновая проверка помечает неполную установку как available).
        if self.find_unity_executable() is None:
            suffix = self._lock_suffix() if self._has_selectable_update() else ""
            return _("↓ Установить", "↓ Install") + suffix
        # Unity установлен и есть обнова — кнопка становится «Обновить».
        if self._has_selectable_update():
            return _("⟳ Обновить", "⟳ Update") + self._lock_suffix()
        return _("▶ Играть", "▶ Play")

    def _get_status_line(self, news_items: list[NewsItem]) -> str:
        active_character = _("Без персонажа", "No character")
        try:
            profile_result = self.gui.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=0.5)
            profile = profile_result[0] if profile_result else {}
            active_character = str(profile.get("character_id") or active_character)
        except Exception:
            pass

        model_name = str(self.gui._get_setting("MODEL", "") or "").strip()
        latest = news_items[0].title if news_items else _("Лента релизов офлайн", "Release feed offline")
        parts = [_("Активно: {character}", "Active: {character}").format(character=active_character)]
        if model_name:
            parts.append(model_name)
        parts.append(latest[:48])
        return " • ".join(parts)

    def refresh_news_content(self):
        news_items = self._get_current_news_items()
        headline = news_items[0].title if news_items else _("Релизы недоступны", "Releases unavailable")
        # if self._update_chip_label is not None:
        #     self._update_chip_label.setText(
        #         _("Доступно обновление: {headline}", "Fresh update: {headline}").format(headline=headline[:48])
        #     )

        if self._news_items_layout is not None:
            while self._news_items_layout.count():
                item = self._news_items_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

            release_items = self._get_release_news_items(limit=3)
            if not release_items:
                release_items = news_items[:3] if news_items else [
                    NewsItem(
                        _("Релизы недоступны", "Releases unavailable"),
                        _("Удалённая лента релизов пока недоступна.", "Remote release feed is currently unavailable."),
                    )
                ]

            for index, item in enumerate(release_items):
                self._news_items_layout.addWidget(self._build_home_news_item(item, is_fresh=index == 0))

        if self._status_line_label is not None:
            self._status_line_label.setText(self._get_status_line(news_items))

    def refresh_primary_label(self):
        if self.primary_button is not None:
            self.primary_button.setText(self._get_primary_action_label())

    def refresh_status_cards(self):
        if self._backend_status_value is not None:
            self._backend_status_value.setText(self._get_backend_status())
        if self._unity_status_value is not None:
            self._unity_status_value.setText(self._get_unity_status())
        self.refresh_primary_label()

    def on_activated(self):
        self.refresh_status_cards()
        self.refresh_news_content()
        self._refresh_update_state()

    def set_progress(self, text: str, value: int, maximum: int, *, busy: bool = False):
        if self.progress_bar is None or self.progress_label is None:
            return

        self.progress_bar.setVisible(True)
        if busy:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, max(1, maximum))
            self.progress_bar.setValue(value)
        self.progress_label.setVisible(True)
        self.progress_label.setText(text)

    def hide_progress(self):
        if self.progress_bar is not None:
            self.progress_bar.setVisible(False)
        if self.progress_label is not None:
            self.progress_label.setVisible(False)
            self.progress_label.setText("")

    def _execute_ui_call(self, fn):
        try:
            fn()
        except Exception:
            logger.exception("Failed to execute home page UI callback")

    def _queue_ui_call(self, fn):
        self._ui_call_requested.emit(fn)

    def show_extra_menu(self, anchor_widget):
        menu = QMenu(self)
        menu.setObjectName("LauncherHomeExtraMenu")
        menu.addAction(
            _("Проверить файлы / обновления", "Verify files / updates"),
            self.run_check_updates_action,
        )
        menu.addAction(
            _("Настройки обновлений", "Update settings"),
            lambda: self.gui.show_settings_category("updates"),
        )
        menu.addAction(
            _("Открыть папку Unity", "Open Unity folder"),
            self._open_unity_folder,
        )
        menu.exec(anchor_widget.mapToGlobal(QPoint(0, anchor_widget.height())))

    def _cancel_installation(self):
        """Отменяет текущую загрузку (устанавливает cancel_event)."""
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._cancel_button is not None:
            self._cancel_button.setEnabled(False)
        if self.progress_label is not None:
            self.progress_label.setText(_("Отмена…", "Cancelling…"))

    def _open_unity_folder(self):
        """Открывает папку установки Unity в проводнике."""
        unity_dir = self._get_unity_install_dir()
        try:
            unity_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            import subprocess
            subprocess.Popen(["explorer", str(unity_dir)])
        except Exception as exc:
            logger.error(f"Не удалось открыть папку Unity: {exc}")

    def run_check_updates_action(self):
        """Запускает проверку обновлений в фоне и показывает результат."""
        if self._home_install_thread_running:
            return
        self.set_progress(_("Проверка обновлений…", "Checking for updates…"), 0, 0, busy=True)

        def check_worker():
            try:
                from updater import get_python_update_info, get_unity_update_info
                channel = self.gui.settings.get("UPDATE_CHANNEL", "stable")
                base_dir = os.environ.get("NEUROMITA_BASE_DIR") or None
                unity_dir = self.gui.settings.get("UNITY_INSTALL_DIR") or None

                py_info = get_python_update_info(base_dir=base_dir, channel=channel)
                unity_info = get_unity_update_info(base_dir=base_dir, unity_dir=unity_dir, channel=channel)

                # Обновляем чекбоксы на карточках и баннер-обнову.
                self.gui._home_update_check_ts = time.monotonic()
                self._queue_ui_call(lambda: self._apply_update_state(py_info, unity_info))

                parts = []
                if py_info.get("available"):
                    parts.append(
                        _("Python: {ver}", "Python: {ver}").format(ver=_strip_v(str(py_info.get("latest_version", ""))))
                    )
                if unity_info.get("available"):
                    parts.append(
                        _("Unity: {ver}", "Unity: {ver}").format(ver=_strip_v(str(unity_info.get("latest_version", ""))))
                    )

                if parts:
                    msg = _("Доступны обновления: {p}", "Updates available: {p}").format(p=", ".join(parts))
                else:
                    msg = _("Обновлений нет.", "No updates available.")

                self._queue_ui_call(lambda m=msg: self.set_progress(m, 100, 100, busy=False))
            except Exception as exc:
                self._queue_ui_call(
                    lambda e=exc: self.set_progress(
                        _("Ошибка проверки: {err}", "Check error: {err}").format(err=e), 0, 0, busy=False
                    )
                )
            finally:
                self._queue_ui_call(lambda: QTimer.singleShot(4000, self.hide_progress))

        threading.Thread(target=check_worker, daemon=True).start()

    def run_primary_action(self):
        if self._has_pending_python_restart():
            self._prompt_restart_after_update()
            return
        # Есть обнова → центральная кнопка обновляет (выбор частей — чекбоксы,
        # код тестера спросит всплывающим окном).
        if self._has_selectable_update():
            self.run_selective_update()
            return

        exe = self.find_unity_executable()
        if exe is None:
            self.run_install_unity()
            return

        try:
            import subprocess

            subprocess.Popen(
                [str(exe)],
                cwd=str(exe.parent),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            logger.info(f"Запущен Unity: {exe}")
        except Exception as exc:
            logger.error(f"Не удалось запустить Unity: {exc}")
            QMessageBox.warning(
                self.gui,
                _("Запуск", "Launch"),
                _("Не удалось запустить Unity: {err}", "Failed to launch Unity: {err}").format(err=exc),
            )

    # Install.* events are dispatched on the bus processor thread — every
    # widget/timer mutation in these handlers must hop to the GUI thread via
    # _queue_ui_call, otherwise Qt prints "QBasicTimer::start: Timers cannot
    # be started from another thread".

    def _on_install_started(self, event):
        data = getattr(event, "data", None) or {}
        title = str(data.get("title") or data.get("name") or _("Установка", "Installation"))
        self._queue_ui_call(lambda t=title: self.set_progress(t, 0, 100, busy=True))

    def _on_install_progress(self, event):
        data = getattr(event, "data", None) or {}
        title = str(data.get("title") or data.get("name") or "")
        downloaded = float(data.get("downloaded") or data.get("current") or 0)
        total = float(data.get("total") or 0)
        message = str(data.get("message") or "")
        if total > 0:
            pct = int(max(0, min(100, downloaded / total * 100)))
            label = title or message or _("Загрузка…", "Downloading…")
            self._queue_ui_call(
                lambda l=label, p=pct: self.set_progress(f"{l} — {p}%", p, 100, busy=False)
            )
        else:
            label = title or message or _("Загрузка…", "Downloading…")
            self._queue_ui_call(lambda l=label: self.set_progress(l, 0, 0, busy=True))

    def _on_install_finished(self, event):
        def _apply():
            self.hide_progress()
            self.refresh_primary_label()
            self.refresh_status_cards()
        self._queue_ui_call(_apply)

    def _on_install_failed(self, event):
        data = getattr(event, "data", None) or {}
        err = str(data.get("error") or data.get("message") or _("ошибка", "error"))

        def _apply():
            if self.progress_label is not None:
                self.progress_label.setText(_("Ошибка: {err}", "Error: {err}").format(err=err))
                self.progress_label.setVisible(True)
            if self.progress_bar is not None:
                self.progress_bar.setVisible(False)
            self._home_install_thread_running = False
            if self.primary_button is not None:
                self.primary_button.setEnabled(True)
            self.refresh_primary_label()
            QTimer.singleShot(4000, self.hide_progress)

        self._queue_ui_call(_apply)

    def run_install_unity(self):
        if self._home_install_thread_running:
            return
        self._home_install_thread_running = True

        # Создаём событие отмены и показываем кнопку «Отменить»
        self._cancel_event = threading.Event()
        if self.primary_button is not None:
            self.primary_button.setEnabled(False)
        if self._cancel_button is not None:
            self._cancel_button.setEnabled(True)
            self._cancel_button.setVisible(True)

        self.set_progress(_("Подготовка к установке…", "Preparing installation…"), 0, 0, busy=True)

        cancel_event = self._cancel_event  # локальная ссылка для потока

        def on_progress(downloaded: int, total: int):
            def apply():
                if total > 0:
                    pct = int(max(0, min(100, downloaded * 100 / total)))
                    mb_done = downloaded / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    text = _("Загрузка Unity… {done:.1f} / {total:.1f} MB", "Downloading Unity… {done:.1f} / {total:.1f} MB").format(
                        done=mb_done,
                        total=mb_total,
                    )
                    self.set_progress(text, pct, 100, busy=False)
                else:
                    mb_done = downloaded / (1024 * 1024)
                    text = _("Загрузка Unity… {done:.1f} MB", "Downloading Unity… {done:.1f} MB").format(done=mb_done)
                    self.set_progress(text, 0, 0, busy=True)
            self._queue_ui_call(apply)

        def on_extract_progress(extracted: int, total: int):
            def apply():
                if total > 0:
                    pct = int(max(0, min(100, extracted * 100 / total)))
                    mb_done = extracted / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    text = _("Распаковка… {done:.1f} / {total:.1f} MB", "Extracting… {done:.1f} / {total:.1f} MB").format(
                        done=mb_done,
                        total=mb_total,
                    )
                    self.set_progress(text, pct, 100, busy=False)
                else:
                    self.set_progress(_("Распаковка…", "Extracting…"), 0, 0, busy=True)
            self._queue_ui_call(apply)

        class ThreadLogger:
            def __init__(self, page):
                self.page = page

            def _set(self, prefix: str, message, level: str):
                getattr(logger, level, logger.info)(f"[home_install] {message}")
                text = f"{prefix}{message}" if prefix else str(message)
                self.page._queue_ui_call(lambda value=text: self.page.set_progress(value, 0, 0, busy=True))

            def info(self, message):
                self._set("", message, "info")

            def warning(self, message):
                self._set("⚠ ", message, "warning")

            def error(self, message):
                self._set("✗ ", message, "error")

            def success(self, message):
                self._set("✓ ", message, "info")

            def notify(self, message):
                self._set("★ ", message, "info")

        ui_log = ThreadLogger(self)

        def worker():
            logger.info("[home_install] Unity install action started")
            try:
                from updater import check_for_unity_updates, get_unity_update_info

                channel = self.gui.settings.get("UPDATE_CHANNEL", "stable")
                tester_code = self.gui.settings.get("TESTER_CODE") or None
                base_dir = os.environ.get("NEUROMITA_BASE_DIR") or None
                unity_dir = self.gui.settings.get("UNITY_INSTALL_DIR") or None

                logger.info(
                    f"[home_install] params: channel={channel}, base_dir={base_dir}, "
                    f"unity_dir={unity_dir}, tester_code={'set' if tester_code else 'empty'}"
                )

                info = get_unity_update_info(base_dir=base_dir, unity_dir=unity_dir, channel=channel)
                logger.info(f"[home_install] update info: {info}")
                if not info or not info.get("ok"):
                    err = (info or {}).get("error") or _("неизвестная ошибка", "unknown error")
                    logger.warning(f"[home_install] check failed: {err}")
                    self._queue_ui_call(
                        lambda e=err: self.set_progress(
                            _("Ошибка проверки: {err}", "Check error: {err}").format(err=e),
                            0, 0, busy=False,
                        )
                    )
                    return

                if not info.get("available") and self.find_unity_executable() is not None:
                    logger.info("[home_install] Unity already up-to-date and installed")
                    self._queue_ui_call(
                        lambda: self.set_progress(_("Unity уже установлен.", "Unity already installed."), 100, 100, busy=False)
                    )
                    return

                logger.info("[home_install] Calling check_for_unity_updates(auto_update=True)")
                check_for_unity_updates(
                    base_dir=base_dir,
                    logger=ui_log,
                    unity_dir=unity_dir,
                    channel=channel,
                    tester_code=tester_code,
                    on_progress=on_progress,
                    on_extract_progress=on_extract_progress,
                    auto_update=True,
                    stop_event=cancel_event,
                )
                logger.info("[home_install] check_for_unity_updates finished")

                if cancel_event.is_set():
                    self._queue_ui_call(
                        lambda: self.set_progress(_("Установка отменена.", "Installation cancelled."), 0, 100, busy=False)
                    )
                else:
                    self._queue_ui_call(
                        lambda: self.set_progress(_("Установка завершена.", "Installation finished."), 100, 100, busy=False)
                    )
            except Exception as exc:
                logger.error(f"[home_install] Unity install failed: {exc}", exc_info=True)
                self._queue_ui_call(
                    lambda e=exc: self.set_progress(_("Ошибка: {err}", "Error: {err}").format(err=e), 0, 0, busy=False)
                )
            finally:
                logger.info("[home_install] worker finished")

                def done():
                    self._home_install_thread_running = False
                    self._cancel_event = None
                    if self._cancel_button is not None:
                        self._cancel_button.setVisible(False)
                        self._cancel_button.setEnabled(True)
                    if self.primary_button is not None:
                        self.primary_button.setEnabled(True)
                    self.refresh_primary_label()
                    self.refresh_status_cards()
                    QTimer.singleShot(4000, self.hide_progress)

                self._queue_ui_call(done)

        threading.Thread(target=worker, daemon=True).start()

    def _prompt_restart_after_update(self) -> bool:
        """Спросить про перезапуск после применения Python-обновления."""
        from utils.app_restart import restart_app

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Обновление установлено", "Update installed"))
        box.setText(_(
            "Python-обновление установлено.\n\n"
            "Перезапустить приложение сейчас, чтобы применить его?\n"
            "(До перезапуска программа работает на старой версии.)",
            "The Python update has been installed.\n\n"
            "Restart the app now to apply it?\n"
            "(Until you restart, the app keeps running the old version.)",
        ))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        if box.exec() == QMessageBox.StandardButton.Yes:
            return bool(restart_app())
        return False

    def run_selective_update(self):
        """Установить отмеченные на карточках части. Python — первым."""
        if self._home_install_thread_running:
            return

        pending_python_version = str((self._update_info_py or {}).get("latest_version") or "").strip()
        want_py = bool(
            self._py_update_check is not None
            and self._py_update_check.isVisible()
            and self._py_update_check.isChecked()
        )
        want_unity = bool(
            self._unity_update_check is not None
            and self._unity_update_check.isVisible()
            and self._unity_update_check.isChecked()
        )
        if not want_py and not want_unity:
            self.set_progress(
                _("Нечего обновлять: отметь Python или Unity.", "Nothing selected: check Python or Unity."),
                0, 100, busy=False,
            )
            QTimer.singleShot(3500, self.hide_progress)
            return

        # Код тестера: из поля/настроек, иначе спрашиваем модалкой.
        tester_code = self._effective_tester_code()
        if not tester_code:
            tester_code = self._prompt_tester_code()
            if tester_code is None:
                self.set_progress(
                    _("Обновление отменено: код тестера не введён.", "Update cancelled: tester code not entered."),
                    0, 100, busy=False,
                )
                QTimer.singleShot(3500, self.hide_progress)
                return

        self._home_install_thread_running = True
        self._cancel_event = threading.Event()
        if self.primary_button is not None:
            self.primary_button.setEnabled(False)
        if self._cancel_button is not None:
            self._cancel_button.setEnabled(True)
            self._cancel_button.setVisible(True)

        self.set_progress(_("Подготовка к установке…", "Preparing installation…"), 0, 0, busy=True)
        cancel_event = self._cancel_event

        def on_progress(downloaded: int, total: int):
            def apply():
                if total > 0:
                    pct = int(max(0, min(100, downloaded * 100 / total)))
                    mb_done = downloaded / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    self.set_progress(
                        _("Загрузка… {done:.1f} / {total:.1f} MB", "Downloading… {done:.1f} / {total:.1f} MB").format(
                            done=mb_done, total=mb_total),
                        pct, 100, busy=False,
                    )
                else:
                    mb_done = downloaded / (1024 * 1024)
                    self.set_progress(
                        _("Загрузка… {done:.1f} MB", "Downloading… {done:.1f} MB").format(done=mb_done),
                        0, 0, busy=True,
                    )
            self._queue_ui_call(apply)

        def on_extract_progress(extracted: int, total: int):
            def apply():
                if total > 0:
                    pct = int(max(0, min(100, extracted * 100 / total)))
                    self.set_progress(_("Распаковка…", "Extracting…"), pct, 100, busy=False)
                else:
                    self.set_progress(_("Распаковка…", "Extracting…"), 0, 0, busy=True)
            self._queue_ui_call(apply)

        class ThreadLogger:
            def __init__(self, page):
                self.page = page

            def _set(self, prefix: str, message, level: str):
                getattr(logger, level, logger.info)(f"[home_update] {message}")
                text = f"{prefix}{message}" if prefix else str(message)
                self.page._queue_ui_call(lambda value=text: self.page.set_progress(value, 0, 0, busy=True))

            def info(self, message):
                self._set("", message, "info")

            def warning(self, message):
                self._set("⚠ ", message, "warning")

            def error(self, message):
                self._set("✗ ", message, "error")

            def success(self, message):
                self._set("✓ ", message, "info")

            def notify(self, message):
                self._set("★ ", message, "info")

        ui_log = ThreadLogger(self)

        def worker():
            logger.info(f"[home_update] selective update started: py={want_py}, unity={want_unity}")
            py_applied = False
            try:
                from updater import check_for_unity_updates, check_for_updates

                channel = self.gui.settings.get("UPDATE_CHANNEL", "stable")
                base_dir = os.environ.get("NEUROMITA_BASE_DIR") or None
                unity_dir = self.gui.settings.get("UNITY_INSTALL_DIR") or None

                # Python — первым: лёгкий и требует перезапуска, не ждём Unity.
                if want_py:
                    self._queue_ui_call(
                        lambda: self.set_progress(_("Обновление Python…", "Updating Python…"), 0, 0, busy=True)
                    )
                    py_applied = bool(check_for_updates(
                        base_dir=base_dir,
                        logger=ui_log,
                        channel=channel,
                        tester_code=tester_code,
                        on_progress=on_progress,
                        auto_update=True,
                        restart_on_success=False,
                        update_mode=(self.gui.settings.get("UPDATE_MODE", "diff") or "diff"),
                        preserve_prompts=bool(self.gui.settings.get("UPDATE_PRESERVE_PROMPTS", True)),
                    ))

                if want_unity and not cancel_event.is_set():
                    self._queue_ui_call(
                        lambda: self.set_progress(_("Обновление Unity…", "Updating Unity…"), 0, 0, busy=True)
                    )
                    check_for_unity_updates(
                        base_dir=base_dir,
                        logger=ui_log,
                        unity_dir=unity_dir,
                        channel=channel,
                        tester_code=tester_code,
                        on_progress=on_progress,
                        on_extract_progress=on_extract_progress,
                        auto_update=True,
                        stop_event=cancel_event,
                    )

                if cancel_event.is_set():
                    self._queue_ui_call(
                        lambda: self.set_progress(_("Установка отменена.", "Installation cancelled."), 0, 100, busy=False)
                    )
                else:
                    self._queue_ui_call(
                        lambda: self.set_progress(_("Установка завершена.", "Installation finished."), 100, 100, busy=False)
                    )
            except Exception as exc:
                logger.error(f"[home_update] selective update failed: {exc}", exc_info=True)
                self._queue_ui_call(
                    lambda e=exc: self.set_progress(_("Ошибка: {err}", "Error: {err}").format(err=e), 0, 0, busy=False)
                )
            finally:
                def done():
                    self._home_install_thread_running = False
                    self._cancel_event = None
                    if self._cancel_button is not None:
                        self._cancel_button.setVisible(False)
                        self._cancel_button.setEnabled(True)
                    if self.primary_button is not None:
                        self.primary_button.setEnabled(True)
                    if py_applied and not cancel_event.is_set():
                        self._mark_python_restart_required(pending_python_version)
                    try:
                        self.refresh_status_cards()
                        # Перепроверим состояние обновлений (баннер/чекбоксы).
                        self._refresh_update_state(force=True)
                    except Exception:
                        logger.error("[home_update] Post-update UI refresh failed", exc_info=True)
                    restart_started = False
                    try:
                        if py_applied and not cancel_event.is_set():
                            restart_started = self._prompt_restart_after_update()
                    except Exception:
                        logger.error("[home_update] Failed to show restart prompt", exc_info=True)
                    if not restart_started:
                        QTimer.singleShot(4000, self.hide_progress)

                self._queue_ui_call(done)

        threading.Thread(target=worker, daemon=True).start()


def build_home_page(window) -> QWidget:
    return HomePage(window)
