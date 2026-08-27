from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from controllers.main_controller import MainController


class _FeatureManagerProbe:
    last: "_FeatureManagerProbe | None" = None

    def __init__(self, _settings, *, max_workers: int = 2) -> None:
        self.max_workers = max_workers
        self.specs = {}
        type(self).last = self

    def register(self, spec) -> None:
        self.specs[spec.name] = spec


class _ServiceRegistryProbe:
    def register(self, *_args, **_kwargs) -> None:
        return None


def test_install_runtime_features_are_lazy_but_explicitly_activatable() -> None:
    registry = _ServiceRegistryProbe()
    controller = MainController.__new__(MainController)

    with (
        patch("controllers.main_controller.RuntimeFeatureManager", _FeatureManagerProbe),
        patch("controllers.main_controller.services", return_value=registry),
    ):
        controller._configure_optional_features("unused", object())

    manager = _FeatureManagerProbe.last
    assert manager is not None

    for name in ("install", "installables"):
        spec = manager.specs[name]
        assert spec.startup is False
        assert spec.enabled(object()) is True


def test_gui_management_features_survive_disabled_runtime_toggles() -> None:
    registry = _ServiceRegistryProbe()
    controller = MainController.__new__(MainController)

    with (
        patch("controllers.main_controller.RuntimeFeatureManager", _FeatureManagerProbe),
        patch("controllers.main_controller.services", return_value=registry),
    ):
        controller._configure_optional_features("unused", object())

    manager = _FeatureManagerProbe.last
    assert manager is not None

    for name in ("local_voice", "voice_models", "speech"):
        assert manager.specs[name].stop_when_disabled is False


def test_backend_navigation_link_targets_install_tab_not_component_settings() -> None:
    source_path = (
        Path(__file__).resolve().parents[2]
        / "ui"
        / "windows"
        / "ai_hub"
        / "dialog.py"
    )
    source = source_path.read_text(encoding="utf-8")
    marker = "if dialog.open_backend_requested:"
    start = source.index(marker)
    end = source.index("return accepted", start)
    branch = source[start:end]

    assert 'self._set_tab("install")' in branch
    assert 'self._select_category("backend")' in branch
    assert "self._pending_component_id" not in branch
