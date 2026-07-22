from __future__ import annotations

import datetime as _dt
import html
import os
import shutil
from typing import Any

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtWidgets import (
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

try:
    import qtawesome as qta
except Exception:
    qta = None

from ui.mvvm import mutable_payload
from ui.windows.ai_hub.presentation import (
    AIHubShowError,
    AIHubState,
    ActivateAIHub,
    CancelQueuedInstall,
    CancelRunningInstall,
    ClearInstallCache,
    ComponentActionContext,
    ComponentAdmissionFailed,
    ConfirmBackendInstall,
    PrepareComponentInstall,
    RefreshAIHub,
    RequestComponentAction,
    SubmitComponentAction,
)
from main_logger import logger
from styles.ai_hub_styles import get_stylesheet as get_ai_hub_stylesheet
from ui.windows.voice_action_windows import VoiceInstallationWindow
from utils import getTranslationVariant as _

from .constants import CATEGORY_ICONS, CATEGORY_ORDER, ROW_CATEGORY_MAP, category_label
from .helpers import meta_from_row, qicon, qpixmap, row_category, status_from_row
from .widgets import CategoryButton, ModelCard, Stat


class _BackendInstallConfirmationDialog(QDialog):
    """Two-action confirmation with an inline navigation link."""

    def __init__(self, body_html: str, *, parent=None) -> None:
        super().__init__(parent)
        self.open_backend_requested = False
        self.setModal(True)
        self.setWindowTitle(_("Подтверждение установки", "Confirm installation"))
        self.setMinimumWidth(620)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(16)

        body = QLabel(body_html, self)
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        body.setOpenExternalLinks(False)
        body.linkActivated.connect(self._on_link_activated)
        root.addWidget(body)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        install = QPushButton(_("Установить всё", "Install all"), self)
        install.setDefault(True)
        install.clicked.connect(self.accept)
        buttons.addWidget(install)

        cancel = QPushButton(_("Отмена", "Cancel"), self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    def _on_link_activated(self, href: str) -> None:
        if str(href) != "backend":
            return
        self.open_backend_requested = True
        self.reject()


class AIHubDialog(QDialog):
    def __init__(
        self,
        view_model,
        settings_view_model,
        settings_binding,
        parent=None,
    ):
        super().__init__(parent)
        self.view_model = view_model
        self._settings_view_model = settings_view_model
        self._settings_binding = settings_binding
        self._rows: list[dict[str, Any]] = []
        self._hardware: dict[str, Any] = {}
        self._selected_category = "tts"
        self._pending_category: str | None = None
        self._pending_component_id: str | None = None
        self._last_task_status = ""
        self._loaded_once = False
        self._last_check_ts: _dt.datetime | None = None
        self._category_buttons: dict[str, CategoryButton] = {}
        self._active_install_window: VoiceInstallationWindow | None = None
        self._queue_state: dict[str, Any] = {"running": None, "pending": []}
        self._queue_popup: QFrame | None = None
        self._queue_popup_layout: QVBoxLayout | None = None
        self._refresh_inflight = False
        self._checking_component_ids: set[str] = set()
        self._rendered_language = ""
        self._build()
        self.view_model.state_changed.connect(self.render)
        self.view_model.effect_emitted.connect(self.handle_effect)
        self.render(self.view_model.state)

        # Живая смена языка: диалог — синглтон (не пересоздаётся при переоткрытии),
        # поэтому карточки/кнопки застывают на языке первого рендера. Перерисовываем
        # по сигналу смены языка (или при следующем показе, если был скрыт).
        try:
            from localization.live import language_changed_signal
            language_changed_signal().connect(self._on_language_changed)
        except Exception:
            pass

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        self.setObjectName("AIHubDialog")
        self.setWindowTitle(_("AI Hub", "AI Hub"))
        self.setModal(False)
        # Кнопка сворачивания: у QDialog её в заголовке по умолчанию нет.
        # WindowSystemMenuHint нужен, чтобы системные кнопки вообще появились;
        # заодно убираем бесполезную контекстную «?»-кнопку.
        flags = self.windowFlags()
        flags |= Qt.WindowType.WindowMinimizeButtonHint
        flags |= Qt.WindowType.WindowSystemMenuHint
        flags &= ~Qt.WindowType.WindowContextHelpButtonHint
        self.setWindowFlags(flags)
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

        # Чип очереди справа от прогресс-бара: «+N в очереди». Кликом
        # разворачивается popup со всей очередью и кнопками отмены — чтобы
        # не искать панель «АКТИВНОСТЬ» в сайдбаре.
        self._install_bar_queue = QPushButton("")
        self._install_bar_queue.setObjectName("AIHubInstallBarQueue")
        self._install_bar_queue.setCursor(Qt.CursorShape.PointingHandCursor)
        self._install_bar_queue.setVisible(False)
        self._install_bar_queue.clicked.connect(self._toggle_queue_popup)
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
            self._close_queue_popup()
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
        self._title_label = QLabel(_("AI Hub", "AI Hub"))
        self._title_label.setObjectName("AIHubTitle")
        title_box.addWidget(self._title_label)
        self._subtitle_label = QLabel(
            _(
                "Установка, удаление и обслуживание локальных AI-компонентов и системных зависимостей.",
                "Install, remove and maintain local AI components and system dependencies.",
            )
        )
        self._subtitle_label.setObjectName("AIHubSubtitle")
        title_box.addWidget(self._subtitle_label)
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
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(14, 16, 14, 14)
        sidebar_layout.setSpacing(8)

        self._categories_header = QLabel(_("КАТЕГОРИИ", "CATEGORIES"))
        self._categories_header.setObjectName("AIHubSidebarHeader")
        sidebar_layout.addWidget(self._categories_header)

        for key in CATEGORY_ORDER:
            btn = CategoryButton(
                key,
                category_label(key),
                CATEGORY_ICONS.get(key, "fa5s.circle"),
                self._select_category,
                sidebar,
            )
            self._category_buttons[key] = btn
            sidebar_layout.addWidget(btn, 0)

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

        sidebar_layout.addWidget(self._activity_panel)

        sidebar_layout.addStretch(1)

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
        sidebar_layout.addWidget(self.btn_refresh)

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
        sidebar_layout.addWidget(self.btn_clear_cache)

        return sidebar

    def _clear_install_cache(self) -> None:
        self.view_model.dispatch(ClearInstallCache())

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
        self._settings_panel = SettingsPanel(self._settings_view_model)
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
        """Build a two-level catalog toolbar without overlapping controls."""
        wrap = QVBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)

        self._component_list_title = QLabel(
            category_label(self._selected_category)
            if self._selected_category in CATEGORY_ORDER
            else _("Компоненты", "Components")
        )
        self._component_list_title.setObjectName("AIHubSectionTitle")
        top.addWidget(self._component_list_title, 0)

        self._check_indicator = QFrame()
        self._check_indicator.setObjectName("AIHubCheckIndicator")
        self._check_indicator.setVisible(False)
        check_layout = QHBoxLayout(self._check_indicator)
        check_layout.setContentsMargins(8, 4, 10, 4)
        check_layout.setSpacing(6)
        self._check_spinner = QPushButton()
        self._check_spinner.setObjectName("AIHubCheckSpinner")
        self._check_spinner.setEnabled(False)
        self._check_spinner.setFixedSize(18, 18)
        if qta is not None:
            try:
                self._check_spin = qta.Spin(self._check_spinner)
                self._check_spinner.setIcon(
                    qta.icon(
                        "fa5s.spinner",
                        color="#dc588a",
                        animation=self._check_spin,
                    )
                )
                self._check_spinner.setIconSize(QSize(13, 13))
            except Exception:
                pass
        check_layout.addWidget(self._check_spinner, 0)
        self._check_text = QLabel(_("Проверяем компоненты…", "Checking components…"))
        self._check_text.setObjectName("AIHubCheckText")
        check_layout.addWidget(self._check_text, 0)
        top.addWidget(self._check_indicator, 0)

        top.addStretch(1)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("AIHubSearch")
        self.search_box.setPlaceholderText(_("Поиск в категории…", "Search this category…"))
        self.search_box.setFixedWidth(280)
        si = qicon("fa5s.search", "#bca9bb")
        if si is not None:
            action = self.search_box.addAction(si, QLineEdit.ActionPosition.LeadingPosition)
            action.setEnabled(False)
        self.search_box.textChanged.connect(self._rebuild_component_list)
        top.addWidget(self.search_box, 0)

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

        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(8)
        self._filter_label = QLabel(_("Реализация", "Runtime"))
        self._filter_label.setObjectName("AIHubToolbarLabel")
        filters.addWidget(self._filter_label, 0)

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
            filters.addWidget(btn, 0)
        self._backend_filter_buttons["all"].setChecked(True)
        filters.addStretch(1)

        wrap.addLayout(top)
        wrap.addLayout(filters)
        return wrap

    def _build_tab_switcher(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._tab_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("install", _("Компоненты", "Components")),
            ("settings", _("Параметры моделей", "Model settings")),
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
                self._refresh_localized_ui()
            except Exception:
                logger.exception("AI Hub: re-render on language change failed")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.view_model.dispatch(ActivateAIHub())
        if self._rendered_language != self._current_ui_language():
            # Язык сменился, пока диалог был скрыт — перерисовываем в текущем языке.
            QTimer.singleShot(0, self._refresh_localized_ui)

    def _refresh_localized_ui(self) -> None:
        self.setWindowTitle(_("AI Hub", "AI Hub"))
        self._title_label.setText(_("AI Hub", "AI Hub"))
        self._subtitle_label.setText(
            _(
                "Установка, удаление и обслуживание локальных AI-компонентов и системных зависимостей.",
                "Install, remove and maintain local AI components and system dependencies.",
            )
        )
        self._categories_header.setText(_("КАТЕГОРИИ", "CATEGORIES"))
        self._activity_header.setText(_("АКТИВНОСТЬ", "ACTIVITY"))
        self.btn_refresh.setText(_("Обновить список", "Refresh list"))
        self.btn_clear_cache.setText(_("Очистить кэш загрузок", "Clear download cache"))
        self._install_logs_btn.setText(_("Логи установки", "Install logs"))
        self._check_text.setText(_("Проверяем компоненты…", "Checking components…"))
        self.search_box.setPlaceholderText(_("Поиск в категории…", "Search this category…"))
        self._open_models_btn.setText(_("Открыть папку моделей", "Open models folder"))
        self._filter_label.setText(_("Реализация", "Runtime"))
        self._backend_filter_buttons["all"].setText(_("Все", "All"))
        self._tab_buttons["install"].setText(_("Компоненты", "Components"))
        self._tab_buttons["settings"].setText(_("Параметры моделей", "Model settings"))
        self.stat_installed.setLabel(_("Установлено", "Installed"))
        self.stat_disk.setLabel(_("Свободно на диске", "Free disk"))
        self.stat_check.setLabel(_("Последняя проверка", "Last check"))
        self.banner_button.setText(_("Оптимизировать", "Optimize"))
        self.banner_dismiss.setText(_("Позже", "Later"))
        if hasattr(self, "_settings_panel"):
            self._settings_panel.retranslate()
        self._refresh_views()

    def refresh(self, *, force: bool = False, include_status: bool | None = None) -> None:
        if not self._rows:
            self._show_scroll_loading()
        elif force:
            self._set_cards_checking()
        self.view_model.dispatch(
            RefreshAIHub(
                force=bool(force),
                include_status=include_status,
                status_category=(
                    self._selected_category
                    if include_status is not False
                    else None
                ),
            )
        )

    def render(self, state: AIHubState) -> None:
        previous_revision = getattr(self, "_rendered_revision", -1)
        self._rendered_revision = state.revision
        self._rows = [dict(mutable_payload(item) or {}) for item in state.rows]
        self._hardware = dict(mutable_payload(state.hardware) or {})
        self._loaded_once = bool(state.loaded_once)
        self._refresh_inflight = bool(state.refreshing)
        self._last_check_ts = state.last_check_ts
        self._queue_state = dict(
            mutable_payload(state.queue_state)
            or {"running": None, "pending": []}
        )
        self._checking_component_ids = set(state.checking_component_ids)

        if hasattr(self, "_check_indicator"):
            self._check_indicator.setVisible(bool(state.refreshing))
        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(not state.refreshing)
        if state.refreshing and not self._rows:
            self._show_scroll_loading()
        elif state.revision != previous_revision:
            self._refresh_views()
        else:
            self._rebuild_queue_panel()
            self._apply_busy_state()

        self._set_task_status(state.task_status)
        self._set_install_logs_visible(state.install_logs_visible)
        self._set_install_bar(
            visible=state.install_bar_visible,
            title=state.install_title,
            progress=state.install_progress,
            detail=self._shorten(state.install_detail, 36),
        )
        if state.error:
            logger.warning("AI Hub presentation error: %s", state.error)

    def handle_effect(self, effect) -> None:
        if isinstance(effect, ConfirmBackendInstall):
            preview = dict(mutable_payload(effect.context.preview) or {})
            if self._confirm_backend_install(preview):
                self._prepare_component_install(effect.context)
            return
        if isinstance(effect, PrepareComponentInstall):
            self._prepare_component_install(effect.context)
            return
        if isinstance(effect, ComponentAdmissionFailed):
            self._handle_queue_admission_failure(
                effect.task_id,
                effect.message,
                install_window=effect.install_window,
            )
            return
        if isinstance(effect, AIHubShowError):
            QMessageBox.critical(self, effect.title, effect.message)

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
            btn.setLabel(category_label(key))
            btn.setCount(counts.get(key, 0))
            btn.setSelected(key == selected)

        self._selected_category = selected
        self._pending_category = None
        self._update_catalog_header()

    def _select_category(self, key: str) -> None:
        if key not in CATEGORY_ORDER:
            return
        self._selected_category = key
        self._update_catalog_header()
        for k, btn in self._category_buttons.items():
            btn.setSelected(k == key)
        self._rebuild_component_list()
        if hasattr(self, "_settings_panel"):
            self._settings_panel.apply_data(self._rows, key)
        self._update_summary()
        if self._loaded_once and not self._refresh_inflight and not self._category_status_loaded(key):
            QTimer.singleShot(0, lambda: self.refresh(force=False, include_status=True))

    def _update_catalog_header(self) -> None:
        title = getattr(self, "_component_list_title", None)
        if title is not None:
            title.setText(
                category_label(self._selected_category)
                if self._selected_category in CATEGORY_ORDER
                else _("Компоненты", "Components")
            )

    def _category_status_loaded(self, category: str) -> bool:
        rows = [row for row in self._rows if row_category(row) == category]
        return bool(rows) and all(isinstance(row.get("status"), dict) for row in rows)

    # ----------------------------------------------------------- filtering
    def _filtered_rows(self) -> list[dict[str, Any]]:
        query = str(self.search_box.text() or "").strip().lower()
        category = self._selected_category
        backend_filter = getattr(self, "_backend_filter", "all")

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

        def _compat_rank(r: dict[str, Any]) -> int:
            status = status_from_row(r)
            if status.get("ready"):
                return 0
            compatibility = r.get("compatibility") if isinstance(r, dict) else None
            return 0 if isinstance(compatibility, dict) and compatibility.get("supported", False) else 1

        rows.sort(key=_compat_rank)
        return rows

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
        """Keep a calm empty state while the toolbar spinner owns progress."""
        self._clear_scroll()

        box = QWidget()
        box.setObjectName("AIHubLoading")
        box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 48, 0, 0)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        label = QLabel(
            _(
                "Каталог появится после проверки установленных компонентов.",
                "The catalog will appear after installed components are checked.",
            )
        )
        label.setObjectName("AIHubEmpty")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)

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

    # Порядок и подписи групп внутри категории RAG.
    _GROUP_ORDER = {"embeddings": 0, "reranker": 1, "other": 2}

    def _grouping_key(self, row: dict[str, Any]) -> str:
        item = str(meta_from_row(row).get("item_id") or "").strip().lower()
        return item if item in ("embeddings", "reranker") else "other"

    def _group_title(self, key: str) -> str:
        titles = {
            "embeddings": _("Эмбеддинги", "Embeddings"),
            "reranker": _("Реранкеры", "Rerankers"),
            "other": _("Прочее", "Other"),
        }
        return titles.get(key, key)

    def _insert_section_header(self, title: str, *, first: bool = False) -> None:
        header = QLabel(title)
        header.setObjectName("AIHubSectionHeader")
        header.setProperty("first", "true" if first else "false")
        self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, header)

    def _rebuild_component_list(self) -> None:
        if hasattr(self, "_open_models_btn"):
            self._open_models_btn.setVisible(self._selected_category == "voices")
        rows = self._filtered_rows()
        # Первичная загрузка ещё идёт (данных нет) — держим индикатор загрузки,
        # а не подменяем его на «ничего не найдено» при переключении категории.
        if not rows and self._refresh_inflight and not self._rows:
            self._show_scroll_loading()
            return
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

        self._component_cards = []

        # Внутри категории RAG модели делятся на эмбеддинги и реранкеры —
        # показываем их сгруппированно с заголовком-разделителем.
        grouped = self._selected_category == "rag"
        if grouped:
            rows = sorted(rows, key=lambda r: self._GROUP_ORDER.get(self._grouping_key(r), 99))

        last_group: str | None = None
        first_header = True
        for row in rows:
            if grouped:
                group = self._grouping_key(row)
                if group != last_group:
                    self._insert_section_header(self._group_title(group), first=first_header)
                    first_header = False
                    last_group = group
            card = ModelCard(
                row,
                on_install=lambda cid: self._request_component_action(cid, "install"),
                on_uninstall=lambda cid: self._request_component_action(cid, "uninstall"),
                on_open_settings=self._open_component_settings,
                parent=self._scroll_content,
                on_reinstall=lambda cid: self._request_component_action(
                    cid, "install", clean=True
                ),
            )
            self._component_cards.append(card)
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, card)
        # Если в этот момент уже идёт установка — сразу заблокировать кнопки (#26).
        self._apply_busy_state()

    def _set_cards_checking(self) -> None:
        """Пометить свободные карточки как проверяемые до нового status snapshot."""
        running = self._queue_state.get("running") if isinstance(self._queue_state, dict) else None
        pending = self._queue_state.get("pending") if isinstance(self._queue_state, dict) else []
        running_tid = str((running or {}).get("task_id") or "").strip()
        pending_tids = {str((j or {}).get("task_id") or "").strip() for j in (pending or [])}
        for card in getattr(self, "_component_cards", []) or []:
            try:
                cid = card._component_id()
                install_tid = f"{cid}:install"
                uninstall_tid = f"{cid}:uninstall"
                if cid in self._checking_component_ids:
                    card.set_state("checking")
                    continue
                if running_tid in (install_tid, uninstall_tid):
                    continue
                if install_tid in pending_tids or uninstall_tid in pending_tids:
                    continue
                card.set_state("checking")
            except Exception:
                pass

    def _apply_busy_state(self) -> None:
        """Disable every catalog mutation while the install queue is active."""
        running = self._queue_state.get("running") if isinstance(self._queue_state, dict) else None
        pending = self._queue_state.get("pending") if isinstance(self._queue_state, dict) else []
        running_tid = str((running or {}).get("task_id") or "").strip()
        pending_tids = {str((j or {}).get("task_id") or "").strip() for j in (pending or [])}
        queue_busy = bool(running or pending)
        for card in getattr(self, "_component_cards", []) or []:
            try:
                cid = card._component_id()
                install_tid = f"{cid}:install"
                uninstall_tid = f"{cid}:uninstall"
                if running_tid in (install_tid, uninstall_tid):
                    card.set_state("running")
                elif install_tid in pending_tids or uninstall_tid in pending_tids:
                    card.set_state("queued")
                elif queue_busy:
                    card.set_state("global_busy")
                elif cid in self._checking_component_ids:
                    card.set_state("checking")
                elif self._refresh_inflight:
                    card.set_state("checking")
                else:
                    card.set_state("idle")
            except Exception:
                pass

        if hasattr(self, "btn_refresh"):
            self.btn_refresh.setEnabled(not queue_busy and not self._refresh_inflight)
        if hasattr(self, "btn_clear_cache"):
            self.btn_clear_cache.setEnabled(not queue_busy)
        if hasattr(self, "banner_button"):
            self.banner_button.setEnabled(not queue_busy)

    # ----------------------------------------------------------- summary / banner
    def _update_summary(self) -> None:
        # "Models" stats — count only model categories (tts/asr/rag).
        # Backend ('Системное ядро') and deps ('Зависимости') aren't models.
        _COUNTED_CATEGORIES = {"tts", "voices", "asr", "rag", "extras", "backend", "dependencies"}
        counted_rows = [r for r in self._rows if row_category(r) in _COUNTED_CATEGORIES]
        installed = sum(1 for r in counted_rows if status_from_row(r).get("ready"))
        components_word = _("компонентов", "components")
        self.stat_installed.setValue(str(installed), components_word)
        hardware = self._hardware
        gpu_vendor = str(hardware.get("vendor") or "CPU").upper()
        primary = hardware.get("primary") if isinstance(hardware.get("primary"), dict) else {}
        gpu_label = str(primary.get("name") or gpu_vendor)
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
        hardware = self._hardware
        gpu_vendor = str(hardware.get("vendor") or "CPU").upper()

        row_cpu = self._row_by_id("backend:cpu")
        row_cuda = self._row_by_id("backend:cuda")
        cpu_ready = bool(status_from_row(row_cpu or {}).get("ready"))
        cuda_ready = bool(status_from_row(row_cuda or {}).get("ready"))

        primary = hardware.get("primary") if isinstance(hardware.get("primary"), dict) else {}
        gpu_label = str(primary.get("name") or gpu_vendor)
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
        self._request_component_action("backend:cuda", "install")

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
            if self._settings_binding is not None and bool(
                self._settings_binding.get("VOICES_HINT_SHOWN", False)
            ):
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

        try:
            if self._settings_binding is not None:
                self._settings_binding.set("VOICES_HINT_SHOWN", True)
        except Exception:
            pass

        if box.clickedButton() is open_btn:
            self._select_category("voices")

    def _confirm_backend_install(self, preview: dict[str, Any]) -> bool:
        backend = str(preview.get("backend_title") or preview.get("backend_kind") or "backend")
        component = str(preview.get("component_title") or preview.get("component_id") or "model")
        component_size = str(preview.get("component_size") or "").strip()
        gpu = str(preview.get("gpu") or "")

        plan_lines = [
            f"• {component}" + (f" ({component_size})" if component_size else "")
        ]
        for item in preview.get("additional_components") or ():
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("id") or backend)
            size = str(item.get("size") or "").strip()
            plan_lines.append(f"• {title}" + (f" ({size})" if size else ""))

        packages = [
            str(item)
            for item in (preview.get("backend_packages") or ())
            if str(item).strip()
        ]
        plan_html = "<br>".join(html.escape(line) for line in plan_lines)
        packages_html = ""
        if packages:
            package_lines = "<br>".join(
                f"• {html.escape(package)}" for package in packages
            )
            packages_html = _(
                "<br><br><b>Пакеты backend:</b><br>{packages}",
                "<br><br><b>Backend packages:</b><br>{packages}",
            ).format(packages=package_lines)

        body_html = _(
            "Для <b>«{component}»</b> не установлен требуемый backend.<br><br>"
            "Обнаружено устройство: <b>{gpu}</b><br>"
            "В рамках этой же транзакции будет установлен: <b>{backend}</b>.<br><br>"
            "<b>План установки:</b><br>{plan}"
            "{packages}<br><br>"
            "Новый runtime будет добавлен рядом с уже установленными и станет "
            "доступен только после проверки. Существующие backend не удаляются.<br>"
            "<a href=\"backend\">Открыть вкладку «Системное ядро»</a>",
            "The required backend for <b>“{component}”</b> is not installed.<br><br>"
            "Detected device: <b>{gpu}</b><br>"
            "The same transaction will also install: <b>{backend}</b>.<br><br>"
            "<b>Installation plan:</b><br>{plan}"
            "{packages}<br><br>"
            "The new runtime is added alongside installed runtimes and becomes "
            "available only after validation. Existing backends are not removed.<br>"
            "<a href=\"backend\">Open the “System Core” tab</a>",
        ).format(
            component=html.escape(component),
            gpu=html.escape(gpu),
            backend=html.escape(backend),
            plan=plan_html,
            packages=packages_html,
        )

        dialog = _BackendInstallConfirmationDialog(body_html, parent=self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if dialog.open_backend_requested:
            self._set_tab("install")
            self._select_category("backend")
            return False
        return accepted

    def _request_component_action(
        self,
        component_id: str,
        action: str,
        *,
        clean: bool = False,
    ) -> None:
        self.view_model.dispatch(
            RequestComponentAction(
                component_id=str(component_id),
                action=str(action),
                clean=bool(clean),
            )
        )

    def _prepare_component_install(self, context: ComponentActionContext) -> None:
        component_id = str(context.component_id)
        action = str(context.action)
        extra = dict(mutable_payload(context.extra) or {})
        preview = dict(mutable_payload(context.preview) or {})
        if action == "install":
            self._maybe_hint_voices(component_id)

        install_window = self._create_install_window(
            component_id,
            action,
            extra=extra,
        )
        callbacks = install_window.get_threadsafe_callbacks()
        if preview:
            try:
                if preview.get("backend_will_install"):
                    callbacks[1](
                        str(
                            extra.get("initial_status")
                            or _("Подготовка backend...", "Preparing backend...")
                        )
                    )
                    callbacks[2](
                        _(
                            "Дополнительно будет установлен backend: {backend}",
                            "The following backend will also be installed: {backend}",
                        ).format(backend=preview.get("backend_title"))
                    )
                for step in preview.get("actions") or ():
                    callbacks[2](f"• {step}")
            except Exception:
                logger.debug("AI Hub: failed to seed install preview logs", exc_info=True)
        self.view_model.dispatch(
            SubmitComponentAction(
                context=context,
                install_window=install_window,
                callbacks=callbacks,
            )
        )

    def _handle_queue_admission_failure(
        self,
        task_id: str,
        message: str,
        *,
        install_window=None,
    ) -> None:
        logger.error(f"Install task '{task_id}' admission failed: {message}")
        self._set_task_status(message)
        self._apply_busy_state()

        win = install_window or self._active_install_window
        if win is None:
            return
        try:
            win.update_status(_("Ошибка запуска", "Startup failed"))
            win.update_log(message)
            win.finalize()
        except Exception:
            logger.exception("AI Hub: failed to report install queue admission error")

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

    def _title_for_component_action(self, component_id: str, action: str, extra: dict | None = None) -> str:
        row = self._row_by_id(component_id) or {}
        meta = meta_from_row(row)
        component_title = str(
            meta.get("title")
            or meta.get("name")
            or row.get("title")
            or row.get("name")
            or component_id
        )
        if action == "uninstall":
            return _("Удаление: {name}", "Removing: {name}").format(name=component_title)
        if isinstance(extra, dict) and extra.get("clean"):
            return _("Переустановка: {name}", "Reinstalling: {name}").format(name=component_title)
        return _("Установка: {name}", "Installing: {name}").format(name=component_title)

    def _create_install_window(self, component_id: str, action: str, extra: dict | None = None) -> VoiceInstallationWindow:
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

        title = self._title_for_component_action(component_id, action, extra=extra)
        win = VoiceInstallationWindow(
            self,
            title,
            str((extra or {}).get("initial_status") or _("Подготовка...", "Preparing...")),
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
        """Чип «+N в очереди» справа от прогресс-бара. Клик разворачивает
        popup со всей очередью и кнопками отмены."""
        chip = getattr(self, "_install_bar_queue", None)
        if chip is None:
            return
        pending = self._queue_state.get("pending") or []
        n = len(pending)
        if n <= 0:
            chip.setVisible(False)
            chip.setText("")
            chip.setToolTip("")
            self._close_queue_popup()
            return
        chip.setText(_("+{n} в очереди ▾", "+{n} queued ▾").format(n=n))
        chip.setToolTip(_("Показать очередь установки", "Show the install queue"))
        chip.setVisible(True)
        if self._queue_popup is not None and self._queue_popup.isVisible():
            self._fill_queue_popup()

    # ------------------------------------------------------- queue popup
    def _toggle_queue_popup(self) -> None:
        if self._queue_popup is not None and self._queue_popup.isVisible():
            self._close_queue_popup()
            return
        self._open_queue_popup()

    def _close_queue_popup(self) -> None:
        popup = getattr(self, "_queue_popup", None)
        if popup is not None:
            popup.hide()

    def _open_queue_popup(self) -> None:
        chip = getattr(self, "_install_bar_queue", None)
        if chip is None:
            return
        if self._queue_popup is None:
            popup = QFrame(self, Qt.WindowType.Popup)
            popup.setObjectName("AIHubQueuePopup")
            lay = QVBoxLayout(popup)
            lay.setContentsMargins(10, 10, 10, 10)
            lay.setSpacing(4)
            self._queue_popup = popup
            self._queue_popup_layout = lay

        self._fill_queue_popup()
        self._queue_popup.show()

    def _fill_queue_popup(self) -> None:
        lay = getattr(self, "_queue_popup_layout", None)
        if lay is None:
            return
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        running = self._queue_state.get("running")
        pending = self._queue_state.get("pending") or []

        header = QLabel(_("ОЧЕРЕДЬ УСТАНОВКИ", "INSTALL QUEUE"))
        header.setObjectName("AIHubSidebarHeader")
        lay.addWidget(header)

        if running:
            lay.addWidget(self._make_queue_row(running, is_running=True, limit=42))
        for job in pending:
            lay.addWidget(self._make_queue_row(job, is_running=False, limit=42))

        self._reposition_queue_popup()

    def _reposition_queue_popup(self) -> None:
        """Popup якорится правым нижним углом к чипу и растёт вверх — нижняя
        плашка прижата к низу окна, вниз места нет."""
        popup = getattr(self, "_queue_popup", None)
        chip = getattr(self, "_install_bar_queue", None)
        if popup is None or chip is None:
            return
        popup.adjustSize()
        anchor = chip.mapToGlobal(chip.rect().topRight())
        popup.move(anchor.x() - popup.width(), anchor.y() - popup.height() - 6)

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

    def _make_queue_row(self, job: dict[str, Any], *, is_running: bool, limit: int = 26) -> QWidget:
        row = QFrame()
        row.setObjectName("AIHubQueueRow")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(2, 2, 2, 2)
        rl.setSpacing(6)

        title = str(job.get("title") or job.get("task_id") or "")
        prefix = "● " if is_running else "• "
        label = QLabel(prefix + self._shorten(title, limit))
        label.setObjectName("AIHubQueueRunning" if is_running else "AIHubQueuePending")
        label.setToolTip(title + (_(" — выполняется", " — running") if is_running else _(" — в очереди", " — queued")))
        rl.addWidget(label, 1)

        if is_running:
            cancel = QPushButton("■")
            cancel.setObjectName("AIHubQueueCancel")
            cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel.setFixedSize(18, 18)
            cancelling = bool(job.get("cancelling"))
            cancel.setEnabled(not cancelling)
            cancel.setToolTip(
                _("Отмена запрошена", "Cancellation requested")
                if cancelling
                else _("Остановить установку", "Stop installation")
            )
            task_id = str(job.get("task_id") or "")
            cancel.clicked.connect(
                lambda _checked=False, tid=task_id: self._cancel_running(tid)
            )
            rl.addWidget(cancel, 0)
        else:
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
        self.view_model.dispatch(CancelQueuedInstall(task_id))

    def _cancel_running(self, task_id: str) -> None:
        if not task_id:
            return
        self.view_model.dispatch(CancelRunningInstall(task_id))

