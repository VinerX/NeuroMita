from __future__ import annotations

from controllers.gui.character_settings_view_model import CharacterSettingsViewModel

import os
import sys
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.character_controller import CharacterController
from controllers.gui import character_settings_logic as logic
from controllers.gui.app_shell_controller import AppShellController
from controllers.gui.chat_panel_view_model import ChatPanelViewModel
from controllers.gui.sandbox_page_controller import SandboxPageController
from controllers.gui.sandbox_page_view_model import SandboxPageViewModel
from core.events import Event, EventBus, Events
from ui.pages.sandbox_page import SandboxPage


class CharacterCommandRoutingTests(unittest.TestCase):
    def setUp(self):
        self.characters = {
            cid: SimpleNamespace(char_id=cid, display_name=cid,
                                 reload_character_data=Mock(), clear_history=Mock())
            for cid in ("Crazy", "Kind")
        }
        self.manager = SimpleNamespace(
            current_character=self.characters["Kind"],
            get_character=Mock(side_effect=self.characters.get),
            get_loaded_characters=Mock(side_effect=lambda: list(self.characters.values())),
            clear_all_histories=Mock(),
        )
        self.manager.set_character_to_change = lambda cid: setattr(self.manager, "target", cid)
        self.manager.check_change_current_character = self.switch_character
        self.bus = EventBus()
        self.addCleanup(self.bus.shutdown)
        self.controller = CharacterController.__new__(CharacterController)
        self.controller.character_manager = self.manager
        self.controller.event_bus = self.bus
        self.controller._subscribe_to_events()
        self.completed = []
        for name in (Events.Character.DATA_RELOADED, Events.Character.HISTORY_CLEARED):
            self.bus.subscribe(name, self.completed.append, weak=False)
        self.port = SandboxPageController.__new__(SandboxPageController)
        self.port._bus = self.bus

    def switch_character(self):
        target = self.characters.get(self.manager.target)
        if target is not None and target is not self.manager.current_character:
            target.reload_character_data()
            self.manager.current_character = target

    def flush(self):
        self.assertTrue(self.bus.flush())

    def test_reload_targets_selected_character_and_publishes_completion(self):
        self.bus.emit(Events.Character.RELOAD_DATA, {"character_id": "Crazy"})
        self.flush()
        self.characters["Crazy"].reload_character_data.assert_called_once_with()
        self.characters["Kind"].reload_character_data.assert_not_called()
        self.assertEqual([(e.name, e.data) for e in self.completed], [
            (Events.Character.DATA_RELOADED, {"character_id": "Crazy"}),
        ])

    def test_invalid_target_does_not_fall_back_to_current_for_any_command(self):
        for name in (Events.Character.RELOAD_DATA, Events.Character.RELOAD_PROMPTS,
                     Events.Character.CLEAR_HISTORY):
            for cid in (None, "", "   ", "Unknown"):
                with self.subTest(name=name, cid=cid):
                    self.bus.emit(name, {"character_id": cid})
                    self.flush()
        for character in self.characters.values():
            character.reload_character_data.assert_not_called()
            character.clear_history.assert_not_called()
        self.assertEqual(self.completed, [])

    def test_global_reload_refreshes_loaded_characters_without_materializing_others(self):
        self.bus.emit(Events.Character.RELOAD_ALL_DATA)
        self.flush()
        for character in self.characters.values():
            character.reload_character_data.assert_called_once_with()
        self.manager.get_character.assert_not_called()
        self.assertEqual({e.data["character_id"] for e in self.completed}, {"Crazy", "Kind"})

    def test_prompt_reload_uses_existing_character_reload_method(self):
        self.bus.emit(Events.Character.RELOAD_PROMPTS, {"character_id": "Crazy"})
        self.flush()
        self.characters["Crazy"].reload_character_data.assert_called_once_with()
        self.characters["Kind"].reload_character_data.assert_not_called()

    def test_global_reload_continues_after_one_character_fails(self):
        self.characters["Crazy"].reload_character_data.side_effect = RuntimeError("test failure")
        with patch("controllers.character_controller.logger.exception"):
            result = self.controller._on_reload_all_data(Event(Events.Character.RELOAD_ALL_DATA))
        self.flush()
        self.assertFalse(result)
        self.characters["Kind"].reload_character_data.assert_called_once_with()
        self.assertEqual([e.data for e in self.completed], [{"character_id": "Kind"}])

    def test_clear_does_not_publish_success_until_operation_finishes(self):
        started = threading.Event()
        release = threading.Event()
        def clear():
            started.set()
            if not release.wait(3):
                raise TimeoutError("clear was not released")
        self.characters["Crazy"].clear_history.side_effect = clear
        try:
            self.port.clear_history("Crazy")
            self.assertTrue(started.wait(2))
            self.assertEqual(self.completed, [])
        finally:
            release.set()
        self.flush()
        self.assertEqual([(e.name, e.data) for e in self.completed], [
            (Events.Character.HISTORY_CLEARED, {"character_id": "Crazy"}),
        ])

    def test_failed_clear_does_not_publish_success(self):
        self.characters["Crazy"].clear_history.side_effect = RuntimeError("test failure")
        with self.assertRaises(RuntimeError):
            self.controller._on_clear_history(Event(
                Events.Character.CLEAR_HISTORY, {"character_id": "Crazy"},
            ))
        self.flush()
        self.assertEqual(self.completed, [])

    def test_switch_and_following_commands_are_serialized(self):
        started = threading.Event()
        release = threading.Event()
        trace = []
        def switch():
            started.set()
            if not release.wait(3):
                raise TimeoutError("switch was not released")
            self.switch_character()
            trace.append("switched")
        self.manager.check_change_current_character = switch
        self.characters["Crazy"].clear_history.side_effect = lambda: trace.append("cleared")
        self.characters["Kind"].reload_character_data.side_effect = lambda: trace.append("reloaded")
        try:
            self.port.select_character("Crazy")
            self.assertTrue(started.wait(2))
            self.port.clear_history("Crazy")
            self.bus.emit(Events.Character.RELOAD_DATA, {"character_id": "Kind"})
            self.assertEqual(trace, [])
        finally:
            release.set()
        self.flush()
        self.assertEqual(trace, ["switched", "cleared", "reloaded"])
        self.characters["Crazy"].reload_character_data.assert_called_once_with()

    def test_reselecting_active_character_reloads_once(self):
        self.port.select_character("Kind")
        self.flush()
        self.characters["Kind"].reload_character_data.assert_called_once_with()
        self.assertEqual(self.completed[0].data, {"character_id": "Kind"})

    def test_reselection_without_reload_does_not_reload(self):
        self.port.select_character("Kind", reload_data=False)
        self.flush()
        self.characters["Kind"].reload_character_data.assert_not_called()

    def test_unknown_selection_does_not_reload_active_character(self):
        self.port.select_character("Unknown")
        self.flush()
        self.characters["Kind"].reload_character_data.assert_not_called()

    def test_sandbox_reset_keeps_character_from_confirmation(self):
        vm = SimpleNamespace(_controller=self.port, emit_effect=Mock())
        vm._clear_history = lambda cid: SandboxPageViewModel._clear_history(vm, cid)
        vm.dispatch = lambda intent: SandboxPageViewModel.dispatch(vm, intent)
        page = SimpleNamespace(_get_current_character_id=lambda: "Crazy", _view_model=vm)
        def confirm(*args):
            self.assertIn("Crazy", args[2])
            self.manager.current_character = self.characters["Kind"]
            return logic.QMessageBox.StandardButton.Yes
        with patch("ui.pages.sandbox_page.QMessageBox.question", side_effect=confirm):
            SandboxPage._on_reset_character(page)
        self.flush()
        self.characters["Crazy"].clear_history.assert_called_once_with()
        self.characters["Kind"].clear_history.assert_not_called()
        vm.emit_effect.assert_not_called()

    def test_cancelled_sandbox_reset_sends_no_command(self):
        vm = SimpleNamespace(dispatch=Mock())
        page = SimpleNamespace(_get_current_character_id=lambda: "Crazy", _view_model=vm)
        with patch("ui.pages.sandbox_page.QMessageBox.question", return_value=logic.QMessageBox.StandardButton.No):
            SandboxPage._on_reset_character(page)
        vm.dispatch.assert_not_called()

    def test_sandbox_prompt_change_reloads_its_explicit_owner(self):
        settings = Mock()
        with patch.object(self.port, "_settings", return_value=settings):
            self.port.select_prompt("Crazy", "Pack")
        self.flush()
        settings.update.assert_called_once_with("PROMPT_SET_Crazy", "Pack")
        self.characters["Crazy"].reload_character_data.assert_called_once_with()
        self.characters["Kind"].reload_character_data.assert_not_called()

    def test_empty_sandbox_target_does_not_use_active_or_settings_character(self):
        settings = Mock()
        with patch.object(self.port, "_settings", return_value=settings), patch.object(
            self.port, "current_character_id", return_value="Kind",
        ), patch.object(logic, "open_db_viewer") as viewer:
            self.port.select_prompt("", "Pack")
            self.port.clear_history("")
            self.port.open_history("host", "")
            vm = SimpleNamespace(state=SimpleNamespace(character_id=""))
            ChatPanelViewModel._open_history(vm, "")
        settings.update.assert_not_called()
        viewer.assert_not_called()
        self.flush()
        self.assertEqual(self.completed, [])

    def test_history_viewers_do_not_switch_active_character(self):
        with patch.object(logic, "open_db_viewer") as viewer:
            self.port.open_history("host", "Crazy")
            viewer.assert_called_once_with("host", character_id="Crazy")
            viewer.reset_mock()
            vm = SimpleNamespace(state=SimpleNamespace(character_id="Kind"),
                                 _bus=self.bus, _host="host", emit_effect=Mock())
            ChatPanelViewModel._open_history(vm, "Crazy")
            viewer.assert_called_once_with("host", character_id="Crazy")
        self.flush()
        self.assertIs(self.manager.current_character, self.characters["Kind"])


