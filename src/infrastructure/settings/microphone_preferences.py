from domain.audio_input import MicrophoneSelection

MICROPHONE_SETTING_KEYS = (
    "NM_MICROPHONE_BACKEND",
    "NM_MICROPHONE_UID",
    "NM_MICROPHONE_ID",
    "NM_MICROPHONE_NAME",
)


def read_microphone_selection(settings) -> MicrophoneSelection:
    index = settings.get("NM_MICROPHONE_ID")
    try:
        index = int(index) if index is not None else None
    except (TypeError, ValueError):
        index = None
    return MicrophoneSelection(
        uid=settings.get("NM_MICROPHONE_UID") or None,
        index=index,
        name=str(settings.get("NM_MICROPHONE_NAME") or ""),
        backend=str(settings.get("NM_MICROPHONE_BACKEND") or ""),
    )


class SettingsMicrophonePreferences:
    def __init__(self, settings):
        self._settings = settings

    def read(self) -> MicrophoneSelection:
        return read_microphone_selection(self._settings)

    def write(self, selection: MicrophoneSelection) -> bool:
        values = {
            "NM_MICROPHONE_BACKEND": selection.backend,
            "NM_MICROPHONE_UID": selection.uid,
            "NM_MICROPHONE_ID": selection.index,
            "NM_MICROPHONE_NAME": selection.name,
            "MIC_DEVICE": f"{selection.name} ({selection.index})",
        }
        changed = False
        for key, value in values.items():
            if self._settings.get(key) != value:
                self._settings.set(key, value)
                changed = True
        if changed:
            self._settings.save_settings()
        return changed
