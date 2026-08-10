"""Application-scoped services used by the GameMaster control plane."""

from __future__ import annotations

from core.services import services
from services.dialogue_transcript_service import DialogueTranscriptService
from services.game_master_directive_registry import GameMasterDirectiveRegistry
from services.game_master_scheduler import GameMasterScheduler


def ensure_game_master_services():
    registry = services().get_optional(GameMasterDirectiveRegistry)
    if registry is None:
        registry = services().register(GameMasterDirectiveRegistry, GameMasterDirectiveRegistry())
    transcript = services().get_optional(DialogueTranscriptService)
    if transcript is None:
        transcript = services().register(DialogueTranscriptService, DialogueTranscriptService())
    scheduler = services().get_optional(GameMasterScheduler)
    if scheduler is None:
        scheduler = services().register(GameMasterScheduler, GameMasterScheduler())
    return registry, transcript, scheduler