class CharacterSettingsRoutingTests(unittest.TestCase):
    def setUp(self):
        self.bus = Mock()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(logic, "get_event_bus", return_value=self.bus))
        self.stack.enter_context(patch.object(logic, "list_prompt_sets", return_value=["Pack"]))
        self.stack.enter_context(patch.object(logic, "update_prompt_set_info"))
        self.values = {"PROMPT_SET_Crazy": "Pack"}
        self.gui = SimpleNamespace(
            character_settings_view_model=CharacterSettingsViewModel(selected_character_id="Crazy", active_character_id="Kind"),
            settings=SimpleNamespace(
                get=lambda key, default=None: self.values.get(key, default),
                set=lambda key, value: self.values.__setitem__(key, value),
            ), prompt_pack_combobox=Mock(),
        )
        self.gui.prompt_pack_combobox.currentText.return_value = "Pack"

    def test_prompt_changes_and_reload_send_selected_character(self):
        for action in (logic.on_prompt_set_changed, logic.reload_character_data,
                       lambda gui: logic.apply_prompt_set(gui, force_apply=False)):
            with self.subTest(action=action):
                self.bus.reset_mock()
                action(self.gui)
                self.bus.emit.assert_called_once_with(
                    Events.Character.RELOAD_DATA, {"character_id": "Crazy"},
                )
                self.assertEqual(self.values, {"PROMPT_SET_Crazy": "Pack"})

    def test_browsing_settings_does_not_reload_any_character(self):
        logic.change_character_actions(self.gui, "Crazy")
        self.bus.emit.assert_not_called()

    def test_empty_settings_selection_does_not_fall_back_to_active_character(self):
        self.gui.character_settings_view_model.select_character("")
        logic.reload_character_data(self.gui)
        self.assertEqual(logic._selected_character_id(self.gui), "")
        self.assertEqual(logic._configured_character_id(self.gui), "")
        self.bus.emit.assert_not_called()

    def test_public_character_query_is_called_instead_of_stringifying_method(self):
        gui = SimpleNamespace(current_character_id=lambda: "Crazy")
        self.assertEqual(logic._selected_character_id(gui), "Crazy")

    def test_background_completion_keeps_original_scope_after_selection_changes(self):
        cases = (
            ("dedup", "Crazy"), ("import", "Crazy"), ("migration", "Crazy"),
            ("restore", "Crazy"), ("full_index", "Crazy"),
            ("import", None), ("migration", None), ("dedup_all", None),
            ("full_index_all", None), ("index_all", None), ("structured", "Crazy"),
            ("structured", None),
        )
        for operation, cid in cases:
            with self.subTest(operation=operation, cid=cid), ExitStack() as stack:
                self.bus.reset_mock()
                self.gui.character_settings_view_model.select_character("Crazy")
                worker = Mock()
                stack.enter_context(patch.object(logic, "TaskWorker", return_value=worker))
                stack.enter_context(patch.object(logic, "ReindexAllCharactersWorker", return_value=worker))
                stack.enter_context(patch.object(logic, "FullReindexAllCharactersWorker", return_value=worker))
                stack.enter_context(patch.object(logic, "_create_reindex_worker", return_value=worker))
                stack.enter_context(patch.object(logic, "QProgressDialog"))
                stack.enter_context(patch.object(logic, "QTimer"))
                stack.enter_context(patch("PyQt6.QtCore.QTimer.singleShot"))
                stack.enter_context(patch("ui.dialogs.background_task_dialog.BackgroundTaskDialog"))
                stack.enter_context(patch.object(logic, "_get_all_character_ids", return_value=["Crazy", "Kind"]))
                stack.enter_context(patch.object(logic, "_reindexing_all_busy", return_value=False))
                stack.enter_context(patch("managers.database_manager.DatabaseManager"))
                stack.enter_context(patch.object(logic.QMessageBox, "question", return_value=logic.QMessageBox.StandardButton.Yes))
                stack.enter_context(patch.object(logic.QMessageBox, "information"))
                if operation == "dedup": logic.run_history_dedup(self.gui)
                elif operation == "dedup_all": logic.run_history_dedup_all(self.gui)
                elif operation == "import": logic._start_import_worker(self.gui, "dummy.json", cid)
                elif operation == "migration": logic._start_migration_worker(self.gui, cid)
                elif operation == "restore": logic._start_legacy_memory_recovery_worker(self.gui, Mock(), cid)
                elif operation == "full_index": logic.run_full_reindexing(self.gui)
                elif operation == "full_index_all": logic.run_full_reindexing_all(self.gui)
                elif operation == "index_all": logic.run_reindexing_all(self.gui)
                else: logic.migrate_db_to_structured(self.gui, cid)
                callback = worker.finished_signal.connect.call_args_list[0].args[0]
                self.gui.character_settings_view_model.select_character("Kind")
                result = {"status": "done"} if operation in ("restore", "migration", "structured") else 1
                callback(result)
                expected = (Events.Character.RELOAD_ALL_DATA,) if cid is None else (
                    Events.Character.RELOAD_DATA, {"character_id": cid},
                )
                self.assertIn(expected, [call.args for call in self.bus.emit.call_args_list])


