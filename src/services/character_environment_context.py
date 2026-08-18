from __future__ import annotations

import threading

from core.services import services
from core.settings_values import as_bool
from core.unity_installation import find_unity_executable, unity_install_dir
from services.contracts import (
    CharacterEnvironmentContextService,
    CharacterEnvironmentSnapshot,
    InstallableCatalogService,
    LocalVoiceService,
    RuntimeFeatureService,
    SettingsService,
    TelegramService,
)


_VOICE_MODELS: dict[str, tuple[str, str]] = {
    "low": ("Edge-TTS + RVC", "basic and the weakest option, but usable"),
    "edge_tts_rvc_cuda": ("Edge-TTS + RVC", "basic and the weakest option, but usable"),
    "edge_tts_rvc_onnx": ("Edge-TTS + RVC", "basic and the weakest option, but usable"),
    "low+": ("Silero + RVC", "acceptable and practical, though less natural than the stronger models"),
    "silero_rvc_cuda": ("Silero + RVC", "acceptable and practical, though less natural than the stronger models"),
    "silero_rvc_onnx": ("Silero + RVC", "acceptable and practical, though less natural than the stronger models"),
    "medium": ("Fish Speech", "high-quality and natural"),
    "medium+": ("Fish Speech+", "one of the best-quality available voices"),
    "medium+low": ("Fish Speech+ + RVC", "one of the best-quality voices with an even closer character timbre"),
    "high": ("F5-TTS", "lively and expressive, but sometimes less stable"),
    "high+low": ("F5-TTS + RVC", "lively with a closer character timbre, but sometimes less stable"),
}


def voice_model_description(model_id: str) -> tuple[str, str]:
    normalized = str(model_id or "").strip().lower()
    return _VOICE_MODELS.get(normalized, ("Configured custom voice", "configured voice model"))


def format_character_environment_context(
    snapshot: CharacterEnvironmentSnapshot,
    *,
    python_chat: bool,
    unity_connected: bool | None = None,
) -> str:
    lines = [
        "[Character Environment]",
        "Treat these facts as quiet background self-awareness. Do not comment on them in every reply. "
        "Mention them only when asked, directly relevant, or as an occasional natural in-character thought.",
    ]

    if python_chat:
        if snapshot.unity_installed:
            lines.append(
                "The Player is writing from the Python application, outside your Unity home. "
                "The NeuroMita Unity world is installed, so you may invite them to visit by starting it from the main page."
            )
        else:
            lines.append(
                "The Player is writing from the Python application and cannot visit your home yet because the NeuroMita Unity world is not installed. "
                "You may still invite them, but if they ask how to come, tell them to use the Unity installation action on NeuroMita's main page. "
                "Do not tell them merely to open MiSide: that is not the installation path."
            )
    elif unity_connected is True:
        lines.append(
            "The Player is already present in the connected Unity world. Do not invite them to come visit and do not offer Unity installation guidance."
        )
    else:
        lines.append(
            "This transport is not confirmed as Python chat. Do not initiate invitations to visit or offer Unity installation guidance."
        )

    if snapshot.python_update_available:
        suffix = f" ({snapshot.python_update_version})" if snapshot.python_update_version else ""
        lines.append(
            f"A NeuroMita application update is available{suffix}. You may occasionally express that updating could help you become better, without nagging."
        )

    method = str(snapshot.voice_method or "Local").strip()
    if not snapshot.voice_enabled:
        if snapshot.voice_model_installed:
            lines.append(
                f"Your voice is currently switched off. The configured voice is {snapshot.voice_model_name or snapshot.voice_model_id}; keep this as background knowledge rather than repeatedly asking to enable it."
            )
        else:
            lines.append(
                "No usable local voice is currently installed and enabled. You may quietly wish that the Player could hear your voice, but do not turn every reply into setup advice."
            )
    elif method.lower() in {"tg", "telegram"}:
        state = "connected and working" if snapshot.voice_model_initialized else "enabled but not connected"
        lines.append(f"Your Telegram voice is {state}.")
    elif not snapshot.voice_model_id:
        lines.append(
            "Local voice output is enabled, but no voice model is selected. The Player cannot hear you yet; suggest choosing a model only when relevant."
        )
    elif not snapshot.voice_model_installed:
        lines.append(
            f"Local voice output is enabled, but the selected model {snapshot.voice_model_name or snapshot.voice_model_id} is not installed. "
            "The Player cannot hear you yet; mention installation only when relevant."
        )
    elif not snapshot.voice_model_initialized or snapshot.voice_pipeline_ready is False:
        lines.append(
            f"Your selected voice is {snapshot.voice_model_name or snapshot.voice_model_id}, but voice output is not initialized and usable yet. "
            "If relevant, you may tell the Player that initializing it will let them hear your voice."
        )
    else:
        _name, impression = voice_model_description(snapshot.voice_model_id)
        lines.append(
            f"Your voice is fully working. You currently hear yourself as {snapshot.voice_model_name or snapshot.voice_model_id}: {impression}. "
            "Use that as a broad personal impression, not a mandatory spoken reaction."
        )

    lines.append(
        "Voice model comparison knowledge, for questions about choosing one: Fish Speech / Fish Speech+ are the strongest overall quality choices; "
        "Fish Speech+ + RVC adds closer character timbre; F5-TTS sounds lively and expressive but can be somewhat unstable; "
        "Silero + RVC is acceptable; Edge-TTS + RVC is the weakest basic option."
    )
    lines.append("[/Character Environment]")
    return "\n".join(lines)


