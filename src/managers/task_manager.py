import uuid
import time
from enum import Enum
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from threading import Lock
from main_logger import logger


class TaskStatus(Enum):
    PENDING = "PENDING"
    VOICING = "VOICING"
    SUCCESS = "SUCCESS"
    FAILED_ON_GENERATION = "FAILED_ON_GENERATION"
    FAILED_ON_VOICEOVER = "FAILED_ON_VOICEOVER"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


@dataclass
class Task:
    uid: str
    status: TaskStatus
    type: str
    data: Dict[str, Any]
    created_at: float
    updated_at: float
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "status": self.status.value,
            "type": self.type,
            "data": self.data,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error
        }


class TaskManager:
    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._lock = Lock()
        self._cleanup_interval = 3600
        self._last_cleanup = time.time()
        
    def create_task(self, task_type: str, data: Dict[str, Any]) -> Task:
        with self._lock:
            uid = str(uuid.uuid4())
            current_time = time.time()
            
            task = Task(
                uid=uid,
                status=TaskStatus.PENDING,
                type=task_type,
                data=data,
                created_at=current_time,
                updated_at=current_time
            )
            
            self._tasks[uid] = task
            logger.info(f"Created task {uid} of type {task_type}")
            
            self._cleanup_if_needed()
            
            return task
    
    def update_task_status(
        self,
        uid: str,
        status: TaskStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> Optional[Task]:
        with self._lock:
            if uid not in self._tasks:
                logger.error(f"Task {uid} not found")
                return None

            task = self._tasks[uid]
            task.status = status
            task.updated_at = time.time()

            if result is not None:
                if isinstance(result, dict):
                    if task.result is None or not isinstance(task.result, dict):
                        task.result = {}
                    task.result.update(result)
                else:
                    task.result = result

            if error is not None:
                task.error = error

            logger.info(f"Updated task {uid} status to {status.value}")
            return task

    def get_task(self, uid: str) -> Optional[Task]:
        with self._lock:
            return self._tasks.get(uid)
    
    def delete_task(self, uid: str) -> bool:
        with self._lock:
            if uid in self._tasks:
                del self._tasks[uid]
                logger.info(f"Deleted task {uid}")
                return True
            return False
    
    def _cleanup_if_needed(self):
        current_time = time.time()
        if current_time - self._last_cleanup > self._cleanup_interval:
            self._cleanup_old_tasks()
            self._last_cleanup = current_time
    
    def _cleanup_old_tasks(self):
        current_time = time.time()
        max_age = 86400
        
        tasks_to_delete = []
        for uid, task in self._tasks.items():
            if current_time - task.created_at > max_age:
                tasks_to_delete.append(uid)
        
        for uid in tasks_to_delete:
            del self._tasks[uid]
            
        if tasks_to_delete:
            logger.info(f"Cleaned up {len(tasks_to_delete)} old tasks")
    
    def clear_all_tasks(self):
        with self._lock:
            self._tasks.clear()
            logger.info("Cleared all tasks")


_global_task_manager = None


def get_task_manager() -> TaskManager:
    global _global_task_manager
    if _global_task_manager is None:
        _global_task_manager = TaskManager()
    return _global_task_manager