class HistoryClearPresentationTests(unittest.TestCase):
    def test_model_character_references_wait_for_completed_switch(self):
        from controllers.model_controller import ModelController

        controller = SimpleNamespace(
            event_bus=Mock(), model=Mock(), _refresh_chat_model_character_refs=Mock(),
            _last_token_stats={"old": True},
        )
        ModelController._on_setting_changed(controller, SimpleNamespace(key="CHARACTER", value="Crazy"))
        controller.event_bus.emit.assert_called_once_with(
            Events.Character.SET_CURRENT, {"character_id": "Crazy"},
        )
        controller._refresh_chat_model_character_refs.assert_not_called()
        ModelController._on_character_current_changed(controller, Event(
            Events.Character.CURRENT_CHANGED, {"character_id": "Crazy"},
        ))
        controller._refresh_chat_model_character_refs.assert_called_once_with()
        self.assertEqual(controller._last_token_stats, {})

    def test_shell_receives_backend_completion_and_unsubscribes_on_close(self):
        bus = EventBus()
        self.addCleanup(bus.shutdown)
        view = Mock()
        presentation = Mock()
        with patch("controllers.gui.app_shell_controller.get_event_bus", return_value=bus):
            shell = AppShellController(view, presentation)
        with patch.object(shell, "current_character_id", return_value="Crazy"), patch(
            "controllers.gui.app_shell_controller.dispatch_to_gui", side_effect=lambda view, apply: apply(),
        ):
            bus.emit(Events.Character.HISTORY_CLEARED, {"character_id": "Kind"})
            self.assertTrue(bus.flush())
            view.render_chat_cleared.assert_not_called()
            bus.emit(Events.Character.HISTORY_CLEARED, {"character_id": "Crazy"})
            self.assertTrue(bus.flush())
            view.render_chat_cleared.assert_called_once_with()
            shell.close_application()
            view.render_chat_cleared.reset_mock()
            bus.emit(Events.Character.HISTORY_CLEARED, {"character_id": "Crazy"})
            self.assertTrue(bus.flush())
            view.render_chat_cleared.assert_not_called()

    def test_completion_checks_live_character_when_ui_callback_runs(self):
        for active, should_clear in (("Kind", False), ("Crazy", True)):
            with self.subTest(active=active):
                callbacks = []
                shell = AppShellController.__new__(AppShellController)
                shell._closed = False
                shell._view = Mock()
                shell.clear_chat = Mock()
                shell.current_character_id = Mock(return_value="Crazy")
                with patch("controllers.gui.app_shell_controller.dispatch_to_gui", side_effect=lambda view, apply: callbacks.append(apply)):
                    shell._on_character_history_cleared(Event(
                        Events.Character.HISTORY_CLEARED, {"character_id": "Crazy"},
                    ))
                shell.clear_chat.assert_not_called()
                shell.current_character_id.return_value = active
                callbacks[0]()
                self.assertEqual(shell.clear_chat.call_count, int(should_clear))

    def test_global_completion_clears_active_chat(self):
        shell = SimpleNamespace(_closed=False, _view=Mock(), clear_chat=Mock(),
                                current_character_id=lambda: "Kind")
        with patch("controllers.gui.app_shell_controller.dispatch_to_gui", side_effect=lambda view, apply: apply()):
            AppShellController._on_character_history_cleared(shell, Event(
                Events.Character.HISTORY_CLEARED, {"all_characters": True},
            ))
        shell.clear_chat.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
