from PyQt6.QtCore import Qt
from localization import translate


CHARACTER_DISPLAY_NAMES = {
    "Crazy": ("Безумная Мита", "Crazy Mita"),
    "Kind": ("Добрая Мита", "Kind Mita"),
    "Cappie": ("Кепочка", "Cappie"),
    "ShortHair": ("Коротковолосая Мита", "Short-haired Mita"),
    "Mila": ("Мила", "Mila"),
    "Sleepy": ("Сонная Мита", "Sleepy Mita"),
    "Ghost": ("Призрачная Мита", "Ghostly Mita"),
    "Creepy": ("Жуткая Мита", "Creepy Mita"),
    "GameMaster": ("Мастер игры", "Game Master"),
}


def character_display_name(character_id, fallback=""):
    pair = CHARACTER_DISPLAY_NAMES.get(character_id)
    return translate(*pair) if pair else str(fallback or character_id or "")


def retranslate_character_list(library):
    for index in range(library.count()):
        item = library.item(index)
        item.setText(character_display_name(item.data(Qt.ItemDataRole.UserRole), item.data(Qt.ItemDataRole.UserRole + 2)))
