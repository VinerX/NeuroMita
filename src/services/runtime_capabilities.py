"""Shared runtime capability snapshot used by prompt and model layers."""
from __future__ import annotations

from typing import Any

from core.services import services
from services.contracts import (
    GameLinkService,
    RuntimeCapabilities,
    RuntimeCapabilitiesService,
    SettingsService,
)


# These fields describe effects that can only be executed by the connected
# game runtime. Keep the policy here so prompt text and structured schemas use
# the same source of truth.
REMOTE_ONLY_STRUCTURED_SEGMENT_FIELDS = frozenset(
    {"animations", "idle_animations", "emotions"}
)


def resolve_runtime_capabilities(
    *,
    settings: Any | None = None,
    game_link: GameLinkService | None = None,
) -> RuntimeCapabilities:
    """Resolve one consistent snapshot from the application services.

    ``settings`` and ``game_link`` are injectable for isolated tests and
    startup fallback. The normal application path uses the registered
    ``RuntimeCapabilitiesService`` below.
    """
    if settings is None:
        settings = services().get_optional(SettingsService)
    if game_link is None:
        game_link = services().get_optional(GameLinkService)

    connected: bool | None = None
    if game_link is not None:
        try:
            connected = bool(game_link.is_connected())
        except Exception:
            connected = None

    remote_only = None if connected is None else not connected
    exclusion_enabled = True
    if settings is not None:
        try:
            exclusion_enabled = bool(
                settings.get(
                    "REMOTE_ONLY_STRUCTURED_FIELDS_EXCLUSION_ENABLED", True
                )
            )
        except Exception:
            exclusion_enabled = True

    excluded = (
        tuple(sorted(REMOTE_ONLY_STRUCTURED_SEGMENT_FIELDS))
        if remote_only is True and exclusion_enabled
        else ()
    )
    return RuntimeCapabilities(
        connected=connected,
        remote_only=remote_only,
        structured_segment_exclude_fields=excluded,
    )


class DefaultRuntimeCapabilitiesService(RuntimeCapabilitiesService):
    """Application-scoped owner of the runtime capability snapshot."""

    def __init__(
        self,
        settings: SettingsService | None = None,
        game_link: GameLinkService | None = None,
    ) -> None:
        self._settings = settings
        self._game_link = game_link

    def snapshot(self) -> RuntimeCapabilities:
        return resolve_runtime_capabilities(
            settings=self._settings,
            game_link=self._game_link,
        )


def runtime_capabilities(*, settings: Any | None = None) -> RuntimeCapabilities:
    """Return the registered snapshot, with a dependency-injected fallback."""
    registered = services().get_optional(RuntimeCapabilitiesService)
    if registered is not None:
        return registered.snapshot()
    return resolve_runtime_capabilities(settings=settings)


__all__ = [
    "DefaultRuntimeCapabilitiesService",
    "REMOTE_ONLY_STRUCTURED_SEGMENT_FIELDS",
    "resolve_runtime_capabilities",
    "runtime_capabilities",
]
