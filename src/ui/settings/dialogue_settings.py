from __future__ import annotations

from ui.gui_templates import create_settings_section
from utils import _


def setup_dialogue_settings_controls(self, parent) -> None:
    """Build persistent dialogue policy settings in their own settings section."""
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
                "Разрешать роутеру назначать следующие ходы после ответа Миты.",
                "Allow the router to schedule follow-up turns after a Mita reply.",
            ),
        },
        {
            "label": _("Как считать автоходы", "How to count automatic turns"),
            "key": "DIALOGUE_AUTO_TURN_COUNT_MODE",
            "type": "combobox",
            "options": [
                (_("Фиксированный лимит", "Fixed limit"), "fixed"),
                (_("По одному на каждую Миту", "One per active Mita"), "per_participant"),
            ],
            "default": "per_participant",
            "depends_on": "MITA_DIALOGUE_AUTO",
            "tooltip": _(
                "Фиксированный режим использует число ниже. Второй режим игнорирует его и даёт один ход на каждую активную говорящую Миту.",
                "Fixed mode uses the number below. The other mode ignores it and gives one turn to each active Mita that can speak.",
            ),
        },
        {
            "label": _("Автоходов на одну Миту (1–24)", "Automatic turns per active Mita (1–24)"),
            "key": "DIALOGUE_AUTO_TURNS_PER_PARTICIPANT",
            "type": "spinbox",
            "default": 1,
            "minimum": 1,
            "maximum": 24,
            "depends_on": "MITA_DIALOGUE_AUTO",
            "tooltip": _(
                "Используется только при режиме «По одному на каждую Миту». Итоговый лимит — число активных говорящих Мит, умноженное на это число.",
                "Used only in One per active Mita mode. The total limit is the active speaking Mitas multiplied by this number.",
            ),
        },
        {
            "label": _("Фиксированный лимит автоходов (0–24)", "Fixed automatic-turn limit (0–24)"),
            "key": "DIALOGUE_MAX_AUTO_TURNS",
            "type": "spinbox",
            "default": 6,
            "minimum": 0,
            "maximum": 24,
            "special_value_text": _("Откл.", "Off"),
            "depends_on": "MITA_DIALOGUE_AUTO",
            "tooltip": _(
                "Используется только при режиме «Фиксированный лимит». 0 отключает автоматические ходы.",
                "Used only in Fixed limit mode. 0 disables automatic turns.",
            ),
        },
        {
            "type": "text",
            "label": _(
                "Используется одно из чисел выше: фиксированный режим берёт фиксированный лимит, а режим «По одной на Миту» умножает число активных говорящих Мит на значение «Автоходов на одну Миту».",
                "Only one number above is used: Fixed limit uses the fixed value, while One per active Mita multiplies active speaking Mitas by the turns-per-Mita value.",
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
            "type": "spinbox",
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
            "type": "spinbox",
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
            "default": "",
        },
    ]

    create_settings_section(
        self,
        parent,
        _("Диалоги", "Dialogue"),
        config,
        icon_name="fa6s.comments",
    )
