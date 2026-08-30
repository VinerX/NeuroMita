from __future__ import annotations

from typing import Any, Callable, Optional

from core.message_content import MessageContentCodec


class HistoryUiProjector:
    def __init__(self, resolve_name: Optional[Callable[[str], str]] = None):
        self._resolve_name = resolve_name

    def _has_visible_user_text(self, content: Any) -> bool:
        return MessageContentCodec.has_visible_content(content)

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

    @staticmethod
    def _is_player_actor(value: Any) -> bool:
        return str(value or "").strip().casefold() == "player"

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
            if role not in ("user", "assistant", "system", "event"):
                continue

            speaker = str(m.get("speaker") or "").strip()
            sender = str(m.get("sender") or "").strip()
            actors = (speaker, sender)
            has_player_actor = any(self._is_player_actor(actor) for actor in actors)
            has_non_player_actor = any(
                actor and not self._is_player_actor(actor) for actor in actors
            )
            display_speaker = next(
                (actor for actor in actors if actor and not self._is_player_actor(actor)),
                speaker or sender,
            )
            target = str(m.get("target") or "")

            content = m.get("content")

            if role == "user" and not self._has_visible_user_text(content):
                continue

            ui_role = role
            if role == "event":
                ui_role = "system"
            speaker_label = ""

            # Detect system-as-user messages (stored as role='user' with [Системное]: prefix)
            # Don't convert them to assistant based on speaker
            _SYS_PREFIX = "[Системное]:"
            is_system_as_user = False
            if role == "user":
                _raw = content if isinstance(content, str) else ""
                if not _raw and isinstance(content, list):
                    for _item in content:
                        if isinstance(_item, dict) and _item.get("type") == "text":
                            _raw = _item.get("text") or _item.get("content", "")
                            break
                if isinstance(_raw, str) and _raw.lstrip().startswith(_SYS_PREFIX):
                    is_system_as_user = True

            if role in ("user", "assistant"):
                if has_player_actor and not has_non_player_actor:
                    ui_role = "user"
                    speaker_label = ""
                elif role == "user" and not has_non_player_actor:
                    # Preserve legacy user rows that have no actor identity.
                    ui_role = "user"
                elif not is_system_as_user:
                    # Only convert non-system-as-user to assistant
                    ui_role = "assistant"
                    speaker_label = self._name(display_speaker)
                    if target and not self._is_player_actor(target):
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
