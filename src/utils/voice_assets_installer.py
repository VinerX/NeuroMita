"""Download / extract / remove per-character voice asset bundles.

Voice bundles are hosted as one ``<ShortName>.zip`` asset per character on a
(low-profile) GitHub *prerelease*. Each archive carries the runtime files that
``get_character_voice_paths`` expects for that character, laid out at the
archive root::

    <ShortName>.pth            (NVIDIA)
    <ShortName>.onnx           (AMD/CPU, optional)
    <ShortName>.index          (optional)
    <ShortName>.wav
    <ShortName>.txt
    <ShortName>_Cuts/<ShortName>_default.wav   (optional, F5 reference)
    <ShortName>_Cuts/<ShortName>_default.txt   (optional)

These are *assets*, not code — nothing here imports torch/Qt, so the module is
unit-testable on the embedded runtime.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable

# Where voice assets live on GitHub. Overridable via env so the repo/tag can be
# repointed (e.g. to a dedicated voices repo) without a code change.
DEFAULT_VOICE_REPO = os.environ.get("NEUROMITA_VOICE_REPO", "Atm4x/NeuroMita")
DEFAULT_VOICE_TAG = os.environ.get("NEUROMITA_VOICE_TAG", "voice-assets")

# Имя ассета-манифеста рядом с zip'ами голосов. Несёт версии (дату/sha256/размер)
# каждого голоса — источник правды для «доступно обновление», развязанный от
# релиза приложения: правишь голос → перезаливаешь zip + бампаешь манифест.
MANIFEST_ASSET = "manifest.json"

_Log = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


def models_dir() -> Path:
    """Root folder that holds the per-character voice files (``Models`` by
    default). Mirrors ``get_character_voice_paths``' resolution so both agree."""
    return Path(os.environ.get("NEUROMITA_MODELS_DIR", os.path.abspath("Models")))


def bundle_url(short_name: str, repo: str = DEFAULT_VOICE_REPO, tag: str = DEFAULT_VOICE_TAG) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{short_name}.zip"


def manifest_url(repo: str = DEFAULT_VOICE_REPO, tag: str = DEFAULT_VOICE_TAG) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{MANIFEST_ASSET}"


# --- Удалённый манифест версий (кэш с TTL) --------------------------------
# Кэшируем распарсенный манифест: status() вызывается по одному разу на каждый
# голос при переопросе списка — без кэша это N сетевых запросов. Переопрос через
# «Проверить обновления» приходит с force=True (см. ctx в контроллере) и кэш минует.
_MANIFEST_CACHE: dict[str, Any] = {"data": None, "ts": 0.0}
_MANIFEST_TTL = 120.0


