from __future__ import annotations

import threading
import time
from collections import deque


def normalize_input_mode(value) -> str:
    return "ptt" if str(value or "").strip().lower() == "ptt" else "vad"


class ASRInputGate:
    """Thread-safe capture policy; release preserves text, cancellation fences it."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._retired = deque(maxlen=64)
        self._state = dict(input_mode="vad", enabled=True, active=False,
                           session_id="", generation=-1, press_generation=-1,
                           epoch=0, revision=0, blocked_until=0.0, lease_until=0.0,
                           needs_release=False)
        self._remote_revision = -1

    def snapshot(self) -> dict:
        with self._lock:
            self._expire()
            return {**self._state, "permitted": self._permitted()}

    def _expire(self):
        if self._state["active"] and self._clock() >= self._state["lease_until"]:
            self.reset()
            self._state["needs_release"] = True

    def _permitted(self) -> bool:
        return self._state["enabled"] and self._clock() >= self._state["blocked_until"]

    def configure(self, *, input_mode=None, enabled=None, blocked_until=None) -> None:
        with self._lock:
            updates = {}
            if input_mode is not None:
                updates["input_mode"] = normalize_input_mode(input_mode)
            if enabled is not None:
                updates["enabled"] = bool(enabled)
            if blocked_until is not None:
                updates["blocked_until"] = float(blocked_until)
            changed = {key: value for key, value in updates.items() if self._state[key] != value}
            if not changed:
                return
            cancel = ("input_mode" in changed or changed.get("enabled") is False
                      or changed.get("blocked_until", 0.0) > self._clock())
            self._state.update(changed)
            if cancel:
                if self._state["active"]:
                    self._state["needs_release"] = True
                self._state["active"] = False
                self._state["epoch"] += 1
            self._state["revision"] += 1

    def ptt(self, *, active: bool, session_id: str, generation: int, cancelled: bool = False) -> bool:
        if type(active) is not bool or type(generation) is not int or not 0 <= generation <= 2**63 - 1:
            return False
        if type(cancelled) is not bool or not isinstance(session_id, str) or not session_id:
            return False
        with self._lock:
            self._expire()
            state = self._state
            if state["input_mode"] != "ptt" or session_id in self._retired:
                return False
            if session_id != state["session_id"]:
                if not active:
                    return False
                if state["session_id"]:
                    self._retired.append(state["session_id"])
                state.update(session_id=session_id, generation=-1, active=False,
                             epoch=state["epoch"] + (1 if state["session_id"] else 0),
                             needs_release=False)
            same_generation_release = generation == state["generation"] and state["active"] and not active
            if generation <= state["generation"] and not same_generation_release:
                return False
            was_active = state["active"]
            state["generation"] = generation
            if not active or cancelled:
                state["needs_release"] = False
            elif not self._permitted():
                state["needs_release"] = True
            state["active"] = active and not cancelled and self._permitted() and not state["needs_release"]
            if state["active"]:
                state["lease_until"] = self._clock() + 3.0
            if state["active"] and not was_active:
                state["press_generation"] = generation
            if cancelled:
                state["epoch"] += 1
            state["revision"] += 1
            return True

    def reset(self) -> None:
        with self._lock:
            if self._state["active"]:
                self._state["needs_release"] = True
            self._state["active"] = False
            self._state["epoch"] += 1
            self._state["revision"] += 1

    def disconnect(self, session_id: str) -> None:
        with self._lock:
            if session_id:
                self._retired.append(session_id)
            if not session_id or session_id == self._state["session_id"]:
                self.reset()
                self._state.update(session_id="", generation=-1, press_generation=-1,
                                   needs_release=False)

    def apply(self, state: dict) -> bool:
        with self._lock:
            revision = state.get("revision", -1)
            if type(revision) is not int or revision <= self._remote_revision:
                return False
            self._remote_revision = revision
            self._state.update({key: state[key] for key in self._state if key in state})
            self._state["input_mode"] = normalize_input_mode(self._state["input_mode"])
            return True

    def valid(self, context: dict) -> bool:
        with self._lock:
            self._expire()
            return (context.get("epoch") == self._state["epoch"]
                    and context.get("input_mode") == self._state["input_mode"]
                    and self._permitted()
                    and (context.get("input_mode") != "ptt"
                         or context.get("session_id") == self._state["session_id"]))
