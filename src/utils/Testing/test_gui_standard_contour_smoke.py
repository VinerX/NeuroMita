from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


class _Subscription:
    def close(self) -> None:
        return None


class GuiStandardContourSmokeTests(unittest.TestCase):
    def test_main_pages_and_settings_sections_build(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget
        except ImportError as exc:
            self.skipTest(f"PyQt6 is unavailable: {exc}")

        from controllers.gui.composition_root import GuiCompositionRoot
        from controllers.gui.main_window_coordinator import MainWindowCoordinator
        from controllers.gui.settings_data_prefetch import (
            API_PROVIDER_NAMES,
            CHARACTER_SETTINGS_SNAPSHOT,
            EMBED_PRESET_ITEMS,
            RAG_CE_STATUS,
            RAG_EMBED_STATUS,
        )
        from core.services import services
        from services.contracts import (
            ApiPresetService,
            CharacterRegistry,
            EmbeddingPresetService,
            GameLinkService,
            InstallableCatalogService,
            ProtocolBuilderService,
            SettingsService,
        )
        from ui.pages.main_page_registry import MAIN_PAGE_ORDER

        class Settings(SettingsService):
            def __init__(self) -> None:
                self.values = {
                    "LANGUAGE": "RU",
                    "SETTINGS_PANEL_WIDTH": 980,
                    "PREBUILD_SETTINGS_PAGE_ON_STARTUP": False,
                    "RAG_ENABLED": False,
                }

            def get(self, key, default=None):
                return self.values.get(str(key), default)

            def set(self, key, value) -> None:
                self.values[str(key)] = value

            def save_settings(self) -> None:
                return None

            def update(self, key, value) -> None:
                self.values[str(key)] = value

            def snapshot(self, keys=None):
                if keys is None:
                    return dict(self.values)
                return {
                    str(key): self.values[str(key)]
                    for key in keys
                    if str(key) in self.values
                }

            def subscribe(self, callback, *, keys=None, replay=False):
                return _Subscription()

        class ApiPresets(ApiPresetService):
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

        class EmbeddingPresets(EmbeddingPresetService):
            def get_full(self, preset_id):
                return {}

            def list_meta(self):
                return {"builtin": [], "custom": []}

            def save(self, data):
                return {}

            def delete(self, preset_id) -> None:
                return None

            def rename(self, preset_id, name) -> None:
                return None

            def reorder(self, order) -> None:
                return None

        class Protocols(ProtocolBuilderService):
            def build_http_request(self, *args, **kwargs):
                return {}

            def list_protocols(self):
                return []

            def get_protocol(self, protocol_id):
                return None

            def list_transforms(self):
                return []

        class Catalog(InstallableCatalogService):
            def list_rows(self, **kwargs):
                return []

            def require_component(self, component_id, *, refresh=False):
                raise KeyError(component_id)

            def install_preview(self, component_id, *, ctx=None):
                return {}

            def invalidate(self, component_id=None) -> None:
                return None

            def settings_schema(self, component_id):
                return []

            def load_settings(self, component_id):
                return {}

            def save_component_settings(self, component_id, values):
                return {}

        class Characters(CharacterRegistry):
            def get(self, character_id):
                return None

            def all_ids(self):
                return ["Crazy"]

            def current(self):
                return None

            def current_id(self):
                return "Crazy"

            def current_profile(self):
                return {"id": "Crazy", "name": "Crazy"}

            def current_name(self):
                return "Crazy"

        class GameLink(GameLinkService):
            def is_connected(self) -> bool:
                return False

        application = QApplication.instance() or QApplication([])
        registry = services()
        registry.reset()
        registry.register(SettingsService, Settings())
        registry.register(ApiPresetService, ApiPresets())
        registry.register(EmbeddingPresetService, EmbeddingPresets())
        registry.register(ProtocolBuilderService, Protocols())
        registry.register(InstallableCatalogService, Catalog())
        registry.register(CharacterRegistry, Characters())
        registry.register(GameLinkService, GameLink())

        root = None
        hosts: list[QWidget] = []
        unhandled: list[str] = []
        original_hook = sys.excepthook
        sys.excepthook = lambda error_type, error, _traceback: unhandled.append(
            f"{error_type.__name__}: {error}"
        )
        try:
            with tempfile.TemporaryDirectory() as base_dir:
                with patch.dict(os.environ, {"NEUROMITA_BASE_DIR": base_dir}), patch.object(
                    MainWindowCoordinator,
                    "prefetch_release_feed",
                    lambda _self: None,
                ):
                    root = GuiCompositionRoot(None)
                    root.page_coordinator.ensure_page("logs")
                    for _ in range(20):
                        application.processEvents()
                        time.sleep(0.005)
                    self.assertNotIn("logs", root.window._page_placeholders)

                    for page_key in MAIN_PAGE_ORDER:
                        page = root.page_coordinator.ensure_page(page_key, eager=True)
                        self.assertIsNotNone(page, page_key)

                    root.presentation.news.load_async = (
                        lambda _target, on_ready: on_ready([])
                    )
                    root.presentation.news.get_releases = lambda: []
                    root.presentation.news.build_items = lambda **_kwargs: []
                    root.presentation.news.get_content = lambda: ""
                    for page_key in MAIN_PAGE_ORDER:
                        root.page_coordinator.switch_page(page_key)
                        application.processEvents()

                    root.presentation.settings_data._cache._values.update(
                        {
                            API_PROVIDER_NAMES: [],
                            CHARACTER_SETTINGS_SNAPSHOT: {
                                "character_list": ["Crazy"],
                                "current_char_id": "Crazy",
                                "provider_items": [],
                            },
                            EMBED_PRESET_ITEMS: [],
                            RAG_CE_STATUS: {},
                            RAG_EMBED_STATUS: {},
                        }
                    )
                    for category in (
                        "general",
                        "language",
                        "api",
                        "characters",
                        "voice",
                        "microphone",
                        "game",
                        "models",
                        "screen",
                        "updates",
                    ):
                        host = QWidget()
                        hosts.append(host)
                        layout = QVBoxLayout(host)
                        root.presentation.settings_sections.build_section(
                            root.window,
                            category,
                            layout,
                        )
                        self.assertGreater(layout.count(), 0, category)

                    for _ in range(60):
                        application.processEvents()
                        time.sleep(0.005)

            self.assertEqual([], unhandled)
        finally:
            sys.excepthook = original_hook
            if root is not None:
                root.close()
                root.window.deleteLater()
            for host in hosts:
                host.deleteLater()
            application.processEvents()
            registry.reset()


if __name__ == "__main__":
    unittest.main()
