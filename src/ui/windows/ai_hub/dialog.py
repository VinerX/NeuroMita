from __future__ import annotations

import datetime as _dt
import os
import shutil
import threading
from typing import Any

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.events import Events, get_event_bus
from core.services import services
from services.contracts import InstallableCatalogService, SettingsService
from services.installable_catalog_service import DefaultInstallableCatalogService
from main_logger import logger
from styles.ai_hub_styles import get_stylesheet as get_ai_hub_stylesheet
from ui.windows.voice_action_windows import VoiceInstallationWindow
from utils import getTranslationVariant as _
from utils.gpu_utils import check_gpu_provider, format_primary_gpu_label, get_primary_gpu_name

from .constants import CATEGORY_ICONS, CATEGORY_LABELS, CATEGORY_ORDER, ROW_CATEGORY_MAP
from .helpers import meta_from_row, qicon, qpixmap, row_category, status_from_row
from .widgets import CategoryButton, ModelCard, Stat


class AIHubDialog(QDialog):
    # Cross-thread dispatcher: event-bus callbacks emit a lambda here and the
    # connected slot runs it on the GUI thread (QueuedConnection by default).
    _ui_call_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.event_bus = get_event_bus()
        registry = services()
        if registry.is_registered(InstallableCatalogService):
            self.catalog = registry.get(InstallableCatalogService)
        else:
            settings = registry.get(SettingsService) if registry.is_registered(SettingsService) else None
            self.catalog = DefaultInstallableCatalogService(settings)
            registry.register(InstallableCatalogService, self.catalog)
        self._rows: list[dict[str, Any]] = []
        self._selected_category = "tts"
        self._pending_category: str | None = None
        self._pending_component_id: str | None = None
        self._last_task_status = ""
        self._loaded_once = False
        self._last_check_ts: _dt.datetime | None = None
        self._category_buttons: dict[str, CategoryButton] = {}
        self._active_install_window: VoiceInstallationWindow | None = None
        self._queue_state: dict[str, Any] = {"running": None, "pending": []}
        self._refresh_generation = 0
        self._refresh_inflight = False
        self._rendered_language = ""
        self._main_controller = None
        self._pending_backend_actions: set[tuple[str, str]] = set()

        self._ui_call_requested.connect(self._execute_ui_call)

        self._build()
        self._bind_events()

        # Живая смена языка: диалог — синглтон (не пересоздаётся при переоткрытии),
        # поэтому карточки/кнопки застывают на языке первого рендера. Перерисовываем
        # по сигналу смены языка (или при следующем показе, если был скрыт).
        try:
            from localization.live import language_changed_signal
            language_changed_signal().connect(self._on_language_changed)
        except Exception:
            pass

    # ------------------------------------------------------------ thread hop
    def _execute_ui_call(self, fn) -> None:
        try:
            fn()
        except Exception:
            logger.exception("AI Hub: UI callback failed")

    def _on_gui_thread(self, fn) -> None:
        """Schedule `fn` to run on the GUI thread.

        Event-bus callbacks fire on the bus's processor thread, so any Qt
        widget mutation (incl. QTimer.start) must be marshalled here first.
        """
        self._ui_call_requested.emit(fn)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self.setObjectName("AIHubDialog")
        self.setWindowTitle(_("AI Hub", "AI Hub"))
        self.setModal(False)
        # Размеры под экран: на узких/масштабированных дисплеях жёсткие 1280×820 и
        # min 1100×700 уводили контент (сайдбар + панель настроек) за левую кромку
        # окна — «интерфейс поехал» (#21). Клампим к доступной геометрии экрана и
        # центрируем, чтобы окно гарантированно помещалось и не уезжало off-screen.
        self.setStyleSheet(get_ai_hub_stylesheet())
        self._apply_screen_aware_geometry(preferred=(1280, 820), minimum=(1000, 640))

        # Use the native OS window chrome — no custom title bar, no shadow.
        # The root frame stays as a styling anchor so the QSS still matches
        # everything inside it.
        root_outer = QVBoxLayout(self)
        root_outer.setContentsMargins(0, 0, 0, 0)

        self._card = QFrame()
        self._card.setObjectName("AIHubRoot")
        root_outer.addWidget(self._card)

        root = QVBoxLayout(self._card)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)

        root.addLayout(self._build_header())
        root.addLayout(self._build_body(), 1)
        root.addLayout(self._build_footer())
        root.addWidget(self._build_install_bar())

    def _build_install_bar(self) -> QFrame:
        """Нижняя плашка установки «как в Steam» (#25): во время установки показывает
        текущий компонент, прогресс-бар и процент·скорость. В простое скрыта."""
        from PyQt6.QtWidgets import QProgressBar

        bar = QFrame()
        bar.setObjectName("AIHubInstallBar")
        bar.setVisible(False)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(12)

        self._install_bar_icon = QLabel()
        self._install_bar_icon.setFixedSize(16, 16)
        pix = qpixmap("fa5s.download", "#dc588a", 14)
        if pix is not None:
            self._install_bar_icon.setPixmap(pix)
        lay.addWidget(self._install_bar_icon, 0)

        self._install_bar_title = QLabel("")
        self._install_bar_title.setObjectName("AIHubInstallBarTitle")
        lay.addWidget(self._install_bar_title, 0)

        self._install_bar_progress = QProgressBar()
        self._install_bar_progress.setObjectName("AIHubInstallBarProgress")
        self._install_bar_progress.setRange(0, 100)
        self._install_bar_progress.setValue(0)
        self._install_bar_progress.setTextVisible(False)
        self._install_bar_progress.setFixedHeight(8)
        lay.addWidget(self._install_bar_progress, 1)

        self._install_bar_detail = QLabel("")
        self._install_bar_detail.setObjectName("AIHubInstallBarDetail")
        lay.addWidget(self._install_bar_detail, 0)

        # Чип очереди: «+N в очереди» (полный список — в всплывающей подсказке).
        self._install_bar_queue = QLabel("")
        self._install_bar_queue.setObjectName("AIHubInstallBarQueue")
        self._install_bar_queue.setVisible(False)
        lay.addWidget(self._install_bar_queue, 0)

        # Кнопка возврата к окну логов установки — переехала с левого края в
        # нижнюю плашку, чтобы разгрузить сайдбар и быть всегда на виду (фидбэк Артёма).
        self._install_logs_btn = QPushButton(_("Логи установки", "Install logs"))
        self._install_logs_btn.setObjectName("AIHubInstallBarLogsBtn")
        self._install_logs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._install_logs_btn.setVisible(False)
        logs_icon = qicon("fa5s.terminal", "#f0d9e6")
        if logs_icon is not None:
            self._install_logs_btn.setIcon(logs_icon)
            self._install_logs_btn.setIconSize(QSize(13, 13))
        self._install_logs_btn.clicked.connect(self._on_reopen_install_logs)
        lay.addWidget(self._install_logs_btn, 0)

        self._install_bar = bar
        return bar

    def _set_install_bar(self, *, visible: bool, title: str = "", progress=None, detail: str = "") -> None:
        bar = getattr(self, "_install_bar", None)
        if bar is None:
            return
        bar.setVisible(bool(visible))
        if not visible:
            return
        if title:
            self._install_bar_title.setText(self._shorten(title, 42))
        if progress is None:
            # Неопределённый прогресс — «бегущая» полоса.
            self._install_bar_progress.setRange(0, 0)
        else:
            self._install_bar_progress.setRange(0, 100)
            try:
                self._install_bar_progress.setValue(max(0, min(100, int(progress))))
            except Exception:
                pass
        self._install_bar_detail.setText(detail or "")

    def _apply_screen_aware_geometry(self, *, preferred: tuple[int, int], minimum: tuple[int, int]) -> None:
        """Подгоняем размер окна под доступную геометрию экрана и центрируем.
        Гарантирует, что окно помещается на экран и не уезжает за левую кромку (#21)."""
        from PyQt6.QtWidgets import QApplication
        try:
            screen = self.screen() or QApplication.primaryScreen()
            avail = screen.availableGeometry()
        except Exception:
            self.resize(*preferred)
            self.setMinimumSize(*minimum)
            return

        margin = 48  # запас под рамки/таскбар
        max_w = max(minimum[0], avail.width() - margin)
        max_h = max(minimum[1], avail.height() - margin)
        w = min(preferred[0], max_w)
        h = min(preferred[1], max_h)
        # Минимум не должен превышать доступный экран, иначе окно нельзя ужать
        # и контент клиппится.
        self.setMinimumSize(min(minimum[0], w), min(minimum[1], h))
        self.resize(w, h)
        # Центрируем в доступной области экрана.
        x = avail.x() + max(0, (avail.width() - w) // 2)
        y = avail.y() + max(0, (avail.height() - h) // 2)
        self.move(x, y)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(14)

        badge = QLabel()
        badge.setObjectName("AIHubIconBadge")
        badge.setFixedSize(48, 48)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = qpixmap("fa5s.magic", "#b74b7d", 22)
        if pix is not None:
            badge.setPixmap(pix)
        else:
            badge.setText("✦")
        header.addWidget(badge, 0)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        title = QLabel(_("AI Hub", "AI Hub"))
        title.setObjectName("AIHubTitle")
        title_box.addWidget(title)
        subtitle = QLabel(
            _(
                "Установка, удаление и обслуживание локальных AI-компонентов и системных зависимостей.",
                "Install, remove and maintain local AI components and system dependencies.",
            )
        )
        subtitle.setObjectName("AIHubSubtitle")
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        # native OS window chrome already provides a close button
        return header

    def _build_body(self) -> QHBoxLayout:
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        body.addWidget(self._build_sidebar(), 0)
        body.addLayout(self._build_main_column(), 1)
        return body

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("AIHubSidebar")
        sidebar.setFixedWidth(258)
        l = QVBoxLayout(sidebar)
        l.setContentsMargins(14, 16, 14, 14)
        l.setSpacing(8)

        cat_header = QLabel(_("КАТЕГОРИИ", "CATEGORIES"))
        cat_header.setObjectName("AIHubSidebarHeader")
        l.addWidget(cat_header)

        for key in CATEGORY_ORDER:
            btn = CategoryButton(
                key,
                CATEGORY_LABELS.get(key, key),
                CATEGORY_ICONS.get(key, "fa5s.circle"),
                self._select_category,
                sidebar,
            )
            self._category_buttons[key] = btn
            l.addWidget(btn, 0)

        self._activity_panel = QFrame()
        self._activity_panel.setObjectName("AIHubActivityPanel")
        self._activity_layout = QVBoxLayout(self._activity_panel)
        self._activity_layout.setContentsMargins(10, 10, 10, 10)
        self._activity_layout.setSpacing(8)
        self._activity_panel.setVisible(False)

        self._activity_header = QLabel(_("АКТИВНОСТЬ", "ACTIVITY"))
        self._activity_header.setObjectName("AIHubSidebarHeader")
        self._activity_layout.addWidget(self._activity_header)

        # task status (install / progress)
        self.task_status_label = QLabel("")
        self.task_status_label.setObjectName("AIHubSidebarStatus")
        self.task_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.task_status_label.setWordWrap(True)
        self.task_status_label.setVisible(False)
        self._activity_layout.addWidget(self.task_status_label)

        # Панель очереди установок: текущая задача + ожидающие (с кнопкой отмены).
        self._queue_panel = QFrame()
        self._queue_panel.setObjectName("AIHubQueuePanel")
        self._queue_layout = QVBoxLayout(self._queue_panel)
        self._queue_layout.setContentsMargins(8, 8, 8, 8)
        self._queue_layout.setSpacing(4)
        self._queue_panel.setVisible(False)
        self._activity_layout.addWidget(self._queue_panel)

        # Кнопка «Логи установки» переехала в нижнюю плашку (_build_install_bar),
        # чтобы разгрузить левый край (фидбэк Артёма). Здесь её больше нет.

        l.addWidget(self._activity_panel)

        l.addStretch(1)

        # "Check for updates" button sits at the very bottom of the sidebar
        self.btn_refresh = QPushButton(_("Проверить обновления", "Check for updates"))
        self.btn_refresh.setObjectName("AIHubSidebarBtn")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setText(_("Обновить список", "Refresh list"))
        ic = qicon("fa5s.sync", "#b74b7d")
        if ic is not None:
            self.btn_refresh.setIcon(ic)
            self.btn_refresh.setIconSize(QSize(13, 13))
        self.btn_refresh.clicked.connect(lambda: self.refresh(force=True))
        l.addWidget(self.btn_refresh)

        # Очистка кэша установщика (pip/uv). Кэш включён, чтобы прерванные
        # загрузки докачивались; кнопка освобождает место при необходимости.
        self.btn_clear_cache = QPushButton(_("Очистить кэш загрузок", "Clear download cache"))
        self.btn_clear_cache.setObjectName("AIHubSidebarBtn")
        self.btn_clear_cache.setCursor(Qt.CursorShape.PointingHandCursor)
        ic_cache = qicon("fa5s.broom", "#b74b7d")
        if ic_cache is not None:
            self.btn_clear_cache.setIcon(ic_cache)
            self.btn_clear_cache.setIconSize(QSize(13, 13))
        self.btn_clear_cache.clicked.connect(self._clear_install_cache)
        l.addWidget(self.btn_clear_cache)

        return sidebar

    def _clear_install_cache(self) -> None:
        import threading

        self._set_task_status(_("Очистка кэша...", "Clearing cache..."))

        def _worker():
            ok = False
            try:
                from utils.pip_installer import PipInstaller
                ok = bool(PipInstaller(update_log=logger.info).purge_cache())
            except Exception as exc:
                logger.error(f"AI Hub: clear cache failed: {exc}", exc_info=True)
            msg = _("Кэш очищен", "Cache cleared") if ok else _("Не удалось очистить кэш", "Failed to clear cache")
            self._on_gui_thread(lambda: (
                self._set_task_status(msg),
                QTimer.singleShot(2500, lambda: self._set_task_status("")),
            ))

        threading.Thread(target=_worker, daemon=True).start()

    def _build_main_column(self) -> QVBoxLayout:
        from PyQt6.QtWidgets import QStackedWidget
        from .settings_panel import SettingsPanel

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)

        col.addLayout(self._build_tab_switcher())
        col.addWidget(self._build_banner())

        # ---- stacked content: page 0 = install (list), page 1 = settings
        self._stack = QStackedWidget()
        self._stack.setObjectName("AIHubStack")

        # install page (existing layout)
        install_page = QWidget()
        ip = QVBoxLayout(install_page)
        ip.setContentsMargins(0, 0, 0, 0)
        ip.setSpacing(14)
        ip.addLayout(self._build_toolbar())
        ip.addWidget(self._build_scroll(), 1)
        self._stack.addWidget(install_page)

        # settings page
        self._settings_panel = SettingsPanel()
        self._stack.addWidget(self._settings_panel)

        col.addWidget(self._stack, 1)
        return col

    def _build_banner(self) -> QFrame:
        self.banner = QFrame()
        self.banner.setObjectName("AIHubBanner")
        self.banner.setVisible(False)
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(18, 14, 18, 14)
        bl.setSpacing(14)

        ico = QLabel()
        ico.setObjectName("AIHubBannerIcon")
        ico.setFixedSize(46, 46)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = qpixmap("fa5s.microchip", "#b74b7d", 22)
        if pix is not None:
            ico.setPixmap(pix)
        bl.addWidget(ico, 0)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        self.banner_title = QLabel("")
        self.banner_title.setObjectName("AIHubBannerTitle")
        self.banner_title.setTextFormat(Qt.TextFormat.RichText)
        text_col.addWidget(self.banner_title)
        self.banner_body = QLabel("")
        self.banner_body.setObjectName("AIHubBannerBody")
        self.banner_body.setWordWrap(True)
        text_col.addWidget(self.banner_body)
        bl.addLayout(text_col, 1)

        self.banner_button = QPushButton(_("Оптимизировать", "Optimize"))
        self.banner_button.setObjectName("AIHubPrimary")
        self.banner_button.setCursor(Qt.CursorShape.PointingHandCursor)
        bi = qicon("fa5s.bolt", "white")
        if bi is not None:
            self.banner_button.setIcon(bi)
            self.banner_button.setIconSize(QSize(13, 13))
        self.banner_button.clicked.connect(self._install_cuda_backend)
        bl.addWidget(self.banner_button, 0)

        self.banner_dismiss = QPushButton(_("Позже", "Later"))
        self.banner_dismiss.setObjectName("AIHubSecondary")
        self.banner_dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        self.banner_dismiss.clicked.connect(lambda: self.banner.setVisible(False))
        bl.addWidget(self.banner_dismiss, 0)

        return self.banner

    def _build_toolbar(self) -> QVBoxLayout:
        """Two-row toolbar.

        Row 1: «Доступные компоненты» (page header) + backend filter pills
               + search + sort.
        Row 2: install / settings tab switcher.
        """
        wrap = QVBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)

        title = QLabel(_("Доступные компоненты", "Available components"))
        title.setObjectName("AIHubSectionTitle")
        top.addWidget(title, 0)

        # «Открыть папку моделей» — показываем только в категории «Голоса Мит»,
        # чтобы можно было вручную положить голосовые файлы (свой бандл, или
        # когда автоустановка недоступна).
        self._open_models_btn = QPushButton(_("Открыть папку моделей", "Open models folder"))
        self._open_models_btn.setObjectName("AIHubSecondary")
        self._open_models_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_icon = qicon("fa5s.folder-open", "#b74b7d")
        if folder_icon is not None:
            self._open_models_btn.setIcon(folder_icon)
            self._open_models_btn.setIconSize(QSize(13, 13))
        self._open_models_btn.clicked.connect(self._open_models_folder)
        self._open_models_btn.setVisible(self._selected_category == "voices")
        top.addWidget(self._open_models_btn, 0)

        top.addStretch(1)

        # backend filter pills
        self._backend_filter = "all"
        self._backend_filter_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("all", _("Все", "All")),
            ("cuda", "NVIDIA / CUDA"),
            ("onnx", "ONNX"),
            ("cpu", "CPU"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("AIHubFilterPill")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("active", "true" if key == "all" else "false")
            btn.clicked.connect(lambda _checked, k=key: self._set_backend_filter(k))
            self._backend_filter_buttons[key] = btn
            top.addWidget(btn, 0)
        self._backend_filter_buttons["all"].setChecked(True)

        top.addSpacing(6)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("AIHubSearch")
        self.search_box.setPlaceholderText(_("Поиск компонентов...", "Search components..."))
        self.search_box.setFixedWidth(240)
        si = qicon("fa5s.search", "#bca9bb")
        if si is not None:
            action = self.search_box.addAction(si, QLineEdit.ActionPosition.LeadingPosition)
            action.setEnabled(False)
        self.search_box.textChanged.connect(self._rebuild_component_list)
        top.addWidget(self.search_box, 0)

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("AIHubSort")
        self.sort_combo.setFixedWidth(220)
        self.sort_combo.addItem(_("По умолчанию", "Default"), "default")
        self.sort_combo.addItem(_("Сначала установленные", "Installed first"), "installed")
        self.sort_combo.addItem(_("По имени", "By name"), "name")
        self.sort_combo.currentIndexChanged.connect(self._rebuild_component_list)
        top.addWidget(self.sort_combo, 0)

        wrap.addLayout(top)
        return wrap

    def _build_tab_switcher(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._tab_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("install", _("Установка", "Install")),
            ("settings", _("Настройки", "Settings")),
        ):
            btn = QPushButton(label)
            btn.setObjectName("AIHubTabBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("active", "true" if key == "install" else "false")
            btn.clicked.connect(lambda _c, k=key: self._set_tab(k))
            row.addWidget(btn, 0)
            self._tab_buttons[key] = btn
        row.addStretch(1)
        return row

    def _build_scroll(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("AIHubScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._scroll_content = QWidget()
        self._scroll_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 8, 0)
        self._scroll_layout.setSpacing(10)
        self._scroll_layout.addStretch(1)

        scroll.setWidget(self._scroll_content)
        return scroll

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(12)

        self.stat_installed = Stat("fa5s.download", _("Установлено", "Installed"))
        # «Доступно обновлений» убрано: компоненты AI Hub не обновляются инкрементально,
        # счётчик всегда был 0 и только путал (фидбэк Артёма).
        self.stat_gpu = Stat("fa5s.microchip", "GPU")
        self.stat_disk = Stat("fa5s.hdd", _("Свободно на диске", "Free disk"))
        self.stat_check = Stat("fa5s.clock", _("Последняя проверка", "Last check"))

        for s in (self.stat_installed, self.stat_gpu, self.stat_disk, self.stat_check):
            s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            footer.addWidget(s, 1)

        return footer

    # ----------------------------------------------------------- events
    def _bind_events(self) -> None:
        self.event_bus.subscribe(Events.Install.TASK_STARTED, self._on_install_started, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_PROGRESS, self._on_install_progress, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)
        self.event_bus.subscribe(Events.Install.QUEUE_CHANGED, self._on_queue_changed, weak=False)

    def apply_payload(self, payload: dict[str, Any] | None) -> None:
        data = payload if isinstance(payload, dict) else {}
        cat = str(data.get("category") or "").strip().lower()
        cat = ROW_CATEGORY_MAP.get(cat, cat)
        cid = str(data.get("component_id") or "").strip()
        if cat:
            self._pending_category = cat
        if cid:
            self._pending_component_id = cid
            # Сразу переключаемся на вкладку «Настройки», не дожидаясь загрузки
            # списка (иначе окно открывается на «Установке» и переезжает только
            # через 1-3 сек). Само выделение модели произойдёт в _refresh_views,
            # когда данные подтянутся.
            self._set_tab("settings")
        if self._loaded_once and self._rows:
            self._refresh_views()
        else:
            self.refresh(force=True)

    def _current_ui_language(self) -> str:
        try:
            from localization import _current_language
            return _current_language()
        except Exception:
            return ""

    def _on_language_changed(self, *_a) -> None:
        # Видимый диалог перерисовываем сразу; скрытый — обновит showEvent при
        # следующем открытии (сравнение _rendered_language с текущим языком).
        if self.isVisible():
            try:
                self._refresh_views()
            except Exception:
                logger.exception("AI Hub: re-render on language change failed")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ensure_install_gui_adapter()
        if not self._loaded_once and not self._refresh_inflight:
            QTimer.singleShot(0, lambda: self.refresh(force=False))
        elif self._loaded_once and self._rendered_language and self._rendered_language != self._current_ui_language():
            # Язык сменился, пока диалог был скрыт — перерисовываем в текущем языке.
            QTimer.singleShot(0, self._refresh_views)

    def _ensure_install_gui_adapter(self) -> None:
        main_controller = self._find_main_controller()
        self._main_controller = main_controller
        gui_controller = getattr(main_controller, "gui_controller", None)
        if gui_controller is None:
            return
        try:
            gui_controller.ensure_optional_gui("install")
        except Exception as exc:
            logger.warning(f"AI Hub install GUI adapter is unavailable: {exc}")

    def refresh(self, *, force: bool = False, include_status: bool | None = None) -> None:
        if include_status is None:
            include_status = bool(force or self._loaded_once)

        self._refresh_generation += 1
        generation = self._refresh_generation
        self._refresh_inflight = True
        self.btn_refresh.setEnabled(False)
        # Пока данных ещё нет (первое открытие) — показываем индикатор загрузки
        # вместо пустого списка (иначе 1-3 сек видно «0 моделей»). Если карточки
        # уже есть (пере-опрос) — не мигаем, оставляем их на экране.
        if not self._rows:
            self._show_scroll_loading()
        elif force:
            # #6: принудительная проверка (после установки / кнопкой) реально
            # опрашивает файлы каждого компонента и это не мгновенно. Пока идёт
            # проверка — показываем на карточках «Проверка файлов…» и блокируем
            # кнопку «Установить», чтобы её нельзя было нажать повторно.
            self._set_cards_checking()

        status_category = self._selected_category if include_status else None

        def _worker() -> None:
            rows = self._fetch_rows(
                force=force,
                include_status=bool(include_status),
                status_category=status_category,
            )
            checked_at = _dt.datetime.now()
            self._on_gui_thread(
                lambda: self._apply_refresh_result(
                    generation, rows, checked_at, bool(include_status)
                )
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_refresh_result(
        self,
        generation: int,
        rows: list[dict[str, Any]],
        checked_at: _dt.datetime,
        included_status: bool,
    ) -> None:
        if generation != self._refresh_generation:
            return
        self._refresh_inflight = False
        self.btn_refresh.setEnabled(True)
        # Пустой ответ при наличии прежних данных — почти всегда таймаут/сбой
        # переопроса (а не реально пустой список: встроенные компоненты есть всегда).
        # Не стираем уже показанные карточки, иначе «все модели исчезают» (фидбэк Артёма).
        if not rows and self._rows:
            logger.warning("AI Hub: пустой результат обновления — оставляю прежний список компонентов")
            self._last_check_ts = checked_at
            self._refresh_views()
            return
        self._rows = rows
        self._loaded_once = True
        self._last_check_ts = checked_at
        self._refresh_views()

        # First paint uses cheap metadata only. File/package status checks are
        # a second background phase so opening AI Hub never waits several
        # seconds before showing the component catalog.
        if rows and not included_status:
            QTimer.singleShot(0, lambda: self.refresh(force=False, include_status=True))

    def _refresh_views(self) -> None:
        self._rebuild_category_list()
        self._update_banner()
        self._rebuild_component_list()
        self._update_summary()
        # propagate the same row set to the Settings panel
        if hasattr(self, "_settings_panel"):
            self._settings_panel.apply_data(self._rows, self._selected_category)
        # Отложенный переход к настройкам конкретного компонента (шестерёнка у модели
        # озвучки и т.п.): открываем вкладку «Настройки» и выделяем нужную модель.
        if self._pending_component_id:
            cid = self._pending_component_id
            self._pending_component_id = None
            self._open_component_settings(cid)
        # Запоминаем язык последнего рендера (для перерисовки после смены языка).
        self._rendered_language = self._current_ui_language()

    # ----------------------------------------------------------- tabs & filters
    def _set_tab(self, key: str) -> None:
        key = key if key in ("install", "settings") else "install"
        for k, btn in self._tab_buttons.items():
            btn.setProperty("active", "true" if k == key else "false")
            btn.setChecked(k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._stack.setCurrentIndex(1 if key == "settings" else 0)
        # the settings panel should reflect the current category when shown
        if key == "settings" and hasattr(self, "_settings_panel"):
            self._settings_panel.apply_data(self._rows, self._selected_category)

    def _set_backend_filter(self, key: str) -> None:
        key = key if key in ("all", "cuda", "onnx", "cpu") else "all"
        self._backend_filter = key
        for k, btn in self._backend_filter_buttons.items():
            btn.setChecked(k == key)
            btn.setProperty("active", "true" if k == key else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._rebuild_component_list()

    def _open_component_settings(self, component_id: str) -> None:
        self._set_tab("settings")
        if hasattr(self, "_settings_panel"):
            self._settings_panel.apply_data(self._rows, self._selected_category)
            self._settings_panel.select_component(component_id)

    def _find_main_controller(self):
        current = self.parent()
        while current is not None:
            controller = getattr(current, "main_controller", None)
            if controller is not None:
                return controller
            current = current.parent() if hasattr(current, "parent") else None
        window = self.window()
        return getattr(window, "main_controller", None) if window is not None else None

    def _fetch_rows(
        self,
        *,
        force: bool = False,
        include_status: bool = True,
        status_category: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            return self.catalog.list_rows(
                include_status=bool(include_status),
                refresh=bool(force),
                status_category=status_category,
            )
        except Exception as exc:
            logger.error(f"AI Hub refresh failed: {exc}", exc_info=True)
            return []

    # ----------------------------------------------------------- categories
    def _rebuild_category_list(self) -> None:
        counts = {key: 0 for key in CATEGORY_ORDER}
        for row in self._rows:
            cat = row_category(row)
            if cat in counts:
                counts[cat] += 1

        selected = self._pending_category or self._selected_category or "tts"
        if selected not in CATEGORY_ORDER:
            selected = "tts"

        for key, btn in self._category_buttons.items():
            btn.setCount(counts.get(key, 0))
            btn.setSelected(key == selected)

        self._selected_category = selected
        self._pending_category = None

    def _select_category(self, key: str) -> None:
        if key not in CATEGORY_ORDER:
            return
        self._selected_category = key
        for k, btn in self._category_buttons.items():
            btn.setSelected(k == key)
        self._rebuild_component_list()
        if hasattr(self, "_settings_panel"):
            self._settings_panel.apply_data(self._rows, key)
        self._update_summary()
        if self._loaded_once and not self._refresh_inflight and not self._category_status_loaded(key):
            QTimer.singleShot(0, lambda: self.refresh(force=False, include_status=True))

    def _category_status_loaded(self, category: str) -> bool:
        rows = [row for row in self._rows if row_category(row) == category]
        return bool(rows) and all(isinstance(row.get("status"), dict) for row in rows)

    # ----------------------------------------------------------- filtering
    def _filtered_rows(self) -> list[dict[str, Any]]:
        from .helpers import is_backend_compatible

        query = str(self.search_box.text() or "").strip().lower()
        category = self._selected_category
        backend_filter = getattr(self, "_backend_filter", "all")
        gpu_vendor = self._detect_gpu_vendor()

        rows: list[dict[str, Any]] = []
        for row in self._rows:
            meta = meta_from_row(row)
            status = status_from_row(row)
            if category and row_category(row) != category:
                continue
            backend = str(meta.get("backend") or "").strip().lower()
            if backend_filter != "all" and backend != backend_filter:
                # exception: "cpu"/"none" components stay visible under any
                # filter — they're universally compatible
                if backend not in ("cpu", "none", ""):
                    continue
            haystack = " ".join(
                [
                    str(meta.get("id") or ""),
                    str(meta.get("title") or ""),
                    str(meta.get("description") or ""),
                    str(meta.get("backend") or ""),
                    " ".join(str(x) for x in (meta.get("tags") or [])),
                    " ".join(str(x) for x in (meta.get("languages") or [])),
                    str(status.get("message") or ""),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            rows.append(row)

        mode = str(self.sort_combo.currentData() or "default")

        def _compat_rank(r: dict[str, Any]) -> int:
            # 0 = compatible or already installed; 1 = incompatible -> bottom
            status = status_from_row(r)
            if status.get("installed") or status.get("ready"):
                return 0
            return 0 if is_backend_compatible(str(meta_from_row(r).get("backend") or ""), gpu_vendor) else 1

        if mode == "installed":
            rows.sort(
                key=lambda r: (
                    _compat_rank(r),
                    0 if status_from_row(r).get("installed") else 1,
                    str(meta_from_row(r).get("title") or ""),
                )
            )
        elif mode == "name":
            rows.sort(key=lambda r: (_compat_rank(r), str(meta_from_row(r).get("title") or "")))
        else:
            # default — preserve original order but push incompatible to the bottom
            rows.sort(key=_compat_rank)
        return rows

    def _detect_gpu_vendor(self) -> str:
        try:
            return str(check_gpu_provider() or "CPU").upper()
        except Exception:
            return "CPU"

    # ----------------------------------------------------------- list rendering
    def _clear_scroll(self) -> None:
        # Remove every child widget but keep the trailing stretch.
        while self._scroll_layout.count() > 1:
            item = self._scroll_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _show_scroll_loading(self) -> None:
        """Показывает индикатор загрузки в области списка компонентов, пока идёт
        первичный опрос (иначе несколько секунд виден пустой список / «0 моделей»)."""
        from PyQt6.QtWidgets import QProgressBar

        self._clear_scroll()

        box = QWidget()
        box.setObjectName("AIHubLoading")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 48, 0, 0)
        lay.setSpacing(14)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        label = QLabel(_("Загрузка компонентов…", "Loading components…"))
        label.setObjectName("AIHubEmpty")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)

        bar = QProgressBar()
        bar.setRange(0, 0)  # неопределённый (бегущая) режим
        bar.setTextVisible(False)
        bar.setFixedSize(240, 6)
        bar.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,0.06); border: none;"
            " border-radius: 3px; }"
            " QProgressBar::chunk { background-color: #b74b7d; border-radius: 3px; }"
        )
        lay.addWidget(bar, 0, Qt.AlignmentFlag.AlignHCenter)

        self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, box)

    def _open_models_folder(self) -> None:
        """Открыть папку с голосовыми моделями (``Models`` или NEUROMITA_MODELS_DIR)
        в системном файловом менеджере. Создаём её, если ещё нет."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        from utils.voice_assets_installer import models_dir

        try:
            path = models_dir()
            path.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as exc:
            logger.info(f"AI Hub: не удалось открыть папку моделей: {exc}")

    def _rebuild_component_list(self) -> None:
        if hasattr(self, "_open_models_btn"):
            self._open_models_btn.setVisible(self._selected_category == "voices")
        rows = self._filtered_rows()
        self._clear_scroll()
        if not rows:
            empty = QLabel(
                _("Ничего не найдено по выбранным критериям.",
                  "No components match the current filters.")
            )
            empty.setObjectName("AIHubEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, empty)
            return

        gpu_vendor = self._detect_gpu_vendor()
        self._component_cards = []
        for row in rows:
            card = ModelCard(
                row,
                on_install=lambda cid: self._emit_component_action_by_id(cid, Events.Installable.INSTALL),
                on_uninstall=lambda cid: self._emit_component_action_by_id(cid, Events.Installable.UNINSTALL),
                on_open_settings=self._open_component_settings,
                gpu_vendor=gpu_vendor,
                parent=self._scroll_content,
                on_reinstall=lambda cid: self._emit_component_action_by_id(
                    cid, Events.Installable.INSTALL, extra={"clean": True}
                ),
            )
            self._component_cards.append(card)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, card)
        # Если в этот момент уже идёт установка — сразу заблокировать кнопки (#26).
        self._apply_busy_state()

    def _set_cards_checking(self) -> None:
        """#6: пометить все свободные карточки как «Проверка файлов…».

        Карточки, которые прямо сейчас ставятся или стоят в очереди, не трогаем —
        их состояние важнее (его вернёт _apply_busy_state). По завершении
        проверки список пересобирается (_rebuild_component_list) и состояния
        восстанавливаются сами.
        """
        running = self._queue_state.get("running") if isinstance(self._queue_state, dict) else None
        pending = self._queue_state.get("pending") if isinstance(self._queue_state, dict) else []
        running_tid = str((running or {}).get("task_id") or "").strip()
        pending_tids = {str((j or {}).get("task_id") or "").strip() for j in (pending or [])}
        for card in getattr(self, "_component_cards", []) or []:
            try:
                cid = card._component_id()
                install_tid = f"{cid}:install"
                uninstall_tid = f"{cid}:uninstall"
                if running_tid in (install_tid, uninstall_tid):
                    continue
                if install_tid in pending_tids or uninstall_tid in pending_tids:
                    continue
                card.set_state("checking")
            except Exception:
                pass

    def _apply_busy_state(self) -> None:
        """Проставляет каждой карточке её состояние относительно очереди установок.

        Раньше во время любой установки блокировались ВСЕ кнопки. По фидбэку
        Артёма чужие кнопки должны оставаться активными и по клику вставать в
        очередь (наработки очереди уже есть в InstallGuiController). Блокируется
        только та карточка, что ставится прямо сейчас («Установка…») или уже
        стоит в очереди («В очереди»)."""
        running = self._queue_state.get("running") if isinstance(self._queue_state, dict) else None
        pending = self._queue_state.get("pending") if isinstance(self._queue_state, dict) else []
        running_tid = str((running or {}).get("task_id") or "").strip()
        pending_tids = {str((j or {}).get("task_id") or "").strip() for j in (pending or [])}
        for card in getattr(self, "_component_cards", []) or []:
            try:
                cid = card._component_id()
                # task_id формируется как "{component_id}:{op}" (см. _task_id_for).
                install_tid = f"{cid}:install"
                uninstall_tid = f"{cid}:uninstall"
                if running_tid in (install_tid, uninstall_tid):
                    card.set_state("running")
                elif install_tid in pending_tids or uninstall_tid in pending_tids:
                    card.set_state("queued")
                else:
                    card.set_state("idle")
            except Exception:
                pass

    # ----------------------------------------------------------- summary / banner
    def _update_summary(self) -> None:
        # "Models" stats — count only model categories (tts/asr/rag).
        # Backend ('Системное ядро') and deps ('Зависимости') aren't models.
        _COUNTED_CATEGORIES = {"tts", "voices", "asr", "rag", "extras", "backend", "dependencies"}
        counted_rows = [r for r in self._rows if row_category(r) in _COUNTED_CATEGORIES]
        installed = sum(1 for r in counted_rows if status_from_row(r).get("installed"))
        components_word = _("компонентов", "components")
        self.stat_installed.setValue(str(installed), components_word)
        gpu_label = format_primary_gpu_label()
        gpu_vendor = self._detect_gpu_vendor()
        self.stat_gpu.setValue(gpu_label, gpu_vendor)

        try:
            usage = shutil.disk_usage(os.path.abspath(os.sep))
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            self.stat_disk.setValue(
                f"{free_gb:.1f} GB",
                _("из {total:.0f} GB", "of {total:.0f} GB").format(total=total_gb),
            )
        except Exception:
            self.stat_disk.setValue("-", "")

        if self._last_check_ts is not None:
            delta = _dt.datetime.now() - self._last_check_ts
            mins = max(0, int(delta.total_seconds() // 60))
            if mins <= 0:
                ago = _("только что", "just now")
            elif mins < 60:
                ago = _("{n} мин. назад", "{n} min ago").format(n=mins)
            else:
                ago = _("{n} ч. назад", "{n} h ago").format(n=mins // 60)
            self.stat_check.setValue(ago, self._last_check_ts.strftime("%d.%m.%Y %H:%M"))
        else:
            self.stat_check.setValue("-", "")

    def _update_banner(self) -> None:
        try:
            gpu_vendor = str(check_gpu_provider() or "CPU").upper()
        except Exception:
            gpu_vendor = "CPU"

        row_cpu = self._row_by_id("backend:cpu")
        row_cuda = self._row_by_id("backend:cuda")
        cpu_ready = bool(status_from_row(row_cpu or {}).get("ready"))
        cuda_ready = bool(status_from_row(row_cuda or {}).get("ready"))

        gpu_name = str(get_primary_gpu_name() or "").strip()
        gpu_label = gpu_name or format_primary_gpu_label()
        show = gpu_vendor == "NVIDIA" and cpu_ready and not cuda_ready
        self.banner.setVisible(show)
        if show:
            self.banner_title.setText(
                _(
                    "Обнаружена видеокарта <span style='color:#b74b7d;font-weight:800;'>{gpu}</span>,"
                    " но активен <span style='color:#b74b7d;font-weight:800;'>CPU-бэкенд</span>",
                    "Detected <span style='color:#b74b7d;font-weight:800;'>{gpu}</span> GPU,"
                    " but the <span style='color:#b74b7d;font-weight:800;'>CPU backend</span> is active",
                ).format(gpu=gpu_label)
            )
            self.banner_body.setText(
                _(
                    "AI Hub видит NVIDIA, но сейчас приложение работает на CPU-стеке. "
                    "Можно установить CUDA-компонент, чтобы заметно ускорить работу.",
                    "AI Hub can see NVIDIA, but the app is currently running on the CPU stack. "
                    "Install the CUDA component to speed things up significantly.",
                )
            )

    def _install_cuda_backend(self) -> None:
        self._pending_category = "backend"
        self._pending_component_id = "backend:cuda"
        self._emit_component_action_by_id("backend:cuda", Events.Installable.INSTALL)

    def _row_by_id(self, component_id: str) -> dict[str, Any] | None:
        for row in self._rows:
            if str(meta_from_row(row).get("id") or "") == component_id:
                return row
        return None

    def _maybe_hint_voices(self, component_id: str) -> None:
        """One-time nudge: installing a TTS engine doesn't fetch the character
        voices — those live under «Голоса Мит». Shown once, then suppressed."""
        if not str(component_id or "").startswith("tts:"):
            return

        # If a voice is already installed, the engine has something to speak
        # with — skip the nudge entirely (e.g. user grabbed a voice first, then
        # the engine).
        try:
            from installables.voice_assets import MITA_VOICES
            from utils.voice_assets_installer import is_installed

            if any(is_installed(v["short_name"]) for v in MITA_VOICES):
                return
        except Exception:
            pass

        try:
            from managers.settings_manager import SettingsManager
        except Exception:
            SettingsManager = None  # type: ignore[assignment]

        if SettingsManager is not None:
            try:
                if bool(SettingsManager.get("VOICES_HINT_SHOWN", False)):
                    return
            except Exception:
                pass

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(_("Не забудьте про голоса", "Don't forget the voices"))
        box.setText(
            _(
                "Движок озвучки сам по себе не говорит голосами Мит — нужны ещё "
                "голосовые модели персонажей.\n\nОткройте категорию «Голоса Мит» в AI Hub "
                "и скачайте нужные (или «Все голоса Мит» сразу).",
                "The TTS engine alone won't speak in the Mitas' voices — you also need "
                "the character voice models.\n\nOpen the «Mita Voices» category in the AI Hub "
                "and download the ones you need (or «All Mita voices» at once).",
            )
        )
        open_btn = box.addButton(_("Открыть «Голоса Мит»", "Open «Mita Voices»"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Понятно", "Got it"), QMessageBox.ButtonRole.RejectRole)
        box.exec()

        if SettingsManager is not None:
            try:
                SettingsManager.set("VOICES_HINT_SHOWN", True)
                SettingsManager.save()
            except Exception:
                pass

        if box.clickedButton() is open_btn:
            self._select_category("voices")

    def _task_id_for(self, component_id: str, event_name: str) -> str:
        op = "uninstall" if event_name == Events.Installable.UNINSTALL else "install"
        return f"{component_id}:{op}"

    def _is_task_active(self, task_id: str) -> bool:
        running = self._queue_state.get("running") or {}
        if str(running.get("task_id") or "") == task_id:
            return True
        return any(
            str((j or {}).get("task_id") or "") == task_id
            for j in self._queue_state.get("pending") or []
        )

    def _emit_component_action_by_id(self, component_id: str, event_name: str, extra: dict | None = None) -> None:
        if not component_id:
            return
        self._resolve_action_backend(component_id, event_name, extra=extra, attempt=0)

    def _resolve_action_backend(
        self,
        component_id: str,
        event_name: str,
        *,
        extra: dict | None,
        attempt: int,
    ) -> None:
        key = (str(component_id), str(event_name))
        if attempt == 0 and key in self._pending_backend_actions:
            self._set_task_status(_("Backend уже подготавливается…", "Backend is already preparing…"))
            return
        main_controller = self._main_controller or self._find_main_controller()
        if main_controller is None:
            self._pending_backend_actions.add(key)
            if attempt >= 100:
                self._pending_backend_actions.discard(key)
                self._set_task_status(_("Backend не запустился", "Backend failed to start"))
                return
            self._set_task_status(_("Backend запускается…", "Backend is starting…"))
            QTimer.singleShot(150, lambda: self._resolve_action_backend(
                component_id, event_name, extra=extra, attempt=attempt + 1
            ))
            return

        self._main_controller = main_controller
        self._pending_backend_actions.discard(key)
        try:
            future = main_controller.ensure_feature_async("installables")
        except Exception as exc:
            self._pending_backend_actions.discard(key)
            logger.error(f"AI Hub installable backend failed to start: {exc}", exc_info=True)
            self._set_task_status(_("Backend установки недоступен", "Install backend is unavailable"))
            return

        if not future.done():
            if key in self._pending_backend_actions:
                return
            self._pending_backend_actions.add(key)
            self._set_task_status(_("Подготовка backend установки…", "Preparing install backend…"))
            future.add_done_callback(
                lambda done: self._on_gui_thread(
                    lambda: self._continue_component_action(
                        done, component_id, event_name, extra, key
                    )
                )
            )
            return

        self._continue_component_action(future, component_id, event_name, extra, key)

    def _continue_component_action(
        self,
        future,
        component_id: str,
        event_name: str,
        extra: dict | None,
        key: tuple[str, str],
    ) -> None:
        self._pending_backend_actions.discard(key)
        try:
            future.result()
            self._ensure_install_gui_adapter()
        except Exception as exc:
            logger.error(f"AI Hub installable backend is unavailable: {exc}", exc_info=True)
            self._set_task_status(_("Backend установки недоступен", "Install backend is unavailable"))
            return
        self._dispatch_component_action(component_id, event_name, extra=extra)

    def _dispatch_component_action(self, component_id: str, event_name: str, extra: dict | None = None) -> None:
        # Дедуп: эту же задачу уже ставят/она в очереди — не плодим дубликат,
        # просто показываем окно и подсказываем, что задача уже в очереди.
        task_id = self._task_id_for(component_id, event_name)
        if self._is_task_active(task_id):
            win = self._active_install_window
            if win is not None:
                try:
                    win.show()
                    win.raise_()
                    win.activateWindow()
                except Exception:
                    pass
            self._set_task_status(_("Уже в очереди", "Already queued"))
            return

        if event_name == Events.Installable.INSTALL:
            self._maybe_hint_voices(component_id)
        install_window = self._create_install_window(component_id, event_name, extra=extra)
        payload = {
            "component_id": component_id,
            "task_id": task_id,
            "with_ui": True,
            "meta": {"source": "ai_hub"},
            "install_window": install_window,
            "install_callbacks": install_window.get_threadsafe_callbacks(),
        }
        if extra:
            payload.update(extra)
        self.event_bus.emit(event_name, payload)
        self._set_task_status(_("Запуск задачи...", "Starting task..."))

    # ----------------------------------------------------------- task events
    def _set_install_logs_visible(self, visible: bool) -> None:
        self._install_logs_btn.setVisible(bool(visible))
        self._update_activity_panel_visibility()

    def _on_install_window_closed(self) -> None:
        self._active_install_window = None
        self._set_install_logs_visible(False)

    def _on_reopen_install_logs(self) -> None:
        win = self._active_install_window
        if win is None:
            self._set_install_logs_visible(False)
            return
        self._set_install_logs_visible(False)
        win.show()
        win.raise_()
        win.activateWindow()

    def _title_for_component_action(self, component_id: str, event_name: str, extra: dict | None = None) -> str:
        row = self._row_by_id(component_id) or {}
        meta = meta_from_row(row)
        component_title = str(
            meta.get("title")
            or meta.get("name")
            or row.get("title")
            or row.get("name")
            or component_id
        )
        if event_name == Events.Installable.UNINSTALL:
            return _("Удаление: {name}", "Removing: {name}").format(name=component_title)
        if isinstance(extra, dict) and extra.get("clean"):
            return _("Переустановка: {name}", "Reinstalling: {name}").format(name=component_title)
        return _("Установка: {name}", "Installing: {name}").format(name=component_title)

    def _create_install_window(self, component_id: str, event_name: str, extra: dict | None = None) -> VoiceInstallationWindow:
        win = self._active_install_window
        if win is not None:
            if getattr(win, "_finished", False):
                win.close()
            else:
                win.show()
                win.raise_()
                win.activateWindow()
                self._set_install_logs_visible(False)
                return win

        title = self._title_for_component_action(component_id, event_name, extra=extra)
        win = VoiceInstallationWindow(
            self,
            title,
            _("Подготовка...", "Preparing..."),
            style_variant="ai_hub",
            reopen_hint_text=_(
                "Это окно можно закрыть — установка продолжится в фоне. "
                "Открыть снова и посмотреть логи можно кнопкой «Логи установки» слева в AI Hub.",
                "You can close this window — the installation keeps running in the "
                "background. Reopen it via the “Install logs” button on the left in AI Hub.",
            ),
        )
        win.minimized.connect(lambda: self._set_install_logs_visible(True))
        win.window_closed.connect(self._on_install_window_closed)
        self._active_install_window = win
        self._set_install_logs_visible(False)
        win.show()
        return win

    def _set_task_status(self, text: str) -> None:
        self._last_task_status = text or ""
        if self._last_task_status:
            self.task_status_label.setText(self._last_task_status)
            self.task_status_label.setVisible(True)
        else:
            self.task_status_label.setVisible(False)
        self._update_activity_panel_visibility()

    def _update_activity_panel_visibility(self) -> None:
        # Кнопка логов теперь в нижней плашке, поэтому левая панель «АКТИВНОСТЬ»
        # показывается только под статус и список очереди.
        has_activity = any((
            self.task_status_label.isVisible(),
            self._queue_panel.isVisible(),
        ))
        self._activity_panel.setVisible(has_activity)

    # ----------------------------------------------------------- queue
    def _on_queue_changed(self, event) -> None:
        data = event.data if isinstance(getattr(event, "data", None), dict) else {}
        self._on_gui_thread(lambda: self._apply_queue_state(data))

    def _apply_queue_state(self, data: dict[str, Any]) -> None:
        running = data.get("running") if isinstance(data, dict) else None
        pending = data.get("pending") if isinstance(data, dict) else []
        self._queue_state = {
            "running": running if isinstance(running, dict) else None,
            "pending": [j for j in (pending or []) if isinstance(j, dict)],
        }
        self._rebuild_queue_panel()
        # Обновить блокировку кнопок установки под новое состояние очереди (#26).
        self._apply_busy_state()

    def _clear_queue_panel(self) -> None:
        while self._queue_layout.count():
            item = self._queue_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    @staticmethod
    def _shorten(text: str, limit: int = 26) -> str:
        text = str(text or "")
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _update_install_bar_queue_chip(self) -> None:
        """Чип «+N в очереди» в нижней плашке (полный список ждёт в подсказке)."""
        chip = getattr(self, "_install_bar_queue", None)
        if chip is None:
            return
        pending = self._queue_state.get("pending") or []
        n = len(pending)
        if n <= 0:
            chip.setVisible(False)
            chip.setText("")
            chip.setToolTip("")
            return
        chip.setText(_("+{n} в очереди", "+{n} queued").format(n=n))
        titles = [str((j or {}).get("title") or (j or {}).get("task_id") or "") for j in pending]
        chip.setToolTip("\n".join(t for t in titles if t))
        chip.setVisible(True)

    def _rebuild_queue_panel(self) -> None:
        self._clear_queue_panel()
        self._update_install_bar_queue_chip()
        running = self._queue_state.get("running")
        pending = self._queue_state.get("pending") or []

        if not running and not pending:
            self._queue_panel.setVisible(False)
            self._update_activity_panel_visibility()
            return

        header = QLabel(_("ОЧЕРЕДЬ УСТАНОВКИ", "INSTALL QUEUE"))
        header.setObjectName("AIHubSidebarHeader")
        self._queue_layout.addWidget(header)

        if running:
            self._queue_layout.addWidget(self._make_queue_row(running, is_running=True))
        for job in pending:
            self._queue_layout.addWidget(self._make_queue_row(job, is_running=False))

        self._queue_panel.setVisible(True)
        self._update_activity_panel_visibility()

    def _make_queue_row(self, job: dict[str, Any], *, is_running: bool) -> QWidget:
        row = QFrame()
        row.setObjectName("AIHubQueueRow")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(2, 2, 2, 2)
        rl.setSpacing(6)

        title = str(job.get("title") or job.get("task_id") or "")
        prefix = "● " if is_running else "• "
        label = QLabel(prefix + self._shorten(title))
        label.setObjectName("AIHubQueueRunning" if is_running else "AIHubQueuePending")
        label.setToolTip(title + (_(" — выполняется", " — running") if is_running else _(" — в очереди", " — queued")))
        rl.addWidget(label, 1)

        if not is_running:
            cancel = QPushButton("✕")
            cancel.setObjectName("AIHubQueueCancel")
            cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel.setFixedSize(18, 18)
            cancel.setToolTip(_("Убрать из очереди", "Remove from queue"))
            task_id = str(job.get("task_id") or "")
            cancel.clicked.connect(lambda _checked=False, tid=task_id: self._cancel_queued(tid))
            rl.addWidget(cancel, 0)

        return row

    def _cancel_queued(self, task_id: str) -> None:
        if not task_id:
            return
        self.event_bus.emit(Events.Install.CANCEL_QUEUED, {"task_id": task_id})

    def _is_installable_task(self, event) -> bool:
        data = event.data if isinstance(getattr(event, "data", None), dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if meta.get("category") in CATEGORY_ORDER or meta.get("category") in ROW_CATEGORY_MAP:
            return True
        cid = str(meta.get("component_id") or data.get("component_id") or "")
        return ":" in cid

    def _on_install_started(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        text = str(data.get("status") or _("Подготовка...", "Preparing..."))
        title = self._install_bar_component_title(data)
        # Кнопка «Логи установки» должна быть видна на всё время установки,
        # а не только когда окно свёрнуто — иначе её «не найти» (фидбэк #23).
        self._on_gui_thread(lambda: (self._set_task_status(text),
                                     self._set_install_logs_visible(True),
                                     self._set_install_bar(visible=True, title=title,
                                                           progress=None, detail=text)))

    def _install_bar_component_title(self, data: dict) -> str:
        """Имя устанавливаемого компонента для плашки: из running-очереди или из meta."""
        running = (self._queue_state or {}).get("running") or {}
        title = str(running.get("title") or "").strip()
        if title:
            return title
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        cid = str(meta.get("component_id") or data.get("component_id") or "").strip()
        row = self._row_by_id(cid) if cid else None
        if row:
            return str(meta_from_row(row).get("title") or cid)
        return cid or _("Установка", "Install")

    def _on_install_progress(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        status = str(data.get("status") or "").strip()
        progress = data.get("progress")
        if not status:
            return
        # Не дублируем процент: статус инсталлятора уже может содержать «… 1% …»,
        # тогда повторное « (1%)» выглядело как «… 1% … (1%)» (фидбэк #24).
        if progress is not None and "%" not in status:
            text = f"{status} ({progress}%)"
        else:
            text = status
        # Деталь плашки — хвост статуса (там процент·скорость·ETA).
        detail = status.split("—", 1)[1].strip() if "—" in status else status
        self._on_gui_thread(lambda: (self._set_task_status(text),
                                     self._set_install_bar(visible=True, progress=progress,
                                                           detail=self._shorten(detail, 36))))

    def _on_install_finished(self, event) -> None:
        if not self._is_installable_task(event):
            return
        done_text = _("Готово", "Done")

        def _apply() -> None:
            self._set_task_status(done_text)
            self._set_install_logs_visible(False)
            self._set_install_bar(visible=True, progress=100, detail=done_text)
            QTimer.singleShot(900, lambda: self._set_install_bar(visible=False))
            QTimer.singleShot(250, lambda: (self.refresh(force=True), self._set_task_status("")))

        self._on_gui_thread(_apply)

    def _on_install_failed(self, event) -> None:
        if not self._is_installable_task(event):
            return
        data = event.data if isinstance(event.data, dict) else {}
        text = str(data.get("error") or _("Ошибка установки", "Install failed"))

        def _apply() -> None:
            self._set_task_status(text)
            self._set_install_logs_visible(False)
            self._set_install_bar(visible=False)
            QTimer.singleShot(250, lambda: self.refresh(force=True))

        self._on_gui_thread(_apply)
