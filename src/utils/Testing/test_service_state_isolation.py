from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication, QComboBox

from controllers.gui.voiceover_controller import VoiceoverGuiController
from controllers.local_voice_controller import LocalVoiceController
from controllers.model_controller import ModelController
from core.events import Event, Events
from services.installable_catalog_service import DefaultInstallableCatalogService


class ServiceStateIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_microphone_and_navigation_settings_do_not_invalidate_tts(self):
        catalog = DefaultInstallableCatalogService.__new__(DefaultInstallableCatalogService)
        catalog.invalidate = Mock()
        for key in ("MIC_ACTIVE", "RECOGNIZER_TYPE", "NM_CURRENT_VOICEOVER", "USE_VOICEOVER"):
            catalog._on_setting_changed(SimpleNamespace(key=key))
        catalog.invalidate.assert_not_called()
        catalog._on_setting_changed(SimpleNamespace(key="VOICE_LANGUAGE"))
        self.assertTrue(catalog.invalidate.called)
        self.assertTrue(all(call.args[0].startswith("tts:") for call in catalog.invalidate.call_args_list))

    def test_asr_settings_only_invalidate_asr_components(self):
        catalog = DefaultInstallableCatalogService.__new__(DefaultInstallableCatalogService)
        catalog.invalidate = Mock()
        catalog._on_asr_setting_changed(SimpleNamespace(engine_id="google"))
        catalog.invalidate.assert_called_once_with("asr:google")
        catalog.invalidate.reset_mock()
        catalog._on_asr_setting_changed(SimpleNamespace(engine_id=""))
        self.assertTrue(catalog.invalidate.called)
        self.assertTrue(all(call.args[0].startswith("asr:") for call in catalog.invalidate.call_args_list))

    def test_pending_voice_status_preserves_selection_and_is_not_an_error(self):
        controller = VoiceoverGuiController.__new__(VoiceoverGuiController)
        controller.view = SimpleNamespace(local_voice_combobox=QComboBox())
        controller._model_id_to_name = {"voice": "Voice"}
        controller._set_local_model_selector_state = Mock()
        controller._set_combobox_by_model_id = Mock()
        controller._save_setting = Mock()
        self.assertEqual(controller._update_local_models_combobox_from_snapshot(set(), "voice"), "voice")
        controller._save_setting.assert_not_called()
        controller._effective_use_voice = lambda: True
        controller._effective_method = lambda: "Local"
        controller._loading_model_id = None
        controller.event_bus = SimpleNamespace(emit=Mock())
        controller._emit_voice_icon_state_from_snapshot({"current_model_id": "voice", "installed": False, "availability": "checking"})
        self.assertEqual(controller.event_bus.emit.call_args.args[1]["state"], "loading")

    def test_only_tts_probe_completion_refreshes_voice_status(self):
        controller = VoiceoverGuiController.__new__(VoiceoverGuiController)
        controller._ui = lambda action: action()
        controller._sync_everything = Mock()
        controller._on_component_status(Event(Events.Install.COMPONENT_STATUS, {"component_id": "asr:google"}))
        controller._sync_everything.assert_not_called()
        controller._on_component_status(Event(Events.Install.COMPONENT_STATUS, {"component_id": "tts:voice"}))
        controller._sync_everything.assert_called_once_with(allow_autoload=False)

    def test_unavailable_readiness_probe_does_not_erase_last_known_tts_state(self):
        controller = LocalVoiceController.__new__(LocalVoiceController)
        controller._initialized_cache = {"voice": True}
        engine = SimpleNamespace(call=Mock(return_value=SimpleNamespace(result=Mock(side_effect=TimeoutError()))))
        controller._get_engine = lambda: engine
        self.assertTrue(controller._on_check_model_initialized(Event(Events.Audio.CHECK_MODEL_INITIALIZED, {"model_id": "voice", "probe_worker": True})))
        self.assertTrue(controller._initialized_cache["voice"])

    def test_context_count_reads_only_recorded_snapshot_and_keeps_user_message(self):
        controller = ModelController.__new__(ModelController)
        controller._context_snapshot_cache = {}
        controller._context_snapshot_lock = threading.RLock()
        controller._get_current_character_id = lambda: "Crazy"
        controller.context_counter = SimpleNamespace(count_tokens=lambda messages: len(messages))
        controller._get_character_ref = Mock(side_effect=AssertionError("Counting must not access DSL"))
        self.assertEqual(controller._build_current_context_messages(), ("Crazy", [], 0))
        messages = [{"role": "system", "content": "Recorded DSL result"}, {"role": "user", "content": "Hello"}]
        controller._record_context_snapshot("Crazy", "chat", messages)
        messages[0]["content"] = "Changed later"
        controller._temporary_system_infos = {"Crazy": [{"role": "system", "content": "Pending event"}]}
        for _ in range(3):
            cid, snapshot, count = controller._build_current_context_messages()
            self.assertEqual(count, 2)
            self.assertEqual(snapshot[0]["content"], "Recorded DSL result")
            self.assertEqual(snapshot[-1]["content"], "Hello")
            snapshot[0]["content"] = "Changed by caller"
        controller._get_character_ref.assert_not_called()
        controller._get_current_character_id = lambda: "Kind"
        self.assertEqual(controller._build_current_context_messages(), ("Kind", [], 0))


if __name__ == "__main__":
    unittest.main()
