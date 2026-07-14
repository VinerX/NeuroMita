from __future__ import annotations

import localization

from localization import translate_for_language
from ui.windows.ai_hub.constants import category_label, status_label


def test_ai_hub_category_label_is_resolved_at_render_time(monkeypatch):
    monkeypatch.setattr(localization, "_current_language", lambda: "RU")
    assert str(category_label("voices")) == "Голоса Мит"

    monkeypatch.setattr(localization, "_current_language", lambda: "ZH")
    assert str(category_label("voices")) == "Mita 语音"
    assert str(status_label("ready")) == "已安装"


def test_incomplete_locale_falls_back_to_english_catalog_not_russian():
    value = translate_for_language("ZH", "Готова", "Ready")

    assert value != "Готова"
    assert value
