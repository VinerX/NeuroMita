from __future__ import annotations

import json
import importlib.util
import sys
import types
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from managers.rag.pipeline.config import RAG_DEFAULTS
from ui.settings.rag_preset_presentation import (
    ActivateRagPresets,
    ApplyRagPreset,
    DeleteRagPreset,
    SaveRagPreset,
)


_SRC_ROOT = Path(__file__).resolve().parents[2]


class _IntentViewModel:
    @classmethod
    def __class_getitem__(cls, _item):
        return cls

    def __init__(self, state, parent=None) -> None:
        _ = parent
        self.state = state
        self.is_closed = False
        self.effects: list[object] = []
        self._subscriptions: list[object] = []

    def set_state(self, state) -> None:
        self.state = state

    def update_state(self, **changes) -> None:
        self.state = replace(self.state, **changes)

    def emit_effect(self, effect) -> None:
        self.effects.append(effect)

    def track_subscription(self, subscription) -> None:
        if subscription is not None:
            self._subscriptions.append(subscription)

    def _post_ui(self, callback, *args) -> None:
        callback(*args)

    def run_latest(self, _name, worker, on_ok=None, on_error=None) -> bool:
        return _run_latest_sync(_name, worker, on_ok, on_error)

    def close(self) -> None:
        if self.is_closed:
            return
        self.is_closed = True
        for subscription in self._subscriptions:
            close = getattr(subscription, "close", None)
            if callable(close):
                close()


def _load_view_model_module():
    dependency = types.ModuleType("controllers.gui.intent_view_model")
    dependency.IntentViewModel = _IntentViewModel
    path = _SRC_ROOT / "controllers/gui/rag_preset_view_model.py"
    spec = importlib.util.spec_from_file_location("_rag_preset_view_model_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {"controllers.gui.intent_view_model": dependency},
    ):
        spec.loader.exec_module(module)
    return module


RAG_MODULE = _load_view_model_module()
RagPresetViewModel = RAG_MODULE.RagPresetViewModel


@dataclass
class _Subscription:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


class _Settings:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = dict(values or {})
        self.subscription = _Subscription()
        self.callback = None

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def update(self, key: str, value) -> None:
        self.values[key] = value

    def snapshot(self, keys=None) -> dict[str, object]:
        if keys is None:
            return dict(self.values)
        return {key: self.values.get(key) for key in keys}

    def subscribe(self, callback, *, keys=None, replay=False):
        _ = keys, replay
        self.callback = callback
        return self.subscription


def _run_latest_sync(_name, worker, on_ok=None, on_error=None) -> bool:
    try:
        result = worker()
    except Exception as exc:  # pragma: no cover - defensive test adapter
        if on_error is not None:
            on_error(exc)
        return False
    if on_ok is not None:
        on_ok(result)
    return True


def test_activate_lists_builtin_presets() -> None:
    settings = _Settings({"RAG_PIPELINE_PRESET": "Keyword+FTS only"})
    view_model = RagPresetViewModel(settings)

    view_model.dispatch(ActivateRagPresets())

    assert "Keyword+FTS only" in view_model.state.names
    assert view_model.state.selected == "Keyword+FTS only"
    assert view_model.state.can_apply is True
    view_model.close()
    assert settings.subscription.closed is True


def test_save_preserves_legitimate_none_values() -> None:
    nullable_key = next(iter(RAG_DEFAULTS))
    settings = _Settings({nullable_key: None})
    view_model = RagPresetViewModel(settings)

    view_model.dispatch(SaveRagPreset("Nullable preset"))

    stored = json.loads(str(settings.values["RAG_PIPELINE_USER_PRESETS"]))
    assert nullable_key in stored["Nullable preset"]
    assert stored["Nullable preset"][nullable_key] is None
    assert settings.values["RAG_PIPELINE_PRESET"] == "Nullable preset"
    view_model.close()


def test_apply_updates_settings_and_finishes_busy_state() -> None:
    settings = _Settings()
    view_model = RagPresetViewModel(settings)
    view_model.run_latest = _run_latest_sync

    with (
        patch.object(
            RAG_MODULE,
            "get_pipeline_preset_settings",
            return_value={"RAG_ENABLED": True, "RAG_EMBED_MODEL": "test-model"},
        ),
        patch.object(
            RAG_MODULE,
            "sync_legacy_settings_to_preset",
        ),
        patch.object(
            RAG_MODULE,
            "missing_model_targets",
            return_value=(),
        ),
    ):
        view_model.dispatch(ApplyRagPreset("Keyword+FTS only"))

    assert settings.values["RAG_ENABLED"] is True
    assert settings.values["RAG_EMBED_MODEL"] == "test-model"
    assert settings.values["RAG_PIPELINE_PRESET"] == "Keyword+FTS only"
    assert view_model.state.busy is False
    view_model.close()


def test_delete_user_preset_returns_to_custom() -> None:
    settings = _Settings(
        {
            "RAG_PIPELINE_USER_PRESETS": json.dumps(
                {"My preset": {"RAG_ENABLED": True}}
            ),
            "RAG_PIPELINE_PRESET": "My preset",
        }
    )
    view_model = RagPresetViewModel(settings)

    view_model.dispatch(DeleteRagPreset("My preset"))

    assert json.loads(str(settings.values["RAG_PIPELINE_USER_PRESETS"])) == {}
    assert settings.values["RAG_PIPELINE_PRESET"] == "Custom"
    assert view_model.state.selected == "Custom"
    view_model.close()