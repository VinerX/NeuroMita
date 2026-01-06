from .registry import ActionRegistry
from .actions.create_task import CreateTaskAction
from .actions.get_task_status import GetTaskStatusAction
from .actions.get_settings import GetSettingsAction


def build_action_registry() -> ActionRegistry:
    reg = ActionRegistry()
    reg.register("create_task", CreateTaskAction())
    reg.register("get_task_status", GetTaskStatusAction())
    reg.register("get_settings", GetSettingsAction())
    return reg