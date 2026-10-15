from typing import Protocol

from domain.audio_input import AudioInputCatalog, MicrophoneSelection


class AudioInputCatalogUnavailable(RuntimeError):
    pass


class MicrophoneIdentityUnavailable(AudioInputCatalogUnavailable):
    def __init__(self, detail=""):
        self.detail = detail
        super().__init__(
            "Не удалось прочитать Windows ID микрофона. Привязка сохранена; обновите список устройств."
        )


class MicrophoneBackendUnavailable(AudioInputCatalogUnavailable):
    def __init__(self, backend):
        self.detail = backend
        super().__init__(
            "Выбранный аудиобэкенд недоступен для этого микрофона. Выберите другой бэкенд или Авто."
        )


class AudioInputCatalogProvider(Protocol):
    def read(self, *, refresh: bool = False) -> AudioInputCatalog: ...


class MicrophonePreferences(Protocol):
    def read(self) -> MicrophoneSelection: ...

    def write(self, selection: MicrophoneSelection) -> bool: ...
