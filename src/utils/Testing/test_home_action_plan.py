from __future__ import annotations

import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PyQt6.QtCore import QCoreApplication

from controllers.gui.home_page_controller import HomePageController
from controllers.gui.home_page_view_model import HomePageViewModel
from ui.pages.home_presentation import HomeState, HomeUpdateState


class _Settings:
    def get(self, _key, default=None):
        return default


def _view_model(state: HomeState) -> HomePageViewModel:
    view_model = HomePageViewModel.__new__(HomePageViewModel)
    view_model._state = state
    view_model._app = SimpleNamespace(pending_restart_version="")
    view_model._settings = _Settings()
    return view_model


def test_available_but_unselected_updates_do_not_replace_play_action() -> None:
    view_model = _view_model(
        HomeState(
            unity_installed=True,
            python_update=HomeUpdateState(available=True, selected=False),
            unity_update=HomeUpdateState(available=True, selected=False),
        )
    )

    assert view_model._primary_action() == "play"


def test_missing_unselected_unity_shows_requirement_instead_of_installing() -> None:
    view_model = _view_model(
        HomeState(
            unity_installed=False,
            unity_update=HomeUpdateState(available=True, selected=False),
        )
    )

    assert view_model._primary_action() == "unavailable"


def test_missing_unity_can_be_selected_for_install_without_update_metadata() -> None:
    view_model = _view_model(
        HomeState(
            unity_installed=False,
            unity_update=HomeUpdateState(installable=True, selected=True),
        )
    )

    assert view_model._primary_action() == "apply"
    assert view_model._apply_action_label() in {"Установить Unity", "Install Unity"}


def test_local_missing_unity_exposes_install_checkbox_state() -> None:
    view_model = _view_model(HomeState())
    view_model._home = SimpleNamespace(
        find_unity_executable=lambda _configured=None: None,
        refresh_process_state=lambda _configured=None: SimpleNamespace(
            state="stopped", error=""
        ),
    )

    view_model._refresh_local_state(emit=False)

    assert view_model.state.unity_update.installable
    assert not view_model.state.unity_update.available
    assert not view_model.state.unity_update.selected


def test_mixed_two_component_plan_uses_compact_install_label() -> None:
    view_model = _view_model(
        HomeState(
            unity_installed=False,
            python_update=HomeUpdateState(available=True, selected=True),
            unity_update=HomeUpdateState(available=True, selected=True),
        )
    )

    assert view_model._primary_action() == "apply"
    assert view_model._apply_action_label() in {
        "Установить компоненты (2)",
        "Install components (2)",
    }


def test_running_unity_replaces_play_with_close_action() -> None:
    view_model = _view_model(
        HomeState(unity_installed=True, unity_process_state="running")
    )

    assert view_model._primary_action() == "stop"


def test_controller_rejects_duplicate_unity_launch(tmp_path, monkeypatch) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None
    monkeypatch.setenv("NEUROMITA_BASE_DIR", str(tmp_path))
    controller = HomePageController()
    controller._publish_process_state(state="running", pid=123)

    with pytest.raises(RuntimeError, match="already running"):
        controller.launch_unity()


class _UpdateResult:
    def __init__(self, *, ok: bool = True, changed: bool = False, restart_required: bool = False) -> None:
        self.ok = ok
        self.changed = changed
        self.restart_required = restart_required

    def as_dict(self) -> dict[str, bool]:
        return {"ok": self.ok, "changed": self.changed, "restart_required": self.restart_required}


def test_selected_unity_runs_after_python_requires_restart() -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    assert app is not None
    controller = HomePageController()
    calls: list[str] = []

    def update_python(**_kwargs):
        calls.append("python")
        return _UpdateResult(changed=True, restart_required=True)

    def update_unity(**_kwargs):
        calls.append("unity")
        return _UpdateResult(changed=True)

    with (
        patch("updater.check_for_updates", side_effect=update_python),
        patch("updater.check_for_unity_updates", side_effect=update_unity),
    ):
        result = controller.apply_updates(
            update_python=True,
            update_unity=True,
            channel="stable",
            tester_code="",
            unity_dir=None,
            update_mode="diff",
            preserve_prompts=True,
            logger_adapter=SimpleNamespace(),
            on_progress=lambda *_args: None,
            on_extract_progress=lambda *_args: None,
            on_verify_progress=lambda *_args: None,
            on_stage=lambda *_args: None,
            stop_event=threading.Event(),
        )

    assert calls == ["python", "unity"]
    assert result["ok"]
    assert result["python_pending_restart"]
    assert set(result["results"]) == {"python", "unity"}


