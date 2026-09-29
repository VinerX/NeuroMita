from __future__ import annotations

import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from controllers.gui.ai_hub_settings_view_model import AIHubSettingsViewModel
from ui.mvvm import immutable_payload, mutable_payload
from ui.windows.ai_hub.settings_panel import SettingsPanel
from ui.windows.ai_hub.settings_presentation import AIHubSettingsState, SelectAIHubSettingsComponent


class ViewModelStub(QObject):
    state_changed = pyqtSignal(object)
    effect_emitted = pyqtSignal(object)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.dispatched = []

    def dispatch(self, intent):
        self.dispatched.append(intent)

    def close(self):
        pass


class SettingsPanelStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from styles.ai_hub_styles import get_stylesheet
        cls.app.setStyleSheet(get_stylesheet())

    def setUp(self):
        self.vm = ViewModelStub(AIHubSettingsState())
        self.panel = SettingsPanel(self.vm)
        self.panel.resize(1100, 680)
        self.panel.show()
        self.app.processEvents()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()

    def render(self, **changes):
        self.vm.state = replace(self.vm.state, **changes)
        self.panel.render(self.vm.state)
        self.app.processEvents()

    def test_initial_catalog_loading_is_visible_and_has_no_disabled_actions(self):
        self.assertTrue(self.panel._state_pane.isVisible())
        self.assertTrue(self.panel._state_pane.icon._spinning)
        self.assertFalse(self.panel._footer.isVisible())
        self.assertLess(self.panel._title.y(), 50)

    def test_loading_error_empty_and_form_use_one_content_area(self):
        header_y = self.panel._title.y()
        self.render(catalog_loading=False, components=(("tts:test", "Test model"),),
                    selected_component_id="tts:test", loading=True, components_revision=1)
        self.assertTrue(self.panel._state_pane.icon._spinning)
        self.render(loading=False, load_error="Cannot read settings")
        self.assertEqual(self.panel._state_pane.description.text(), "Cannot read settings")
        self.assertTrue(self.panel._state_pane.action.isVisible())
        self.assertFalse(self.panel._state_pane.icon._spinning)
        self.render(load_error="")
        self.assertTrue(self.panel._state_pane.isVisible())
        self.render(schema=immutable_payload([{
            "key": "device", "label": "Device", "type": "combobox",
            "options": {"values": ["cuda:0", "cpu"], "default": "cuda:0"},
        }]), values=immutable_payload({"device": "cuda:0"}), form_revision=1)
        self.assertTrue(self.panel._scroll.isVisible())
        self.assertFalse(self.panel._state_pane.isVisible())
        self.assertTrue(self.panel._footer.isVisible())
        self.assertEqual(self.panel._title.y(), header_y)
        self.assertLess(self.panel._form._widgets["device"].y(), 60)

    def test_catalog_loaders_replace_counts_and_clear_when_empty_result_arrives(self):
        from ui.windows.ai_hub.dialog import AIHubDialog
        from ui.windows.ai_hub.presentation import AIHubState
        main_vm = ViewModelStub(AIHubState(refreshing=True))
        settings_vm = ViewModelStub(AIHubSettingsState())
        dialog = AIHubDialog(view_model=main_vm, settings_view_model=settings_vm, settings_binding=None)
        try:
            dialog.show()
            self.app.processEvents()
            self.assertTrue(dialog._catalog_loading_pane.icon._spinning)
            for button in dialog._category_buttons.values():
                self.assertTrue(button._count_spinner.isVisible())
                self.assertFalse(button._count_lbl.isVisible())
            dialog.render(replace(main_vm.state, refreshing=False, loaded_once=True))
            self.app.processEvents()
            self.assertIsNone(dialog._catalog_loading_pane)
            for button in dialog._category_buttons.values():
                self.assertFalse(button._count_spinner.isVisible())
                self.assertTrue(button._count_lbl.isVisible())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_save_status_does_not_move_or_recreate_fields(self):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QLabel
        schema = [{"key": "device", "label": "Device", "type": "combobox",
                   "help": "A long explanation that wraps across several lines to exercise layout sizing. " * 3,
                   "options": {"values": ["cpu", "cuda:0"], "default": "cpu"}},
                  {"key": "pitch", "label": "Pitch", "help": "Pitch description", "type": "entry"}]
        self.render(catalog_loading=False, components=(("tts:a", "A"),), selected_component_id="tts:a",
                    components_revision=1, form_revision=1, schema=immutable_payload(schema),
                    values=immutable_payload({"device": "cpu", "pitch": "6"}))
        self.assertFalse(self.panel._btn_save.isEnabled())
        self.assertFalse(self.panel._btn_reset.isEnabled())
        widget = self.panel._form._widgets["device"]
        labels = self.panel._form.findChildren(QLabel, "AIHubFormHelp")
        def geometry():
            return [w.mapTo(self.panel, QPoint()).y() for w in [widget, *labels, self.panel._btn_save]]
        initial = geometry()
        self.render(dirty=True)
        self.assertTrue(self.panel._btn_save.isEnabled())
        self.render(saving=True, save_status="saving", status_text="Saving…")
        self.assertEqual(geometry(), initial)
        self.render(saving=False, dirty=False, save_status="saved", status_text="Saved",
                    form_revision=2)
        self.assertIs(self.panel._form._widgets["device"], widget)
        self.assertEqual(geometry(), initial)
        self.assertFalse(self.panel._btn_save.isEnabled())
        self.render(save_status="error", status_text="An exceptionally long failure message " * 20)
        self.assertEqual(geometry(), initial)

    def test_spinner_stops_when_panel_is_hidden(self):
        self.panel.grab()
        icon = self.panel._state_pane.icon
        timer = icon._animation.info[icon][0]
        self.assertTrue(timer.isActive())
        self.panel.hide()
        self.app.processEvents()
        self.assertFalse(timer.isActive())

    def test_unsaved_navigation_can_be_cancelled_or_confirmed(self):
        self.render(catalog_loading=False, components=(("tts:a", "A"), ("tts:b", "B")),
                    selected_component_id="tts:a", components_revision=1, form_revision=1,
                    schema=immutable_payload([{"key": "device", "type": "combobox",
                                               "options": {"values": ["cpu", "cuda:0"], "default": "cpu"}}]),
                    values=immutable_payload({"device": "cpu"}))
        self.panel._form._widgets["device"].setCurrentIndex(1)
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Cancel):
            self.panel._list.setCurrentRow(1)
        self.assertEqual(self.panel._list.currentRow(), 0)
        self.assertFalse(any(isinstance(intent, SelectAIHubSettingsComponent) for intent in self.vm.dispatched))
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Discard):
            self.panel._list.setCurrentRow(1)
        self.assertTrue(any(isinstance(intent, SelectAIHubSettingsComponent) for intent in self.vm.dispatched))


class SettingsViewModelStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from styles.ai_hub_styles import get_stylesheet
        cls.app.setStyleSheet(get_stylesheet())

    def setUp(self):
        self.vm = AIHubSettingsViewModel(catalog=SimpleNamespace(), application=SimpleNamespace(),
                                         open_documentation=lambda _url: None)
        self.addCleanup(self.vm.close)

    def test_catalog_loading_changes_even_when_the_rows_are_unchanged(self):
        self.vm.apply_rows([], "tts", loading=True)
        self.assertTrue(self.vm.state.catalog_loading)
        self.vm.apply_rows([], "tts", loading=False)
        self.assertFalse(self.vm.state.catalog_loading)
        self.assertEqual(self.vm.state.selected_component_id, "")

    def test_model_loading_discards_previous_form_and_exposes_failure(self):
        self.vm.update_state(schema=immutable_payload([{"key": "old"}]), compile_available=True)
        with patch.object(self.vm, "run_latest", return_value=True) as loader:
            self.vm.select_component("tts:new")
        self.assertTrue(self.vm.state.loading)
        self.assertFalse(self.vm.state.schema)
        self.assertFalse(self.vm.state.compile_available)
        loader.call_args.args[3](RuntimeError("Settings failed"))
        self.assertFalse(self.vm.state.loading)
        self.assertIn("Settings failed", self.vm.state.load_error)

    def test_empty_category_invalidates_an_old_pending_settings_load(self):
        self.vm.update_state(selected_component_id="tts:old", loading=True)
        self.vm._next_generation("ai-hub-settings-load")
        previous = self.vm._generations["ai-hub-settings-load"]
        self.vm.apply_rows([], "asr", loading=False)
        self.assertGreater(self.vm._generations["ai-hub-settings-load"], previous)
        self.assertFalse(self.vm.state.loading)

    def test_dirty_state_compares_with_saved_values_and_reset_restores_them(self):
        from ui.windows.ai_hub.settings_presentation import AIHubSettingsChanged, ResetAIHubSettings
        self.vm.update_state(selected_component_id="tts:a", values=immutable_payload({"device": "cpu"}),
                             saved_values=immutable_payload({"device": "cpu"}))
        self.vm.dispatch(AIHubSettingsChanged(immutable_payload({"device": "cuda:0"})))
        self.assertTrue(self.vm.state.dirty)
        self.vm.dispatch(AIHubSettingsChanged(immutable_payload({"device": "cpu"})))
        self.assertFalse(self.vm.state.dirty)
        self.vm.dispatch(AIHubSettingsChanged(immutable_payload({"device": "cuda:0"})))
        self.vm.dispatch(ResetAIHubSettings())
        self.assertFalse(self.vm.state.dirty)
        self.assertEqual(dict(mutable_payload(self.vm.state.values)), {"device": "cpu"})

    def test_background_catalog_refresh_preserves_unsaved_form(self):
        self.vm._category = "tts"
        self.vm.update_state(components=(("tts:test", "Test"),), selected_component_id="tts:test",
                             dirty=True, values=immutable_payload({"device": "cuda:1"}))
        rows = [{"metadata": {"id": "tts:test", "category": "tts", "title": "Test"},
                 "status": {"installed": True}}]
        with patch.object(self.vm, "run_latest") as loader:
            self.vm.apply_rows(rows, "tts", loading=True)
        loader.assert_not_called()
        self.assertTrue(self.vm.state.dirty)
        self.assertTrue(self.vm.state.catalog_loading)


if __name__ == "__main__":
    unittest.main()
