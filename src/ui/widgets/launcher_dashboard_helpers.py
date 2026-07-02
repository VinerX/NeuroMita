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
from localization.live import register_if_tr

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
    item_id: str = ""
    timestamp: str = ""
    full_text: str = ""
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

    _append_release_feed(layout, list(items))

    layout.addStretch(1)
    return root


def _create_section_block(header_text: str, items: list[NewsItem]) -> QWidget:
    block = QWidget()
    block.setObjectName("LauncherShellPage")
    block_layout = QVBoxLayout(block)
    block_layout.setContentsMargins(2, 6, 2, 0)
    block_layout.setSpacing(12)

    header = QLabel(header_text)
    register_if_tr(header, header_text)
    header.setObjectName("LauncherShellSectionHeader")
    block_layout.addWidget(header)

    for item in items:
        block_layout.addWidget(_create_news_card(item))

    return block


def _append_release_feed(layout: QVBoxLayout, items: list[NewsItem]) -> None:
    """Делит ленту на секции PRE-RELEASES / RELEASES с заголовками и добавляет
    фильтр-табы (Все / Релизы / Пререлизы). Прочие записи (offline/news) идут
    отдельной секцией и показываются только в режиме «Все»."""
    pre_items = [it for it in items if _news_item_kind(it) == "pre"]
    rel_items = [it for it in items if _news_item_kind(it) == "release"]
    other_items = [it for it in items if _news_item_kind(it) == "other"]

    # Секции в порядке мокапа: сначала пререлизы, затем релизы, затем прочее.
    sections: list[tuple[str, QWidget]] = []
    if pre_items:
        sections.append(("pre", _create_section_block(_("ПРЕРЕЛИЗЫ", "PRE-RELEASES"), pre_items)))
    if rel_items:
        sections.append(("release", _create_section_block(_("РЕЛИЗЫ", "RELEASES"), rel_items)))
    if other_items:
        sections.append(("other", _create_section_block(_("ПРОЧЕЕ", "OTHER"), other_items)))

    # Фильтр-табы показываем только когда есть что фильтровать (оба типа релизов).
    if pre_items and rel_items:
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(2, 4, 2, 0)
        tab_row.setSpacing(8)

        tabs: list[tuple[QPushButton, str]] = []

        def _apply_filter(mode: str) -> None:
            for kind, widget in sections:
                # «Все» показывает всё; конкретный фильтр — только свою секцию
                # (секция «Прочее» видна лишь в режиме «Все»).
                widget.setVisible((mode == "all") or (kind == mode))
            for button, button_mode in tabs:
                button.setProperty("active", button_mode == mode)
                # перерисовать стиль под новое значение свойства
                button.style().unpolish(button)
                button.style().polish(button)

        for label, mode in (
            (_("Все", "All"), "all"),
            (_("Релизы", "Releases"), "release"),
            (_("Пререлизы", "Pre-releases"), "pre"),
        ):
            btn = QPushButton(label)
            register_if_tr(btn, label)
            btn.setObjectName("LauncherShellFilterTab")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("active", mode == "all")
            btn.clicked.connect(lambda _checked=False, m=mode: _apply_filter(m))
            tabs.append((btn, mode))
            tab_row.addWidget(btn)
        tab_row.addStretch(1)
        layout.addLayout(tab_row)

    for _kind, widget in sections:
        layout.addWidget(widget)


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
    register_if_tr(eyebrow, eyebrow_text)  # как и title ниже — иначе live-смена не обновит
    eyebrow.setObjectName("LauncherShellEyebrow")
    layout.addWidget(eyebrow)

    title = QLabel(title_text)
    register_if_tr(title, title_text)
    title.setObjectName("LauncherShellTitle")
    title.setWordWrap(True)
    layout.addWidget(title)

    subtitle = QLabel(subtitle_text)
    register_if_tr(subtitle, subtitle_text)
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


def _news_item_kind(item: NewsItem) -> str:
    """Категория для группировки/фильтрации: pre | release | other."""
    tag = str(item.tag or "").strip().upper()
    if tag == "PRE-RELEASE":
        return "pre"
    if tag == "RELEASE":
        return "release"
    return "other"


def _badge_kind(item: NewsItem) -> str:
    kind = _news_item_kind(item)
    if kind == "pre":
        return "pre"
    if kind == "release":
        return "release"
    return "offline"


def _create_news_card(item: NewsItem) -> QFrame:
    card = QFrame()
    card.setObjectName("LauncherShellNewsCard")
    card.setProperty("newsKind", _news_item_kind(item))
    if item.item_id:
        card.setProperty("itemId", item.item_id)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(10)

    # ── Шапка карточки: цветной бейдж статуса + дата (семантически отдельный блок) ──
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(8)
    if item.tag:
        badge = QLabel(str(item.tag).upper())
        badge.setObjectName("LauncherShellBadge")
        badge.setProperty("kind", _badge_kind(item))
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
    if item.timestamp:
        date = QLabel(item.timestamp)
        date.setObjectName("LauncherShellMeta")
        header.addWidget(date, 0, Qt.AlignmentFlag.AlignVCenter)
    header.addStretch(1)
    layout.addLayout(header)

    title = QLabel(item.title)
    title.setObjectName("LauncherShellSectionTitle")
    title.setWordWrap(True)
    layout.addWidget(title)

    # Разделитель отделяет название от описания (визуальное деление блоков).
    divider = QFrame()
    divider.setObjectName("LauncherShellCardDivider")
    layout.addWidget(divider)

    summary = QLabel(item.summary)
    summary.setObjectName("LauncherShellBody")
    summary.setWordWrap(True)
    layout.addWidget(summary)

    details_scroll = None
    toggle_btn = None
    full_text = str(item.full_text or "").strip()
    if full_text and full_text != str(item.summary or "").strip():
        details = QLabel(full_text)
        details.setObjectName("LauncherShellBody")
        details.setWordWrap(True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.setContentsMargins(12, 10, 12, 10)
        details.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Длинный changelog уезжает в скролл с ограниченной высотой — карточка
        # больше не «выспамливает километровые описания» на всю страницу.
        details_scroll = QScrollArea()
        details_scroll.setObjectName("LauncherShellDetailsScroll")
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QFrame.Shape.NoFrame)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        details_scroll.setMaximumHeight(240)
        details_scroll.setWidget(details)
        details_scroll.setVisible(False)
        layout.addWidget(details_scroll)

        toggle_btn = QPushButton(_("Развернуть", "Expand"))
        toggle_btn.setObjectName("LauncherShellGhostButton")
        toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_btn.setIcon(qta.icon("fa6s.angle-down", color="#ffd2ec"))

        def _toggle_details(_checked=False, area=details_scroll, button=toggle_btn):
            expanded = not area.isVisible()
            area.setVisible(expanded)
            button.setText(_("Свернуть", "Collapse") if expanded else _("Развернуть", "Expand"))
            button.setIcon(qta.icon("fa6s.angle-up" if expanded else "fa6s.angle-down", color="#ffd2ec"))

        toggle_btn.clicked.connect(_toggle_details)

    if item.action is not None or toggle_btn is not None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 2, 0, 0)
        if toggle_btn is not None:
            row.addWidget(toggle_btn)
        if item.action is not None:
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
    register_if_tr(button, action.label)
    button.setObjectName("LauncherShellActionButton" if action.accent else "LauncherShellGhostButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setIcon(qta.icon(action.icon_name, color="#ffffff" if action.accent else "#ffd2ec"))
    if action.tooltip:
        button.setToolTip(action.tooltip)
    if action.callback is not None:
        button.clicked.connect(action.callback)
    return button
