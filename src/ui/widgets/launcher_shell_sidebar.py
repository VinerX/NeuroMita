from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import qtawesome as qta
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from utils import _

from localization import translate as _tr
from localization.live import language_changed_signal, tr_set
from ui.widgets.launcher_shell_theme import apply_launcher_shell_theme, resolve_launcher_asset


@dataclass(frozen=True)
class SidebarSection:
    """Раздел сайдбара. Подписи храним парой ru/en, чтобы их можно было
    перевести вживую при смене языка (а не замораживать на старте)."""

    key: str
    title_ru: str
    title_en: str
    icon_name: str
    subtitle_ru: str = ""
    subtitle_en: str = ""
    min_mode: str = "basic"

    @property
    def title(self) -> str:
        return _tr(self.title_ru, self.title_en)

    @property
    def subtitle(self) -> str:
        return _tr(self.subtitle_ru, self.subtitle_en)


DEFAULT_SIDEBAR_SECTIONS: tuple[SidebarSection, ...] = (
    SidebarSection("home", "Главная", "Home", "fa6s.house", "Обзор лаунчера", "Launcher overview"),
    SidebarSection("settings", "Настройки", "Settings", "fa6s.gear", "Системные параметры", "System controls"),
    SidebarSection("sandbox", "Песочница", "Sandbox", "fa6s.flask", "Быстрый вход в чат", "Quick chat access"),
    SidebarSection("news", "Релизы", "Releases", "fa6s.rectangle-list", "Лента релизов проекта", "Project release feed"),
    SidebarSection("developer", "Дев", "Dev", "fa6s.bug", "Отладка и дообучение", "Debug & fine-tuning", min_mode="full"),
    SidebarSection("wiki", "Вики", "Wiki", "fa6s.book-open", "Полная база знаний по приложению", "Full in-app knowledge base"),
    SidebarSection("logs", "Логи", "Logs", "fa6s.list", "События и диагностика", "Events and diagnostics"),
)


