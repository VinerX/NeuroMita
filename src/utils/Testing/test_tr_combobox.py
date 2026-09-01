"""Тест TRQComboBox: живой перевод пунктов, стабильность значения, отсутствие
ложных сигналов. Запуск (Venv-python, offscreen):

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src \
    "C:/Games/NeuroMita/Venv/Scripts/python.exe" src/utils/Testing/test_tr_combobox.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication


def main() -> int:
    app = QApplication(sys.argv)
    from managers.settings_manager import SettingsManager
    SettingsManager(os.path.join(tempfile.mkdtemp(), "s.json"))
    SettingsManager.set("LANGUAGE", "RU")

    from localization.live import set_language
    from ui.widgets.tr_combobox import TRQComboBox

    cb = TRQComboBox()
    # Сентинел (переводимый, стабильное значение) + два data-пункта.
    cb.set_items([("Текущий", "Current", "Текущий"), "PresetA", "PresetB"])

    fired = []
    cb.currentIndexChanged.connect(lambda i: fired.append(i))

    assert cb.itemText(0) == "Текущий", cb.itemText(0)
    assert cb.current_value() == "Текущий", cb.current_value()

    # Выбор data-пункта по значению.
    assert cb.set_current_value("PresetA")
    assert cb.current_value() == "PresetA"

    # Живой перевод: текст сентинела меняется, ЗНАЧЕНИЕ и выбор — нет.
    fired.clear()
    set_language("EN")
    assert cb.itemText(0) == "Current", cb.itemText(0)
    assert cb.itemText(1) == "PresetA", cb.itemText(1)  # data не переводится
    assert cb.current_value() == "PresetA", cb.current_value()
    assert fired == [], f"retranslate не должен эмитить сигнал: {fired}"

    # Возврат к сентинелу по стабильному значению (а не по тексту).
    assert cb.set_current_value("Текущий")
    assert cb.currentText() == "Current"   # отображение — EN
    assert cb.current_value() == "Текущий"  # значение — каноническое

    # Пере-наполнение сохраняет выбранное значение.
    set_language("RU")
    cb.set_items([("Текущий", "Current", "Текущий"), "PresetA", "PresetB", "PresetC"])
    assert cb.current_value() == "Текущий", cb.current_value()

    # set_data_items: чисто данные, выбор по тексту.
    cb.set_data_items(["Crazy", "Kind", "Ghost"], current="Kind")
    assert cb.current_value() == "Kind"
    set_language("EN")
    assert cb.currentText() == "Kind"  # data не трогается

    # Робастность к insertSeparator: переводимый пункт ПОСЛЕ сепаратора
    # (паттерн model/prompt-комбо в песочнице) переводится корректно, т.к. пара
    # перевода хранится в роли пункта, а не в индекс-параллельном списке.
    set_language("RU")
    cb2 = TRQComboBox()
    cb2.add_data_item("PresetA", value=1)
    cb2.insertSeparator(cb2.count())
    cb2.add_tr_item("Настроить…", "Configure…", value="__cfg__")
    set_language("EN")
    assert cb2.itemText(0) == "PresetA"        # data не трогается
    assert cb2.itemText(2) == "Configure…"     # tr после сепаратора — переведён
    assert cb2.itemData(2) == "__cfg__"        # значение стабильно
    set_language("RU")

    print("TRQComboBox: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
