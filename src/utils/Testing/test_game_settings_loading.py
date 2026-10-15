from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from services.contracts import CharacterRegistry
from ui.settings.game_settings import setup_game_controls

_APP = None


@pytest.mark.parametrize("connected", [True, False])
def test_game_section_uses_metadata_without_loading_unity_character(connected):
    global _APP
    _APP = QApplication.instance() or QApplication([])

    class Settings(dict):
        def set(self, key, value):
            self[key] = value

    root = QWidget()
    root.settings = Settings(
        ENABLE_GAMES=True,
        ENABLE_GAME_CHESS=True,
        ALLOW_GAMES_WHEN_CONNECTED=True,
    )
    root._save_setting = root.settings.set
    registry = Mock()
    registry.current.return_value = SimpleNamespace(
        char_id="Crazy",
        display_name="Sandbox Mita",
    )
    registry.display_name_of.return_value = "Unity Mita"
    registry.get.side_effect = AssertionError(
        "Opening settings must not load a character"
    )
    game_link = Mock()
    game_link.is_connected.return_value = connected
    game_link.unity_target_character_id.return_value = "Kind"
    try:
        with patch("ui.settings.game_settings.get_event_bus"), patch(
            "ui.settings.game_settings.use",
            side_effect=lambda service: (
                registry if service is CharacterRegistry else game_link
            ),
        ):
            setup_game_controls(root, QVBoxLayout(root), beat_view_model=Mock())
        registry.get.assert_not_called()
        assert root.launch_chess_button.isEnabled()
        assert "Sandbox Mita" in root.launch_chess_button.text()
        if connected:
            registry.display_name_of.assert_called_once_with("Kind")
            assert "Unity Mita" in root.launch_chess_button.text()
        else:
            game_link.unity_target_character_id.assert_not_called()
            assert "Unity Mita" not in root.launch_chess_button.text()
    finally:
        root.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
