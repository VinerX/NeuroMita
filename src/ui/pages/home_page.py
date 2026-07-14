from __future__ import annotations

from pathlib import Path

import qtawesome as qta
from PyQt6.QtCore import QPoint, QRectF, QSize, Qt, QSignalBlocker, QTimer
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from localization.live import tr_set
from main_logger import logger
from ui.pages.home_presentation import (
    HomeActivated,
    HomeApplyUpdatesRequested,
    HomeCancelRequested,
    HomeExternalProgress,
    HomeHideProgress,
    HomeInstallUnityRequested,
    HomeLanguageChanged,
    HomeNewsItemState,
    HomeOpenRelease,
    HomeOpenReleaseRequested,
    HomeOpenUnityFolderRequested,
    HomePrimaryRequested,
    HomePromptRestart,
    HomePromptTesterCode,
    HomeRefreshNews,
    HomeRefreshSidebar,
    HomeRefreshUpdates,
    HomeRestartDecision,
    HomeShowError,
    HomeState,
    HomeStopUnityRequested,
    HomeTesterCodeSubmitted,
    HomeToggleUpdate,
)
from utils import _


def _strip_v(version: str) -> str:
    text = str(version or "").strip()
    return text[1:] if text[:1] in ("v", "V") else text


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
        if self._bg.isNull():
            painter.fillRect(rect, QColor("#09050f"))
            return
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


class LauncherPrimaryButton(QPushButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._progress_visible = False
        self._progress_busy = False
        self._progress_value = 0
        self._progress_maximum = 100
        self._pulse = 0
        self._animation = QTimer(self)
        self._animation.setInterval(35)
        self._animation.timeout.connect(self._advance_pulse)

    def set_operation_progress(
        self,
        *,
        visible: bool,
        value: int,
        maximum: int,
        busy: bool,
    ) -> None:
        self._progress_visible = bool(visible)
        self._progress_value = max(0, int(value))
        self._progress_maximum = max(1, int(maximum or 1))
        self._progress_busy = bool(busy)
        if self._progress_visible and self._progress_busy:
            if not self._animation.isActive():
                self._animation.start()
        else:
            self._animation.stop()
        self.update()

    def _advance_pulse(self) -> None:
        self._pulse = (self._pulse + 3) % 140
        self.update()

    def paintEvent(self, _event) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButtonBevel, option)
        if self._progress_visible:
            content = self.rect().adjusted(1, 1, -1, -1)
            painter.save()
            painter.setClipRect(content)
            if self._progress_busy:
                width = max(70, int(content.width() * 0.28))
                left = int((content.width() + width) * self._pulse / 140) - width
                fill = content.adjusted(left, 0, -(content.width() - left - width), 0)
            else:
                width = int(content.width() * min(1.0, self._progress_value / self._progress_maximum))
                fill = content.adjusted(0, 0, -(content.width() - width), 0)
            painter.fillRect(fill, QColor(255, 255, 255, 38))
            painter.restore()
        painter.drawControl(QStyle.ControlElement.CE_PushButtonLabel, option)


