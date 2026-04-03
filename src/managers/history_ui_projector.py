from __future__ import annotations

from typing import Any, Callable, Optional


class HistoryUiProjector:
    def __init__(self, resolve_name: Optional[Callable[[str], str]] = None):
        self._resolve_name = resolve_name

    def _has_visible_user_text(self, content: Any) -> bool:
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, list):
            for it in content:
                if not isinstance(it, dict):
                    continue
                if it.get("type") == "text":
                    txt = it.get("text")
                    if txt is None:
                        txt = it.get("content", "")
                    if str(txt or "").strip():
                        return True
                if it.get("type") == "image_url":
                    return True
        return False

    def _name(self, cid: str) -> str:
        cid = str(cid or "")
        if not cid:
            return ""
        if self._resolve_name:
            try:
                n = self._resolve_name(cid)
                if n:
                    return str(n)
            except Exception:
                pass
        return cid

    def _decorate_for_ui(self, role: str, content: Any, speaker_label: str) -> Any:
        if not speaker_label:
            return content

        if isinstance(content, list):
            return [{"type": "meta", "speaker": speaker_label}] + content

        if isinstance(content, str):
            return [{"type": "meta", "speaker": speaker_label}, {"type": "text", "text": content}]

        return [{"type": "meta", "speaker": speaker_label}, {"type": "text", "text": str(content)}]

    def project_for_ui(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        if not isinstance(messages, list):
            return out

        for m in messages:
            if not isinstance(m, dict):
                continue

            role = str(m.get("role") or "")
            if role not in ("user", "assistant", "system"):
                continue

            speaker = str(m.get("speaker") or m.get("sender") or "")
            target = str(m.get("target") or "")

            content = m.get("content")

            if role == "user" and not self._has_visible_user_text(content):
                continue

            ui_role = role
            speaker_label = ""

            if role in ("user", "assistant"):
                if speaker == "Player":
                    ui_role = "user"
                    speaker_label = ""
                else:
                    ui_role = "assistant"
                    speaker_label = self._name(speaker)
                    if target and target != "Player":
                        # Don't add → target when there are multiple distinct segment targets:
                        # message_renderer splits those into separate bubbles and adds arrows itself.
                        structured = m.get("structured_data") or {}
                        segments = structured.get("segments") or []
                        distinct_targets = {str(s.get("target") or "") for s in segments if isinstance(s, dict)}
                        if len(distinct_targets) <= 1:
                            speaker_label = f"{speaker_label} → {self._name(target)}"

            mm = dict(m)
            mm["role"] = ui_role
            mm["content"] = self._decorate_for_ui(ui_role, content, speaker_label)

            out.append(mm)

        return out