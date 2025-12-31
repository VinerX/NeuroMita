from typing import List, Dict, Tuple
import re
from PyQt6.QtGui import QColor
from utils import getTranslationVariant as _


class ChatMessageDelegate:
    def __init__(self):
        self.role_label_colors = {
            "user": QColor("gold"),
            "assistant": QColor("hot pink"),
            "system": QColor("#66ccff"),
        }
        self.role_content_colors = {
            "system": QColor("#a7d8ff"),
        }
        self.tag_color = QColor("#00FF00")

    def get_label(self, gui, role: str, speaker_name: str = "") -> Tuple[str, QColor, bool]:
        if role == "user":
            if speaker_name and speaker_name != "Player":
                return (f"{speaker_name}: ", self.role_label_colors["user"], True)
            return (_("Вы: ", "You: "), self.role_label_colors["user"], True)

        if role == "assistant":
            name = speaker_name or (gui._get_character_name() if hasattr(gui, "_get_character_name") else "Assistant")
            return (f"{name}: ", self.role_label_colors["assistant"], True)

        if role == "system":
            return (_("Система: ", "System: "), self.role_label_colors["system"], True)

        return (f"{role}: ", QColor("#dcdcdc"), True)

    def get_content_color(self, role: str):
        return self.role_content_colors.get(role, None)

    def get_timestamp(self, show: bool, message_time: str) -> str:
        import time
        if not show:
            return ""
        return f"[{message_time}] " if message_time else time.strftime("[%H:%M:%S] ")

    def split_text_with_tags(self, text: str, hide_tags: bool) -> List[Dict]:
        if hide_tags:
            pattern = r'(<([^>]+)>)(.*?)(</\2>)|(<([^>]+)>)'
            clean_text = re.sub(pattern, "", text, flags=re.DOTALL)
            clean_text = re.sub(r' +', ' ', clean_text).strip()
            return [{"type": "text", "content": clean_text, "tag": "default"}]

        parts = []
        matches = list(re.finditer(r'(<([^>]+)>)(.*?)(</\2>)|(<([^>]+)>)', text))
        last_end = 0
        if not matches:
            parts.append({"type": "text", "content": text, "tag": "default"})
            return parts

        for m in matches:
            start, end = m.span()
            if start > last_end:
                parts.append({"type": "text", "content": text[last_end:start], "tag": "default"})
            if m.group(1) is not None:
                parts.append({"type": "text", "content": m.group(1), "tag": "tag_green"})
                parts.append({"type": "text", "content": m.group(3), "tag": "default"})
                parts.append({"type": "text", "content": m.group(4), "tag": "tag_green"})
            elif m.group(5) is not None:
                parts.append({"type": "text", "content": m.group(5), "tag": "tag_green"})
            last_end = end

        if last_end < len(text):
            parts.append({"type": "text", "content": text[last_end:], "tag": "default"})
        return parts