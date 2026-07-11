from typing import Optional, Dict, Any
from main_logger import logger
from core.events import get_event_bus, Events, Event
from managers.task_manager import get_task_manager, TaskStatus, Task
from services.contracts import TaskService


class TaskController(TaskService):
    def __init__(self):
        self.event_bus = get_event_bus()
        self.task_manager = get_task_manager()
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Task.CREATE_TASK, self._on_create_task, weak=False)
        self.event_bus.subscribe(Events.Task.UPDATE_TASK_STATUS, self._on_update_task_status, weak=False)
        self.event_bus.subscribe(Events.Task.NOTIFY_TASK_UPDATE, self._on_notify_task_update, weak=False)

    # ── TaskService (прямой вызов из asyncio-loop сервера) ──────────────────
    def create_task(self, task_type: str, data: Dict[str, Any]) -> Task:
        task = self.task_manager.create_task(task_type, data)
        # Уведомляем сервер о создании задачи
        self.event_bus.emit(Events.Task.TASK_CREATED, {'task': task.snapshot()})
        return task

    def get_task(self, uid: str) -> Optional[Task]:
        return self.task_manager.get_task(uid) if uid else None

    def update_task_status(self, uid: str, status: Any, result: Any = None, error: Any = None) -> Optional[Task]:
        if not uid or not status:
            logger.error("Missing uid or status in update_task_status")
            return None
        task = self.task_manager.update_task_status(uid, status, result, error)
        if task:
            # Уведомляем о изменении статуса
            self.event_bus.emit(Events.Task.TASK_STATUS_CHANGED, {'task': task.snapshot()})
        return task

    # ── Bus-подписчики (тонкие делегаты) ────────────────────────────────────
    def _on_create_task(self, event: Event) -> Task:
        return self.create_task(event.data.get('type', 'chat'), event.data.get('data', {}))

    def _on_update_task_status(self, event: Event) -> Optional[Task]:
        return self.update_task_status(
            event.data.get('uid'),
            event.data.get('status'),
            event.data.get('result'),
            event.data.get('error'),
        )

    def _on_get_task(self, event: Event) -> Optional[Task]:
        return self.get_task(event.data.get('uid'))
        
    def _on_notify_task_update(self, event: Event):
        task = event.data.get('task')
        if task:
            # Уведомляем сервер об обновлении задачи для отправки клиенту
            self.event_bus.emit(Events.Server.SEND_TASK_UPDATE, {'task': task})