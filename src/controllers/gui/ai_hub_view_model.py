from __future__ import annotations

import datetime as dt
import time
from typing import Any

from PyQt6.QtCore import QTimer

from controllers.gui.intent_view_model import IntentViewModel
from ui.mvvm import immutable_payload, mutable_payload
from controllers.gui.presentation_contracts import UiTopic
from ui.windows.ai_hub.constants import CATEGORY_ORDER, ROW_CATEGORY_MAP
from ui.windows.ai_hub.helpers import meta_from_row
from ui.windows.ai_hub.presentation import (
    AIHubShowError,
    AIHubState,
    ActivateAIHub,
    CancelQueuedInstall,
    CancelRunningInstall,
    ClearInstallCache,
    ComponentActionContext,
    ComponentAdmissionFailed,
    ConfirmBackendInstall,
    PrepareComponentInstall,
    RefreshAIHub,
    RequestComponentAction,
    SubmitComponentAction,
)
from utils import getTranslationVariant as _
from main_logger import logger

# Проверка статусов идёт вне Qt и может трогать сторонние пакеты или сеть.
# Зависший worker не должен бесконечно держать кнопки установки заблокированными.
STATUS_REFRESH_TIMEOUT_MS = 20_000


class AIHubViewModel(IntentViewModel[AIHubState]):
    _VALID_ACTIONS = frozenset({"install", "uninstall", "initialize"})

    def __init__(self, presentation, parent=None) -> None:
        super().__init__(
            AIHubState(
                queue_state=immutable_payload({"running": None, "pending": []})
            ),
            parent,
        )
        self._presentation = presentation
        self._catalog = presentation.installables
        self._install_ui_generation = 0
        self._refresh_timeout_generation = 0
        for topic, callback in (
            (UiTopic.INSTALL_TASK_STARTED, self._on_install_started),
            (UiTopic.INSTALL_TASK_PROGRESS, self._on_install_progress),
            (UiTopic.INSTALL_TASK_FINISHED, self._on_install_finished),
            (UiTopic.INSTALL_CATALOG_CHANGED, self._on_catalog_changed),
            (UiTopic.INSTALL_TASK_FAILED, self._on_install_failed),
            (UiTopic.INSTALL_QUEUE_CHANGED, self._on_queue_changed),
        ):
            self.track_subscription(
                presentation.events.subscribe(topic, callback, weak=False)
            )

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, ActivateAIHub):
            self.activate()
            return
        if isinstance(intent, RefreshAIHub):
            self.refresh(
                force=bool(intent.force),
                include_status=intent.include_status,
                status_category=intent.status_category,
            )
            return
        if isinstance(intent, ClearInstallCache):
            self.clear_cache()
            return
        if isinstance(intent, RequestComponentAction):
            self.request_component_action(
                intent.component_id,
                intent.action,
                clean=bool(intent.clean),
            )
            return
        if isinstance(intent, SubmitComponentAction):
            self.submit_component_action(intent)
            return
        if isinstance(intent, CancelQueuedInstall):
            self._catalog.cancel_queued(str(intent.task_id))
            return
        if isinstance(intent, CancelRunningInstall):
            self._catalog.cancel_running(str(intent.task_id))

    def activate(self) -> None:
        if self._presentation.app.backend_ready:
            try:
                self._presentation.app.ensure_optional_gui("install")
            except Exception:
                pass
        if not self.state.loaded_once and not self.state.refreshing:
            self.refresh(force=False)

    def refresh(
        self,
        *,
        force: bool = False,
        include_status: bool | None = None,
        status_category: str | None = None,
    ) -> None:
        if include_status is None:
            include_status = bool(force or self.state.loaded_once)
        self.update_state(refreshing=True, error=None)
        self._refresh_timeout_generation += 1
        generation = self._refresh_timeout_generation
        QTimer.singleShot(
            STATUS_REFRESH_TIMEOUT_MS,
            lambda: self._on_refresh_timeout(generation),
        )

        def worker() -> dict[str, Any]:
            rows = self._catalog.list_rows(
                include_status=bool(include_status),
                refresh=bool(force),
                status_category=status_category,
            )
            return {
                "rows": list(rows or []),
                "hardware": dict(self._catalog.hardware_snapshot() or {}),
                "checked_at": dt.datetime.now(),
                "included_status": bool(include_status),
            }

        self.run_coalesced(
            "ai-hub-refresh",
            worker,
            self._apply_refresh,
            self._apply_refresh_error,
        )

    def clear_cache(self) -> None:
        if "ai-hub-cache-clear" in self._inflight:
            return
        clearing = _("Очистка кэша...", "Clearing cache...")
        self.update_state(task_status=clearing, error=None)

        def applied(ok: bool) -> None:
            message = (
                _("Кэш очищен", "Cache cleared")
                if ok
                else _("Не удалось очистить кэш", "Failed to clear cache")
            )
            self.update_state(task_status=message)
            QTimer.singleShot(2500, lambda: self._clear_task_status_if(message))

        self.run_exclusive(
            "ai-hub-cache-clear",
            lambda: bool(self._catalog.purge_cache()),
            applied,
            lambda error: self._operation_error(
                _("Очистка кэша", "Clear cache"), error
            ),
        )

    def request_component_action(
        self,
        component_id: str,
        action: str,
        *,
        clean: bool = False,
    ) -> None:
        component_id = str(component_id or "").strip()
        action = str(action or "install").strip().lower()
        if not component_id or action not in self._VALID_ACTIONS:
            return
        task_id = self._task_id_for(component_id, action)
        if self._is_task_active(task_id):
            self.update_state(task_status=_("Уже в очереди", "Already queued"))
            return
        # Занятость очереди больше не блокирует запрос: другой компонент
        # встаёт в FIFO-очередь бэкенда (дедуп по task_id — выше, дубль
        # быстрых кликов по тому же компоненту ловит `_inflight`).

        operation_name = f"ai-hub-action:{component_id}:{action}"
        if operation_name in self._inflight:
            self.update_state(
                task_status=_(
                    "Backend уже подготавливается…",
                    "Backend is already preparing…",
                )
            )
            return

        self.update_state(
            task_status=_("Backend запускается…", "Backend is starting…"),
            error=None,
        )

        def worker() -> ComponentActionContext:
            self._wait_for_backend()
            future = self._presentation.app.ensure_feature_async("installables")
            future.result(timeout=60)
            preview: dict[str, Any] = {}
            extra: dict[str, Any] = {"clean": True} if clean else {}
            if action == "install":
                preview = dict(self._catalog.install_preview(component_id) or {})
                extra["install_preview"] = preview
                backend_title = str(preview.get("backend_title") or "")
                if preview.get("backend_will_install") and backend_title:
                    extra["initial_status"] = _(
                        "План: {backend} → модель",
                        "Plan: {backend} → model",
                    ).format(backend=backend_title)
            return ComponentActionContext(
                component_id=component_id,
                action=action,
                extra=immutable_payload(extra),
                preview=immutable_payload(preview),
            )

        def prepared(context: ComponentActionContext) -> None:
            try:
                self._presentation.app.ensure_optional_gui("install")
            except Exception as exc:
                self._operation_error(
                    _("Backend установки", "Install backend"), exc
                )
                return
            self.update_state(task_status="")
            preview = mutable_payload(context.preview) or {}
            if preview.get("backend_will_install"):
                self.emit_effect(ConfirmBackendInstall(context))
            else:
                self.emit_effect(PrepareComponentInstall(context))

        self.run_exclusive(
            operation_name,
            worker,
            prepared,
            lambda error: self._operation_error(
                _("Backend установки", "Install backend"), error
            ),
        )

    def submit_component_action(self, intent: SubmitComponentAction) -> None:
        context = intent.context
        component_id = str(context.component_id or "").strip()
        action = str(context.action or "install").strip().lower()
        if not component_id or action not in self._VALID_ACTIONS:
            return
        task_id = self._task_id_for(component_id, action)
        if self._is_task_active(task_id):
            self.update_state(task_status=_("Уже в очереди", "Already queued"))
            return

        extra = dict(mutable_payload(context.extra) or {})
        payload = {
            "component_id": component_id,
            "task_id": task_id,
            "with_ui": True,
            "meta": {"source": "ai_hub"},
            "install_window": intent.install_window,
            "install_callbacks": intent.callbacks,
            "initial_status": str(
                extra.get("initial_status")
                or _("Подготовка...", "Preparing...")
            ),
        }
        payload.update(extra)
        try:
            admission = self._catalog.admit(action, payload)
        except Exception as exc:
            self._admission_failed(task_id, intent.install_window, str(exc))
            return
        if not admission.accepted:
            self._admission_failed(
                task_id,
                intent.install_window,
                admission.error
                or _(
                    "Очередь установки недоступна. Перезапустите приложение.",
                    "The installation queue is unavailable. Restart the application.",
                ),
            )
            return
        self.update_state(
            task_status=(
                _("Уже в очереди", "Already queued")
                if admission.duplicate
                else _("В очереди", "Queued")
            )
        )

    def _apply_refresh(self, payload: dict[str, Any]) -> None:
        rows = [dict(item) for item in (payload.get("rows") or ())]
        previous_rows = [
            dict(mutable_payload(item) or {}) for item in self.state.rows
        ]
        if not rows and previous_rows:
            rows = previous_rows
        included_status = bool(payload.get("included_status"))
        self.update_state(
            rows=tuple(immutable_payload(item) for item in rows),
            hardware=immutable_payload(payload.get("hardware") or {}),
            loaded_once=True,
            refreshing=False,
            last_check_ts=payload.get("checked_at"),
            checking_component_ids=frozenset(),
            error=None,
            revision=self.state.revision + 1,
        )
        if rows and not included_status:
            self.refresh(force=False, include_status=True)

    def _apply_refresh_error(self, error: Exception) -> None:
        self.update_state(refreshing=False, error=str(error))

    def _on_refresh_timeout(self, generation: int) -> None:
        """Разблокировать UI, если проверка статусов не уложилась в бюджет."""
        if generation != self._refresh_timeout_generation or not self.state.refreshing:
            return
        logger.warning(
            "AI Hub status refresh timed out after %d ms", STATUS_REFRESH_TIMEOUT_MS
        )
        self.update_state(
            refreshing=False,
            checking_component_ids=frozenset(),
            task_status=_(
                "Проверка файлов не завершилась. Новая проверка будет доступна после завершения текущей. Если состояние не изменится, перезапустите приложение.",
                "The file check did not finish. A new check will be available after the current one ends. If the state does not change, restart the application.",
            ),
        )

    def _on_install_started(self, event) -> None:
        if not self._is_installable_task(event):
            return
        self._install_ui_generation += 1
        data = self._event_data(event)
        status = str(data.get("status") or _("Подготовка...", "Preparing..."))
        component_id = self._event_component_id(event)
        title = self._component_title(component_id, data)
        self._post_ui(
            lambda: self.update_state(
                task_status=status,
                install_bar_visible=True,
                install_logs_visible=True,
                install_title=title,
                install_progress=None,
                install_detail=status,
            )
        )

    def _on_install_progress(self, event) -> None:
        if not self._is_installable_task(event):
            return
        self._install_ui_generation += 1
        data = self._event_data(event)
        status = str(data.get("status") or "").strip()
        if not status:
            return
        progress = data.get("progress")
        try:
            normalized_progress = int(progress) if progress is not None else None
        except (TypeError, ValueError):
            normalized_progress = None
        text = (
            f"{status} ({normalized_progress}%)"
            if normalized_progress is not None and "%" not in status
            else status
        )
        detail = status.split("—", 1)[1].strip() if "—" in status else status
        self._post_ui(
            lambda: self.update_state(
                task_status=text,
                install_bar_visible=True,
                install_progress=normalized_progress,
                install_detail=detail,
            )
        )

    def _on_install_finished(self, event) -> None:
        if not self._is_installable_task(event):
            return
        self._install_ui_generation += 1
        generation = self._install_ui_generation
        component_id = self._event_component_id(event)

        def apply() -> None:
            checking = set(self.state.checking_component_ids)
            if component_id:
                checking.add(component_id)
            done = _("Готово", "Done")
            self.update_state(
                task_status="",
                checking_component_ids=frozenset(checking),
                install_bar_visible=True,
                install_logs_visible=False,
                install_progress=100,
                install_detail=done,
            )
            self.refresh(force=True)
            QTimer.singleShot(
                900,
                lambda generation=generation: self._hide_install_bar(generation),
            )

        self._post_ui(apply)

    def _on_catalog_changed(self, _event) -> None:
        self._post_ui(lambda: self.refresh(force=True))

    def _on_install_failed(self, event) -> None:
        if not self._is_installable_task(event):
            return
        self._install_ui_generation += 1
        data = self._event_data(event)
        message = str(data.get("error") or _("Ошибка установки", "Install failed"))

        def apply() -> None:
            self.update_state(
                task_status=message,
                install_bar_visible=False,
                install_logs_visible=False,
                error=message,
            )
            self.refresh(force=True)

        self._post_ui(apply)

    def _on_queue_changed(self, event) -> None:
        data = self._event_data(event)
        queue_state = immutable_payload(
            {
                "running": data.get("running"),
                "pending": list(data.get("pending") or []),
            }
        )
        self._post_ui(lambda: self.update_state(queue_state=queue_state))

    def _wait_for_backend(self) -> None:
        deadline = time.monotonic() + 15.0
        while not self._presentation.app.backend_ready:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    self._presentation.app.startup_error
                    or _("Backend не запустился", "Backend failed to start")
                )
            time.sleep(0.15)

    @staticmethod
    def _task_id_for(component_id: str, action: str) -> str:
        operation = "uninstall" if action == "uninstall" else "install"
        return f"{component_id}:{operation}"

    def _is_task_active(self, task_id: str) -> bool:
        queue = mutable_payload(self.state.queue_state) or {}
        running = queue.get("running") or {}
        if str(running.get("task_id") or "") == task_id:
            return True
        return any(
            str((item or {}).get("task_id") or "") == task_id
            for item in queue.get("pending") or []
        )

    def _admission_failed(self, task_id: str, install_window: Any, message: str) -> None:
        self.update_state(task_status=str(message), error=str(message))
        self.emit_effect(
            ComponentAdmissionFailed(
                task_id=str(task_id),
                message=str(message),
                install_window=install_window,
            )
        )

    def _operation_error(self, title: str, error: Exception) -> None:
        message = str(error)
        self.update_state(task_status=message, error=message)
        self.emit_effect(AIHubShowError(str(title), message))

    def _clear_task_status_if(self, expected: str) -> None:
        if not self.is_closed and self.state.task_status == expected:
            self.update_state(task_status="")

    def _hide_install_bar(self, generation: int) -> None:
        if (
            not self.is_closed
            and self._install_ui_generation == generation
        ):
            self.update_state(install_bar_visible=False)

    def _component_title(self, component_id: str, data: dict[str, Any]) -> str:
        queue = mutable_payload(self.state.queue_state) or {}
        running = queue.get("running") if isinstance(queue, dict) else None
        title = str((running or {}).get("title") or "").strip()
        if title:
            return title
        for frozen_row in self.state.rows:
            row = dict(mutable_payload(frozen_row) or {})
            meta = meta_from_row(row)
            if str(meta.get("id") or "") == component_id:
                return str(meta.get("title") or component_id)
        return component_id or _("Установка", "Install")

    @staticmethod
    def _event_data(event) -> dict[str, Any]:
        data = getattr(event, "data", None)
        return dict(data) if isinstance(data, dict) else {}

    @classmethod
    def _event_component_id(cls, event) -> str:
        data = cls._event_data(event)
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        return str(meta.get("component_id") or data.get("component_id") or "").strip()

    @classmethod
    def _is_installable_task(cls, event) -> bool:
        data = cls._event_data(event)
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        category = str(meta.get("category") or "").strip().lower()
        if category in CATEGORY_ORDER or category in ROW_CATEGORY_MAP:
            return True
        return ":" in cls._event_component_id(event)
