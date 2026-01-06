from core.events import Events, Event
from .base_controller import BaseController


class SettingsSidebarController(BaseController):
    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.GUI.SET_SETTINGS_ICON_INDICATOR, self._on_set_icon_indicator, weak=False)

    def _on_set_icon_indicator(self, event: Event):
        data = event.data or {}
        category = str(data.get("category") or "").strip()
        state = data.get("state", None)
        tooltip = data.get("tooltip", None)

        if not self.view or not category:
            return

        def apply():
            btn = getattr(self.view, "settings_buttons", {}).get(category)
            if btn and hasattr(btn, "set_indicator_state"):
                btn.set_indicator_state(state, tooltip_text=tooltip)

        self._ui(apply)