class LauncherSidebarWidget(QFrame):
    page_requested = pyqtSignal(str)
    social_requested = pyqtSignal(str)
    utility_requested = pyqtSignal(str)
    install_logs_requested = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        sections: Iterable[SidebarSection] | None = None,
        initial_page: str = "home",
        on_page_requested: Callable[[str], None] | None = None,
        version_provider: Callable[[], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LauncherShellSidebar")
        self.setFixedWidth(230)
        apply_launcher_shell_theme(self)

        if on_page_requested is not None:
            self.page_requested.connect(on_page_requested)

        self._sections = list(sections or DEFAULT_SIDEBAR_SECTIONS)
        self._version_provider = version_provider
        self._nav_buttons: dict[str, QPushButton] = {}
        self._active_page = ""
        self._active_language = "ru"

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        self._lang_buttons: dict[str, QPushButton] = {}
        self._lang_pills_layout: QHBoxLayout | None = None
        # Вторая пилюля — всегда последний выбранный НЕ английский язык.
        # По умолчанию русский; обновляется при каждой смене на неанглийский.
        self._last_secondary_lang = "ru"
        self._version_label: QLabel | None = None

        self._build_ui()
        self.set_active_page(initial_page)

        # Live-смена языка: подписи раздела обновляются реестром (tr_set), а
        # набор «быстрых» пилюль внизу зависит от текущего языка — пересобираем.
        try:
            language_changed_signal().connect(self._on_language_changed)
        except Exception:
            pass

    def _on_language_changed(self, code: str = "") -> None:
        normalized = str(code or self._active_language or "ru").lower()
        self._active_language = normalized
        self._rebuild_lang_pills()
        self.set_active_language(normalized)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        # Чуть уже горизонтальные поля (18→13): освобождаем место в футере, чтобы
        # строка версии не обрезалась (фидбэк vinerx «не влезает версия»).
        layout.setContentsMargins(13, 20, 13, 18)
        layout.setSpacing(12)

        layout.addWidget(self._build_brand_card())
        layout.addWidget(self._build_brand_divider())
        layout.addWidget(self._build_nav_card())
        self._install_logs_btn = self._build_install_logs_button()
        layout.addWidget(self._install_logs_btn)
        layout.addStretch(1)
        layout.addWidget(self._build_social_block())
        layout.addWidget(self._build_footer_block())

    def _build_install_logs_button(self) -> QPushButton:
        button = QPushButton()
        tr_set(button, "Логи установки", "Install logs", "setText")
        button.setObjectName("LauncherShellNavButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(qta.icon("fa6s.terminal", color="#ffd2ec"))
        tr_set(
            button,
            "Открыть окно установки и посмотреть логи",
            "Open the installation window and view logs",
            "setToolTip",
        )
        button.clicked.connect(self.install_logs_requested.emit)
        button.setVisible(False)
        return button

    def set_install_logs_visible(self, visible: bool) -> None:
        btn = getattr(self, "_install_logs_btn", None)
        if btn is not None:
            btn.setVisible(bool(visible))

    def _build_brand_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellBrandRow")

        row = QHBoxLayout(card)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(12)

        icon_label = QLabel()
        icon_label.setFixedSize(44, 44)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_path = resolve_launcher_asset("icon.png") or ("Icon.png" if Path("Icon.png").exists() else None)
        if logo_path:
            pixmap = QPixmap(logo_path).scaled(
                44,
                44,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon_label.setPixmap(pixmap)
        row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(0)

        title = QLabel("NeuroMita")
        title.setObjectName("LauncherShellBrandTitle")
        title_column.addWidget(title)

        subtitle = QLabel("Launcher")
        subtitle.setObjectName("LauncherShellBrandSubtitle")
        title_column.addWidget(subtitle)

        row.addLayout(title_column, 1)
        return card

    def _build_brand_divider(self) -> QFrame:
        divider = QFrame()
        divider.setObjectName("LauncherShellDivider")
        divider.setFixedHeight(1)
        return divider

    def _build_nav_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellNavHost")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(8)

        for section in self._sections:
            button = QPushButton()
            button.setObjectName("LauncherShellNavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("active", False)
            button.setIcon(qta.icon(section.icon_name, color="#ffd2ec"))
            tr_set(button, section.title_ru, section.title_en, "setText")
            tr_set(
                button,
                section.subtitle_ru or section.title_ru,
                section.subtitle_en or section.title_en,
                "setToolTip",
            )
            button.clicked.connect(lambda checked=False, key=section.key: self.request_page(key))
            self._button_group.addButton(button)
            self._nav_buttons[section.key] = button
            layout.addWidget(button)

        return card

    def _build_social_block(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("LauncherShellSocialBlock")
        wrapper.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(6)

        label = QLabel()
        tr_set(label, "СОЦ. СЕТИ", "SOCIAL", "setText")
        label.setObjectName("LauncherShellEyebrow")
        layout.addWidget(label)

        icon_card = QFrame()
        icon_card.setObjectName("LauncherShellSocialIconCard")
        icon_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(icon_card)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(12)

        # Пружина слева (оттолкнет кнопки к центру)
        row.addStretch(1)
        for key, title_text, icon_name in (
            ("discord", "Discord", "fa6b.discord"),
            ("github", "GitHub", "fa6b.github"),
            ("youtube", "YouTube", "fa6b.youtube"),
            ("boosty", "Boosty", "mdi.fire"),
        ):
            button = QPushButton("")
            button.setObjectName("LauncherShellSocialButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(qta.icon(icon_name, color="#ffd2ec"))
            button.setToolTip(title_text)
            button.setFixedSize(36, 36)
            button.setStyleSheet("""
                QPushButton#LauncherShellSocialButton {
                    background-color: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(255, 255, 255, 0.05);
                    border-radius: 6px;
                }
                QPushButton#LauncherShellSocialButton:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                    border: 1px solid rgba(255, 210, 236, 0.3);
                }
            """)
            button.clicked.connect(lambda checked=False, value=key: self.social_requested.emit(value))
            row.addWidget(button)

        row.addStretch(1)
        layout.addWidget(icon_card)
        return wrapper

    def _build_footer_block(self) -> QWidget:
        wrapper = QWidget()
        wrapper.setObjectName("LauncherShellFooterBlock")
        wrapper.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Контейнер для «быстрых» пилюль языков — его содержимое пересобирается
        # при смене языка (вторая пилюля зависит от текущего языка).
        pills_host = QWidget()
        # Явный objectName + прозрачный фон: иначе глобальное правило
        # QWidget { background-color: bg_root } из main-стилей рисует под
        # обеими пилюлями сплошной прямоугольник (фидбэк vinerx).
        pills_host.setObjectName("LauncherShellLangPillsHost")
        pills_layout = QHBoxLayout(pills_host)
        pills_layout.setContentsMargins(0, 0, 0, 0)
        pills_layout.setSpacing(6)
        self._lang_pills_layout = pills_layout
        self._rebuild_lang_pills()
        layout.addWidget(pills_host)

        # Иконка-планета справа от языков — ведёт в настройки языка.
        lang_settings_btn = QPushButton()
        lang_settings_btn.setObjectName("LauncherShellLangGlobe")
        # Нейтральный (приглушённый) цвет: глобус — это утилитарная кнопка, не
        # должен «гореть» акцентным розовым (фидбэк vinerx).
        lang_settings_btn.setIcon(qta.icon("fa6s.globe", color="#8b8b9c"))
        lang_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lang_settings_btn.setFixedSize(26, 26)
        tr_set(lang_settings_btn, "Настройки языка", "Language settings", "setToolTip")
        lang_settings_btn.clicked.connect(lambda: self.utility_requested.emit("language"))
        layout.addWidget(lang_settings_btn)

        layout.addStretch(1)

        version_label = QLabel(self._read_version_string())
        version_label.setObjectName("LauncherShellVersionLabel")
        self._version_label = version_label
        layout.addWidget(version_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return wrapper

    def _read_version_string(self) -> str:
        try:
            pending_version = str(self._version_provider() or "") if self._version_provider else ""
        except Exception:
            pending_version = ""
        if pending_version:
            return f"v{pending_version} ↻"
        try:
            from _version import __version__ as ver
            return f"v{ver}"
        except Exception:
            return ""

    def refresh_version_label(self) -> None:
        if self._version_label is not None:
            self._version_label.setText(self._read_version_string())

    def _rebuild_lang_pills(self) -> None:
        """Пересобирает «быстрые» пилюли языков: всегда EN слева + одна вторая.

        EN — основной язык (левая пилюля). Вторая пилюля показывает последний
        выбранный НЕ английский язык (по умолчанию русский), чтобы текущий язык
        был под рукой одним кликом. Активная пилюля подсвечивается («горит»)."""
        layout = self._lang_pills_layout
        if layout is None:
            return
        # Очистка прежних пилюль.
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._lang_buttons = {}

        try:
            from localization import available_languages
            available = {c.lower() for c in available_languages("full")}
        except Exception:
            available = {"ru", "en"}
        current = str(self._active_language or "ru").lower()

        # Запоминаем последний выбранный неанглийский язык для второй пилюли.
        if current != "en" and current in available:
            self._last_secondary_lang = current
        second = self._last_secondary_lang
        if second == "en" or second not in available:
            second = "ru"

        for code in ("en", second):
            button = QPushButton(code.upper())
            button.setObjectName("LauncherShellLangPill")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(34, 26)
            button.clicked.connect(lambda checked=False, value=code: self.utility_requested.emit(f"language:{value}"))
            self._lang_buttons[code] = button
            layout.addWidget(button)

    def request_page(self, page_key: str) -> None:
        self.set_active_page(page_key)
        self.page_requested.emit(page_key)

    def set_active_page(self, page_key: str) -> None:
        if page_key not in self._nav_buttons:
            return
        if self._active_page == page_key:
            self._nav_buttons[page_key].setChecked(True)
            return

        self._active_page = page_key
        for key, button in self._nav_buttons.items():
            is_active = key == page_key
            button.blockSignals(True)
            button.setChecked(is_active)
            button.setProperty("active", is_active)
            button.style().unpolish(button)
            button.style().polish(button)
            button.blockSignals(False)

    def set_active_language(self, code: str) -> None:
        code = (code or "").lower()
        self._active_language = code
        for key, button in self._lang_buttons.items():
            is_active = key == code
            button.blockSignals(True)
            button.setChecked(is_active)
            button.setProperty("active", is_active)
            button.style().unpolish(button)
            button.style().polish(button)
            button.blockSignals(False)

    def apply_nav_mode(self, mode_rank: int) -> None:
        _rank = {"basic": 0, "advanced": 1, "full": 2}
        for section in self._sections:
            button = self._nav_buttons.get(section.key)
            if button is None:
                continue
            need = _rank.get(section.min_mode, 0)
            button.setVisible(need <= mode_rank)

    def apply_section_visibility(self, is_enabled_fn) -> None:
        """Show/hide nav buttons via the per-section toggles. Sections whose
        spec defaults to "basic" stay always visible; gated sections (e.g.
        "developer") follow their SECTION_<KEY>_ENABLED toggle."""
        for section in self._sections:
            button = self._nav_buttons.get(section.key)
            if button is None:
                continue
            if section.min_mode == "basic":
                button.setVisible(True)
                continue
            try:
                button.setVisible(bool(is_enabled_fn(section.key)))
            except Exception:
                button.setVisible(True)

    def set_language_label(self, text: str) -> None:
        # Сохранено для совместимости со старым API: новый сайдбар показывает
        # отдельные кнопки RU/EN, поэтому label больше не используется.
        return
