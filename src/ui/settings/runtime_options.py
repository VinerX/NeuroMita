from __future__ import annotations

from typing import Iterable

from ui.settings.runtime_options_presentation import (
    CameraDeviceSelected,
    LoadCameraOptions,
    LoadProviderOptions,
    SettingsRuntimeOptionsState,
)


def attach_runtime_options_view_model(gui, view_model) -> None:
    current = getattr(gui, "_settings_runtime_options_view_model", None)
    if current is view_model:
        return
    if current is not None and not current.is_closed:
        raise RuntimeError("A different runtime-options view model is already attached")
    gui._settings_runtime_options_view_model = view_model
    gui._settings_runtime_provider_keys = set()
    view_model.state_changed.connect(lambda state: _render(gui, state))


def ensure_runtime_options_view_model(gui):
    view_model = getattr(gui, "_settings_runtime_options_view_model", None)
    if view_model is None or view_model.is_closed:
        raise RuntimeError("Settings runtime-options view model is not attached")
    return view_model


def register_provider_options(gui, setting_keys: Iterable[str]) -> None:
    view_model = ensure_runtime_options_view_model(gui)
    gui._settings_runtime_provider_keys.update(str(key) for key in setting_keys if key)
    _render(gui, view_model.state)
    view_model.dispatch(LoadProviderOptions())


def register_camera_options(gui) -> None:
    view_model = ensure_runtime_options_view_model(gui)
    _render(gui, view_model.state)
    view_model.dispatch(LoadCameraOptions())


def refresh_camera_options(gui) -> None:
    ensure_runtime_options_view_model(gui).dispatch(LoadCameraOptions(force=True))


def select_camera_option(gui, value: str) -> None:
    ensure_runtime_options_view_model(gui).dispatch(CameraDeviceSelected(str(value or "")))


def _render(gui, state: SettingsRuntimeOptionsState) -> None:
    for key in tuple(getattr(gui, "_settings_runtime_provider_keys", ()) or ()):
        combo = getattr(gui, key, None)
        if combo is not None:
            _replace_combo(combo, state.provider_options)

    combo = getattr(gui, "camera_combobox", None)
    if combo is not None:
        if state.camera_options:
            current = combo.currentText()
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItems([str(item) for item in state.camera_options])
                if current and combo.findText(current) >= 0:
                    combo.setCurrentText(current)
            finally:
                combo.blockSignals(False)
        combo.setEnabled(not state.cameras_loading)


def _replace_combo(combo, options) -> None:
    current = combo.current_value() if hasattr(combo, "current_value") else combo.currentText()
    combo.blockSignals(True)
    try:
        combo.clear()
        for option in options or ():
            ru = getattr(option, "tr_ru", None)
            if ru is not None and hasattr(combo, "add_tr_item"):
                combo.add_tr_item(ru, getattr(option, "tr_en", ""))
            elif hasattr(combo, "add_data_item"):
                combo.add_data_item(str(option), value=str(option))
            else:
                combo.addItem(str(option))
        if hasattr(combo, "set_current_value"):
            if not combo.set_current_value(current) and combo.count():
                combo.setCurrentIndex(0)
        else:
            index = combo.findText(str(current))
            combo.setCurrentIndex(index if index >= 0 else 0)
    finally:
        combo.blockSignals(False)