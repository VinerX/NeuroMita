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

from ui.widgets.launcher_shell_theme import apply_launcher_shell_theme, resolve_launcher_asset


@dataclass(frozen=True)
class SidebarSection:
    key: str
    title: str
    icon_name: str
    subtitle: str = ""


DEFAULT_SIDEBAR_SECTIONS: tuple[SidebarSection, ...] = (
    SidebarSection("home", _("Главная", "Home"), "fa6s.house", _("Обзор лаунчера", "Launcher overview")),
    SidebarSection("news", _("Новости", "News"), "fa6s.newspaper", _("Апдейты и заметки", "Updates and notes")),
    SidebarSection("sandbox", _("Песочница", "Sandbox"), "fa6s.flask", _("Быстрый вход в чат", "Quick chat access")),
    SidebarSection("settings", _("Настройки", "Settings"), "fa6s.sliders", _("Системные параметры", "System controls")),
    SidebarSection("logs", _("Логи", "Logs"), "fa6s.wave-square", _("События и диагностика", "Events and diagnostics")),
)


DEFAULT_SIDEBAR_SECTIONS = (
    SidebarSection("home", _("Главная", "Home"), "fa6s.house", _("Обзор лаунчера", "Launcher overview")),
    SidebarSection("news", _("Новости", "News"), "fa6s.rectangle-list", _("Апдейты и заметки", "Updates and notes")),
    SidebarSection("sandbox", _("Песочница", "Sandbox"), "fa6s.flask", _("Быстрый вход в чат", "Quick chat access")),
    SidebarSection("settings", _("Настройки", "Settings"), "fa6s.gear", _("Системные параметры", "System controls")),
    SidebarSection("logs", _("Логи", "Logs"), "fa6s.list", _("События и диагностика", "Events and diagnostics")),
)


