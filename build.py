import zipapp
import pathlib
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


PROJECT_DIR = Path(__file__).parent
env = load_env(PROJECT_DIR / "build.env")

OUTPUT_DIR = Path(env.get("BUILD_OUTPUT_DIR", str(PROJECT_DIR / "build_output")))
BUILD_MODE = env.get("BUILD_MODE", "full").lower()

# Папки: берём из BUILD_COPY_DIRS или дефолт
_copy_dirs_raw = env.get("BUILD_COPY_DIRS", "Prompts")
DIRS_TO_COPY: List[Tuple[Path, Path]] = [
    (PROJECT_DIR / d.strip(), OUTPUT_DIR / Path(d.strip()).name)
    for d in _copy_dirs_raw.split(",") if d.strip()
]

# Файлы: берём из BUILD_COPY_FILES или дефолт
_copy_files_raw = env.get("BUILD_COPY_FILES", "requirements.txt,extra/init.py,extra/Icon.png")
FILES_TO_COPY: List[Tuple[Path, Path]] = [
    (PROJECT_DIR / f.strip(), OUTPUT_DIR / Path(f.strip()).name)
    for f in _copy_files_raw.split(",") if f.strip()
]


def bin_filter(path: pathlib.Path) -> bool:
    excluded_parts = {"include", "Prompts", "PromptsCatalogue",
                      "ReadmeFiles", "MitaAiC#", "__pycache__"}
    if any(p in path.parts for p in excluded_parts):
        print(f"Игнорирую: {path}")
        return False
    if path.suffix in (".log", ".tmp", ".test", ".exe"):
        print(f"Игнорирую: {path}")
        return False
    print(f"Добавляю: {path}")
    return True


def copy_entries(entries: List[Tuple[Path, Path]]) -> None:
    for src, dst in entries:
        if src.is_file():
            print(f"Копирую файл {src} -> {dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elif src.is_dir():
            print(f"Копирую папку {src} -> {dst}")
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            print(f"Предупреждение: {src} не существует, пропускаю")


if __name__ == "__main__":
    print(f"Режим сборки : {BUILD_MODE}")
    print(f"Выходная папка: {OUTPUT_DIR}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pyz_filename = "NeuroMita.pyz"
    pyz_temp = PROJECT_DIR / pyz_filename
    pyz_dest = OUTPUT_DIR / pyz_filename

    print("\nСобираю .pyz архив...")
    zipapp.create_archive(
        source=str(PROJECT_DIR / "src"),
        target=str(pyz_temp),
        filter=bin_filter,
        compressed=True,
    )
    print(f"Архив собран: {pyz_temp}")

    print(f"Перемещаю в {pyz_dest}...")
    shutil.move(str(pyz_temp), str(pyz_dest))
    print(f"Готово: {pyz_dest}")

    if BUILD_MODE == "full":
        print("\nПолный режим — копирую дополнительные файлы...")
        copy_entries(DIRS_TO_COPY)
        copy_entries(FILES_TO_COPY)
    else:
        print("\nБыстрый режим — только .pyz.")

    print(f"\nСборка завершена! Результат: {OUTPUT_DIR}")
