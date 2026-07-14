from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from core.events import Events, get_event_bus
from game_connections.services.beat_backend_spec import (
    BACKEND_AUTO,
    BACKEND_BEAT_THIS,
    BACKEND_DSP,
    BACKEND_LIBROSA,
    backend_display_name,
    normalize_backend_choice,
)
from game_connections.services.beat_service import get_beat_service


@dataclass(frozen=True, slots=True)
class BeatSettingsState:
    preferred_backend: str
    resolved_backend: str
    cache_entries: int
    cache_bytes: int
    cache_dir: str
    available_backends: tuple[str, ...]
    beat_this_installed: bool


class BeatSettingsController:
    """Application boundary for the passive Beat Sync settings view."""

    BACKEND_AUTO = BACKEND_AUTO
    BACKEND_BEAT_THIS = BACKEND_BEAT_THIS
    BACKEND_LIBROSA = BACKEND_LIBROSA
    BACKEND_DSP = BACKEND_DSP

    def __init__(self) -> None:
        self._bus = get_event_bus()

    def normalize_backend(self, value: Any) -> str:
        return normalize_backend_choice(value)

    def backend_label(self, backend_id: str) -> str:
        return backend_display_name(backend_id)

    def state(self) -> BeatSettingsState:
        status = get_beat_service().get_backend_status()
        backends = status.backends if isinstance(status.backends, dict) else {}
        available = [BACKEND_AUTO]
        for backend_id in (BACKEND_BEAT_THIS, BACKEND_LIBROSA):
            item = backends.get(backend_id)
            if isinstance(item, dict) and item.get("installed"):
                available.append(backend_id)
        available.append(BACKEND_DSP)
        beat_this = backends.get(BACKEND_BEAT_THIS)
        return BeatSettingsState(
            preferred_backend=normalize_backend_choice(status.preferred_backend),
            resolved_backend=normalize_backend_choice(status.resolved_backend),
            cache_entries=int(status.cache_entries or 0),
            cache_bytes=int(status.cache_bytes or 0),
            cache_dir=str(status.cache_dir),
            available_backends=tuple(available),
            beat_this_installed=bool(
                isinstance(beat_this, dict) and beat_this.get("installed")
            ),
        )

    def set_backend(self, backend_id: str) -> str:
        normalized = normalize_backend_choice(backend_id)
        get_beat_service().reset_runtime_state()
        return normalized

    def reset_runtime(self) -> None:
        get_beat_service().reset_runtime_state()

    def build_cache(self, directory: str) -> dict[str, int]:
        summary = get_beat_service().build_cache_for_directory(
            str(directory), auto_install=False
        )
        return {
            "scanned_files": int(summary.scanned_files or 0),
            "cache_hits": int(summary.cache_hits or 0),
            "generated": int(summary.generated or 0),
            "failed": int(summary.failed or 0),
        }

    def cache_directory(self) -> str:
        path = Path(self.state().cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        return str(path.resolve())

    def open_hub(self, preferred_backend: str) -> None:
        backend_id = normalize_backend_choice(preferred_backend)
        self._bus.emit(
            Events.GUI.SHOW_WINDOW,
            {
                "window_id": "ai_hub",
                "payload": {
                    "category": "beats",
                    "component_id": f"beats:{backend_id}",
                },
            },
        )

    def show_info(self, title: str, message: str) -> None:
        self._bus.emit(
            Events.GUI.SHOW_INFO_MESSAGE,
            {"title": str(title), "message": str(message)},
        )

    def show_error(self, title: str, message: str) -> None:
        self._bus.emit(
            Events.GUI.SHOW_ERROR_MESSAGE,
            {"title": str(title), "message": str(message)},
        )

    def subscribe_install_results(
        self,
        on_finished: Callable[[str], None],
        on_failed: Callable[[str], None],
    ) -> tuple[Any, Any]:
        def finished(event) -> None:
            data = event.data if isinstance(event.data, dict) else {}
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            if meta.get("kind") == "beats":
                self.reset_runtime()
                on_finished(str(meta.get("op") or "install"))

        def failed(event) -> None:
            data = event.data if isinstance(event.data, dict) else {}
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            if meta.get("kind") == "beats":
                self.reset_runtime()
                on_failed(str(meta.get("op") or "install"))

        return (
            self._bus.subscribe(Events.Install.TASK_FINISHED, finished, weak=False),
            self._bus.subscribe(Events.Install.TASK_FAILED, failed, weak=False),
        )
