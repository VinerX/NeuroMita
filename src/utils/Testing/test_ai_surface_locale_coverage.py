from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _extractor(root: Path):
    spec = importlib.util.spec_from_file_location(
        "i18n_extract_for_test", root / "scripts" / "i18n_extract.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_all_new_ai_engine_and_ai_hub_strings_are_in_every_locale():
    src = Path(__file__).resolve().parents[2]
    root = src.parent
    extract = _extractor(root)
    pairs: dict[str, str] = {}
    sources = [
        src / "ui" / "settings" / "ai_engine_settings.py",
        *(src / "ui" / "windows" / "ai_hub").glob("*.py"),
    ]
    for source in sources:
        for ru, en in extract.scan_file(source)[0]:
            if ru and en:
                pairs.setdefault(ru, en)

    locales = src / "localization" / "locales"
    for locale in locales.glob("*.json"):
        if locale.name.startswith("_"):
            continue
        catalog = json.loads(locale.read_text(encoding="utf-8"))
        missing = sorted(key for key in pairs if key not in catalog)
        assert not missing, f"{locale.name}: missing {missing}"
