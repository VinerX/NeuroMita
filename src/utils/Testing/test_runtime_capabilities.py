"""Проверки единого источника runtime capabilities."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from core.services import services
from services.contracts import GameLinkService, RuntimeCapabilitiesService
from services.game_link_service import DisconnectedGameLinkService
from services.runtime_capabilities import DefaultRuntimeCapabilitiesService


class _Settings:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def get(self, key: str, default=None):
        if key == "REMOTE_ONLY_STRUCTURED_FIELDS_EXCLUSION_ENABLED":
            return self.enabled
        return default


class RuntimeCapabilitiesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._previous = services().get_optional(RuntimeCapabilitiesService)

    def tearDown(self) -> None:
        if self._previous is None:
            services().unregister(RuntimeCapabilitiesService)
        else:
            services().register(
                RuntimeCapabilitiesService,
                self._previous,
                replace=True,
            )

    def test_snapshot_is_shared_policy_for_remote_prompt_and_schema(self):
        service = DefaultRuntimeCapabilitiesService(
            _Settings(), DisconnectedGameLinkService()
        )
        services().register(RuntimeCapabilitiesService, service, replace=True)

        snapshot = service.snapshot()

        self.assertFalse(snapshot.connected)
        self.assertTrue(snapshot.remote_only)
        self.assertEqual(
            snapshot.structured_segment_exclude_fields,
            (
                "allow_sleep",
                "animations",
                "clothes",
                "emotions",
                "end_game",
                "face_params",
                "idle_animations",
                "intents",
                "interactions",
                "movement_modes",
                "start_game",
                "visual_effects",
            ),
        )
        # commands and music are program-level; intents require a connected Unity runtime.
        for kept in ("commands", "music", "text"):
            self.assertNotIn(kept, snapshot.structured_segment_exclude_fields)

    def test_debug_setting_is_applied_by_the_shared_service(self):
        settings = _Settings(enabled=False)
        service = DefaultRuntimeCapabilitiesService(
            settings, DisconnectedGameLinkService()
        )
        services().register(RuntimeCapabilitiesService, service, replace=True)

        snapshot = service.snapshot()

        self.assertTrue(snapshot.remote_only)
        self.assertEqual(snapshot.structured_segment_exclude_fields, ())


if __name__ == "__main__":
    unittest.main()