def test_ai_hub_install_events_do_not_change_home_progress() -> None:
    view_model = _view_model(HomeState())
    progress_calls: list[tuple] = []
    post_calls: list[object] = []
    view_model.post_progress = lambda *args, **kwargs: progress_calls.append((args, kwargs))
    view_model._post_ui = lambda callback: post_calls.append(callback)
    ai_hub_event = SimpleNamespace(
        data={"meta": {"source": "ai_hub"}, "title": "AI Hub component", "error": "failed"}
    )

    view_model._on_install_started(ai_hub_event)
    view_model._on_install_progress(ai_hub_event)
    view_model._on_install_finished(ai_hub_event)
    view_model._on_install_failed(ai_hub_event)

    assert progress_calls == []
    assert post_calls == []


def _update_check_view_model(monkeypatch, *, state=None, result=None, error=None):
    import controllers.gui.home_page_view_model as module

    monkeypatch.setattr(module, "_", lambda _ru, en: en)
    view_model = _view_model(state or HomeState(unity_installed=True))
    view_model._last_update_check = 0
    view_model._app.mark_update_check = Mock()
    view_model._app.publish_python_update = Mock()
    view_model.update_state = lambda **changes: setattr(
        view_model, "_state", replace(view_model.state, **changes)
    )
    view_model._refresh_local_state = lambda: None
    view_model._set_progress = Mock()
    view_model._schedule_hide_progress = Mock()
    view_model.run_coalesced = lambda _key, _worker, applied, failed: (
        failed(error) if error else applied(result)
    )
    return view_model


@pytest.mark.parametrize("failed_components", [("Python",), ("Unity",), ("Python", "Unity")])
def test_failed_update_checks_are_not_reported_as_no_updates(monkeypatch, failed_components):
    result = tuple(
        {"ok": False, "error": "Connection timed out"}
        if component in failed_components else {"ok": True, "available": False}
        for component in ("Python", "Unity")
    )
    view_model = _update_check_view_model(monkeypatch, result=result)
    view_model.refresh_updates(force=True, show_result=True)

    message = view_model._set_progress.call_args.args[0]
    assert message == "Could not check for updates"
    assert "No updates available" not in message
    assert view_model.state.error == message
    assert not view_model.state.update_checking
    if "Python" in failed_components:
        view_model._app.publish_python_update.assert_not_called()


def test_partial_check_failure_keeps_successful_update_visible(monkeypatch):
    view_model = _update_check_view_model(monkeypatch, result=(
        {"ok": True, "available": True, "latest_version": "v2026.10.15.2"},
        {"ok": False, "error": "Connection timed out"},
    ))
    view_model.refresh_updates(force=True, show_result=True)

    assert view_model.state.python_update.available
    message = view_model._set_progress.call_args.args[0]
    assert view_model.state.python_update.latest_version == "v2026.10.15.2"
    assert message == "Could not check for updates"


def test_failed_check_preserves_previously_found_updates(monkeypatch):
    previous = HomeUpdateState(available=True, selected=True, latest_version="v2026.10.15.2")
    view_model = _update_check_view_model(
        monkeypatch, state=HomeState(python_update=previous, unity_update=previous),
        result=({"ok": False, "error": "Offline"}, {"ok": False, "error": "Offline"}),
    )
    view_model.refresh_updates(force=True, show_result=True)

    assert view_model.state.python_update == previous
    assert view_model.state.unity_update == previous
    assert view_model.state.error


def test_successful_check_clears_error_and_can_report_no_updates(monkeypatch):
    view_model = _update_check_view_model(
        monkeypatch, state=HomeState(error="Previous network error"),
        result=({"ok": True, "available": False}, {"ok": True, "available": False}),
    )
    view_model.refresh_updates(force=True, show_result=True)

    assert view_model.state.error is None
    assert view_model._set_progress.call_args.args[0] == "No updates available."


def test_unexpected_update_check_exception_reports_failure(monkeypatch):
    view_model = _update_check_view_model(monkeypatch, error=RuntimeError("Network unavailable"))
    view_model.refresh_updates(force=True, show_result=True)

    assert view_model._set_progress.call_args.args[0] == "Could not check for updates"
    assert view_model.state.error
    assert not view_model.state.update_checking
