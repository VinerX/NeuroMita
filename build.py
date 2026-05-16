import pathlib
import zipfile
import os
import shutil
from pathlib import Path
from typing import List, Tuple


def load_env(env_path: Path) -> dict:
    env = {}
    if not env_path.exists():
        return env
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def resolve_path(raw: str, base: Path) -> Path:
    """Абсолютный путь берём как есть, относительный — от base."""
    p = Path(raw)
    return p if p.is_absolute() else base / p


PROJECT_DIR = Path(__file__).parent
env = load_env(PROJECT_DIR / "build.env")

OUTPUT_DIR = Path(env.get("BUILD_OUTPUT_DIR", str(PROJECT_DIR / "build_output")))
BUILD_MODE = env.get("BUILD_MODE", "full").lower()

# Фильтровать dot-папки (.cache, .git и т.п.) при копировании папок
EXCLUDE_DOT_DIRS = env.get("BUILD_EXCLUDE_DOT_DIRS", "1") == "1"

# Папки для full-режима: поддержка абсолютных путей
_copy_dirs_raw = env.get("BUILD_COPY_DIRS", "Prompts")
DIRS_TO_COPY: List[Tuple[Path, Path]] = [
    (resolve_path(d.strip(), PROJECT_DIR), OUTPUT_DIR / Path(d.strip()).name)
    for d in _copy_dirs_raw.split(",") if d.strip()
]

# Папки для fast-режима
_fast_dirs_raw = env.get("BUILD_FAST_COPY_DIRS", "Prompts")
FAST_DIRS_TO_COPY: List[Tuple[Path, Path]] = [
    (resolve_path(d.strip(), PROJECT_DIR), OUTPUT_DIR / Path(d.strip()).name)
    for d in _fast_dirs_raw.split(",") if d.strip()
]

ALWAYS_DIRS_TO_COPY: List[Tuple[Path, Path]] = [
    (PROJECT_DIR / "assets" / "launcher_ui", OUTPUT_DIR / "assets" / "launcher_ui"),
]

# Файлы: поддержка абсолютных путей
_copy_files_raw = env.get("BUILD_COPY_FILES", "extra/init.py,extra/Icon.png")
FILES_TO_COPY: List[Tuple[Path, Path]] = [
    (resolve_path(f.strip(), PROJECT_DIR), OUTPUT_DIR / Path(f.strip()).name)
    for f in _copy_files_raw.split(",") if f.strip()
]

# Скрипты запуска/установки для копирования в корень билда
_root_scripts_raw = env.get("BUILD_ROOT_SCRIPTS", "")
ROOT_SCRIPTS: List[Tuple[Path, Path]] = [
    (resolve_path(s.strip(), PROJECT_DIR), OUTPUT_DIR / Path(s.strip()).name)
    for s in _root_scripts_raw.split(",") if s.strip()
]

# Части пути, исключаемые из pyz
EXCLUDED_PARTS = {
    "include", "Prompts", "PromptsCatalogue", "ReadmeFiles",
    "MitaAiC#", "__pycache__", "Testing",
}


def bin_filter(path: pathlib.Path) -> bool:
    for part in path.parts:
        if part.startswith("."):
            print(f"Игнорирую (dot): {path}")
            return False
        if part in EXCLUDED_PARTS:
            print(f"Игнорирую: {path}")
            return False
    if path.suffix in (".log", ".tmp", ".test", ".exe"):
        print(f"Игнорирую: {path}")
        return False
    print(f"Добавляю: {path}")
    return True


EXCLUDE_CHECKPOINTS = env.get("BUILD_EXCLUDE_CHECKPOINTS", "1") == "1"


def make_copy_ignore():
    """Возвращает ignore-функцию для shutil.copytree."""
    if not EXCLUDE_DOT_DIRS and not EXCLUDE_CHECKPOINTS:
        return None
    def ignore(directory, contents):
        ignored = []
        for name in contents:
            if EXCLUDE_DOT_DIRS and name.startswith("."):
                ignored.append(name)
            elif EXCLUDE_CHECKPOINTS and name == "checkpoints":
                ignored.append(name)
        if ignored:
            print(f"  Пропускаю в {directory}: {ignored}")
        return ignored
    return ignore


def copy_entries(entries: List[Tuple[Path, Path]]) -> None:
    ignore_fn = make_copy_ignore()
    for src, dst in entries:
        if src.is_file():
            print(f"Копирую файл {src} -> {dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elif src.is_dir():
            print(f"Копирую папку {src} -> {dst}")
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore_fn)
        else:
            print(f"Предупреждение: {src} не существует, пропускаю")


if __name__ == "__main__":
    print(f"Режим сборки        : {BUILD_MODE}")
    print(f"Выходная папка      : {OUTPUT_DIR}")
    print(f"Фильтр dot-папок    : {'вкл' if EXCLUDE_DOT_DIRS else 'выкл'}")
    print(f"Фильтр checkpoints  : {'вкл' if EXCLUDE_CHECKPOINTS else 'выкл'}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pyz_filename = "NeuroMita.pyz"
    pyz_temp = PROJECT_DIR / pyz_filename
    pyz_dest = OUTPUT_DIR / pyz_filename

    print("\nСобираю .pyz архив...")
    src_dir = PROJECT_DIR / "src"
    with open(pyz_temp, "wb") as fd:
        with zipfile.ZipFile(fd, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as zf:
            for path in sorted(src_dir.rglob("*")):
                if path.is_dir():
                    continue
                arcname = path.relative_to(src_dir)
                if not bin_filter(arcname):
                    continue
                zf.write(path, arcname)
    print(f"Архив собран: {pyz_temp}")

    print(f"Перемещаю в {pyz_dest}...")
    shutil.move(str(pyz_temp), str(pyz_dest))
    print(f"Готово: {pyz_dest}")

    # requirements.txt — всегда
    req = PROJECT_DIR / "requirements.txt"
    if req.exists():
        print(f"\nКопирую requirements.txt -> {OUTPUT_DIR / 'requirements.txt'}")
        shutil.copy2(req, OUTPUT_DIR / "requirements.txt")

    if BUILD_MODE == "full":
        print("\nПолный режим — копирую дополнительные файлы...")
        copy_entries(DIRS_TO_COPY)
        copy_entries(FILES_TO_COPY)
    else:
        print("\nБыстрый режим — .pyz + requirements.txt + быстрые папки...")
        copy_entries(FAST_DIRS_TO_COPY)

    print("\nКопирую обязательные launcher assets...")
    copy_entries(ALWAYS_DIRS_TO_COPY)

    if ROOT_SCRIPTS:
        print("\nКопирую скрипты запуска...")
        copy_entries(ROOT_SCRIPTS)

    if env.get("BUILD_ARCHIVE", "0") == "1":
        archive_path = env.get("BUILD_ARCHIVE_PATH")
        if not archive_path:
            print("\nПредупреждение: BUILD_ARCHIVE=1, но BUILD_ARCHIVE_PATH не задан — архив не создан.")
        else:
            archive_base = Path(archive_path)
            archive_base.parent.mkdir(parents=True, exist_ok=True)
            print(f"\nУпаковываю {OUTPUT_DIR} -> {archive_base}.zip ...")
            shutil.make_archive(str(archive_base), "zip", root_dir=OUTPUT_DIR.parent, base_dir=OUTPUT_DIR.name)
            print(f"Архив готов: {archive_base}.zip")

    print(f"\nСборка завершена! Результат: {OUTPUT_DIR}")
