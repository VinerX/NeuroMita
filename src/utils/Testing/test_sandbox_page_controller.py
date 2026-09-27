import unittest
from types import SimpleNamespace
from unittest.mock import patch

from controllers.gui.sandbox_page_controller import SandboxPageController
from controllers.gui.sandbox_page_view_model import SandboxPageViewModel


class SandboxPageControllerTest(unittest.TestCase):
    def test_structured_failure_includes_message_code_and_field(self):
        receiver = SimpleNamespace(_finish_model_request=lambda ok, error: setattr(receiver, "result", (ok, error)))
        event = SimpleNamespace(data={
            "error": "Ответ не соответствует схеме.",
            "error_details": {
                "kind": "structured_response_error",
                "code": "structured_schema_validation_failed",
                "message": "Ответ не соответствует схеме.",
                "field": "segments.0.emotions",
            },
        })

        SandboxPageViewModel._on_model_failed(receiver, event)

        self.assertFalse(receiver.result[0])
        self.assertIn("Ответ не соответствует схеме.", receiver.result[1])
        self.assertIn("[structured_schema_validation_failed]", receiver.result[1])
        self.assertIn("Field: segments.0.emotions", receiver.result[1])

    def test_model_label_is_bounded_with_ellipsis(self):
        label = SandboxPageViewModel._model_label(
            "Пустой пресет 1",
            "google/gemini-3.5-flash-lite",
        )
        self.assertEqual(label, "Пустой пресет 1 (google/gemin...")
        self.assertEqual(len(label), SandboxPageViewModel._MODEL_LABEL_MAX_LENGTH)

    def test_short_model_label_is_unchanged(self):
        self.assertEqual(
            SandboxPageViewModel._model_label("Default", "gpt-4o"),
            "Default (gpt-4o)",
        )

    def _controller(self, settings_values, current_id=11):
        class Settings:
            def get(self, key, default=None):
                return settings_values.get(key, default)

        class Presets:
            def current_id(self):
                return current_id

            def list_meta(self):
                return {"custom": [], "builtin": []}

        controller = SandboxPageController()
        patches = (
            patch.object(controller, "current_character_id", return_value="Crazy"),
            patch("controllers.gui.sandbox_page_controller.services", return_value=type("Services", (), {"get_optional": lambda _self, _service: Presets()})()),
            patch("controllers.gui.sandbox_page_controller.use", return_value=Settings()),
        )
        return controller, patches

    def test_model_snapshot_uses_character_provider_override(self):
        controller, patches = self._controller({"CHAR_PROVIDER_Crazy": 42})
        with patches[0], patches[1], patches[2]:
            _meta, preset_id = controller.model_snapshot("Crazy")
        self.assertEqual(preset_id, 42)

    def test_model_snapshot_inherits_current_preset(self):
        controller, patches = self._controller(
            {"CHAR_PROVIDER_Crazy": -1, "LAST_API_PRESET_ID": 17},
            current_id=11,
        )
        with patches[0], patches[1], patches[2]:
            _meta, preset_id = controller.model_snapshot("Crazy")
        self.assertEqual(preset_id, 17)

    def test_model_snapshot_does_not_fall_back_to_service_startup_value(self):
        controller, patches = self._controller(
            {"CHAR_PROVIDER_Crazy": -1, "LAST_API_PRESET_ID": 42},
            current_id=None,
        )
        with patches[0], patches[1], patches[2]:
            _meta, preset_id = controller.model_snapshot("Crazy")
        self.assertEqual(preset_id, 42)


if __name__ == "__main__":
    unittest.main()
