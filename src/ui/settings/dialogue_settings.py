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
            "default_checkbutton": False,
            "widget_name": "MITA_DIALOGUE_AUTO",
            "tooltip": _(
                "Разрешать роутеру назначать следующие ходы после ответа Миты.",
                "Allow the router to schedule follow-up turns after a Mita reply.",
            ),
        },
        {
            "label": _("Максимум автоходов после запроса (0–24)", "Maximum automatic turns after a player message (0–24)"),
            "key": "DIALOGUE_MAX_AUTO_TURNS",
            "type": "spinbox",
            "default": 6,
            "minimum": 0,
            "maximum": 24,
            "special_value_text": _("Откл.", "Off"),
            "depends_on": "MITA_DIALOGUE_AUTO",
            "tooltip": _(
                "0 отключает автоматические ходы.",
                "0 disables automatic turns.",
            ),
        },
        {
            "label": _("Подсчёт лимита автоходов", "Automatic turn budget"),
            "key": "DIALOGUE_AUTO_TURN_COUNT_MODE",
            "type": "combobox",
            "options": [
                (_("Фиксированный лимит", "Fixed limit"), "fixed"),
                (_("По одному на каждую Миту", "One per selected Mita"), "per_participant"),
            ],
            "default": "fixed",
            "depends_on": "MITA_DIALOGUE_AUTO",
            "tooltip": _(
                "Во втором режиме размер цепочки равен количеству активных Мит в разговоре.",
                "In the second mode, the chain budget equals the number of active Mitas in the conversation.",
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
