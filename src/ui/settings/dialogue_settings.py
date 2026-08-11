from __future__ import annotations

from ui.gui_templates import create_settings_section
from utils import _


def add_dialogue_settings_section(self, parent) -> None:
    """Add dialogue policy controls to the Game settings page."""
    config = [
        {
            "type": "text",
            "label": _(
                "Автоматические разговоры персонажей, продолжения и GameMaster.",
                "Automatic character conversations, continuations and GameMaster.",
            ),
        },
        {
            "type": "subsection",
            "label": _("Автоматические диалоги", "Automatic dialogues"),
        },
        {
            "label": _("Автодиалоги между персонажами", "Automatic dialogues between characters"),
            "key": "MITA_DIALOGUE_AUTO",
            "type": "checkbutton",
            "default_checkbutton": True,
            "widget_name": "MITA_DIALOGUE_AUTO",
            "tooltip": _(
                "Разрешать Unity планировать следующие ходы после ответа Миты.",
                "Allow Unity to schedule follow-up turns after a Mita reply.",
            ),
        },
        {
            "label": _("Максимум ходов в цепочке (1–24)", "Maximum turns in chain (1–24)"),
            "key": "DIALOGUE_MAX_CHAIN_TURNS",
            "type": "number_stepper",
            "default": 3,
            "minimum": 1,
            "maximum": 24,
            "depends_on": "MITA_DIALOGUE_AUTO",
            "tooltip": _(
                "Максимальное число ответов Мит, включая первый ответ на сообщение игрока.",
                "Maximum number of Mita replies, including the first response to the player's message.",
            ),
        },
        {"type": "end"},
        {
            "type": "subsection",
            "label": _("Продолжения", "Continuations"),
        },
        {
            "label": _("Максимум продолжений одной Миты (0–12)", "Maximum continuations by one Mita (0–12)"),
            "key": "DIALOGUE_MAX_CONTINUES",
            "type": "number_stepper",
            "default": 3,
            "minimum": 0,
            "maximum": 12,
            "special_value_text": _("Откл.", "Off"),
            "tooltip": _(
                "0 запрещает продолжения той же Митой, но не останавливает общую цепочку.",
                "0 prevents same-Mita continuations without stopping the shared conversation chain.",
            ),
        },
        {"type": "end"},
        {
            "type": "subsection",
            "label": _("Режим GameMaster", "GameMaster"),
        },
        {
            "label": _("Включить GameMaster", "Enable GameMaster"),
            "key": "GM_ON",
            "type": "checkbutton",
            "default_checkbutton": False,
            "tooltip": _(
                "GameMaster периодически проверяет разговор и может выдать направление.",
                "GameMaster periodically reviews the conversation and may issue a directive.",
            ),
        },
        {
            "label": _("Ответы Мит между проверками (1–100)", "Mita replies between GameMaster checks (1–100)"),
            "key": "GM_REPEAT",
            "type": "number_stepper",
            "default": 2,
            "minimum": 1,
            "maximum": 100,
            "tooltip": _(
                "Сколько ответов Мит проходит между проверками GameMaster.",
                "How many Mita replies occur between GameMaster checks.",
            ),
        },
        {
            "label": _("Задача GameMaster", "GameMaster prompt"),
            "key": "GM_SMALL_PROMPT",
            "type": "textarea",
            "default": "??????? ??? ???????",
        },
    ]

    create_settings_section(
        self,
        parent,
        _("Диалоги", "Dialogue"),
        config,
        icon_name="fa6s.comments",
    )
