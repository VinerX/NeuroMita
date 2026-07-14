from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt

from ui.widgets.launcher_dashboard_helpers import (
    DashboardAction,
    create_shell_page_container,
    _create_hero_card,
)
from utils import _
from localization.live import tr_set


class DeveloperPage(QWidget):
    def __init__(self, parent, finetune_view_model, page_actions, settings):
        super().__init__(parent)
        self._page_actions = page_actions
        self._settings = settings
        self._finetune_view_model = finetune_view_model
        self.setObjectName("DeveloperPage")
        self.destroyed.connect(lambda *_args: self._finetune_view_model.close())

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root, content_layout = create_shell_page_container()
        root.setParent(self)

        content_layout.addWidget(self._build_hero())
        content_layout.addWidget(self._build_finetune_card())
        content_layout.addStretch(1)

        root_layout.addWidget(root)

    # ── Hero ──────────────────────────────────────────────────────────────────

    def _build_hero(self) -> QFrame:
        return _create_hero_card(
            "DEV",
            _("Сбор данных для дообучения", "Fine-tune data collection"),
            _(
                "Сбор и экспорт данных для дообучения модели. Параметры отладки переехали в Песочницу → Отладка.",
                "Collect and export data for fine-tuning. Debug parameters moved to Sandbox → Debug.",
            ),
            actions=[
                DashboardAction(
                    _("Sandbox", "Sandbox"),
                    callback=lambda: self._page_actions.switch_page("sandbox"),
                    icon_name="fa6s.flask",
                    accent=False,
                ),
            ],
        )

    # ── Debug card ────────────────────────────────────────────────────────────

    def _build_debug_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        title = tr_set(QLabel(), "Отладка", "Debug")
        title.setObjectName("LauncherShellSectionTitle")
        layout.addWidget(title)

        subtitle = tr_set(
            QLabel(),
            "Параметры вывода structured output, системные сообщения, снапшоты и просмотр контекста.",
            "Structured output display, system messages, history snapshots and context viewer.",
        )
        subtitle.setObjectName("LauncherShellMeta")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #333; margin: 4px 0;")
        layout.addWidget(sep)

        try:
            from ui.settings.debug_settings import setup_debug_panel_controls
            setup_debug_panel_controls(
                layout,
                settings=self._settings,
                insert_system_message=self._page_actions.insert_debug_message,
                save_snapshot=self._page_actions.save_debug_snapshot,
                load_snapshot=self._page_actions.load_debug_snapshot,
                view_context=self._page_actions.view_debug_context,
            )
        except Exception as exc:
            err = QLabel(f"[debug_settings error] {exc}")
            err.setWordWrap(True)
            layout.addWidget(err)

        return card

    # ── Finetune card ─────────────────────────────────────────────────────────

    def _build_finetune_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        try:
            from ui.settings.data_settings import setup_data_settings_controls
            setup_data_settings_controls(
                self,
                layout,
                view_model=self._finetune_view_model,
            )
        except Exception as exc:
            err = QLabel(f"[data_settings error] {exc}")
            err.setWordWrap(True)
            layout.addWidget(err)

        return card

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_activated(self):
        pass

    def on_deactivated(self):
        pass

    @property
    def settings(self):
        return self._settings

    def _get_setting(self, key, default=None):
        getter = getattr(self._settings, "get", None)
        return getter(str(key), default) if callable(getter) else default

    def _save_setting(self, key, value) -> None:
        setter = getattr(self._settings, "set", None)
        if callable(setter):
            setter(str(key), value)



def build_developer_page(parent, finetune_view_model, page_actions, settings) -> QWidget:
    page = DeveloperPage(parent, finetune_view_model, page_actions, settings)
    finetune_view_model.setParent(page)
    return page
