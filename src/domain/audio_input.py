from dataclasses import dataclass
from enum import Enum


class EndpointIdentityStatus(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class MicrophoneSelection:
    uid: str | None = None
    index: int | None = None
    name: str = ""
    backend: str = ""


@dataclass(frozen=True, slots=True)
class ASRInputDevice:
    index: int
    name: str
    host_api: str
    default_sample_rate: float | None = None
    display_name: str | None = None
    uid: str | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.name

    @property
    def selection(self) -> MicrophoneSelection:
        return MicrophoneSelection(
            self.uid, self.index, self.label if self.uid else self.name
        )


@dataclass(frozen=True, slots=True)
class AudioInputCatalog:
    devices: tuple[ASRInputDevice, ...] = ()
    representations: tuple[ASRInputDevice, ...] = ()
    preferred_indices: tuple[tuple[int, int], ...] = ()
    default_index: int | None = None
    identity_status: EndpointIdentityStatus = EndpointIdentityStatus.AVAILABLE
    identity_detail: str = ""
    compatible_representations: tuple[ASRInputDevice, ...] = ()
