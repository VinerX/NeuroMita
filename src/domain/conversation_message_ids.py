from __future__ import annotations

import uuid


class ConversationMessageIds:
    @staticmethod
    def incoming(request_id: str | None = None) -> str:
        return ConversationMessageIds._make("in", request_id)

    @staticmethod
    def assistant(task_id: str | None = None) -> str:
        return ConversationMessageIds._make("out", task_id)

    @staticmethod
    def turn(base_id: str | None = None) -> str:
        return ConversationMessageIds._make("turn", base_id)

    @staticmethod
    def system(base_id: str | None = None) -> str:
        return ConversationMessageIds._make("sys", base_id)

    @staticmethod
    def _make(prefix: str, base_id: str | None) -> str:
        base = str(base_id or "").strip()
        if base:
            return f"{prefix}:{base}"
        return f"{prefix}:{uuid.uuid4().hex}"
