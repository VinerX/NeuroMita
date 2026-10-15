from __future__ import annotations

from dataclasses import dataclass

from ui.mvvm import UiEffect, UiIntent


@dataclass(frozen=True, slots=True)
class SettingsPageState:
    loading_sections: frozenset[str] = frozenset()
    failed_sections: tuple[tuple[str, str], ...] = ()
    preparing_features: frozenset[str] = frozenset()
    feature_errors: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class PrepareSettingsSection(UiIntent):
    category: str
    feature_names: tuple[str, ...] = ()
    require_backend: bool = False
    gui_feature: str | None = None
    defer_features: bool = False


@dataclass(frozen=True, slots=True)
class SettingsSectionFeaturesReady(UiEffect):
    category: str


@dataclass(frozen=True, slots=True)
class SettingsSectionReady(UiEffect):
    category: str


@dataclass(frozen=True, slots=True)
class SettingsSectionFailed(UiEffect):
    category: str
    message: str
