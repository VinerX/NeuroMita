from __future__ import annotations

import unittest
from unittest.mock import patch

from core.services import services
from services.contracts import ApiPresetService, ProtocolBuilderService
from startup.api_configuration import ensure_api_configuration


class _Protocols(ProtocolBuilderService):
    def build_http_request(self, *args, **kwargs):
        return {}

    def list_protocols(self):
        return []

    def get_protocol(self, protocol_id):
        return None

    def list_transforms(self):
        return []


class _Presets(ApiPresetService):
    def __init__(self) -> None:
        self.close_count = 0

    def get_full(self, preset_id):
        return {}

    def list_meta(self):
        return {"builtin": [], "custom": [], "current_id": None}

    def current_id(self):
        return None

    def save_custom(self, data):
        return {}

    def delete_custom(self, preset_id) -> None:
        return None

    def save_order(self, order) -> None:
        return None

    def export_preset(self, preset_id, path) -> None:
        return None

    def import_preset(self, path) -> None:
        return None

    def save_state(self, preset_id, state) -> None:
        return None

    def load_state(self, preset_id):
        return {}

    def set_current(self, preset_id) -> None:
        return None

    def close(self) -> None:
        self.close_count += 1


class ApiConfigurationStartupTests(unittest.TestCase):
    def setUp(self) -> None:
        services().reset()

    def tearDown(self) -> None:
        services().reset()

    def test_shell_owns_services_and_backend_borrows_same_instances(self) -> None:
        protocols = _Protocols()
        presets = _Presets()

        with (
            patch(
                "controllers.protocols_controller.ensure_protocols_controller",
                return_value=protocols,
            ),
            patch(
                "controllers.api_presets_controller.ApiPresetsController",
                return_value=presets,
            ),
        ):
            shell_runtime = ensure_api_configuration()
            backend_runtime = ensure_api_configuration()

        self.assertTrue(shell_runtime.owns_presets)
        self.assertFalse(backend_runtime.owns_presets)
        self.assertIs(shell_runtime.presets, backend_runtime.presets)
        self.assertIs(shell_runtime.protocols, backend_runtime.protocols)

        backend_runtime.close()
        self.assertEqual(0, presets.close_count)
        shell_runtime.close()
        shell_runtime.close()
        self.assertEqual(1, presets.close_count)

    def test_api_settings_section_does_not_require_conversation_backend(self) -> None:
        from ui.pages.settings.settings_page_widget import _BACKEND_REQUIRED_SECTIONS

        self.assertNotIn("api", _BACKEND_REQUIRED_SECTIONS)
        self.assertIn("characters", _BACKEND_REQUIRED_SECTIONS)
        self.assertIn("models", _BACKEND_REQUIRED_SECTIONS)


if __name__ == "__main__":
    unittest.main()
