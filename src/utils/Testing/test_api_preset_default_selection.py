from types import SimpleNamespace

import controllers.api_presets_controller as api_presets_module
from controllers.api_presets_controller import ApiPresetsController


class _Settings:
    def __init__(self, values):
        self.values = dict(values)
        self.updates = []
        self.save_calls = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def update(self, key, value):
        self.values[key] = value
        self.updates.append((key, value))

    def save_settings(self):
        self.save_calls += 1


def _controller(*, presets, templates, order):
    controller = ApiPresetsController.__new__(ApiPresetsController)
    controller.presets = presets
    controller.templates = templates
    controller.presets_order = order
    controller.current_preset_id = None
    return controller


def test_default_selection_replaces_template_id_with_first_configured_preset(monkeypatch):
    settings = _Settings({"LAST_API_PRESET_ID": 1})
    monkeypatch.setattr(api_presets_module, "use", lambda _service: settings)
    controller = _controller(
        presets={42: SimpleNamespace()},
        templates={1: SimpleNamespace()},
        order=[42],
    )

    controller._ensure_default_preset()

    assert controller.current_preset_id == 42
    assert settings.updates == [("LAST_API_PRESET_ID", 42)]
    assert settings.save_calls == 1


def test_default_selection_keeps_configured_preset(monkeypatch):
    settings = _Settings({"LAST_API_PRESET_ID": 42})
    monkeypatch.setattr(api_presets_module, "use", lambda _service: settings)
    controller = _controller(
        presets={42: SimpleNamespace()},
        templates={1: SimpleNamespace()},
        order=[42],
    )

    controller._ensure_default_preset()

    assert controller.current_preset_id == 42
    assert settings.updates == []
    assert settings.save_calls == 0
