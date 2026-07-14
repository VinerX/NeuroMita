from __future__ import annotations

from main_logger import logger


def setup_api_controls(self, parent_layout, *, wire_api) -> None:
    from .ui import build_api_settings_ui

    build_api_settings_ui(self, parent_layout)
    try:
        wire_api(self)
    except Exception as exc:
        logger.error("Failed to initialize API settings presenter: %s", exc, exc_info=True)
        if hasattr(self, "provider_label"):
            self.provider_label.setText("API presets: controller init failed (see logs)")