class HomePage(LauncherHomeBackground):
    """Passive launcher home view: intents in, immutable state/effects out."""

    def __init__(self, parent, view_model, page_actions):
        super().__init__(parent)
        self.view_model = view_model
        self._page_actions = page_actions
        self._state = HomeState()
        self._rendered_news: tuple[HomeNewsItemState, ...] = ()
        self._backend_status_value: QLabel | None = None
        self._unity_status_value: QLabel | None = None
        self._py_update_check: QCheckBox | None = None
        self._unity_update_check: QCheckBox | None = None
        self._py_new_badge: QLabel | None = None
        self._unity_new_badge: QLabel | None = None
        self._news_items_layout: QVBoxLayout | None = None
        self._menu_button: QPushButton | None = None
        self.primary_button: LauncherPrimaryButton | None = None

        self._build_ui()
        self.view_model.state_changed.connect(self.render)
        self.view_model.effect_emitted.connect(self.handle_effect)
        self.destroyed.connect(lambda *_args: self.view_model.close())
        try:
            from localization.live import language_changed_signal

            language_changed_signal().connect(self._on_language_changed)
        except Exception:
            logger.debug("Home language signal is unavailable", exc_info=True)
        self.render(self.view_model.state)

    def dispatch_intent(self, intent) -> None:
        self.view_model.dispatch(intent)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(44, 42, 36, 32)
        layout.setSpacing(0)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(24)

        left_column = QVBoxLayout()
        left_column.setSpacing(14)
        title = tr_set(QLabel(), "Добро пожаловать!", "Welcome!")
        title.setObjectName("LauncherHomeTitle")
        left_column.addWidget(title)
        subtitle = tr_set(
            QLabel(),
            "Погрузись Miside по-новому с NeuroMita.",
            "Experience Miside in a new way with NeuroMita.",
        )
        subtitle.setObjectName("LauncherHomeSubtitle")
        left_column.addWidget(subtitle)
        left_column.addStretch(1)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        backend_card, self._backend_status_value, self._py_update_check, self._py_new_badge = self._build_status_card(
            "fa6b.python", _("Python-бэкенд", "Python backend"), "#ffd86b", "python"
        )
        status_row.addWidget(backend_card)
        unity_card, self._unity_status_value, self._unity_update_check, self._unity_new_badge = self._build_status_card(
            "mdi.unity", "Unity", "#f0f0f0", "unity"
        )
        status_row.addWidget(unity_card)
        left_column.addLayout(status_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(0)
        self.primary_button = LauncherPrimaryButton()
        self.primary_button.setObjectName("LauncherHomePrimaryButton")
        self.primary_button.clicked.connect(
            lambda: self.dispatch_intent(HomePrimaryRequested())
        )
        button_row.addWidget(self.primary_button, 1)

        self._menu_button = QPushButton("")
        self._menu_button.setObjectName("LauncherHomeMenuButton")
        self._menu_button.setIcon(qta.icon("fa6s.chevron-down", color="#ffd2ec"))
        self._menu_button.setIconSize(QSize(14, 14))
        self._menu_button.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        self._menu_button.clicked.connect(self._on_menu_button_clicked)
        button_row.addWidget(self._menu_button)
        left_column.addLayout(button_row)

        right_column = QVBoxLayout()
        right_column.setContentsMargins(0, 0, 0, 8)
        right_column.addStretch(1)
        right_column.addWidget(self._build_news_panel())
        content.addLayout(left_column, 5)
        content.addLayout(right_column, 2)
        layout.addLayout(content)

    def _build_status_card(
        self,
        icon_name: str,
        title_text: str,
        color: str,
        component: str,
    ) -> tuple[QFrame, QLabel, QCheckBox, QLabel]:
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
        eyebrow_row = QHBoxLayout()
        eyebrow_row.setSpacing(6)
        title = QLabel(title_text.upper())
        title.setObjectName("LauncherHomeStatusEyebrow")
        eyebrow_row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        badge = QLabel("")
        badge.setObjectName("LauncherHomeNewBadge")
        badge.setVisible(False)
        eyebrow_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        eyebrow_row.addStretch(1)
        text_column.addLayout(eyebrow_row)
        value = QLabel("")
        value.setObjectName("LauncherHomeStatusValue")
        text_column.addWidget(value)
        layout.addLayout(text_column, 1)

        update_check = QCheckBox()
        update_check.setObjectName("LauncherHomeStatusCheck")
        update_check.setVisible(False)
        tr_set(
            update_check,
            "Выбрать компонент для установки или обновления",
            "Select component for installation or update",
            "setToolTip",
        )
        update_check.toggled.connect(
            lambda selected, name=component: self.dispatch_intent(
                HomeToggleUpdate(name, bool(selected))
            )
        )
        layout.addWidget(update_check, 0, Qt.AlignmentFlag.AlignTop)
        return card, value, update_check, badge

    def _build_news_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("LauncherHomeNewsPanel")
        panel.setMinimumWidth(280)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = tr_set(
            QLabel(),
            "Последние релизы",
            "Latest releases",
            transform=str.upper,
        )
        title.setObjectName("LauncherHomeNewsTitle")
        header.addWidget(title)
        header.addStretch(1)
        all_news = tr_set(QPushButton(), "Все релизы", "All releases")
        all_news.setObjectName("LauncherHomeLinkButton")
        all_news.clicked.connect(lambda: self._page_actions.switch_page("news"))
        header.addWidget(all_news)
        layout.addLayout(header)
        divider = QFrame()
        divider.setObjectName("LauncherHomeDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        items_host = QWidget()
        items_host.setObjectName("LauncherHomeNewsItems")
        self._news_items_layout = QVBoxLayout(items_host)
        self._news_items_layout.setContentsMargins(0, 0, 0, 0)
        self._news_items_layout.setSpacing(8)
        layout.addWidget(items_host)
        return panel

    def render(self, state: HomeState) -> None:
        self._state = state
        if self._backend_status_value is not None:
            self._backend_status_value.setText(state.backend_status)
        if self._unity_status_value is not None:
            self._unity_status_value.setText(state.unity_status)
        self._render_update_control(
            self._py_update_check,
            self._py_new_badge,
            state.python_update.available or state.python_update.installable,
            state.python_update.available,
            state.python_update.selected,
            state.python_update.latest_version,
        )
        self._render_update_control(
            self._unity_update_check,
            self._unity_new_badge,
            state.unity_update.available or state.unity_update.installable,
            state.unity_update.available,
            state.unity_update.selected,
            state.unity_update.latest_version,
        )
        if self.primary_button is not None:
            mode = "progress" if state.progress_visible else state.primary_action
            if self.primary_button.property("mode") != mode:
                self.primary_button.setProperty("mode", mode)
                self.primary_button.style().unpolish(self.primary_button)
                self.primary_button.style().polish(self.primary_button)
            full_text = state.progress_text if state.progress_visible and state.progress_text else state.primary_label
            available_width = max(140, self.primary_button.width() - 90)
            visible_text = self.primary_button.fontMetrics().elidedText(
                full_text,
                Qt.TextElideMode.ElideRight,
                available_width,
            )
            self.primary_button.setText(visible_text)
            self.primary_button.setToolTip(full_text if visible_text != full_text else "")
            icon_name = state.primary_icon_name
            if state.progress_visible:
                if state.progress_busy:
                    icon_name = "fa6s.spinner"
                elif state.progress_maximum > 0 and state.progress_value >= state.progress_maximum:
                    icon_name = "fa6s.check"
                else:
                    icon_name = "fa6s.download"
            self.primary_button.setIcon(qta.icon(icon_name, color="#ffffff"))
            self.primary_button.setIconSize(QSize(15, 15))
            self.primary_button.setEnabled(
                state.operation is None
                and not state.progress_visible
                and state.primary_action not in {"busy", "starting", "stopping", "unavailable"}
            )
        self._render_progress(state)
        self._render_menu_indicator(state)
        if state.news != self._rendered_news:
            self._rendered_news = state.news
            self._render_news(state.news)

    def _render_update_control(
        self,
        control: QCheckBox | None,
        badge: QLabel | None,
        selectable: bool,
        available: bool,
        selected: bool,
        version: str,
    ) -> None:
        if control is not None:
            blocker = QSignalBlocker(control)
            control.setVisible(bool(selectable))
            control.setChecked(bool(selectable and selected))
            del blocker
        if badge is not None:
            badge.setVisible(bool(available))
            if available:
                normalized = _strip_v(version)
                badge.setText(
                    _("NEW {ver}", "NEW {ver}").format(ver=normalized).strip()
                    if normalized
                    else _("NEW", "NEW")
                )

    def _render_progress(self, state: HomeState) -> None:
        if self.primary_button is not None:
            self.primary_button.set_operation_progress(
                visible=state.progress_visible,
                value=state.progress_value,
                maximum=state.progress_maximum,
                busy=state.progress_busy,
            )

    def _render_menu_indicator(self, state: HomeState) -> None:
        if self._menu_button is None:
            return
        if state.operation is not None:
            self._menu_button.setProperty("hasUpdate", "false")
            if state.can_cancel:
                self._menu_button.setIcon(qta.icon("fa6s.xmark", color="#ffffff"))
                self._menu_button.setToolTip(_("Отменить", "Cancel"))
                self._menu_button.setEnabled(True)
                self._menu_button.setProperty("mode", "cancel")
            else:
                self._menu_button.setIcon(qta.icon("fa6s.lock", color="#8f8793"))
                self._menu_button.setToolTip(_("Этот этап нельзя прервать", "This stage cannot be interrupted"))
                self._menu_button.setEnabled(False)
                self._menu_button.setProperty("mode", "locked")
            self._menu_button.style().unpolish(self._menu_button)
            self._menu_button.style().polish(self._menu_button)
            return
        has_update = bool(
            state.python_update.available or state.unity_update.available
        )
        color = "#ffcf7d" if has_update else "#ffd2ec"
        self._menu_button.setIcon(qta.icon("fa6s.chevron-down", color=color))
        self._menu_button.setEnabled(True)
        self._menu_button.setProperty("mode", "menu")
        self._menu_button.setProperty("hasUpdate", "true" if has_update else "false")
        self._menu_button.setToolTip(
            _("Доступны обновления", "Updates available")
            if has_update
            else _("Дополнительно", "More")
        )
        self._menu_button.style().unpolish(self._menu_button)
        self._menu_button.style().polish(self._menu_button)

    def _on_menu_button_clicked(self) -> None:
        if self._state.operation is not None:
            if self._state.can_cancel:
                self.dispatch_intent(HomeCancelRequested())
            return
        if self._menu_button is not None:
            self.show_extra_menu(self._menu_button)

    def _render_news(self, items: tuple[HomeNewsItemState, ...]) -> None:
        if self._news_items_layout is None:
            return
        while self._news_items_layout.count():
            item = self._news_items_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not items:
            items = (
                HomeNewsItemState(
                    _("Релизы недоступны", "Releases unavailable"),
                    _(
                        "Удалённая лента релизов пока недоступна.",
                        "Remote release feed is currently unavailable.",
                    ),
                ),
            )
        for item in items:
            self._news_items_layout.addWidget(self._build_news_item(item))

    def _build_news_item(self, item: HomeNewsItemState) -> QFrame:
        row = QFrame()
        row.setObjectName("LauncherHomeNewsItem")
        if item.item_id:
            row.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        title = QLabel(item.title)
        title.setObjectName("LauncherHomeNewsItemTitle")
        layout.addWidget(title, 1)
        tooltip = str(item.full_text or item.summary or "").strip()
        if tooltip:
            row.setToolTip(tooltip)
            title.setToolTip(tooltip)
        if item.timestamp:
            stamp = QLabel(self._format_news_date(item.timestamp))
            stamp.setObjectName("LauncherHomeNewsDate")
            layout.addWidget(stamp, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        if item.item_id:
            row.mousePressEvent = lambda _event, release_id=item.item_id: self.dispatch_intent(
                HomeOpenReleaseRequested(release_id)
            )
        return row

    @staticmethod
    def _format_news_date(value: str) -> str:
        date_part = str(value or "")[:10]
        parts = date_part.split("-")
        return f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else date_part

    def handle_effect(self, effect) -> None:
        if isinstance(effect, HomePromptTesterCode):
            code, accepted = QInputDialog.getText(
                self,
                _("Код тестера", "Tester code"),
                _(
                    "Введите код тестера для установки релизных архивов.",
                    "Enter the tester code required to install release archives.",
                ),
                QLineEdit.EchoMode.Password,
                "",
            )
            self.dispatch_intent(
                HomeTesterCodeSubmitted(
                    effect.continuation,
                    str(code or "").strip() if accepted else None,
                )
            )
            return
        if isinstance(effect, HomePromptRestart):
            result = QMessageBox.question(
                self,
                _("Обновление установлено", "Update installed"),
                _(
                    "Python-обновление установлено.\n\n"
                    "Перезапустить приложение сейчас, чтобы применить его?",
                    "The Python update has been installed.\n\n"
                    "Restart the application now to apply it?",
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            self.dispatch_intent(
                HomeRestartDecision(result == QMessageBox.StandardButton.Yes)
            )
            return
        if isinstance(effect, HomeShowError):
            QMessageBox.warning(self, effect.title, effect.message)
            return
        if isinstance(effect, HomeOpenRelease):
            self._page_actions.open_release_page(effect.release_id)
            return
        if isinstance(effect, HomeRefreshSidebar):
            self._page_actions.refresh_sidebar_version()

    def show_extra_menu(self, anchor_widget) -> None:
        menu = QMenu(self)
        menu.setObjectName("LauncherHomeExtraMenu")
        menu.addAction(
            _("Проверить обновления", "Check for updates"),
            lambda: self.dispatch_intent(HomeRefreshUpdates(force=True, show_result=True)),
        )
        menu.addAction(
            _("Настройки обновлений", "Update settings"),
            lambda: self._page_actions.show_settings_category("updates"),
        )
        menu.addAction(
            _("Открыть папку Unity", "Open Unity folder"),
            lambda: self.dispatch_intent(HomeOpenUnityFolderRequested()),
        )
        if self._state.unity_process_state == "running":
            menu.addSeparator()
            menu.addAction(
                _("Закрыть Unity", "Close Unity"),
                lambda: self.dispatch_intent(HomeStopUnityRequested()),
            )
        menu.exec(anchor_widget.mapToGlobal(QPoint(0, anchor_widget.height())))

    def on_activated(self) -> None:
        self.dispatch_intent(HomeActivated())

    def refresh_primary_label(self) -> None:
        self.render(self.view_model.state)

    def refresh_status_cards(self) -> None:
        self.dispatch_intent(HomeLanguageChanged())

    def refresh_news_content(self) -> None:
        self.dispatch_intent(HomeRefreshNews())

    def set_progress(
        self,
        text: str,
        value: int,
        maximum: int,
        *,
        busy: bool = False,
    ) -> None:
        self.dispatch_intent(
            HomeExternalProgress(
                text=str(text),
                value=int(value),
                maximum=int(maximum),
                busy=bool(busy),
            )
        )

    def hide_progress(self) -> None:
        self.dispatch_intent(HomeHideProgress())

    def run_primary_action(self) -> None:
        self.dispatch_intent(HomePrimaryRequested())

    def run_install_unity(self) -> None:
        self.dispatch_intent(HomeInstallUnityRequested())

    def run_selective_update(self) -> None:
        self.dispatch_intent(HomeApplyUpdatesRequested())

    def run_check_updates_action(self) -> None:
        self.dispatch_intent(HomeRefreshUpdates(force=True, show_result=True))

    def run_verify_action(self) -> None:
        self.run_check_updates_action()

    def _on_language_changed(self, _code: str = "") -> None:
        self.dispatch_intent(HomeLanguageChanged())


def build_home_page(parent, view_model, page_actions) -> QWidget:
    page = HomePage(parent, view_model, page_actions)
    view_model.setParent(page)
    return page
