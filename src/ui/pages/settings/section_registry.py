from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt6.QtWidgets import QVBoxLayout

from ui.settings import (
    api_settings,
    character_settings,
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
        nav_label=("Общие", "General"),
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
        nav_label=("Персонажи", "Characters"),
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
        nav_label=("Озвучка", "Voice"),
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
        nav_label=("Игра", "Game"),
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
        nav_label=("Модели", "Models"),
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
        nav_label=("Экран", "Screen"),
        title=("Экран и камера", "Screen and camera"),
        subtitle=(
            "Захват экрана, анализ изображений и визуальный контекст.",
            "Screen capture, image analysis and visual context.",
        ),
        min_mode="full",
        builder_ref=screen_analysis_settings.setup_screen_analysis_controls,
    ),
    SettingsSectionSpec(
        key="updates",
        icon_name="fa6s.rotate",
        nav_label=("Обновления", "Updates"),
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


def build_settings_containers(gui) -> dict[str, object]:
    page = getattr(gui, "settings_page", None)
    if page is not None and hasattr(page, "settings_containers"):
        return page.settings_containers
    return {}
