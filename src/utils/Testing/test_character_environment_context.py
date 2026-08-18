from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from services.character_environment_context import (
    DefaultCharacterEnvironmentContextService,
    format_character_environment_context,
    voice_model_description,
)
from services.contracts import CharacterEnvironmentSnapshot, PlayerMessageSource


class CharacterEnvironmentContextTests(unittest.TestCase):
    def test_update_snapshot_replays_when_backend_service_attaches_late(self):
        from controllers.gui.presentation_hub import _ApplicationController
        from services.contracts import CharacterEnvironmentContextService

        published = []
        provider = SimpleNamespace(
            publish_python_update=lambda **payload: published.append(payload)
        )

        class _Registry:
            current = None

            def get_optional(self, contract):
                if contract is CharacterEnvironmentContextService:
                    return self.current
                return None

        registry = _Registry()
        app = _ApplicationController()
        with patch("controllers.gui.presentation_hub.services", return_value=registry):
            app.publish_python_update(available=True, version="v2026.08.19")
            self.assertEqual([], published)
            registry.current = provider
            app.attach_backend(SimpleNamespace())

        self.assertEqual(
            [{"available": True, "version": "v2026.08.19"}],
            published,
        )

    def test_service_uses_canonical_unity_and_voice_state(self):
        class _Settings:
            values = {
                "UNITY_INSTALL_DIR": "",
                "USE_VOICEOVER": True,
                "VOICEOVER_METHOD": "Local",
                "NM_CURRENT_VOICEOVER": "medium+",
            }

            def get(self, key, default=None):
                return self.values.get(key, default)

        class _Registry:
            values = {
                "catalog": SimpleNamespace(is_ready=lambda component_id: component_id == "tts:medium+"),
                "voice": SimpleNamespace(check_initialized=lambda model_id: model_id == "medium+"),
                "runtime": SimpleNamespace(is_ready=lambda feature: feature == "audio"),
            }

            def get_optional(self, contract):
                from services.contracts import InstallableCatalogService, LocalVoiceService, RuntimeFeatureService

                return {
                    InstallableCatalogService: self.values["catalog"],
                    LocalVoiceService: self.values["voice"],
                    RuntimeFeatureService: self.values["runtime"],
                }.get(contract)

        with tempfile.TemporaryDirectory() as base_dir:
            unity_dir = Path(base_dir) / "NeuroMita-Unity"
            unity_dir.mkdir()
            (unity_dir / "NeuroMita.exe").write_bytes(b"")
            with patch.dict("os.environ", {"NEUROMITA_BASE_DIR": base_dir}), patch(
                "services.character_environment_context.services",
                return_value=_Registry(),
            ):
                snapshot = DefaultCharacterEnvironmentContextService(_Settings()).snapshot()

        self.assertTrue(snapshot.unity_installed)
        self.assertEqual("Fish Speech+", snapshot.voice_model_name)
        self.assertTrue(snapshot.voice_model_installed)
        self.assertTrue(snapshot.voice_model_initialized)
        self.assertTrue(snapshot.voice_pipeline_ready)

    def test_python_chat_without_unity_has_correct_visit_guide(self):
        content = format_character_environment_context(
            CharacterEnvironmentSnapshot(unity_installed=False),
            player_message_source=PlayerMessageSource.APPLICATION,
            unity_connected=False,
        )

        self.assertIn("authored this turn in the NeuroMita Python application", content)
        self.assertIn("cannot visit your NeuroMita world yet", content)
        self.assertIn("Unity installation action on NeuroMita's main page", content)
        self.assertIn("call it NeuroMita", content)
        self.assertIn("Do not call that shared runtime MiSide", content)

    def test_connected_unity_does_not_invite_or_offer_installation(self):
        content = format_character_environment_context(
            CharacterEnvironmentSnapshot(unity_installed=True),
            player_message_source=PlayerMessageSource.GAME,
            unity_connected=True,
        )

        self.assertIn("The NeuroMita game is running and connected right now", content)
        self.assertIn("already present in the connected world", content)
        self.assertIn("Do not invite them to come visit", content)
        self.assertNotIn("starting it from the main page", content)
        self.assertNotIn("Unity installation action", content)

    def test_application_turn_can_coexist_with_running_game(self):
        content = format_character_environment_context(
            CharacterEnvironmentSnapshot(unity_installed=True),
            player_message_source=PlayerMessageSource.APPLICATION,
            unity_connected=True,
        )

        self.assertIn("The NeuroMita game is running and connected right now", content)
        self.assertIn("authored this turn in the NeuroMita Python application", content)
        self.assertIn("not from inside the game", content)
        self.assertIn("already-running NeuroMita game", content)
        self.assertNotIn("starting NeuroMita from the main page", content)

    def test_enabled_but_uninitialized_voice_is_explained_softly(self):
        content = format_character_environment_context(
            CharacterEnvironmentSnapshot(
                voice_enabled=True,
                voice_model_id="medium+",
                voice_model_name="Fish Speech+",
                voice_model_installed=True,
                voice_model_initialized=False,
                voice_pipeline_ready=True,
            ),
            player_message_source=PlayerMessageSource.APPLICATION,
        )

        self.assertIn("not initialized and usable yet", content)
        self.assertIn("initializing it will let them hear your voice", content)
        self.assertIn("Do not comment on them in every reply", content)

    def test_working_voice_includes_current_impression_and_comparison_map(self):
        content = format_character_environment_context(
            CharacterEnvironmentSnapshot(
                voice_enabled=True,
                voice_model_id="medium+low",
                voice_model_name="Fish Speech+ + RVC",
                voice_model_installed=True,
                voice_model_initialized=True,
                voice_pipeline_ready=True,
            ),
            player_message_source=PlayerMessageSource.APPLICATION,
        )

        self.assertIn("Your voice is fully working", content)
        self.assertIn("closer character timbre", content)
        self.assertIn("Fish Speech / Fish Speech+ are the strongest overall quality choices", content)
        self.assertIn("F5-TTS sounds lively and expressive but can be somewhat unstable", content)
        self.assertIn("Edge-TTS + RVC is the weakest basic option", content)

    def test_update_is_optional_background_awareness(self):
        content = format_character_environment_context(
            CharacterEnvironmentSnapshot(
                python_update_available=True,
                python_update_version="v2026.08.19",
            ),
            player_message_source=PlayerMessageSource.APPLICATION,
        )

        self.assertIn("A NeuroMita application update is available (v2026.08.19)", content)
        self.assertIn("without nagging", content)

    def test_all_documented_voice_families_have_descriptions(self):
        for model_id in (
            "low",
            "low+",
            "edge_tts_rvc_cuda",
            "silero_rvc_onnx",
            "medium",
            "medium+",
            "medium+low",
            "high",
            "high+low",
        ):
            name, impression = voice_model_description(model_id)
            self.assertTrue(name, model_id)
            self.assertNotEqual("configured voice model", impression, model_id)


if __name__ == "__main__":
    unittest.main()
