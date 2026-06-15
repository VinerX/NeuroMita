from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import qtawesome as qta
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from utils import _

from ui.widgets.launcher_shell_theme import apply_launcher_shell_theme


Callback = Callable[[], None]


@dataclass(slots=True)
class DashboardAction:
    label: str
    callback: Callback | None = None
    icon_name: str = "fa6s.bolt"
    accent: bool = True
    tooltip: str = ""


@dataclass(slots=True)
class DashboardMetric:
    label: str
    value: str
    meta: str = ""


@dataclass(slots=True)
class DashboardCard:
    title: str
    body: str
    meta: str = ""
    icon_name: str = "fa6s.star"
    action: DashboardAction | None = None


@dataclass(slots=True)
class NewsItem:
    title: str
    summary: str
    tag: str = "Update"
    timestamp: str = ""
    action: DashboardAction | None = None


@dataclass(slots=True)
class LogItem:
    level: str
    message: str
    timestamp: str = ""
    context: str = ""
    action: DashboardAction | None = None


def create_shell_page_container() -> tuple[QWidget, QVBoxLayout]:
    root = QWidget()
    root.setObjectName("LauncherShellRoot")
    apply_launcher_shell_theme(root)

    backdrop = QFrame(root)
    backdrop.setObjectName("LauncherShellBackdrop")
    outer = QVBoxLayout(root)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(backdrop)

    backdrop_layout = QVBoxLayout(backdrop)
    backdrop_layout.setContentsMargins(14, 12, 14, 12)
    backdrop_layout.setSpacing(0)

    scroll = QScrollArea()
    scroll.setObjectName("LauncherShellScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)

    content = QWidget()
    content.setObjectName("LauncherShellPage")
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(14, 14, 14, 14)
    content_layout.setSpacing(14)

    scroll.setWidget(content)
    backdrop_layout.addWidget(scroll)
    return root, content_layout


def create_home_page(
    *,
    title: str,
    subtitle: str,
    hero_tag: str = "HOME",
    metrics: Iterable[DashboardMetric] = (),
    actions: Iterable[DashboardAction] = (),
    cards: Iterable[DashboardCard] = (),
) -> QWidget:
    root, layout = create_shell_page_container()
    layout.addWidget(_create_hero_card(hero_tag, title, subtitle, actions))

    metrics_list = list(metrics)
    if metrics_list:
        layout.addLayout(_create_metrics_row(metrics_list))

    cards_list = list(cards)
    if cards_list:
        layout.addLayout(_create_card_grid(cards_list))

    layout.addStretch(1)
    return root


def create_news_page(
    *,
    title: str | None = None,
    subtitle: str | None = None,
    items: Iterable[NewsItem] = (),
    header_actions: Iterable[DashboardAction] = (),
) -> QWidget:
    page_title = title or _("Новости лаунчера", "Launcher news")
    page_subtitle = subtitle or _("Свежие заметки, changelog и внутренние апдейты.", "Fresh notes, changelog and internal updates.")
    root, layout = create_shell_page_container()
    layout.addWidget(_create_hero_card("NEWS", page_title, page_subtitle, header_actions))

    for item in items:
        layout.addWidget(_create_news_card(item))

    layout.addStretch(1)
    return root


def create_logs_page(
    *,
    title: str | None = None,
    subtitle: str | None = None,
    items: Iterable[LogItem] = (),
    header_actions: Iterable[DashboardAction] = (),
) -> QWidget:
    page_title = title or _("Лента логов", "Logs stream")
    page_subtitle = subtitle or _("Короткий helper для системных событий, ошибок и служебных действий.", "A compact helper for system events, errors and service actions.")
    root, layout = create_shell_page_container()
    layout.addWidget(_create_hero_card("LOGS", page_title, page_subtitle, header_actions))

    for item in items:
        layout.addWidget(_create_log_card(item))

    layout.addStretch(1)
    return root


def _create_hero_card(
    eyebrow_text: str,
    title_text: str,
    subtitle_text: str,
    actions: Iterable[DashboardAction],
) -> QFrame:
    card = QFrame()
    card.setObjectName("LauncherShellHeroCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    eyebrow = QLabel(eyebrow_text)
    eyebrow.setObjectName("LauncherShellEyebrow")
    layout.addWidget(eyebrow)

    title = QLabel(title_text)
    title.setObjectName("LauncherShellTitle")
    title.setWordWrap(True)
    layout.addWidget(title)

    subtitle = QLabel(subtitle_text)
    subtitle.setObjectName("LauncherShellSubtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)

    actions_list = list(actions)
    if actions_list:
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(10)
        for action in actions_list:
            row.addWidget(_create_action_button(action))
        row.addStretch(1)
        layout.addLayout(row)

    return card


def _create_metrics_row(metrics: list[DashboardMetric]) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)

    for metric in metrics:
        card = QFrame()
        card.setObjectName("LauncherShellMetricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        label = QLabel(metric.label)
        label.setObjectName("LauncherShellMeta")
        layout.addWidget(label)

        value = QLabel(metric.value)
        value.setObjectName("LauncherShellSectionValue")
        layout.addWidget(value)

        if metric.meta:
            meta = QLabel(metric.meta)
            meta.setObjectName("LauncherShellHint")
            meta.setWordWrap(True)
            layout.addWidget(meta)

        row.addWidget(card, 1)

    return row


def _create_card_grid(cards: list[DashboardCard]) -> QGridLayout:
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(12)

    for index, card_data in enumerate(cards):
        card = QFrame()
        card.setObjectName("LauncherShellSectionCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)

        icon = QLabel()
        icon.setPixmap(qta.icon(card_data.icon_name, color="#ffd2ec").pixmap(18, 18))
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        title = QLabel(card_data.title)
        title.setObjectName("LauncherShellSectionTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        layout.addLayout(top)

        body = QLabel(card_data.body)
        body.setObjectName("LauncherShellBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        if card_data.meta:
            meta = QLabel(card_data.meta)
            meta.setObjectName("LauncherShellMeta")
            meta.setWordWrap(True)
            layout.addWidget(meta)

        if card_data.action is not None:
            action_row = QHBoxLayout()
            action_row.setContentsMargins(0, 4, 0, 0)
            action_row.addWidget(_create_action_button(card_data.action))
            action_row.addStretch(1)
            layout.addLayout(action_row)

        grid.addWidget(card, index // 2, index % 2)

    return grid


def _create_news_card(item: NewsItem) -> QFrame:
    card = QFrame()
    card.setObjectName("LauncherShellNewsCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(10)

    meta = QLabel(" / ".join(part for part in (item.tag, item.timestamp) if part))
    meta.setObjectName("LauncherShellEyebrow")
    layout.addWidget(meta)

    title = QLabel(item.title)
    title.setObjectName("LauncherShellSectionTitle")
    title.setWordWrap(True)
    layout.addWidget(title)

    summary = QLabel(item.summary)
    summary.setObjectName("LauncherShellBody")
    summary.setWordWrap(True)
    layout.addWidget(summary)

    if item.action is not None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)
        row.addWidget(_create_action_button(item.action))
        row.addStretch(1)
        layout.addLayout(row)

    return card


def _create_log_card(item: LogItem) -> QFrame:
    card = QFrame()
    card.setObjectName("LauncherShellLogCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(8)

    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(8)

    level = QLabel(item.level.upper())
    level.setObjectName("LauncherShellEyebrow")
    header.addWidget(level)

    if item.timestamp:
        timestamp = QLabel(item.timestamp)
        timestamp.setObjectName("LauncherShellMeta")
        header.addWidget(timestamp)

    header.addStretch(1)
    layout.addLayout(header)

    message = QLabel(item.message)
    message.setObjectName("LauncherShellSectionTitle")
    message.setWordWrap(True)
    layout.addWidget(message)

    if item.context:
        context = QLabel(item.context)
        context.setObjectName("LauncherShellBody")
        context.setWordWrap(True)
        layout.addWidget(context)

    if item.action is not None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.addWidget(_create_action_button(item.action))
        row.addStretch(1)
        layout.addLayout(row)

    return card


def _create_action_button(action: DashboardAction) -> QPushButton:
    button = QPushButton(action.label)
    button.setObjectName("LauncherShellActionButton" if action.accent else "LauncherShellGhostButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setIcon(qta.icon(action.icon_name, color="#ffffff" if action.accent else "#ffd2ec"))
    if action.tooltip:
        button.setToolTip(action.tooltip)
    if action.callback is not None:
        button.clicked.connect(action.callback)
    return button
