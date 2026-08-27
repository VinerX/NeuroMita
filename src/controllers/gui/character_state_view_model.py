from __future__ import annotations

import re
from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from core.events import Events, get_event_bus
from ui.widgets.character_state_presentation import (
    CharacterParamState,
    CharacterStatePanelState,
    CharacterStatState,
    RefreshCharacterState,
)


class CharacterStateViewModel(IntentViewModel[CharacterStatePanelState]):
    def __init__(self, *, current_character, parent=None) -> None:
        super().__init__(CharacterStatePanelState(), parent)
        self._current_character = current_character
        self._rebuild_requested = True
        bus = get_event_bus()
        for event_name in (
            Events.Character.CURRENT_CHANGED,
            Events.Character.RELOAD_DATA,
            Events.Model.ON_SUCCESSFUL_RESPONSE,
        ):
            self.track_subscription(
                bus.subscribe(event_name, self._on_refresh_event, weak=False)
            )

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, RefreshCharacterState):
            self.refresh(rebuild=bool(intent.rebuild))

    def refresh(self, *, rebuild: bool = False) -> None:
        self._rebuild_requested = self._rebuild_requested or bool(rebuild)
        if not self.state.loading:
            self.update_state(loading=True)
        self.run_coalesced(
            "character-state-refresh",
            self._build_snapshot,
            self._apply_snapshot,
            lambda _error: self.update_state(loading=False),
        )

    def _on_refresh_event(self, event: Any) -> None:
        rebuild = getattr(event, "name", "") in {
            Events.Character.CURRENT_CHANGED,
            Events.Character.RELOAD_DATA,
        }
        self._post_ui(lambda: self.refresh(rebuild=rebuild))

    def _build_snapshot(self) -> CharacterStatePanelState:
        character = self._current_character()
        if character is None:
            return CharacterStatePanelState(loading=False)
        variables = dict(getattr(character, "variables", {}) or {})
        character_id = str(getattr(character, "char_id", "") or "")
        custom = tuple(
            item
            for item in (
                self._custom_param_state(param, character, variables)
                for param in list(getattr(character, "custom_params", []) or [])
            )
            if item is not None
        )
        return CharacterStatePanelState(
            character_id=character_id,
            attitude=self._stat(character, "attitude"),
            boredom=self._stat(character, "boredom"),
            stress=self._stat(character, "stress"),
            secret_exposed=bool(variables.get("secretExposed", False)),
            custom_params=custom,
            all_variables_text=self._all_variables_text(variables),
            loading=False,
            revision=self.state.revision + 1,
        )

    def _apply_snapshot(self, state: CharacterStatePanelState) -> None:
        self._rebuild_requested = False
        self.set_state(state)

    @staticmethod
    def _stat(character: Any, key: str) -> CharacterStatState:
        try:
            value = float(character.get_variable(key, 0.0) or 0.0)
            minimum = float(character.get_variable(f"{key}_min", 0.0))
            maximum = float(character.get_variable(f"{key}_max", 100.0))
        except Exception:
            value, minimum, maximum = 0.0, 0.0, 100.0
        return CharacterStatState(value=value, minimum=minimum, maximum=maximum)

    @classmethod
    def _custom_param_state(
        cls,
        param: dict[str, Any],
        character: Any,
        variables: dict[str, Any],
    ) -> CharacterParamState | None:
        name = str(param.get("name") or "").strip()
        if not name:
            return None
        kind = str(param.get("type") or "float").lower()
        value = variables.get(name)
        if kind in ("float", "int"):
            minimum, maximum = cls._custom_bounds(param, character, name)
            try:
                value = float(value or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            return CharacterParamState(name, kind, value, minimum, maximum)
        if kind == "bool":
            return CharacterParamState(name, kind, bool(value))
        return None

    @staticmethod
    def _custom_bounds(
        param: dict[str, Any],
        character: Any,
        name: str,
    ) -> tuple[float, float]:
        for key_min, key_max in (("min", "max"), ("value_min", "value_max")):
            if key_min in param or key_max in param:
                try:
                    return float(param.get(key_min, 0.0)), float(param.get(key_max, 100.0))
                except Exception:
                    pass
        formula = str(param.get("formula") or "")
        match = re.search(
            r"max\(\s*(-?\d+(?:\.\d+)?)\s*,\s*min\(.*?,\s*(-?\d+(?:\.\d+)?)\s*\)",
            formula,
        )
        if match:
            return float(match.group(1)), float(match.group(2))
        try:
            current = float(character.get_variable(name, 0.0) or 0.0)
        except Exception:
            current = 0.0
        upper = 100.0 if current <= 0 else max(100.0, ((int(current) // 50) + 1) * 50.0)
        return 0.0, upper

    @staticmethod
    def _all_variables_text(variables: dict[str, Any]) -> str:
        lines: list[str] = []
        for key in sorted(variables, key=str.lower):
            value = variables[key]
            if isinstance(value, bool):
                text = "true" if value else "false"
            elif value is None:
                text = "None"
            elif isinstance(value, float):
                text = f"{value:.3f}".rstrip("0").rstrip(".")
            elif isinstance(value, str):
                text = (
                    f'"{value}"'
                    if value and (" " in value or "\n" in value or value[0] in "{[#")
                    else value
                )
            else:
                text = str(value)
            if len(text) > 300:
                text = text[:297] + "..."
            lines.append(f"{key}: {text}")
        return "\n".join(lines) if lines else "—"