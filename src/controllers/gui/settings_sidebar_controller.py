from core.events import Events, Event
from .base_controller import BaseController


class SettingsSidebarController(BaseController):
    def __init__(self, main_controller, view):
        self._indicator_states: dict[str, tuple[object, object]] = {}
        super().__init__(main_controller, view)

    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.GUI.SET_SETTINGS_ICON_INDICATOR, self._on_set_icon_indicator, weak=False)
        self.event_bus.subscribe(Events.GUI.PRELOAD_SETTINGS_SECTIONS, self._on_preload_sections, weak=False)

    def _on_set_icon_indicator(self, event: Event):
        data = event.data or {}
        category = str(data.get("category") or "").strip()
        state = data.get("state", None)
        tooltip = data.get("tooltip", None)

        if category:
            self._indicator_states[category] = (state, tooltip)

        if not self.view or not category:
            return

        self._ui(lambda: self._apply_indicator(category, state, tooltip))

    def _apply_indicator(self, category: str, state, tooltip) -> None:
        button = getattr(self.view, "settings_buttons", {}).get(category)
        if button and hasattr(button, "set_indicator_state"):
            button.set_indicator_state(state, tooltip_text=tooltip)

    def _on_preload_sections(self, event: Event):
        payload = event.data if isinstance(event.data, dict) else {}
        sections = tuple(payload.get("sections") or ())

        def replay() -> None:
            for category, (state, tooltip) in self._indicator_states.items():
                self._apply_indicator(category, state, tooltip)

        self._ui(replay)

        preload_keys = {
            str(item[1])
            for item in sections
            if isinstance(item, (tuple, list)) and len(item) >= 2
        }
        if "voice_status" in preload_keys:
            self.event_bus.emit(Events.GUI.VOICEOVER_REFRESH)
