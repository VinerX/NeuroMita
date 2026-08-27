# -*- coding: utf-8 -*-
"""Сборка голосовых бандлов Мит + манифест версий для релиза ``voice-assets``.

Для каждого голоса собирает ``<Name>.zip`` (ZIP_STORED, файлы в корне архива —
контракт ``utils.voice_assets_installer``) из папки ``Models/`` и пишет/обновляет
``manifest.json`` с полями ``date`` / ``sha256`` / ``size``. Именно эти zip и
манифест затем заливаются в релиз — sha256 совпадает байт-в-байт, потому что
хэшируется ровно то, что уходит на аплоад.

Примеры::

    # пересобрать три голоса на сегодняшнюю дату и обновить манифест
    python scripts/build_voice_bundles.py GhostMita ShorthairMita SleepyMita

    # все голоса из манифеста воли, с явной датой
    python scripts/build_voice_bundles.py --all --date 2026-07-03

Заливка (руками, чтобы не палить токен в CI)::

    gh release upload voice-assets _voice_bundles/GhostMita.zip _voice_bundles/manifest.json \
        --repo Atm4x/NeuroMita --clobber
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = Path(os.environ.get("NEUROMITA_MODELS_DIR", REPO_ROOT / "Models"))
OUT_DIR = REPO_ROOT / "_voice_bundles"
MANIFEST = OUT_DIR / "manifest.json"

# Файлы на голос (все опциональные, кроме модели). Порядок фиксирован → архив
# детерминирован.
def _members(name: str) -> list[str]:
    return [
        f"{name}.pth", f"{name}.onnx", f"{name}.index", f"{name}.wav", f"{name}.txt",
        f"{name}_Cuts/{name}_default.wav", f"{name}_Cuts/{name}_default.txt",
    ]


def _all_voice_names() -> list[str]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from installables.voice_assets import MITA_VOICES  # noqa: E402
    return [str(v["short_name"]) for v in MITA_VOICES]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_one(name: str) -> tuple[Path, int]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}.zip"
    present = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for rel in _members(name):
            src = MODELS_DIR / rel.replace("/", os.sep)
            if src.exists():
                z.write(src, arcname=rel)
                present += 1
            else:
                print(f"  {name}: пропуск отсутствующего {rel}")
    if present == 0:
        raise SystemExit(f"{name}: в {MODELS_DIR} нет ни одного файла — нечего паковать")
    return out, present


def load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("voices"), dict):
                return data
        except Exception:
            pass
    return {"schema": 1, "voices": {}}


def main() -> None:
    ap = argparse.ArgumentParser(description="Собрать голосовые бандлы + манифест версий")
    ap.add_argument("names", nargs="*", help="Короткие имена голосов (напр. GhostMita)")
    ap.add_argument("--all", action="store_true", help="Все голоса из MITA_VOICES")
    ap.add_argument("--date", default=_dt.date.today().isoformat(), help="Дата версии (YYYY-MM-DD)")
    args = ap.parse_args()

    names = _all_voice_names() if args.all else args.names
    if not names:
        ap.error("укажите имена голосов или --all")

    manifest = load_manifest()
    voices = manifest["voices"]
    built = []
    for name in names:
        out, present = build_one(name)
        size = out.stat().st_size
        digest = _sha256(out)
        voices[name] = {"date": args.date, "sha256": digest, "size": size}
        built.append(out)
        print(f"{name}.zip  {size/1e6:6.1f}MB  {present} файлов  sha256={digest[:12]}…  date={args.date}")

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nМанифест: {MANIFEST}")
    upload = " ".join(f'"{p}"' for p in built + [MANIFEST])
    print(f"\nЗалить:\n  gh release upload voice-assets {upload} --repo Atm4x/NeuroMita --clobber")


if __name__ == "__main__":
    main()