class LauncherSidebarWidget(QFrame):
    page_requested = pyqtSignal(str)
    social_requested = pyqtSignal(str)
    utility_requested = pyqtSignal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        sections: Iterable[SidebarSection] | None = None,
        initial_page: str = "home",
        on_page_requested: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LauncherShellSidebar")
        apply_launcher_shell_theme(self)

        if on_page_requested is not None:
            self.page_requested.connect(on_page_requested)

        self._sections = list(sections or DEFAULT_SIDEBAR_SECTIONS)
        self._nav_buttons: dict[str, QPushButton] = {}
        self._active_page = ""

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        self._status_title_label: QLabel | None = None
        self._status_value_label: QLabel | None = None
        self._lang_button: QPushButton | None = None
        self._promo_button: QPushButton | None = None

        self._build_ui()
        self.set_active_page(initial_page)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        layout.addWidget(self._build_brand_card())
        layout.addWidget(self._build_nav_card())
        layout.addStretch(1)
        layout.addWidget(self._build_social_card())
        layout.addWidget(self._build_status_card())
        layout.addWidget(self._build_promo_card())

    def _build_brand_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(0, 0, 0, 0)
        logo_row.setSpacing(12)

        icon_label = QLabel()
        logo_path = resolve_launcher_asset("icon.png") or ("Icon.png" if Path("Icon.png").exists() else None)
        if logo_path:
            pixmap = QPixmap(logo_path).scaled(
                42,
                42,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon_label.setPixmap(pixmap)
        logo_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(4)

        eyebrow = QLabel("NEON SHELL")
        eyebrow.setObjectName("LauncherShellEyebrow")
        title_column.addWidget(eyebrow)

        title = QLabel("NeuroMita")
        title.setObjectName("LauncherShellTitle")
        title_column.addWidget(title)

        subtitle = QLabel(_("Лаунчер-панель проекта", "Project launcher shell"))
        subtitle.setObjectName("LauncherShellSubtitle")
        subtitle.setWordWrap(True)
        title_column.addWidget(subtitle)

        logo_row.addLayout(title_column, 1)
        layout.addLayout(logo_row)
        return card

    def _build_nav_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        nav_title = QLabel(_("Разделы", "Sections"))
        nav_title.setObjectName("LauncherShellSectionTitle")
        layout.addWidget(nav_title)

        for section in self._sections:
            button = QPushButton()
            button.setObjectName("LauncherShellNavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("active", False)
            button.setIcon(qta.icon(section.icon_name, color="#ffd2ec"))
            button.setText(section.title)
            button.setToolTip(section.subtitle or section.title)
            button.clicked.connect(lambda checked=False, key=section.key: self.request_page(key))
            self._button_group.addButton(button)
            self._nav_buttons[section.key] = button
            layout.addWidget(button)

        return card

    def _build_social_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSocialCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(_("Ссылки", "Social"))
        title.setObjectName("LauncherShellSectionTitle")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        for key, title_text, icon_name in (
            ("discord", "Discord", "fa6b.discord"),
            ("vk", "VK", "fa6b.vk"),
            ("youtube", "YouTube", "fa6b.youtube"),
        ):
            button = QPushButton("")
            button.setObjectName("LauncherShellSocialButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(qta.icon(icon_name, color="#ffd2ec"))
            button.setToolTip(title_text)
            button.setFixedSize(48, 42)
            button.clicked.connect(lambda checked=False, value=key: self.social_requested.emit(value))
            row.addWidget(button)

        layout.addLayout(row)

        lang_button = QPushButton(_("Язык: RU/EN", "Language: RU/EN"))
        lang_button.setObjectName("LauncherShellChipButton")
        lang_button.setCursor(Qt.CursorShape.PointingHandCursor)
        lang_button.clicked.connect(lambda: self.utility_requested.emit("language"))
        self._lang_button = lang_button
        layout.addWidget(lang_button)

        return card

    def _build_status_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellStatusCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        dot = QLabel()
        dot.setObjectName("LauncherShellStatusDot")
        top_row.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        title = QLabel(_("Статус", "Status"))
        title.setObjectName("LauncherShellSectionTitle")
        top_row.addWidget(title)
        top_row.addStretch(1)
        layout.addLayout(top_row)

        value = QLabel(_("Система готова", "System ready"))
        value.setObjectName("LauncherShellSectionValue")
        layout.addWidget(value)

        meta = QLabel(_("Все shell widgets изолированы и готовы к подключению.", "All shell widgets are isolated and ready to mount."))
        meta.setObjectName("LauncherShellMeta")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        self._status_title_label = title
        self._status_value_label = value
        return card

    def _build_promo_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellPromoCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        eyebrow = QLabel("PROMO")
        eyebrow.setObjectName("LauncherShellEyebrow")
        layout.addWidget(eyebrow)

        title = QLabel(_("Launcher Shell", "Launcher Shell"))
        title.setObjectName("LauncherShellSectionTitle")
        layout.addWidget(title)

        body = QLabel(
            _(
                "Единый вход для главной, новостей, песочницы, настроек и логов.",
                "One entry point for home, news, sandbox, settings and logs.",
            )
        )
        body.setObjectName("LauncherShellBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        promo_button = QPushButton(_("Открыть Home", "Open Home"))
        promo_button.setObjectName("LauncherShellPromoButton")
        promo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        promo_button.clicked.connect(lambda: self.request_page("home"))
        self._promo_button = promo_button
        layout.addWidget(promo_button)
        return card

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

        if self._promo_button is not None:
            current_title = next((section.title for section in self._sections if section.key == page_key), page_key.title())
            self._promo_button.setText(_("Открыть: ", "Open: ") + current_title)

    def set_status(self, title: str, value: str) -> None:
        if self._status_title_label is not None:
            self._status_title_label.setText(title)
        if self._status_value_label is not None:
            self._status_value_label.setText(value)

    def set_language_label(self, text: str) -> None:
        if self._lang_button is not None:
            self._lang_button.setText(text)
