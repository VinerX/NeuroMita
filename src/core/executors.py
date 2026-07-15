"""Public facade for the application executor registry."""

from core.executor_registry import (
    ExecutorRegistry,
    PoolSaturated,
    Pools,
    executors,
)
from core.task_supervisor import task_supervisor as _task_supervisor

# Importing the public facade must preserve the old lifecycle guarantee: daemon
# pools created through ``executors()`` are registered in the task supervisor.
_task_supervisor()

__all__ = ["ExecutorRegistry", "PoolSaturated", "Pools", "executors"]
