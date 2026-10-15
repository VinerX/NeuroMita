from __future__ import annotations

import threading
from collections import deque


def capture_key(context: dict) -> tuple:
    return (context.get("session_id", ""), context.get("epoch", 0),
            context.get("press_generation", -1))


def capture_id(context: dict) -> str:
    return f"{context.get('epoch', 0)}:{context.get('press_generation', -1)}"


class CaptureProgressTracker:
    """Track queued work separately from microphone activity, per capture."""

    def __init__(self, emit):
        self._emit = emit
        self._lock = threading.RLock()
        self._entries = {}
        self._revision = 0
        self._finished = deque(maxlen=64)

    def _entry(self, context):
        return self._entries.setdefault(capture_key(context), dict(
            context=dict(context), active=bool(context.get("active")),
            buffered=False, voiced=False, pending=0, error="", last=None))

    def _publish(self, entry):
        c = entry["context"]
        manual = c.get("input_mode") in ("ptt", "radio")
        complete = manual and not entry["active"] and not entry["buffered"] and not entry["pending"]
        phase = ("completed" if complete else "error" if entry["error"] else
                 "recognizing" if entry["pending"] and c.get("target") != "game" else
                 "speech" if entry["voiced"] else
                 "listening" if entry["active"] else
                 "recognizing" if entry["buffered"] or entry["pending"] else "idle")
        signature = (phase, entry["active"], entry["pending"], entry["error"])
        if signature != entry["last"]:
            entry["last"] = signature
            self._revision += 1
            self._emit(dict(phase=phase, active=entry["active"],
                            pending=entry["pending"], error=entry["error"],
                            revision=self._revision, capture_id=capture_id(c),
                            capture_context=dict(c)))
        return complete

    def observe(self, state, buffered_context, *, voiced):
        with self._lock:
            key = capture_key(state)
            listening = state.get("permitted", False) and (
                state.get("active", False) or state.get("input_mode") == "vad")
            if listening:
                self._entry(state)
            elif (state.get("input_mode") in ("radio", "ptt") and
                  state.get("press_generation", -1) >= 0 and key not in self._finished):
                self._entry(state)
            for old_key, entry in list(self._entries.items()):
                c = entry["context"]
                if c.get("epoch") != state.get("epoch") or c.get("session_id") != state.get("session_id"):
                    self._revision += 1
                    self._emit(dict(phase="cancelled", active=False, pending=0,
                                    error="capture_cancelled", revision=self._revision,
                                    capture_id=capture_id(c), capture_context=dict(c)))
                    del self._entries[old_key]
                    continue
                entry["active"] = old_key == key and listening
                entry["buffered"] = buffered_context is not None and capture_key(buffered_context) == old_key
                entry["voiced"] = old_key == key and listening and voiced
                if self._publish(entry):
                    self._finished.append(old_key)
                    del self._entries[old_key]

    def enqueue(self, context):
        with self._lock:
            entry = self._entry(context)
            entry["pending"] += 1

    def finish(self, context, error=""):
        with self._lock:
            key = capture_key(context)
            entry = self._entries.get(key)
            if entry is None:
                return
            entry["pending"] = max(0, entry["pending"] - 1)
            entry["error"] = error or entry["error"]
            if self._publish(entry):
                self._finished.append(key)
                del self._entries[key]


class GameCaptureTranscripts:
    def __init__(self):
        self._entries = {}
        self._lock = threading.RLock()

    def append(self, context, text):
        with self._lock:
            entry = self._entries.setdefault(capture_key(context), dict(context=dict(context), parts=[]))
            entry["parts"].append(text.strip())
            return self._payload(entry, final=False)

    def complete(self, context):
        with self._lock:
            entry = self._entries.pop(capture_key(context), None)
            return self._payload(entry, final=True) if entry else None

    def discard_invalid(self, valid):
        with self._lock:
            self._entries = {k: v for k, v in self._entries.items() if valid(v["context"])}

    @staticmethod
    def _payload(entry, *, final):
        context = entry["context"]
        return dict(text=" ".join(entry["parts"]), final=final,
                    revision=len(entry["parts"]) + int(final),
                    capture_id=capture_id(context), press_generation=context["press_generation"],
                    client_id=context["session_id"], capture_context=context)
