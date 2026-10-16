from __future__ import annotations

from controllers.gui.character_settings_view_model import CharacterSettingsViewModel

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.character_controller import CharacterController
from controllers.gui import character_settings_logic as logic
from core.events import Event, EventBus, Events


class CharacterHistoryClearTests(unittest.TestCase):
    def setUp(self):
        self.characters = {
            cid: SimpleNamespace(char_id=cid, clear_history=Mock())
            for cid in ("Crazy", "Kind")
        }
        self.manager = SimpleNamespace(
            current_character=self.characters["Kind"],
            get_character=Mock(side_effect=self.characters.get),
        )
        self.controller = CharacterController.__new__(CharacterController)
        self.controller.character_manager = self.manager
        self.bus = EventBus()
        self.controller.event_bus = self.bus
        self.addCleanup(self.bus.shutdown)
        self.bus.subscribe(
            Events.Character.CLEAR_HISTORY,
            self.controller._on_clear_history,
            weak=False,
        )
        self.commands = Mock()
        self.commands.emit.side_effect = self.emit_command
        bus_patch = patch.object(logic, "get_event_bus", return_value=self.commands)
        bus_patch.start()
        self.addCleanup(bus_patch.stop)
        self.gui = SimpleNamespace(
            character_settings_view_model=CharacterSettingsViewModel(selected_character_id="Crazy", active_character_id="Kind"),
            clear_chat_display=Mock(), update_debug_info=Mock(),
        )

    def test_settings_clear_selected_character_without_switching_active(self):
        for selected, active in (("Crazy", "Kind"), ("Kind", "Crazy"), ("Crazy", "Crazy")):
            with self.subTest(selected=selected, active=active):
                for character in self.characters.values():
                    character.clear_history.reset_mock()
                self.gui.clear_chat_display.reset_mock()
                self.gui.character_settings_view_model.select_character(selected)
                self.gui.character_settings_view_model.set_active_character(active)
                self.manager.current_character = self.characters[active]
                with patch.object(logic.QMessageBox, "question", return_value=logic.QMessageBox.StandardButton.Yes) as question:
                    logic.clear_history(self.gui)

                self.assertIn(selected, question.call_args.args[2])
                self.commands.emit.assert_called_with(
                    Events.Character.CLEAR_HISTORY, {"character_id": selected}
                )
                self.characters[selected].clear_history.assert_called_once_with()
                other = "Kind" if selected == "Crazy" else "Crazy"
                self.characters[other].clear_history.assert_not_called()
                self.assertIs(self.manager.current_character, self.characters[active])
                self.gui.clear_chat_display.assert_not_called()

    def test_cancel_does_not_clear_any_character(self):
        with patch.object(logic.QMessageBox, "question", return_value=logic.QMessageBox.StandardButton.No):
            logic.clear_history(self.gui)

        self.commands.emit.assert_not_called()
        self.assert_nothing_cleared()
        self.gui.clear_chat_display.assert_not_called()

    def test_no_selection_does_not_offer_or_send_clear(self):
        self.gui = SimpleNamespace()
        with patch.object(logic.QMessageBox, "question") as question, patch.object(logic.QMessageBox, "information") as information:
            logic.clear_history(self.gui)

        question.assert_not_called()
        information.assert_called_once()
        self.commands.emit.assert_not_called()
        self.assert_nothing_cleared()

    def test_selection_change_during_confirmation_keeps_confirmed_target(self):
        def confirm(*args):
            self.gui.character_settings_view_model.select_character("Kind")
            return logic.QMessageBox.StandardButton.Yes

        with patch.object(logic.QMessageBox, "question", side_effect=confirm):
            logic.clear_history(self.gui)

        self.characters["Crazy"].clear_history.assert_called_once_with()
        self.characters["Kind"].clear_history.assert_not_called()

    def test_sandbox_command_without_id_clears_active_character(self):
        self.emit_command(Events.Character.CLEAR_HISTORY)

        self.characters["Kind"].clear_history.assert_called_once_with()
        self.characters["Crazy"].clear_history.assert_not_called()
        self.manager.get_character.assert_not_called()

    def test_invalid_explicit_target_never_clears_active_character(self):
        for character_id in ("Unknown", "", "   ", None):
            with self.subTest(character_id=character_id):
                result = self.controller._on_clear_history(
                    Event(Events.Character.CLEAR_HISTORY, {"character_id": character_id})
                )

                self.assertFalse(result)
                self.assert_nothing_cleared()

    def test_no_active_character_does_not_prevent_targeted_clear(self):
        self.manager.current_character = None

        self.emit_command(Events.Character.CLEAR_HISTORY, {"character_id": "Crazy"})

        self.characters["Crazy"].clear_history.assert_called_once_with()
        self.characters["Kind"].clear_history.assert_not_called()

    def test_no_active_character_makes_untargeted_clear_a_noop(self):
        self.manager.current_character = None

        result = self.controller._on_clear_history(Event(Events.Character.CLEAR_HISTORY))

        self.assertFalse(result)
        self.assert_nothing_cleared()

    def assert_nothing_cleared(self):
        for character in self.characters.values():
            character.clear_history.assert_not_called()

    def emit_command(self, name, data=None):
        self.bus.emit(name, data)
        self.assertTrue(self.bus.flush())


if __name__ == "__main__":
    unittest.main()
