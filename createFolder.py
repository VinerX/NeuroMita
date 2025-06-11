import os
import shutil
import subprocess
from pathlib import Path
import sys
from typing import List, Tuple

# Конфигурация - Если это юзает не VinerX, то меняй на свои пути! (не кидай в пул реквест)
PROJECT_DIR = Path(r"F:\Games\OpenAI_API_TEST\OpenMita")
STEAM_MODS_DIR = Path(r"F:\Games\steam2\steamapps\common\MiSide\Mods")
OUTPUT_DIR = PROJECT_DIR / "dist" / "NeuroMita"
VENV_PYINSTALLER = PROJECT_DIR / "venv" / "Scripts" / "pyinstaller.exe"
SEVEN_ZIP_PATH = r"C:\Program Files\7-Zip\7z.exe"  # Путь к 7-Zip

FINAL_ZIP_NAME = "NeuroMita "+"0."+"011"+"MitaWorld"+"Test"+".7z"

# Файлы для копирования
FILES_TO_COPY = [
    (STEAM_MODS_DIR / "MitaAI.dll", OUTPUT_DIR),
    (STEAM_MODS_DIR / "assetbundle.test", OUTPUT_DIR),
    (PROJECT_DIR / "init.py", OUTPUT_DIR),
    (PROJECT_DIR / "init_triton.bat", OUTPUT_DIR),
    (PROJECT_DIR / "ffmpeg.exe", OUTPUT_DIR),
    (PROJECT_DIR / "icon.png", OUTPUT_DIR),
]

# Папки для копирования (рекурсивно)
DIRS_TO_COPY = [
    (PROJECT_DIR / "libs", OUTPUT_DIR / "libs"),
    (PROJECT_DIR / "include", OUTPUT_DIR / "include"),
    (PROJECT_DIR / "Prompts", OUTPUT_DIR / "Prompts"),
]


def run_command(command: List[str], cwd: str = None) -> bool:
    """Запускает команду и возвращает True при успехе"""
    try:
        print(f"Выполняю команду: {' '.join(command)}")
        result = subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при выполнении команды:\n{e}")
        return False


def copy_files(files: List[Tuple[Path, Path]]) -> None:
    """Копирует файлы и папки"""
    for src, dst in files:
        if src.is_file():
            print(f"Копирую файл {src} -> {dst}")
            os.makedirs(dst.parent, exist_ok=True)
            shutil.copy2(src, dst)
        elif src.is_dir():
            print(f"Копирую папку {src} -> {dst}")
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            print(f"Предупреждение: {src} не существует и будет пропущен")


def build_with_pyinstaller() -> bool:
    """Запускает сборку с PyInstaller"""
    pyinstaller_cmd = [
        str(VENV_PYINSTALLER),
        "--name", "NeuroMita",
        "--noconfirm",
        "--add-data", f"{PROJECT_DIR / 'Prompts'}/*;Prompts",
        "--add-data", f"{PROJECT_DIR / 'Prompts'}/**/*;Prompts",
        str(PROJECT_DIR / "Main.py")
    ]
    return run_command(pyinstaller_cmd, cwd=str(PROJECT_DIR))


def create_7z_archive() -> bool:
    """Создает 7z архив с собранным проектом"""
    if not os.path.exists(SEVEN_ZIP_PATH):
        print("7-Zip не найден, пропускаю создание архива")
        return False

    archive_path = PROJECT_DIR / "dist" / FINAL_ZIP_NAME
    if archive_path.exists():
        print(f"Удаляю существующий архив {archive_path}")
        archive_path.unlink()

    cmd = [
        SEVEN_ZIP_PATH,
        "a", "-t7z",
        str(archive_path),
        str(OUTPUT_DIR / "*")
    ]

    if run_command(cmd):
        print(f"Архив успешно создан: {archive_path}")
        return True
    return False


def main():
    print("=== Начало процесса сборки ===")

    # Шаг 1: Сборка с PyInstaller
    if not build_with_pyinstaller():
        print("Ошибка при сборке с PyInstaller!")
        sys.exit(1)

    # Шаг 2: Копирование дополнительных файлов
    print("\n=== Копирование дополнительных файлов ===")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    copy_files(FILES_TO_COPY)
    copy_files(DIRS_TO_COPY)

    # Шаг 3: Создание архива (опционально)
    print("\n=== Создание архива ===")
    create_7z_archive()

    print("\n=== Сборка успешно завершена ===")
    input("Нажмите Enter для выхода...")


if __name__ == "__main__":
    main()