from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QTimer

from controllers.gui.intent_view_model import IntentViewModel
from core.events import Events, get_event_bus
from main_logger import logger
from ui.pages.home_presentation import (
    HomeActivated,
    HomeApplyUpdatesRequested,
    HomeCancelRequested,
    HomeExternalProgress,
    HomeHideProgress,
    HomeInstallUnityRequested,
    HomeLanguageChanged,
    HomeNewsItemState,
    HomeOpenRelease,
    HomeOpenReleaseRequested,
    HomeOpenUnityFolderRequested,
    HomePrimaryRequested,
    HomePromptRestart,
    HomePromptTesterCode,
    HomeRefreshNews,
    HomeRefreshSidebar,
    HomeRefreshUpdates,
    HomeRestartDecision,
    HomeShowError,
    HomeState,
    HomeStopUnityRequested,
    HomeTesterCodeSubmitted,
    HomeToggleUpdate,
    HomeUpdateState,
)
from utils import _


_UPDATE_CHECK_THROTTLE_SEC = 600.0


def _strip_v(version: str) -> str:
    text = str(version or "").strip()
    return text[1:] if text[:1] in ("v", "V") else text


class _ProgressLogger:
    def __init__(self, view_model: "HomePageViewModel", prefix: str) -> None:
        self._view_model = view_model
        self._prefix = prefix

    def _set(self, marker: str, message: Any, level: str) -> None:
        getattr(logger, level, logger.info)(f"[{self._prefix}] {message}")

    def info(self, message: Any) -> None:
        self._set("", message, "info")

    def warning(self, message: Any) -> None:
        self._set("⚠ ", message, "warning")

    def error(self, message: Any) -> None:
        self._set("✗ ", message, "error")

    def success(self, message: Any) -> None:
        self._set("✓ ", message, "info")

    def notify(self, message: Any) -> None:
        self._set("★ ", message, "info")


