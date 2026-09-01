from __future__ import annotations

from types import SimpleNamespace

from controllers.model_controller import ModelController


def test_setting_callback_is_safe_before_model_initialization() -> None:
    controller = object.__new__(ModelController)

    controller._on_setting_changed(SimpleNamespace(key="LANGUAGE", value="EN"))
    controller._on_setting_changed(SimpleNamespace(key="EULA_ACCEPTED", value=True))
    controller._on_setting_changed(SimpleNamespace(key="CHARACTER", value="Crazy"))


def test_setting_callback_applies_changes_after_model_initialization() -> None:
    applied: list[tuple[str, object]] = []
    controller = object.__new__(ModelController)
    controller.model = SimpleNamespace(
        cfg=SimpleNamespace(
            apply_setting=lambda key, value: applied.append((key, value))
        )
    )

    controller._on_setting_changed(SimpleNamespace(key="LANGUAGE", value="EN"))

    assert applied == [("LANGUAGE", "EN")]
