from __future__ import annotations

from ui.gui_templates import create_settings_section
from utils import _

_GAME_MASTER_SETTINGS_VISIBLE = False


def add_dialogue_settings_section(self, parent) -> None:
    """Add dialogue policy controls to the Game settings page."""
    config = [
        {
            "type": "text",
            "label": _(
                "Автоматические разговоры персонажей и продолжения.",
                "Automatic character conversations and continuations.",
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
            "label": _("Минимум кругов разговора (1–24)", "Minimum conversation rounds (1–24)"),
            "key": "DIALOGUE_AUTO_ROUNDS",
            "type": "number_stepper",
            "default": 1,
            "minimum": 1,
            "maximum": 24,
            "depends_on": "MITA_DIALOGUE_AUTO",
            "tooltip": _(
                "Каждая активная Мита отвечает хотя бы столько раз. Явные target-обращения могут добавить ответы сверх этой квоты.",
                "Each active Mita replies at least this many times. Explicit target addresses may add replies beyond this quota.",
            ),
        },
        {
            "label": _("Предельное число ходов в цепочке (1–200)", "Maximum turns in chain (1–200)"),
            "key": "DIALOGUE_MAX_CHAIN_TURNS",
            "type": "number_stepper",
            "default": 24,
            "minimum": 1,
            "maximum": 200,
            "depends_on": "MITA_DIALOGUE_AUTO",
            "tooltip": _(
                "Жёсткий предохранитель: учитывает первый ответ и дополнительные ответы по target. При достижении лимита цепочка завершается, даже если круги не закончены.",
                "Hard safety limit: includes the first reply and extra target replies. Reaching it ends the chain even if rounds remain.",
            ),
        },
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
    ]

    # The implementation is retained for later work, but the unfinished
    # controls must not be exposed or accidentally re-enabled from saved data.
    if _GAME_MASTER_SETTINGS_VISIBLE:
        config.extend([
            {
                "type": "subsection",
                "label": _("Режим GameMaster", "GameMaster"),
            },
            {
                "label": _("Включить GameMaster", "Enable GameMaster"),
                "key": "GM_ON",
                "type": "checkbutton",
                "default_checkbutton": False,
            },
            {
                "label": _("Ответы Мит между проверками (1–100)", "Mita replies between GameMaster checks (1–100)"),
                "key": "GM_REPEAT",
                "type": "number_stepper",
                "default": 2,
                "minimum": 1,
                "maximum": 100,
            },
            {
                "label": _("Задача GameMaster", "GameMaster prompt"),
                "key": "GM_SMALL_PROMPT",
                "type": "textarea",
                "default": "",
            },
        ])

    create_settings_section(
        self,
        parent,
        _("Диалоги", "Dialogue"),
        config,
        icon_name="fa6s.comments",
    )
