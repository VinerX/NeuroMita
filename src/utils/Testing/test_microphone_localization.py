import importlib.util
import json
import os
from pathlib import Path
from string import Formatter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

import localization
from handlers.asr_models.asr_languages import asr_language_field
from localization.live import refresh_all
from localization.schema import option_label
from ui.settings.microphone_settings.ui import build_microphone_settings_ui
from ui.windows.ai_hub.schema_renderer import SchemaForm

ROOT = Path(__file__).resolve().parents[3]
LOCALES = sorted(path.stem.upper() for path in (ROOT / "src/localization/locales").glob("*.json") if not path.name.startswith("_"))
_APP = None


def test_microphone_sources_are_extractable_and_translated_in_every_locale():
    spec = importlib.util.spec_from_file_location("extract", ROOT / "scripts/i18n_extract.py")
    extract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract)
    files = [
        "ui/settings/microphone_settings/ui.py", "ui/settings/microphone_settings/widgets.py",
        "controllers/gui/microphone_settings_controller.py",
        "controllers/gui/microphone_monitor_controller.py", "handlers/asr_models/asr_languages.py",
    ]
    pairs = dict(pair for file in files for pair in extract.scan_file(ROOT / "src" / file)[0] if pair[0])
    ui_keys = {key for file in files[:-1] for key, _ in extract.scan_file(ROOT / "src" / file)[0]}
    assert {"Язык распознавания", "Отправлять распознанный текст сразу.", "Фиксированная частота: 16000 Гц.", "Украинский", "Английский (США)", "Автоопределение"} <= pairs.keys()
    formatter = Formatter()
    for lang in LOCALES:
        catalog = json.loads((ROOT / f"src/localization/locales/{lang.lower()}.json").read_text(encoding="utf-8"))
        for key, english in pairs.items():
            assert catalog.get(key), (lang, key)
            assert {field for _, field, _, _ in formatter.parse(key) if field} == {field for _, field, _, _ in formatter.parse(catalog[key]) if field}, (lang, key)
            if lang != "EN" and english and key != english and key in ui_keys:
                assert catalog[key] != english, (lang, key)


@pytest.mark.parametrize("language", ["RU", *LOCALES])
def test_both_surfaces_use_catalogs_and_live_changes_keep_selection(language, monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    current = ["RU"]
    monkeypatch.setattr(localization, "_current_language", lambda: current[0])
    workspace = QWidget()
    workspace.settings = {}
    build_microphone_settings_ui(workspace, QVBoxLayout(workspace))
    form = SchemaForm([asr_language_field("google")])
    form.set_values({"language": "uk-UA"})
    changes = []
    combo = form._widgets["language"]
    combo.currentIndexChanged.connect(changes.append)
    current[0] = language
    refresh_all()
    assert form.values()["language"] == "uk-UA"
    assert not form.is_dirty()
    assert not changes
    assert combo.currentText() == option_label(asr_language_field("google"), "uk-UA")
    texts = [label.text() for label in workspace.findChildren(QLabel)]
    for source in ("Язык распознавания", "Отправлять распознанный текст сразу.", "Фиксированная частота: 16000 Гц."):
        assert localization.translate(source) in texts
    for engine in ("google", "whisper", "gigaam"):
        field = asr_language_field(engine)
        for code in field["options"]:
            label = option_label(field, code)
            assert code in label
            assert "★" not in label
            assert " / " not in label
    if language == "UK":
        assert combo.currentText() == "українська (uk-UA)"
    workspace.mic_monitor_controller.monitor.close()
    workspace.close()
    form.close()
    workspace.deleteLater()
    form.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
