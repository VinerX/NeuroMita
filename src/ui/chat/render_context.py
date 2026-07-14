from __future__ import annotations

from typing import Any, Callable


class ChatRenderContext:
    """Narrow mutable UI context owned by the chat renderer.

    The renderer receives only its visual surface, settings query and typed
    message actions instead of the whole application window.
    """

    def __init__(
        self,
        *,
        settings_getter: Callable[[str, Any], Any],
        character_name_getter: Callable[[], str],
        chat_message_actions: Any,
        chat_delegate: Any,
    ) -> None:
        self._settings_getter = settings_getter
        self._character_name_getter = character_name_getter
        self.chat_message_actions = chat_message_actions
        self.chat_delegate = chat_delegate
        self.chat_window = None
        self._chat_font_size = None
        self._think_block_widgets: dict[int, Any] = {}
        self._think_block_counter = 0
        self._stream_render_states: dict[str, dict[str, Any]] = {}

    def bind_chat_window(self, chat_window: Any) -> None:
        self.chat_window = chat_window

    def set_font_size(self, font_size: int) -> None:
        self._chat_font_size = int(font_size)

    def _get_setting(self, key: str, default: Any = None) -> Any:
        return self._settings_getter(str(key), default)

    def _get_character_name(self) -> str:
        return str(self._character_name_getter() or "Assistant")