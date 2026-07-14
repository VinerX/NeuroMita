from __future__ import annotations

from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from ui.settings.beat_settings_presentation import (
    BeatBackendSelected,
    BeatOpenCacheRequested,
    BeatOpenDirectory,
    BeatOpenHubRequested,
    BeatRebuildCacheRequested,
    BeatSettingsActivated,
    BeatSettingsState,
    BeatShowMessage,
)
from utils import getTranslationVariant as _


class BeatSettingsViewModel(IntentViewModel[BeatSettingsState]):
    def __init__(self, *, controller, settings, parent=None) -> None:
        super().__init__(BeatSettingsState(), parent)
        self._controller = controller
        self._settings = settings
        finished, failed = controller.subscribe_install_results(
            self._install_finished,
            self._install_failed,
        )
        self.track_subscription(finished)
        self.track_subscription(failed)
        subscribe = getattr(settings, "subscribe", None)
        if callable(subscribe):
            self.track_subscription(
                subscribe(
                    lambda _change: self._post_ui(self.refresh),
                    keys=("BEAT_SYNC_BACKEND",),
                )
            )

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, BeatSettingsActivated):
            self.refresh()
            return
        if isinstance(intent, BeatBackendSelected):
            backend_id = self._controller.set_backend(intent.backend_id)
            self._settings.set("BEAT_SYNC_BACKEND", backend_id)
            self.refresh()
            return
        if isinstance(intent, BeatOpenHubRequested):
            self._controller.open_hub(self.state.preferred_backend)
            return
        if isinstance(intent, BeatOpenCacheRequested):
            self.emit_effect(BeatOpenDirectory(self._controller.cache_directory()))
            return
        if isinstance(intent, BeatRebuildCacheRequested):
            self.rebuild_cache(intent.directory)

    def refresh(self, *, message: str | None = None) -> None:
        def worker():
            return self._controller.state()

        def applied(snapshot) -> None:
            labels = tuple(
                (backend_id, self._controller.backend_label(backend_id))
                for backend_id in snapshot.available_backends
            )
            self.update_state(
                preferred_backend=str(snapshot.preferred_backend),
                resolved_backend=str(snapshot.resolved_backend),
                available_backends=tuple(snapshot.available_backends),
                backend_labels=labels,
                beat_this_installed=bool(snapshot.beat_this_installed),
                cache_entries=int(snapshot.cache_entries),
                cache_bytes=int(snapshot.cache_bytes),
                cache_directory=str(snapshot.cache_dir),
                busy=False,
                message=str(message or self.state.message),
                error=None,
                revision=self.state.revision + 1,
            )

        self.run_coalesced(
            "beat-settings-refresh",
            worker,
            applied,
            lambda error: self.update_state(busy=False, error=str(error)),
        )

    def rebuild_cache(self, directory: str) -> None:
        directory = str(directory or "").strip()
        if not directory:
            return
        self._settings.set("BEAT_SYNC_LAST_SCAN_DIR", directory)
        self.update_state(
            busy=True,
            message=_(
                "Сканирование музыки и построение кеша...",
                "Scanning music and building cache...",
            ),
            error=None,
        )

        def worker() -> dict[str, int]:
            return dict(self._controller.build_cache(directory))

        def applied(summary: dict[str, int]) -> None:
            message = _(
                "Обработано: {processed}/{total} | Уже в кеше: {cached} | Построено: {built} | Ошибок: {failed}",
                "Processed: {processed}/{total} | Cached: {cached} | Built: {built} | Errors: {failed}",
            ).format(
                processed=summary["scanned_files"] - summary["failed"],
                total=summary["scanned_files"],
                cached=summary["cache_hits"],
                built=summary["generated"],
                failed=summary["failed"],
            )
            self.emit_effect(BeatShowMessage(_("Beat Sync", "Beat Sync"), message))
            self.refresh(message=message)

        def failed(error: Exception) -> None:
            message = _(
                "Не удалось построить кеш битов:\n{}",
                "Failed to build beat cache:\n{}",
            ).format(error)
            self.update_state(busy=False, message=message, error=str(error))
            self.emit_effect(
                BeatShowMessage(_("Beat Sync", "Beat Sync"), message, error=True)
            )

        self.run_exclusive(
            "beat-settings-cache-build",
            worker,
            applied,
            failed,
        )

    def _install_finished(self, operation: str) -> None:
        messages = {
            "install": _("Beat backend установлен", "Beat backend installed"),
            "initialize": _("Beat backend инициализирован", "Beat backend initialized"),
            "uninstall": _("Beat backend удалён", "Beat backend uninstalled"),
        }
        message = messages.get(
            str(operation),
            _("Beat backend обновлён", "Beat backend updated"),
        )
        self._post_ui(lambda: self._finish_install_result(message, False))

    def _install_failed(self, operation: str) -> None:
        messages = {
            "install": _("Ошибка установки Beat backend", "Beat backend installation failed"),
            "initialize": _("Ошибка инициализации Beat backend", "Beat backend initialization failed"),
            "uninstall": _("Ошибка удаления Beat backend", "Beat backend removal failed"),
        }
        message = messages.get(
            str(operation),
            _("Ошибка операции Beat backend", "Beat backend operation failed"),
        )
        self._post_ui(lambda: self._finish_install_result(message, True))

    def _finish_install_result(self, message: str, is_error: bool) -> None:
        self.emit_effect(
            BeatShowMessage(
                _("Beat Sync", "Beat Sync"),
                str(message),
                error=is_error,
            )
        )
        self.refresh(message=message)