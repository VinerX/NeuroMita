import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from ui.settings.character_settings.ui import build_character_settings_ui
from controllers.gui.character_settings_logic import (
    _build_character_library, _select_character_settings, _filter_character_library,
)


class CharacterSettingsWorkspaceTest(unittest.TestCase):
    def setUp(self):
        language = patch("localization._current_language", return_value="EN")
        language.start()
        self.addCleanup(language.stop)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from PyQt6.QtGui import QFont, QFontDatabase
        from styles.main_styles import get_stylesheet
        for filename in ("segoeui.ttf", "segoeuib.ttf"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + filename)
        cls.app.setFont(QFont("Segoe UI", 10))
        cls.app.setStyleSheet(get_stylesheet())

    def test_library_selection_and_layout(self):
        window = QWidget()
        build_character_settings_ui(window, QVBoxLayout(window))
        self.assertEqual(window.btn_history_view.property("actionTitle"), "history_view")
        self.assertEqual(window.btn_maint_index_new.property("actionTitle"), "index_new")
        self.assertEqual(window.btn_maint_tags.property("actionTitle"), "tags")
        for name in ("history_view", "history_export", "history_import", "files_db", "tags",
                     "dedupe", "index_new", "reindex", "reset_history", "purge"):
            self.assertTrue(getattr(window, "btn_all_" + name).toolTip(), name)
        window._active_character_id = "Crazy"
        window._character_names = {"Crazy": "Crazy Mita", "Creepy": "Creepy Mita"}
        with patch("controllers.gui.character_settings_logic.change_character_actions") as load:
            _build_character_library(window, ["Crazy", "Creepy", "Ghost", "GameMaster"], "Crazy")
            self.assertEqual([window.character_library.item(i).text() for i in range(4)],
                             ["Crazy Mita", "Ghostly Mita", "Creepy Mita", "Game Master"])
            _select_character_settings(window, window.character_library.item(2))
            self.assertEqual(window._configured_char_id, "Creepy")
            self.assertEqual(window._active_character_id, "Crazy")
            self.assertEqual(window.character_name.text(), "Creepy Mita")
            self.assertEqual(window.character_id_label.text(), "id: Creepy")
            load.assert_called_with(window, "Creepy")
        _filter_character_library(window, "ghost")
        self.assertFalse(window.character_library.item(1).isHidden())
        self.assertTrue(window.character_library.item(0).isHidden())
        from ui.character_names import character_display_name, retranslate_character_list
        with patch("localization._current_language", return_value="RU"):
            self.assertEqual(character_display_name("Crazy"), "Безумная Мита")
            retranslate_character_list(window.character_library)
            self.assertEqual(window.character_library.item(0).text(), "Безумная Мита")
            from PyQt6.QtCore import Qt
            self.assertEqual(window.character_library.item(0).data(Qt.ItemDataRole.UserRole), "Crazy")
        for section in (window.character_provider_section, window.character_history_section, window.maintenance_section,
                        window.character_danger_section):
            self.assertTrue(section.is_collapsed)
            section.expand()
            self.assertFalse(section.is_collapsed)
            section.collapse()
        window.resize(1200, 720)
        window.show()
        self.app.processEvents()
        short_height = window.character_workspace_splitter.height()
        window.resize(1200, 900)
        self.app.processEvents()
        self.assertGreater(window.character_workspace_splitter.height(), short_height)
        _filter_character_library(window, "")
        window.grab().save(os.path.join(os.environ.get("TEMP", "."), "character-settings-qa.png"))
        window.maintenance_section.expand()
        self.app.processEvents()
        window.grab().save(os.path.join(os.environ.get("TEMP", "."), "character-settings-actions-qa.png"))
        window.character_danger_section.expand()
        window.character_prompt_section.collapse()
        window.hide()
        window.show()
        self.app.processEvents()
        self.assertFalse(window.character_prompt_section.is_collapsed)
        self.assertTrue(window.maintenance_section.is_collapsed)
        self.assertTrue(window.character_danger_section.is_collapsed)
        window.close()

    def test_character_section_fills_parent_height(self):
        from ui.pages.settings.settings_page_widget import SettingsSectionPage
        from ui.pages.settings.section_registry import SETTINGS_SECTION_SPECS
        spec = next(spec for spec in SETTINGS_SECTION_SPECS if spec.key == "characters")
        page = SettingsSectionPage(spec)
        build_character_settings_ui(page, page.body_layout)
        page.resize(1200, 850)
        page.show()
        self.app.processEvents()
        self.assertGreater(page.character_workspace_splitter.height(), 700)
        page.close()

    def test_provider_uses_ids_with_duplicate_names(self):
        from controllers.gui.character_settings_logic import _set_character_provider_items, save_character_provider
        from presets.character_provider import provider_preset_id
        window = QWidget()
        build_character_settings_ui(window, QVBoxLayout(window))
        class Settings:
            values = {"CHAR_PROVIDER_Crazy": 102}
            def get(self, key, default=None):
                return self.values.get(key, default)
            def set(self, key, value):
                self.values[key] = value
        window.settings = Settings()
        window._configured_char_id = "Crazy"
        choices = [dict(id=101, name="Same", model="model-a", provider="google"),
                   dict(id=102, name="Same", model="model-b", provider="openrouter")]
        _set_character_provider_items(window, choices)
        self.assertEqual(window.char_provider_combobox.current_value(), 102)
        self.assertEqual(window.char_provider_combobox.currentText(), "Same (model-b)")
        self.assertFalse(window.char_provider_combobox.itemIcon(2).isNull())
        from presets.character_provider import character_provider_choices
        from ui.provider_icons import provider_icon
        inherited = character_provider_choices({"custom": [dict(id=102, name="Router", default_model="model-b",
            provider_name="openai_compatible", template_name="OpenRouter", protocol_id="openai_compatible_default")]})
        _set_character_provider_items(window, inherited)
        self.assertEqual(window.char_provider_combobox.itemIcon(1).cacheKey(), provider_icon("openrouter").cacheKey())
        inherited[0]["model"] = "  "
        _set_character_provider_items(window, inherited)
        self.assertEqual(window.char_provider_combobox.currentText(), "Router (None)")
        save_character_provider(window, 101)
        self.assertEqual(window.settings.values["CHAR_PROVIDER_Crazy"], 101)
        self.assertIsNone(provider_preset_id(-1))
        self.assertEqual(provider_preset_id(102), 102)
        self.assertIsNone(provider_preset_id("Same"))
        from presets.character_provider import migrate_character_provider_settings
        window.settings.snapshot = lambda: dict(window.settings.values)
        window.settings.values["CHAR_PROVIDER_Crazy"] = "Old name"
        migrate_character_provider_settings(window.settings, {"custom": [{"id": 101, "name": "Old name"}]})
        self.assertEqual(window.settings.values["CHAR_PROVIDER_Crazy"], 101)
        window.close()


if __name__ == "__main__":
    unittest.main()
