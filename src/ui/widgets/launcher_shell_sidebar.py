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
    min_mode: str = "basic"


DEFAULT_SIDEBAR_SECTIONS: tuple[SidebarSection, ...] = (
    SidebarSection("home", _("Главная", "Home"), "fa6s.house", _("Обзор лаунчера", "Launcher overview")),
    SidebarSection("settings", _("Настройки", "Settings"), "fa6s.gear", _("Системные параметры", "System controls")),
    SidebarSection("sandbox", _("Песочница", "Sandbox"), "fa6s.flask", _("Быстрый вход в чат", "Quick chat access")),
    SidebarSection("news", _("Релизы", "Releases"), "fa6s.rectangle-list", _("Лента релизов проекта", "Project release feed")),
    SidebarSection("developer", _("Дев", "Dev"), "fa6s.bug", _("Отладка и дообучение", "Debug & fine-tuning"), min_mode="full"),
    SidebarSection("logs", _("Логи", "Logs"), "fa6s.list", _("События и диагностика", "Events and diagnostics")),
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
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LauncherShellSidebar")
        self.setFixedWidth(230)
        apply_launcher_shell_theme(self)

        if on_page_requested is not None:
            self.page_requested.connect(on_page_requested)

        self._sections = list(sections or DEFAULT_SIDEBAR_SECTIONS)
        self._nav_buttons: dict[str, QPushButton] = {}
        self._active_page = ""

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        self._lang_buttons: dict[str, QPushButton] = {}
        self._version_label: QLabel | None = None

        self._build_ui()
        self.set_active_page(initial_page)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
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
        button = QPushButton(_("Логи установки", "Install logs"))
        button.setObjectName("LauncherShellNavButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(qta.icon("fa6s.terminal", color="#ffd2ec"))
        button.setToolTip(_(
            "Открыть окно установки и посмотреть логи",
            "Open the installation window and view logs",
        ))
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
            button.setText(section.title)
            button.setToolTip(section.subtitle or section.title)
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

        label = QLabel(_("СОЦ. СЕТИ", "SOCIAL"))
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
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(6)

        # Языки строим динамически из доступных JSON-локалей (RU + всё, что найдено
        # в localization/locales и внешней папке NEUROMITA_BASE_DIR/Localization).
        try:
            from localization import available_languages
            langs = [c.lower() for c in available_languages()]
        except Exception:
            langs = ["ru", "en"]
        # RU всегда первым, остальные по алфавиту
        langs = ["ru"] + sorted(c for c in langs if c != "ru")
        for code in langs:
            label_text = code.upper()
            button = QPushButton(label_text)
            button.setObjectName("LauncherShellLangPill")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(40, 28)
            button.clicked.connect(lambda checked=False, value=code: self.utility_requested.emit(f"language:{value}"))
            self._lang_buttons[code] = button
            layout.addWidget(button)

        layout.addStretch(1)

        version_label = QLabel(self._read_version_string())
        version_label.setObjectName("LauncherShellVersionLabel")
        self._version_label = version_label
        layout.addWidget(version_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return wrapper

    def _read_version_string(self) -> str:
        pending_version = str(getattr(self.window(), "_pending_python_restart_version", "") or "").strip()
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
