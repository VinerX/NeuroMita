from .registry import ActionRegistry
from .actions.create_task import CreateTaskAction
from .actions.get_task_status import GetTaskStatusAction
from .actions.get_settings import GetSettingsAction
from .actions.get_music_beats import GetMusicBeatsAction
from .actions.speech_state import SpeechStateAction
from .actions.hello import HelloAction


def build_action_registry() -> ActionRegistry:
    reg = ActionRegistry()
    reg.register("create_task", CreateTaskAction())
    reg.register("get_task_status", GetTaskStatusAction())
    reg.register("get_settings", GetSettingsAction())
    reg.register("get_music_beats", GetMusicBeatsAction())
    reg.register("speech_state", SpeechStateAction())
    reg.register("hello", HelloAction())
    return reg
