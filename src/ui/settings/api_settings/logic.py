from __future__ import annotations

from main_logger import logger
from ui.settings.api_settings.controllers import ApiSettingsController


def wire_api_settings_logic(self):
    try:
        ctl = ApiSettingsController(self)
        setattr(self, "api_settings_logic", ctl)
        return ctl
    except Exception as e:
        logger.error(f"Failed to init ApiSettingsController: {e}", exc_info=True)
        try:
            # fallback UI hint
            if hasattr(self, "provider_label"):
                self.provider_label.setText("API presets: controller init failed (see logs)")
        except Exception:
            pass
        return None
