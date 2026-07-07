from __future__ import annotations

from typing import Iterable, Sequence

from core.events import Events, get_event_bus
from main_logger import logger
from ui.async_bus import run_async
from utils import getTranslationVariant as _


CURRENT_PROVIDER_VALUE = "Текущий"
CURRENT_PROVIDER_EN_VALUE = "Current"


def current_provider_options() -> list:
    return [_(CURRENT_PROVIDER_VALUE, CURRENT_PROVIDER_EN_VALUE)]


def load_api_provider_options_async(gui, setting_keys: Sequence[str], *, name: str = "api-provider-options"):
    keys = tuple(str(key) for key in setting_keys if key)
    if not keys:
        return None

    def _worker() -> list[str]:
        result = get_event_bus().emit_and_wait(Events.ApiPresets.GET_PRESET_LIST, timeout=1.0)
        return _provider_names_from_result(result)

    def _apply(provider_names: Iterable[str]) -> None:
        _apply_api_provider_options(gui, keys, provider_names)

    return run_async(gui, _worker, _apply, name=name)


def _provider_names_from_result(result) -> list[str]:
    meta = result[0] if result else None
    if not isinstance(meta, dict):
        return []

    names: list[str] = []
    seen = set()
    for preset in meta.get("custom", []) or []:
        name = str(getattr(preset, "name", "") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _apply_api_provider_options(gui, setting_keys: Sequence[str], provider_names: Iterable[str]) -> None:
    names = _unique_provider_names(provider_names)
    for key in setting_keys:
        combo = getattr(gui, key, None)
        if combo is None:
            continue
        try:
            _replace_provider_combo(combo, names)
        except RuntimeError:
            continue
        except Exception:
            logger.warning(f"[provider_options] Failed to refresh provider combo: {key}", exc_info=True)


def _replace_provider_combo(combo, provider_names: Sequence[str]) -> None:
    current = _canonical_current_value(
        combo.current_value() if hasattr(combo, "current_value") else combo.currentText()
    )
    blocked = combo.blockSignals(True)
    try:
        combo.clear()
        if hasattr(combo, "add_tr_item"):
            combo.add_tr_item(CURRENT_PROVIDER_VALUE, CURRENT_PROVIDER_EN_VALUE, value=CURRENT_PROVIDER_VALUE)
            for name in provider_names:
                combo.add_data_item(name, value=name)
        else:
            combo.addItem(CURRENT_PROVIDER_VALUE)
            for name in provider_names:
                combo.addItem(name)

        selected = False
        if hasattr(combo, "set_current_value"):
            selected = combo.set_current_value(current)
            if not selected:
                selected = combo.set_current_value(CURRENT_PROVIDER_VALUE)
        elif current:
            index = combo.findText(str(current))
            if index >= 0:
                combo.setCurrentIndex(index)
                selected = True

        if not selected and combo.count():
            combo.setCurrentIndex(0)
    finally:
        combo.blockSignals(blocked)


def _canonical_current_value(value):
    text = str(value or "").strip()
    if text.lower() == CURRENT_PROVIDER_EN_VALUE.lower() or text == CURRENT_PROVIDER_VALUE:
        return CURRENT_PROVIDER_VALUE
    return value


def _unique_provider_names(provider_names: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen = {CURRENT_PROVIDER_VALUE, CURRENT_PROVIDER_EN_VALUE}
    for name in provider_names or []:
        text = str(name or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
