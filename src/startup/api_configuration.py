from __future__ import annotations

import threading
from dataclasses import dataclass

from core.services import services
from services.contracts import ApiPresetService, ProtocolBuilderService


_bootstrap_lock = threading.RLock()


@dataclass(slots=True)
class ApiConfigurationRuntime:
    """Application-scoped LLM configuration services.

    Preset editing and connection checks do not depend on the conversation
    runtime, local voice, ASR, or the game server.  The GUI creates these
    services before the backend thread starts; headless startup creates the
    same pair on demand.
    """

    protocols: ProtocolBuilderService
    presets: ApiPresetService
    owns_presets: bool = False
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self.owns_presets:
            return
        close = getattr(self.presets, "close", None)
        if callable(close):
            close()


def ensure_api_configuration() -> ApiConfigurationRuntime:
    """Return the process services, creating only the missing application owners."""

    registry = services()
    with _bootstrap_lock:
        protocols = registry.get_optional(ProtocolBuilderService)
        if protocols is None:
            from controllers.protocols_controller import ensure_protocols_controller

            protocols = ensure_protocols_controller()
            registry.register(ProtocolBuilderService, protocols)

        presets = registry.get_optional(ApiPresetService)
        owns_presets = presets is None
        if presets is None:
            from controllers.api_presets_controller import ApiPresetsController

            presets = ApiPresetsController()
            registry.register(ApiPresetService, presets)

        return ApiConfigurationRuntime(
            protocols=protocols,
            presets=presets,
            owns_presets=owns_presets,
        )