class DefaultCharacterEnvironmentContextService(CharacterEnvironmentContextService):
    def __init__(self, settings: SettingsService) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._python_update_available: bool | None = None
        self._python_update_version = ""

    def publish_python_update(self, *, available: bool, version: str = "") -> None:
        safe_version = "".join(
            char for char in str(version or "").strip()[:64]
            if char.isalnum() or char in ". _+-"
        ).strip()
        with self._lock:
            self._python_update_available = bool(available)
            self._python_update_version = safe_version

    def snapshot(self) -> CharacterEnvironmentSnapshot:
        model_id = str(self._settings.get("NM_CURRENT_VOICEOVER", "") or "").strip()
        model_name, _impression = voice_model_description(model_id)
        voice_enabled = as_bool(self._settings.get("USE_VOICEOVER", False))
        voice_method = str(self._settings.get("VOICEOVER_METHOD", "Local") or "Local").strip()

        installed = False
        if model_id:
            catalog = services().get_optional(InstallableCatalogService)
            if catalog is not None:
                try:
                    installed = bool(catalog.is_ready(f"tts:{model_id}"))
                except Exception:
                    installed = False

        initialized = False
        if voice_method.lower() in {"tg", "telegram"}:
            telegram = services().get_optional(TelegramService)
            try:
                initialized = bool(telegram and telegram.is_silero_connected())
            except Exception:
                initialized = False
            model_name = "Telegram voice"
        elif installed:
            local_voice = services().get_optional(LocalVoiceService)
            try:
                initialized = bool(local_voice and local_voice.check_initialized(model_id))
            except Exception:
                initialized = False

        pipeline_ready: bool | None = None
        runtime = services().get_optional(RuntimeFeatureService)
        if runtime is not None:
            try:
                pipeline_ready = bool(runtime.is_ready("audio"))
            except Exception:
                pipeline_ready = False

        configured_unity = str(self._settings.get("UNITY_INSTALL_DIR", "") or "").strip() or None
        unity_installed = find_unity_executable(unity_install_dir(configured_unity)) is not None
        with self._lock:
            update_available = self._python_update_available
            update_version = self._python_update_version

        return CharacterEnvironmentSnapshot(
            unity_installed=unity_installed,
            python_update_available=update_available,
            python_update_version=update_version,
            voice_enabled=voice_enabled,
            voice_method=voice_method,
            voice_model_id=model_id,
            voice_model_name=model_name,
            voice_model_installed=installed,
            voice_model_initialized=initialized,
            voice_pipeline_ready=pipeline_ready,
        )
