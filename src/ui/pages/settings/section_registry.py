from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout

from ui.settings import (
    api_settings,
    character_settings,
    data_settings,
    game_settings,
    general_settings,
    microphone_settings,
    model_interaction_settings,
    screen_analysis_settings,
    updates_settings,
    voiceover_settings,
)
from utils import _

TextPair = tuple[str, str]
SectionBuilder = Callable[[object, QVBoxLayout], None]


@dataclass(frozen=True, slots=True)
class SettingsSectionSpec:
    key: str
    icon_name: str
    nav_label: TextPair
    title: TextPair
    subtitle: TextPair
    min_mode: str
    builder_ref: str | SectionBuilder


SETTINGS_SECTION_SPECS: tuple[SettingsSectionSpec, ...] = (
    SettingsSectionSpec(
        key="general",
        icon_name="fa6s.gear",
        nav_label=("General", "General"),
        title=("Общие настройки", "General settings"),
        subtitle=(
            "Базовые параметры интерфейса, приватности, памяти и языка.",
            "Core interface, privacy, memory and language settings.",
        ),
        min_mode="basic",
        builder_ref=general_settings.setup_general_settings_controls,
    ),
    SettingsSectionSpec(
        key="api",
        icon_name="fa6s.plug",
        nav_label=("API", "API"),
        title=("Подключение к моделям", "Model connectivity"),
        subtitle=(
            "Провайдеры, пресеты, ключи и параметры генерации ответов.",
            "Providers, presets, keys and generation parameters.",
        ),
        min_mode="basic",
        builder_ref=api_settings.setup_api_controls,
    ),
    SettingsSectionSpec(
        key="characters",
        icon_name="fa6s.user",
        nav_label=("Characters", "Characters"),
        title=("Персонажи", "Characters"),
        subtitle=(
            "Профили, шаблоны поведения и история выбранного персонажа.",
            "Profiles, behavior presets and selected character history.",
        ),
        min_mode="basic",
        builder_ref=character_settings.setup_mita_controls,
    ),
    SettingsSectionSpec(
        key="voice",
        icon_name="fa6s.volume-high",
        nav_label=("Voice", "Voice"),
        title=("Озвучка", "Voice"),
        subtitle=(
            "Голосовой выход, локальные голоса и параметры синтеза.",
            "Speech output, local voices and synthesis settings.",
        ),
        min_mode="advanced",
        builder_ref=voiceover_settings.setup_voiceover_controls,
    ),
    SettingsSectionSpec(
        key="microphone",
        icon_name="fa6s.microphone",
        nav_label=("ASR", "ASR"),
        title=("Микрофон и ASR", "Microphone and ASR"),
        subtitle=(
            "Устройства ввода, распознавание речи и словарь терминов.",
            "Input devices, speech recognition and glossary settings.",
        ),
        min_mode="advanced",
        builder_ref=microphone_settings.setup_microphone_controls,
    ),
    SettingsSectionSpec(
        key="game",
        icon_name="fa5s.gamepad",
        nav_label=("Game", "Game"),
        title=("Связь с игрой", "Game integration"),
        subtitle=(
            "Параметры подключения и обмена данными с игрой.",
            "Connection settings and data exchange with the game.",
        ),
        min_mode="advanced",
        builder_ref=game_settings.setup_game_controls,
    ),
    SettingsSectionSpec(
        key="models",
        icon_name="fa6s.robot",
        nav_label=("Models", "Models"),
        title=("Модели и поведение", "Models and behavior"),
        subtitle=(
            "Управление логикой ответа, памятью, мышлением и RAG.",
            "Control response logic, memory, thinking and RAG.",
        ),
        min_mode="full",
        builder_ref=model_interaction_settings.setup_model_interaction_controls,
    ),
    SettingsSectionSpec(
        key="screen",
        icon_name="fa6s.display",
        nav_label=("Screen", "Screen"),
        title=("Экран и камера", "Screen and camera"),
        subtitle=(
            "Захват экрана, анализ изображений и визуальный контекст.",
            "Screen capture, image analysis and visual context.",
        ),
        min_mode="full",
        builder_ref=screen_analysis_settings.setup_screen_analysis_controls,
    ),
    SettingsSectionSpec(
        key="debug",
        icon_name="fa6s.bug",
        nav_label=("Debug", "Debug"),
        title=("Системная телеметрия", "System telemetry"),
        subtitle=(
            "Текущее состояние модулей, отладочная информация и индикаторы.",
            "Current module status, debug information and live indicators.",
        ),
        min_mode="full",
        builder_ref="_debug_wrapper",
    ),
    SettingsSectionSpec(
        key="news",
        icon_name="fa6s.newspaper",
        nav_label=("News", "News"),
        title=("Новости проекта", "Project news"),
        subtitle=(
            "Сводка обновлений и последние заметки по сборке.",
            "Build notes and recent project updates.",
        ),
        min_mode="full",
        builder_ref="_news_wrapper",
    ),
    SettingsSectionSpec(
        key="data",
        icon_name="fa5s.database",
        nav_label=("Data", "Data"),
        title=("Данные и хранилище", "Data and storage"),
        subtitle=(
            "История, экспорт, резервные данные и локальное хранилище.",
            "History, export, backups and local storage.",
        ),
        min_mode="full",
        builder_ref=data_settings.setup_data_settings_controls,
    ),
    SettingsSectionSpec(
        key="updates",
        icon_name="fa6s.rotate",
        nav_label=("Updates", "Updates"),
        title=("Обновления", "Updates"),
        subtitle=(
            "Управление обновлением клиента и связанных компонентов.",
            "Manage client and component updates.",
        ),
        min_mode="advanced",
        builder_ref=updates_settings.setup_updates_settings_controls,
    ),
)


def get_settings_section_specs() -> tuple[SettingsSectionSpec, ...]:
    return SETTINGS_SECTION_SPECS


def iter_settings_button_specs() -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (
            spec.icon_name,
            _(spec.nav_label[0], spec.nav_label[1]),
            spec.key,
            spec.min_mode,
        )
        for spec in SETTINGS_SECTION_SPECS
    )


def build_settings_containers(gui) -> dict[str, QScrollArea]:
    gui.settings_containers = {}

    for spec in SETTINGS_SECTION_SPECS:
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setObjectName(f"ScrollArea_{spec.key}")
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content_widget = QFrame()
        content_widget.setObjectName(f"ContentWidget_{spec.key}")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(12)

        header_card = QFrame()
        header_card.setObjectName("SettingsHeroCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(18, 18, 18, 18)
        header_layout.setSpacing(6)

        title_label = QLabel(_(spec.title[0], spec.title[1]))
        title_label.setObjectName("SettingsHeroTitle")
        header_layout.addWidget(title_label)

        subtitle_label = QLabel(_(spec.subtitle[0], spec.subtitle[1]))
        subtitle_label.setObjectName("SettingsHeroSubtitle")
        subtitle_label.setWordWrap(True)
        header_layout.addWidget(subtitle_label)

        content_layout.addWidget(header_card)

        builder = spec.builder_ref
        if isinstance(builder, str):
            getattr(gui, builder)(content_layout)
        else:
            builder(gui, content_layout)

        content_layout.addStretch()
        scroll_area.setWidget(content_widget)
        gui.settings_containers[spec.key] = scroll_area
        gui.settings_overlay.add_container(scroll_area)

    return gui.settings_containers
