from __future__ import annotations

from types import SimpleNamespace

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
