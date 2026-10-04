from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ASRInputDevice:
    index: int
    name: str
    host_api: str
    default_sample_rate: float | None = None

    @property
    def option_text(self) -> str:
        return f"{self.name} ({self.index})"