class HomePageViewModel(IntentViewModel[HomeState]):
    """Owns launcher-home state and all updater/install orchestration."""

    def __init__(
        self,
        *,
        host: Any,
        app: Any,
        home_controller: Any,
        news_controller: Any,
        settings: Any,
        parent=None,
    ) -> None:
        super().__init__(HomeState(), parent)
        self._host = host
        self._app = app
        self._home = home_controller
        self._news = news_controller
        self._settings = settings
        self._last_update_check = float(app.last_update_check_ts)
        self._cancel_event: threading.Event | None = None
        self._pending_continuation: str | None = None
        self._operation_components: tuple[str, ...] = ()

        bus = get_event_bus()
        self.track_subscription(
            bus.subscribe(Events.Install.TASK_STARTED, self._on_install_started, weak=False)
        )
        self.track_subscription(
            bus.subscribe(Events.Install.TASK_PROGRESS, self._on_install_progress, weak=False)
        )
        self.track_subscription(
            bus.subscribe(Events.Install.TASK_FINISHED, self._on_install_finished, weak=False)
        )
        self.track_subscription(
            bus.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)
        )
        self._home.process_state_changed.connect(self._on_unity_process_state)
        self._refresh_local_state(emit=False)

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, HomeActivated):
            self._refresh_local_state()
            self.refresh_news()
            self.refresh_updates(force=intent.force_update_check)
            return
        if isinstance(intent, HomeLanguageChanged):
            self._refresh_local_state()
            self.refresh_news()
            return
        if isinstance(intent, HomeRefreshUpdates):
            self.refresh_updates(force=intent.force, show_result=intent.show_result)
            return
        if isinstance(intent, HomeRefreshNews):
            self.refresh_news()
            return
        if isinstance(intent, HomeExternalProgress):
            self._set_progress(
                intent.text,
                intent.value,
                intent.maximum,
                busy=bool(intent.busy),
            )
            return
        if isinstance(intent, HomeHideProgress):
            self._hide_progress_if_idle()
            return
        if isinstance(intent, HomeToggleUpdate):
            self._toggle_update(intent.component, intent.selected)
            return
        if isinstance(intent, HomePrimaryRequested):
            self._run_primary_action()
            return
        if isinstance(intent, HomeInstallUnityRequested):
            update = self.state.unity_update
            if update.available or update.installable:
                self.update_state(
                    unity_update=HomeUpdateState(
                        available=update.available,
                        installable=update.installable,
                        selected=True,
                        latest_version=update.latest_version,
                    )
                )
                self._refresh_computed_state()
                self._request_selective_update()
            return
        if isinstance(intent, HomeApplyUpdatesRequested):
            self._request_selective_update()
            return
        if isinstance(intent, HomeOpenUnityFolderRequested):
            self._open_unity_folder()
            return
        if isinstance(intent, HomeCancelRequested):
            self._cancel_current_operation()
            return
        if isinstance(intent, HomeStopUnityRequested):
            self._stop_unity()
            return
        if isinstance(intent, HomeTesterCodeSubmitted):
            self._resume_with_tester_code(intent.continuation, intent.code)
            return
        if isinstance(intent, HomeRestartDecision):
            self._handle_restart_decision(intent.accepted)
            return
        if isinstance(intent, HomeOpenReleaseRequested):
            self.emit_effect(HomeOpenRelease(str(intent.release_id or "")))

    def refresh_updates(self, *, force: bool = False, show_result: bool = False) -> None:
        if not force:
            if not bool(self._settings.get("UPDATE_CHECK_ON_STARTUP", True)):
                return
            if time.monotonic() - self._last_update_check < _UPDATE_CHECK_THROTTLE_SEC:
                return

        self._last_update_check = time.monotonic()
        self._app.mark_update_check(self._last_update_check)
        if show_result:
            self._set_progress(
                _("Проверка обновлений…", "Checking for updates…"),
                0,
                0,
                busy=True,
            )
        self.update_state(update_checking=True, error=None)

        channel = str(self._settings.get("UPDATE_CHANNEL", "stable") or "stable")
        unity_dir = self._settings.get("UNITY_INSTALL_DIR") or None

        def worker() -> tuple[dict[str, Any], dict[str, Any]]:
            return self._home.update_info(channel=channel, unity_dir=unity_dir)

        def applied(result: tuple[dict[str, Any], dict[str, Any]]) -> None:
            py_info, unity_info = result
            self._apply_update_info(py_info, unity_info)
            if show_result:
                parts: list[str] = []
                if self.state.python_update.available:
                    parts.append(
                        _("Python: {ver}", "Python: {ver}").format(
                            ver=_strip_v(self.state.python_update.latest_version)
                        )
                    )
                if self.state.unity_update.available:
                    parts.append(
                        _("Unity: {ver}", "Unity: {ver}").format(
                            ver=_strip_v(self.state.unity_update.latest_version)
                        )
                    )
                text = (
                    _("Доступны обновления: {parts}", "Updates available: {parts}").format(
                        parts=", ".join(parts)
                    )
                    if parts
                    else _("Обновлений нет.", "No updates available.")
                )
                self._set_progress(text, 100, 100, busy=False)
                self._schedule_hide_progress()

        def failed(error: Exception) -> None:
            self.update_state(update_checking=False, error=str(error))
            if show_result:
                self._set_progress(
                    _("Ошибка проверки: {err}", "Check error: {err}").format(err=error),
                    0,
                    0,
                    busy=False,
                )
                self._schedule_hide_progress()

        self.run_coalesced("home-update-check", worker, applied, failed)

    def refresh_news(self) -> None:
        try:
            self._news.load_async(self._host, self._on_news_ready)
        except Exception as exc:
            logger.debug("Home release feed refresh failed: %s", exc)

    def post_progress(
        self,
        text: str,
        value: int,
        maximum: int,
        *,
        busy: bool,
    ) -> None:
        self._post_ui(
            lambda: self._set_progress(text, value, maximum, busy=busy)
        )

    def close(self) -> None:
        cancel = self._cancel_event
        if cancel is not None:
            cancel.set()
        self._cancel_event = None
        super().close()

    def _run_primary_action(self) -> None:
        action = self.state.primary_action
        if action == "stop":
            self._stop_unity()
        elif action == "restart":
            self.emit_effect(HomePromptRestart())
        elif action == "apply":
            self._request_selective_update()
        elif action == "play":
            try:
                self._home.launch_unity(self._settings.get("UNITY_INSTALL_DIR") or None)
            except Exception as exc:
                self.emit_effect(
                    HomeShowError(
                        _("Запуск", "Launch"),
                        _(
                            "Не удалось запустить Unity: {err}",
                            "Failed to launch Unity: {err}",
                        ).format(err=exc),
                    )
                )

    def _toggle_update(self, component: str, selected: bool) -> None:
        normalized = str(component or "").strip().lower()
        if normalized == "python":
            update = self.state.python_update
            self.update_state(
                python_update=HomeUpdateState(
                    available=update.available,
                    installable=update.installable,
                    selected=bool(selected) and update.available,
                    latest_version=update.latest_version,
                )
            )
        elif normalized == "unity":
            update = self.state.unity_update
            self.update_state(
                unity_update=HomeUpdateState(
                    available=update.available,
                    installable=update.installable,
                    selected=bool(selected) and (update.available or update.installable),
                    latest_version=update.latest_version,
                )
            )
        self._refresh_computed_state()

    def _apply_update_info(
        self,
        py_info: dict[str, Any] | None,
        unity_info: dict[str, Any] | None,
    ) -> None:
        py_available = bool((py_info or {}).get("available")) and not self._pending_restart()
        unity_available = bool((unity_info or {}).get("available"))
        previous_py = self.state.python_update
        previous_unity = self.state.unity_update
        self.update_state(
            python_update=HomeUpdateState(
                available=py_available,
                selected=py_available and previous_py.available and previous_py.selected,
                latest_version=str((py_info or {}).get("latest_version") or ""),
            ),
            unity_update=HomeUpdateState(
                available=unity_available,
                installable=not self.state.unity_installed,
                selected=(unity_available or not self.state.unity_installed)
                and (previous_unity.available or previous_unity.installable)
                and previous_unity.selected,
                latest_version=str((unity_info or {}).get("latest_version") or ""),
            ),
            update_checking=False,
            error=None,
        )
        self._refresh_local_state()

    def _refresh_local_state(self, *, emit: bool = True) -> None:
        pending = self._pending_restart_version()
        backend_status = self._backend_status(pending)
        configured_unity = self._settings.get("UNITY_INSTALL_DIR") or None
        unity_installed = self._home.find_unity_executable(
            configured_unity
        ) is not None
        process = self._home.refresh_process_state(
            configured_unity
        )
        unity_status = self._unity_status(process.state)
        current_unity_update = self.state.unity_update
        unity_update = HomeUpdateState(
            available=current_unity_update.available,
            installable=not unity_installed,
            selected=current_unity_update.selected
            and (current_unity_update.available or not unity_installed),
            latest_version=current_unity_update.latest_version,
        )
        if emit:
            self.update_state(
                backend_status=backend_status,
                unity_status=unity_status,
                unity_installed=unity_installed,
                unity_process_state=process.state,
                unity_process_error=process.error,
                unity_update=unity_update,
                pending_restart_version=pending,
                revision=self.state.revision + 1,
            )
            self._refresh_computed_state()
            return
        self._state = HomeState(
            backend_status=backend_status,
            unity_status=unity_status,
            unity_installed=unity_installed,
            unity_process_state=process.state,
            unity_process_error=process.error,
            unity_update=unity_update,
            pending_restart_version=pending,
        )
        self._refresh_computed_state(emit=False)

    def _refresh_computed_state(self, *, emit: bool = True) -> None:
        action = self._primary_action()
        labels = {
            "busy": _("Выполняется операция…", "Operation in progress…"),
            "starting": _("Запуск Unity…", "Starting Unity…"),
            "stopping": _("Закрытие Unity…", "Closing Unity…"),
            "stop": _("Unity запущена — закрыть", "Unity is running — close"),
            "restart": _("Перезапустить", "Restart"),
            "apply": self._apply_action_label(),
            "play": _("Играть", "Play"),
            "unavailable": _("Для запуска нужна Unity", "Unity is required to play"),
        }
        icons = {
            "busy": "fa6s.spinner",
            "starting": "fa6s.spinner",
            "stopping": "fa6s.spinner",
            "stop": "fa6s.stop",
            "restart": "fa6s.rotate-right",
            "apply": "fa6s.download",
            "play": "fa6s.play",
            "unavailable": "mdi.unity",
        }
        icon = icons[action]
        if action == "apply" and not self._tester_code():
            icon = "fa6s.lock"
        changes = {
            "primary_action": action,
            "primary_label": labels[action],
            "primary_icon_name": icon,
        }
        if emit:
            self.update_state(**changes)
        else:
            from dataclasses import replace

            self._state = replace(self._state, **changes)

    def _primary_action(self) -> str:
        if self.state.operation is not None:
            return "busy"
        process_state = self.state.unity_process_state
        if process_state == "starting":
            return "starting"
        if process_state == "stopping":
            return "stopping"
        if process_state == "running":
            return "stop"
        if self._pending_restart():
            return "restart"
        if self._has_selected_update():
            return "apply"
        return "play" if self.state.unity_installed else "unavailable"

    def _selected_components(self) -> tuple[str, ...]:
        selected: list[str] = []
        if self.state.python_update.available and self.state.python_update.selected:
            selected.append("python")
        if (
            self.state.unity_update.available or self.state.unity_update.installable
        ) and self.state.unity_update.selected:
            selected.append("unity")
        return tuple(selected)

    def _apply_action_label(self) -> str:
        selected = self._selected_components()
        if len(selected) > 1:
            if not self.state.unity_installed and "unity" in selected:
                return _("Установить компоненты (2)", "Install components (2)")
            return _("Обновить компоненты (2)", "Update components (2)")
        if selected == ("python",):
            return _("Обновить Python", "Update Python")
        if selected == ("unity",):
            return (
                _("Обновить Unity", "Update Unity")
                if self.state.unity_installed
                else _("Установить Unity", "Install Unity")
            )
        return _("Выберите компоненты", "Select components")

    def _has_selected_update(self) -> bool:
        return bool(
            self.state.python_update.available
            and self.state.python_update.selected
            or (self.state.unity_update.available or self.state.unity_update.installable)
            and self.state.unity_update.selected
        )

    def _request_selective_update(self) -> None:
        if self.state.operation is not None:
            return
        if not self._has_selected_update():
            self._set_progress(
                _(
                    "Нечего обновлять: отметь Python или Unity.",
                    "Nothing selected: check Python or Unity.",
                ),
                0,
                100,
                busy=False,
            )
            self._schedule_hide_progress()
            return
        code = self._tester_code()
        if not code:
            self._pending_continuation = "apply-updates"
            self.emit_effect(HomePromptTesterCode("apply-updates"))
            return
        self._start_selective_update(code)

    def _resume_with_tester_code(self, continuation: str, code: str | None) -> None:
        normalized = str(code or "").strip()
        if str(continuation) != self._pending_continuation:
            return
        self._pending_continuation = None
        if not normalized:
            self._set_progress(
                _(
                    "Обновление отменено: код тестера не введён.",
                    "Update cancelled: tester code not entered.",
                ),
                0,
                100,
                busy=False,
            )
            self._schedule_hide_progress()
            return
        self._settings.set("TESTER_CODE", normalized)
        self._settings.save()
        self._refresh_computed_state()
        self._start_selective_update(normalized)

    def _start_selective_update(self, tester_code: str) -> None:
        if self.state.operation is not None:
            return
        update_python = bool(
            self.state.python_update.available and self.state.python_update.selected
        )
        update_unity = bool(
            (self.state.unity_update.available or self.state.unity_update.installable)
            and self.state.unity_update.selected
        )
        pending_python_version = self.state.python_update.latest_version
        components = tuple(
            component
            for component, selected in (("python", update_python), ("unity", update_unity))
            if selected
        )
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._operation_components = components
        self.update_state(
            operation="apply-updates",
            operation_component=components[0] if components else "",
            operation_item_index=1 if components else 0,
            operation_item_total=len(components),
            can_cancel=True,
            error=None,
        )
        self._set_progress(
            _("Подготовка к установке…", "Preparing installation…"),
            0,
            0,
            busy=True,
        )
        settings = self._settings.snapshot()
        progress_logger = _ProgressLogger(self, "home_update")

        def worker() -> dict[str, Any]:
            return dict(
                self._home.apply_updates(
                    update_python=update_python,
                    update_unity=update_unity,
                    channel=str(settings.get("UPDATE_CHANNEL") or "stable"),
                    tester_code=tester_code,
                    unity_dir=settings.get("UNITY_INSTALL_DIR") or None,
                    update_mode=str(settings.get("UPDATE_MODE") or "diff"),
                    preserve_prompts=bool(
                        settings.get("UPDATE_PRESERVE_PROMPTS", True)
                    ),
                    logger_adapter=progress_logger,
                    on_progress=self._download_progress(),
                    on_extract_progress=self._extract_progress,
                    on_verify_progress=self._verify_progress,
                    on_stage=self._operation_stage,
                    stop_event=cancel_event,
                )
                or {}
            )

        def completed(result: dict[str, Any]) -> None:
            python_applied = bool(result.get("python_applied"))
            python_pending_restart = bool(result.get("python_pending_restart"))
            if result.get("cancelled") or cancel_event.is_set():
                self._set_progress(
                    _("Установка отменена.", "Installation cancelled."),
                    0,
                    100,
                    busy=False,
                )
            elif not result.get("ok"):
                failed = [
                    (component, data)
                    for component, data in dict(result.get("results") or {}).items()
                    if not data.get("ok")
                ]
                details = "; ".join(
                    f"{component.title()}: {data.get('error') or data.get('status') or 'error'}"
                    for component, data in failed
                )
                self._set_progress(
                    _("Не удалось установить: {err}", "Installation failed: {err}").format(
                        err=details or _("неизвестная ошибка", "unknown error")
                    ),
                    0,
                    100,
                    busy=False,
                )
            elif python_pending_restart:
                self._set_progress(
                    _(
                        "Перезапустите приложение, чтобы завершить обновление Python.",
                        "Restart the application to finish the Python update.",
                    ),
                    100,
                    100,
                    busy=False,
                )
            else:
                self._set_progress(
                    _("Установка завершена.", "Installation finished."),
                    100,
                    100,
                    busy=False,
                )
            if python_applied and not cancel_event.is_set():
                self._mark_python_restart_required(pending_python_version)
            self._finish_operation(prompt_restart=python_applied and not cancel_event.is_set())

        self.run_exclusive(
            "home-apply-updates",
            worker,
            completed,
            self._finish_operation_error,
        )

    def _finish_operation(self, *, prompt_restart: bool = False) -> None:
        self._cancel_event = None
        self._operation_components = ()
        self.update_state(
            operation=None,
            operation_component="",
            operation_stage="",
            operation_item_index=0,
            operation_item_total=0,
            can_cancel=False,
        )
        self._refresh_local_state()
        self.refresh_updates(force=True)
        if prompt_restart:
            self.emit_effect(HomePromptRestart())
        else:
            self._schedule_hide_progress()

    def _finish_operation_error(self, error: Exception) -> None:
        self._cancel_event = None
        self._operation_components = ()
        self.update_state(
            operation=None,
            operation_component="",
            operation_stage="",
            operation_item_index=0,
            operation_item_total=0,
            can_cancel=False,
            error=str(error),
        )
        self._set_progress(
            _("Ошибка: {err}", "Error: {err}").format(err=error),
            0,
            0,
            busy=False,
        )
        self._refresh_local_state()
        self._schedule_hide_progress()

    def _cancel_current_operation(self) -> None:
        cancel = self._cancel_event
        if cancel is None or self.state.operation is None or not self.state.can_cancel:
            return
        cancel.set()
        self.update_state(can_cancel=False)
        self._set_progress(
            _("Отмена…", "Cancelling…"),
            0,
            0,
            busy=True,
        )

    def _stop_unity(self) -> None:
        try:
            if not self._home.stop_unity():
                self._refresh_local_state()
        except Exception as exc:
            self.emit_effect(
                HomeShowError(
                    _("Unity", "Unity"),
                    _(
                        "Не удалось закрыть Unity: {err}",
                        "Failed to close Unity: {err}",
                    ).format(err=exc),
                )
            )

    def _on_unity_process_state(self, snapshot) -> None:
        if self.is_closed:
            return
        process_state = str(getattr(snapshot, "state", "stopped") or "stopped")
        self.update_state(
            unity_status=self._unity_status(process_state),
            unity_process_state=process_state,
            unity_process_error=str(getattr(snapshot, "error", "") or ""),
        )
        self._refresh_computed_state()
        if getattr(snapshot, "state", "") == "failed":
            self._set_progress(
                _("Ошибка запуска Unity: {err}", "Unity launch error: {err}").format(
                    err=getattr(snapshot, "error", "") or _("неизвестная ошибка", "unknown error")
                ),
                0,
                100,
                busy=False,
            )
            self._schedule_hide_progress()

    def _open_unity_folder(self) -> None:
        try:
            self._home.open_unity_folder(
                self._settings.get("UNITY_INSTALL_DIR") or None
            )
        except Exception as exc:
            self.emit_effect(
                HomeShowError(
                    _("Unity", "Unity"),
                    _(
                        "Не удалось открыть папку Unity: {err}",
                        "Failed to open Unity folder: {err}",
                    ).format(err=exc),
                )
            )

    def _handle_restart_decision(self, accepted: bool) -> None:
        if not accepted:
            self._schedule_hide_progress()
            return
        try:
            self._home.restart_application()
        except Exception as exc:
            self.emit_effect(
                HomeShowError(
                    _("Перезапуск", "Restart"),
                    _(
                        "Не удалось перезапустить приложение: {err}",
                        "Failed to restart the application: {err}",
                    ).format(err=exc),
                )
            )

    def _on_news_ready(self, _releases: list[dict[str, Any]]) -> None:
        try:
            items = self._news.build_items(limit=3)
            news = tuple(
                HomeNewsItemState(
                    title=str(item.title),
                    summary=str(item.summary),
                    item_id=str(item.item_id or ""),
                    timestamp=str(item.timestamp or ""),
                    full_text=str(item.full_text or ""),
                )
                for item in items
            )
        except Exception as exc:
            logger.debug("Failed to build home news items: %s", exc)
            news = ()
        self._post_ui(
            lambda news=news: self.update_state(
                news=news,
                revision=self.state.revision + 1,
            )
        )

    def _download_progress(self):
        last_time = time.monotonic()
        last_bytes = 0
        smoothed_speed = 0.0

        def callback(downloaded: int, total: int) -> None:
            nonlocal last_time, last_bytes, smoothed_speed
            now = time.monotonic()
            if downloaded < last_bytes:
                last_time = now
                last_bytes = 0
                smoothed_speed = 0.0
            elapsed = max(0.001, now - last_time)
            delta = max(0, downloaded - last_bytes)
            if delta > 0:
                instant_speed = delta / elapsed
                smoothed_speed = instant_speed if smoothed_speed <= 0 else smoothed_speed * 0.72 + instant_speed * 0.28
                last_time = now
                last_bytes = downloaded
            state = self.state
            item_suffix = (
                f" ({state.operation_item_index}/{state.operation_item_total})"
                if state.operation_item_total > 1 and state.operation_item_index > 0
                else ""
            )
            speed_text = self._format_transfer_speed(smoothed_speed)
            if total > 0:
                pct = int(max(0, min(100, downloaded * 100 / total)))
                eta_text = ""
                if smoothed_speed > 0 and total > downloaded:
                    eta_seconds = int((total - downloaded) / smoothed_speed)
                    eta_text = _(" · ~{seconds} с", " · ~{seconds}s").format(seconds=max(1, eta_seconds))
                text = _(
                    "Загрузка{item} · {pct}%{speed}{eta}",
                    "Downloading{item} · {pct}%{speed}{eta}",
                ).format(
                    item=item_suffix,
                    pct=pct,
                    speed=f" · {speed_text}" if speed_text else "",
                    eta=eta_text,
                )
                self.post_progress(text, pct, 100, busy=False)
            else:
                done_mb = downloaded / (1024 * 1024)
                text = _(
                    "Загрузка{item} · {done:.1f} MB{speed}",
                    "Downloading{item} · {done:.1f} MB{speed}",
                ).format(
                    item=item_suffix,
                    done=done_mb,
                    speed=f" · {speed_text}" if speed_text else "",
                )
                self.post_progress(text, 0, 0, busy=True)

        return callback

    @staticmethod
    def _format_transfer_speed(bytes_per_second: float) -> str:
        if bytes_per_second <= 0:
            return ""
        value = float(bytes_per_second)
        units = ("B/s", "KB/s", "MB/s", "GB/s")
        for unit in units:
            if value < 1024.0 or unit == units[-1]:
                return f"{value:.1f} {unit}" if unit != "B/s" else f"{int(value)} {unit}"
            value /= 1024.0
        return ""

    def _operation_stage(
        self,
        component: str,
        stage: str,
        stage_index: int,
        stage_total: int,
        can_cancel: bool,
    ) -> None:
        normalized = str(component or "").lower()
        try:
            item_index = self._operation_components.index(normalized) + 1
        except ValueError:
            item_index = 1
        item_total = max(1, len(self._operation_components))
        stage_labels = {
            "Downloading": _("Загрузка", "Downloading"),
            "Extracting": _("Распаковка", "Extracting"),
            "Verifying staged files": _("Проверка файлов", "Verifying files"),
            "Applying update": _("Применение обновления", "Applying update"),
            "Recovering installation": _("Восстановление установки", "Recovering installation"),
            "Completed": _("Установка завершена", "Installation completed"),
        }
        label = stage_labels.get(stage, str(stage))
        if item_total > 1:
            label = f"{label} ({item_index}/{item_total})"

        def apply() -> None:
            self.update_state(
                operation_component=normalized,
                operation_stage=str(stage),
                operation_item_index=item_index,
                operation_item_total=item_total,
                can_cancel=bool(can_cancel),
            )
            self._set_progress(label, 0, 0, busy=True)

        self._post_ui(apply)

    def _extract_progress(self, extracted: int, total: int) -> None:
        suffix = (
            f" ({self.state.operation_item_index}/{self.state.operation_item_total})"
            if self.state.operation_item_total > 1
            else ""
        )
        text = _("Распаковка", "Extracting") + suffix
        if total > 0:
            pct = int(max(0, min(100, extracted * 100 / total)))
            self.post_progress(f"{text} · {pct}%", pct, 100, busy=False)
        else:
            self.post_progress(text, 0, 0, busy=True)

    def _verify_progress(self, processed: int, total: int) -> None:
        suffix = (
            f" ({self.state.operation_item_index}/{self.state.operation_item_total})"
            if self.state.operation_item_total > 1
            else ""
        )
        text = _("Проверка файлов", "Verifying files") + suffix
        if total > 0:
            pct = int(max(0, min(100, processed * 100 / total)))
            self.post_progress(f"{text} · {pct}%", pct, 100, busy=False)
        else:
            self.post_progress(text, 0, 0, busy=True)

    def _set_progress(
        self,
        text: str,
        value: int,
        maximum: int,
        *,
        busy: bool,
    ) -> None:
        self.update_state(
            progress_visible=bool(text),
            progress_text=str(text or ""),
            progress_value=int(value),
            progress_maximum=max(0, int(maximum)),
            progress_busy=bool(busy),
        )

    def _schedule_hide_progress(self, delay_ms: int = 4000) -> None:
        QTimer.singleShot(max(0, int(delay_ms)), self._hide_progress_if_idle)

    def _hide_progress_if_idle(self) -> None:
        if not self.is_closed and self.state.operation is None:
            self.update_state(
                progress_visible=False,
                progress_text="",
                progress_value=0,
                progress_maximum=100,
                progress_busy=False,
            )

    def _backend_status(self, pending_version: str) -> str:
        if pending_version:
            return _(
                "Установлен v{ver} • нужен перезапуск",
                "Installed v{ver} • restart required",
            ).format(ver=_strip_v(pending_version))
        try:
            from _version import __version__ as version

            return _("Установлен v{ver}", "Installed v{ver}").format(
                ver=_strip_v(str(version))
            )
        except Exception:
            return _("Установлен", "Installed")

    def _unity_status(self, process_state: str = "stopped") -> str:
        configured = self._settings.get("UNITY_INSTALL_DIR") or None
        executable = self._home.find_unity_executable(configured)
        if executable is None:
            return _("Не установлен", "Not installed")
        version = ""
        try:
            version_file = Path(self._home.unity_install_dir(configured)) / "_version.txt"
            if version_file.exists():
                version = version_file.read_text(encoding="utf-8").strip()
        except Exception:
            logger.debug("Failed to read Unity version", exc_info=True)
        state_labels = {
            "starting": _("Запускается", "Starting"),
            "running": _("Запущена", "Running"),
            "stopping": _("Закрывается", "Closing"),
        }
        if process_state in state_labels:
            label = state_labels[process_state]
            return f"{label} • v{_strip_v(version)}" if version else label
        if version:
            return _("Установлен v{ver}", "Installed v{ver}").format(
                ver=_strip_v(version)
            )
        return _("Установлен", "Installed")

    def _tester_code(self) -> str:
        return str(self._settings.get("TESTER_CODE", "") or "").strip()

    def _pending_restart(self) -> bool:
        return bool(self._pending_restart_version())

    def _pending_restart_version(self) -> str:
        return self._app.pending_restart_version

    def _mark_python_restart_required(self, version: str | None) -> None:
        normalized = str(version or "").strip()
        self._app.set_pending_restart_version(normalized)
        self.update_state(
            pending_restart_version=normalized,
            python_update=HomeUpdateState(),
        )
        self.emit_effect(HomeRefreshSidebar())
        self._refresh_local_state()

    def _on_install_started(self, event) -> None:
        if self.state.operation is not None:
            return
        data = event.data if isinstance(getattr(event, "data", None), dict) else {}
        title = str(data.get("title") or data.get("name") or _("Установка", "Installation"))
        self.post_progress(title, 0, 100, busy=True)

    def _on_install_progress(self, event) -> None:
        if self.state.operation is not None:
            return
        data = event.data if isinstance(getattr(event, "data", None), dict) else {}
        title = str(data.get("title") or data.get("name") or "")
        downloaded = float(data.get("downloaded") or data.get("current") or 0)
        total = float(data.get("total") or 0)
        message = str(data.get("message") or "")
        if total > 0:
            pct = int(max(0, min(100, downloaded / total * 100)))
            label = title or message or _("Загрузка…", "Downloading…")
            self.post_progress(f"{label} — {pct}%", pct, 100, busy=False)
        else:
            self.post_progress(
                title or message or _("Загрузка…", "Downloading…"),
                0,
                0,
                busy=True,
            )

    def _on_install_finished(self, _event) -> None:
        self._post_ui(self._handle_external_install_finished)

    def _handle_external_install_finished(self) -> None:
        if self.state.operation is None:
            self._hide_progress_if_idle()
        self._refresh_local_state()

    def _on_install_failed(self, event) -> None:
        if self.state.operation is not None:
            return
        data = event.data if isinstance(getattr(event, "data", None), dict) else {}
        message = str(data.get("error") or data.get("message") or _("ошибка", "error"))
        self._post_ui(
            lambda: self._set_progress(
                _("Ошибка: {err}", "Error: {err}").format(err=message),
                0,
                0,
                busy=False,
            )
        )
