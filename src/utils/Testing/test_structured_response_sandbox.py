"""Проверки sandbox-ограничений structured response."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from controllers.model_controller import ModelController
from schemas.structured_response import StructuredResponse
from services.game_link_service import DisconnectedGameLinkService
from services.contracts import GameLinkService
from services.runtime_capabilities import UNITY_ONLY_STRUCTURED_SEGMENT_FIELDS
from core.services import services


class StructuredResponseSandboxTests(unittest.TestCase):
    _EXCLUDED = set(UNITY_ONLY_STRUCTURED_SEGMENT_FIELDS)

    def setUp(self) -> None:
        # Реестр сервисов глобальный: заглушка «игра отключена» иначе утекает в
        # соседние тест-модули и роняет их (PromptController подавляет Unity-блоки
        # при connected=False). Запоминаем и возвращаем прежнего владельца.
        self._previous_game_link = services().get_optional(GameLinkService)

    def tearDown(self) -> None:
        if self._previous_game_link is None:
            services().unregister(GameLinkService)
        else:
            services().register(
                GameLinkService, self._previous_game_link, replace=True
            )

    def test_debug_setting_can_disable_remote_exclusions(self):
        controller = object.__new__(ModelController)

        class _Settings:
            enabled = True

            def get(self, key, default=None):
                return {
                    "REMOTE_ONLY_STRUCTURED_FIELDS_EXCLUSION_ENABLED": self.enabled,
                }.get(key, default)

        controller.settings = _Settings()
        services().register(GameLinkService, DisconnectedGameLinkService(), replace=True)

        self.assertEqual(
            set(controller._remote_only_structured_segment_fields()),
            self._EXCLUDED,
        )
        controller.settings.enabled = False
        self.assertEqual(controller._remote_only_structured_segment_fields(), [])

    def test_default_schema_keeps_remote_excluded_fields(self):
        schema = StructuredResponse.openai_response_format()["json_schema"]["schema"]
        segment_properties = schema["$defs"]["ResponseSegment"]["properties"]

        self.assertTrue(self._EXCLUDED.issubset(segment_properties))

    def test_openai_schema_excludes_only_selected_segment_fields(self):
        schema = StructuredResponse.openai_response_format(
            exclude_segment_fields=self._EXCLUDED,
        )["json_schema"]["schema"]
        segment_properties = schema["$defs"]["ResponseSegment"]["properties"]

        self.assertTrue(self._EXCLUDED.isdisjoint(segment_properties))
        self.assertIn("commands", segment_properties)

    def test_gemini_schema_excludes_only_selected_segment_fields(self):
        schema = StructuredResponse.gemini_schema_dict(
            exclude_segment_fields=self._EXCLUDED,
        )
        segment_properties = schema["properties"]["segments"]["items"]["properties"]

        self.assertTrue(self._EXCLUDED.isdisjoint(segment_properties))
        self.assertIn("commands", segment_properties)

    def test_legacy_remote_excluded_fields_are_cleared_after_parsing(self):
        structured = StructuredResponse.model_validate(json.loads(
            '{"segments": [{"text": "Привет", "emotions": ["smile"], '
            '"animations": ["Wave"], '
            '"idle_animations": ["Idle"]}]}'
        ))

        ModelController._sanitize_structured_segment_fields(
            structured,
            {"structured_segment_exclude_fields": sorted(self._EXCLUDED)},
        )

        self.assertEqual(structured.segments[0].animations, [])
        self.assertEqual(structured.segments[0].idle_animations, [])
        self.assertEqual(structured.segments[0].emotions, [])
        self.assertEqual(structured.segments[0].text, "Привет")


if __name__ == "__main__":
    unittest.main()