def fetch_remote_manifest(force: bool = False, timeout: float = 4.0) -> dict[str, Any] | None:
    """Скачать и распарсить ``manifest.json`` релиза. Кэш с TTL; при сетевом сбое
    возвращаем прежний кэш (пусть устаревший), чтобы не терять уже известные версии.

    Формат: ``{"schema": 1, "voices": {"<Name>": {"date": "...", "sha256": "...",
    "size": 123}}}``. Отсутствие манифеста в релизе (404) — норм: вернём None, и
    механизм обновлений просто «молчит»."""
    now = time.time()
    cached = _MANIFEST_CACHE.get("data")
    if not force and cached is not None and (now - float(_MANIFEST_CACHE.get("ts") or 0.0)) < _MANIFEST_TTL:
        return cached
    try:
        req = urllib.request.Request(manifest_url(), headers={"User-Agent": "NeuroMita"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("voices"), dict):
            return cached
        _MANIFEST_CACHE["data"] = data
        _MANIFEST_CACHE["ts"] = now
        return data
    except Exception:
        return cached


def remote_entry(short_name: str, manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(manifest, dict):
        return None
    voices = manifest.get("voices")
    if not isinstance(voices, dict):
        return None
    entry = voices.get(short_name)
    return entry if isinstance(entry, dict) else None


# --- Локальный маркер установленных версий --------------------------------

def versions_store_path(base: Path | None = None) -> Path:
    root = base if base is not None else models_dir()
    return root / ".voice_versions.json"


def read_installed_versions(base: Path | None = None) -> dict[str, Any]:
    path = versions_store_path(base)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_installed_versions(data: dict[str, Any], base: Path | None = None) -> None:
    path = versions_store_path(base)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def installed_version(short_name: str, base: Path | None = None) -> dict[str, Any] | None:
    entry = read_installed_versions(base).get(short_name)
    return entry if isinstance(entry, dict) else None


def record_installed_version(short_name: str, entry: dict[str, Any] | None, base: Path | None = None) -> None:
    """Запомнить, какую версию голоса мы только что распаковали (дата/sha256/размер)."""
    data = read_installed_versions(base)
    if entry:
        data[short_name] = {k: entry.get(k) for k in ("date", "sha256", "size") if entry.get(k) is not None}
    else:
        data[short_name] = {}
    _write_installed_versions(data, base)


def clear_installed_version(short_name: str, base: Path | None = None) -> None:
    data = read_installed_versions(base)
    if short_name in data:
        data.pop(short_name, None)
        _write_installed_versions(data, base)


def is_update_available(short_name: str, manifest: dict[str, Any] | None, base: Path | None = None) -> bool:
    """Голос установлен, но версия на диске отличается от релизной.

    Сверяем по sha256 (если есть с обеих сторон), иначе по дате. Установленный
    голос без локального маркера (ставился до появления версионирования) считаем
    устаревшим — так пользователи со старой озвучкой получат перекачку."""
    if not is_installed(short_name):
        return False
    remote = remote_entry(short_name, manifest)
    if not remote:
        return False
    local = installed_version(short_name, base)
    if not local:
        return True
    r_sha, l_sha = remote.get("sha256"), local.get("sha256")
    if r_sha and l_sha:
        return str(r_sha) != str(l_sha)
    r_date, l_date = remote.get("date"), local.get("date")
    if r_date and l_date:
        return str(r_date) != str(l_date)
    # Недостаточно данных для сравнения — не дёргаем пользователя.
    return False


def bundle_cache_path(short_name: str, base: Path | None = None) -> Path:
    """Temp path the bundle archive is downloaded to before extraction."""
    root = base if base is not None else models_dir()
    return root / ".voice_cache" / f"{short_name}.zip"


def _expected_model_path(short_name: str) -> Path:
    """Provider-correct model file (.pth on NVIDIA, .onnx otherwise) — the same
    file the voice handlers load, so its presence is our "installed" signal."""
    # Imported lazily: utils.__init__ pulls in heavy siblings, and this module
    # must stay importable from plain file-op contexts (tests, CI).
    from utils import get_character_voice_paths

    return Path(get_character_voice_paths({"short_name": short_name})["pth_path"])


def is_installed(short_name: str) -> bool:
    """A voice is "installed" once a model file is present.

    Provider-agnostic on purpose: a bundle may ship only ``.pth`` (the ``.onnx``
    is optional), so an AMD/CPU machine — whose provider-correct extension is
    ``.onnx`` — would otherwise report a perfectly good ``.pth`` voice as "not
    installed" forever and re-download it on every run. Either model extension
    counts; the .index / reference .wav only refine quality and stay optional
    (the handlers already guard their existence)."""
    root = models_dir()
    if (root / f"{short_name}.pth").exists() or (root / f"{short_name}.onnx").exists():
        return True
    # Нестандартное расположение — спросим у общего резолвера путей.
    try:
        return _expected_model_path(short_name).exists()
    except Exception:
        return False


def extract_bundle(zip_path: str | Path, short_name: str, log: _Log = _noop, *, base: Path | None = None) -> bool:
    """Unpack ``<ShortName>.zip`` into the models directory.

    Tolerates a single ``Models/`` (or ``<ShortName>/``) wrapper folder inside
    the archive and guards against path traversal. Returns True on success.
    """
    zip_path = Path(zip_path)
    root = base if base is not None else models_dir()
    root.mkdir(parents=True, exist_ok=True)

    # Распаковываем во временный staging-каталог и лишь затем переносим файлы на
    # место. Так провал в середине (битый zip, нет места на диске) не оставляет
    # наполовину распакованный голос, который is_installed примет за рабочий.
    stage = root / f".stage_{short_name}"
    if stage.exists():
        shutil.rmtree(stage, ignore_errors=True)

    try:
        with zipfile.ZipFile(zip_path) as z:
            members = [m for m in z.infolist() if not m.is_dir()]
            if not members:
                log(f"Voice bundle {zip_path.name} is empty.")
                return False

            names = [m.filename.replace("\\", "/") for m in members]
            strip = _common_wrapper(names, short_name)

            staged: list[tuple[Path, Path]] = []  # (staged_path, final_path)
            for info in members:
                rel = info.filename.replace("\\", "/")
                if strip and rel.startswith(strip):
                    rel = rel[len(strip):]
                rel = rel.lstrip("/")
                if not rel or ".." in Path(rel).parts:
                    continue
                staged_path = stage / rel
                staged_path.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(staged_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                staged.append((staged_path, root / rel))

            if not staged:
                log(f"Voice bundle {zip_path.name} produced no usable files.")
                return False

            # Перенос на место: каждый файл — атомарный replace (та же ФС).
            written = 0
            for staged_path, final_path in staged:
                final_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged_path, final_path)
                written += 1
            log(f"Extracted {written} file(s) for {short_name} into {root}")
            return written > 0
    except zipfile.BadZipFile:
        log(f"Voice bundle {zip_path.name} is not a valid zip.")
        return False
    except Exception as exc:  # noqa: BLE001 — surface to install log, don't crash the task
        log(f"Failed to extract {zip_path.name}: {exc}")
        return False
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def _common_wrapper(names: Iterable[str], short_name: str) -> str:
    """Detect a single leading folder shared by every member, e.g. the archive
    was zipped as ``Models/Crazy.pth`` or ``CrazyMita/Crazy.pth``. Returns the
    prefix to strip (with trailing slash) or ""."""
    candidates = (f"Models/", f"{short_name}/")
    for prefix in candidates:
        if all(n.startswith(prefix) for n in names):
            return prefix
    return ""


def remove_assets(short_name: str, log: _Log = _noop, *, base: Path | None = None) -> bool:
    """Delete every runtime file belonging to ``short_name`` (both model
    extensions, index, reference audio/text, and the ``_Cuts`` defaults)."""
    root = base if base is not None else models_dir()
    targets = [
        root / f"{short_name}.pth",
        root / f"{short_name}.onnx",
        root / f"{short_name}.index",
        root / f"{short_name}.wav",
        root / f"{short_name}.txt",
        root / f"{short_name}_Cuts" / f"{short_name}_default.wav",
        root / f"{short_name}_Cuts" / f"{short_name}_default.txt",
    ]
    removed = 0
    for path in targets:
        try:
            if path.exists():
                path.unlink()
                removed += 1
        except OSError as exc:
            log(f"Could not remove {path.name}: {exc}")

    cuts = root / f"{short_name}_Cuts"
    try:
        if cuts.is_dir() and not any(cuts.iterdir()):
            cuts.rmdir()
    except OSError:
        pass

    log(f"Removed {removed} file(s) for {short_name}")

    # Успех меряем по факту: модельных файлов (.pth/.onnx) не осталось. Иначе при
    # залоченном файле (голос загружен в TTS) мы бы отрапортовали «удалено», хотя
    # голос на месте и is_installed по-прежнему True.
    model_left = (root / f"{short_name}.pth").exists() or (root / f"{short_name}.onnx").exists()
    if model_left:
        log(f"Voice {short_name} still has model files (possibly in use).")
        return False
    clear_installed_version(short_name, base=root)
    return True
