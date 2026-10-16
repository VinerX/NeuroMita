from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock, patch

from controllers.gui import character_settings_logic as logic
from controllers.gui.character_settings_view_model import CharacterSettingsViewModel


class CharacterSettingsViewModelTests(unittest.TestCase):
    def test_selected_and_active_characters_are_independent(self):
        model = CharacterSettingsViewModel()
        model.select_character("Crazy")
        model.set_active_character("Kind")
        self.assertEqual(model.state.selected_character_id, "Crazy")
        self.assertEqual(model.state.active_character_id, "Kind")
        model.set_active_character("Mila")
        self.assertEqual(model.state.selected_character_id, "Crazy")

    def test_catalogue_snapshots_are_immutable_copies(self):
        names = {"Crazy": "Crazy Mita"}
        choices = [{"id": 1, "name": "Provider"}]
        model = CharacterSettingsViewModel()
        model.set_character_names(names)
        model.set_provider_choices(choices)
        names["Crazy"] = "Changed"
        choices[0]["name"] = "Changed"
        self.assertEqual(model.state.character_names["Crazy"], "Crazy Mita")
        self.assertEqual(model.state.provider_choices[0]["name"], "Provider")
        with self.assertRaises(TypeError):
            model.state.character_names["Crazy"] = "Changed"
        with self.assertRaises(FrozenInstanceError):
            model.state.snapshot_loading = True

    def test_instances_do_not_share_selection_or_catalogue(self):
        first = CharacterSettingsViewModel()
        second = CharacterSettingsViewModel()
        first.select_character("Crazy")
        first.set_provider_choices([{"id": 1}])
        self.assertIsNone(second.state.selected_character_id)
        self.assertEqual(second.state.provider_choices, ())

    def test_late_snapshot_keeps_new_active_character_and_settings_selection(self):
        model = CharacterSettingsViewModel(selected_character_id="Crazy", active_character_id="Kind")
        gui = SimpleNamespace(character_settings_view_model=model)
        services = Mock()
        services.get_optional.return_value = None
        with patch.object(logic, "services", return_value=services), patch.object(
            logic, "_build_character_library",
        ), patch.object(logic, "update_prompt_set_info"):
            logic._apply_character_settings_snapshot(gui, {
                "character_list": ["Crazy", "Kind"], "current_char_id": "Crazy",
                "character_names": {"Crazy": "Crazy Mita", "Kind": "Kind Mita"},
            })
        self.assertEqual(model.state.active_character_id, "Kind")
        self.assertEqual(model.state.selected_character_id, "Crazy")

    def test_closed_model_ignores_late_snapshot(self):
        model = CharacterSettingsViewModel(selected_character_id="Crazy")
        gui = SimpleNamespace(character_settings_view_model=model)
        data = Mock()
        data.get.return_value = None
        logic._load_character_settings_snapshot_async(gui, data)
        self.assertTrue(model.state.snapshot_loading)
        apply = data.request.call_args.args[3]
        model.close()
        with patch.object(logic, "_apply_character_settings_snapshot") as apply_to_view:
            apply({"current_char_id": "Kind"})
        apply_to_view.assert_not_called()
        self.assertEqual(model.state.selected_character_id, "Crazy")


if __name__ == "__main__":
    unittest.main()
