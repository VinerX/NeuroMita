# -*- coding: utf-8 -*-
"""
Лаунчер NeuroMita для готового билда (для промтеров).

Запускается встроенным питоном игры: libs\\python\\python.exe run.py
(см. run.bat). Делает то же, что launch.py при разработке, но без сборки:

1. Ставит минимальные зависимости из requirements.txt (один раз, пока
   requirements.txt не изменится) во встроенный питон.
2. Запускает NeuroMita.pyz этим же питоном.
3. Перезапускает игру, если апдейтер вернул код 42 (применил обновление).

Скрипт намеренно простой и устойчивый: ничего лишнего (torch, onnxruntime,
TTS) не ставит — тяжёлые бэкенды игра доустанавливает сама при первом
использовании.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

# Консоль может быть в cp866/cp1251 — переключаем вывод на utf-8, чтобы
# русский текст не падал с UnicodeEncodeError и читался при chcp 65001.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)  # встроенный питон игры (libs\python\python.exe)
REQ_FILE = ROOT / "requirements.txt"
HASH_FILE = ROOT / ".req_hash"
PYZ = ROOT / "NeuroMita.pyz"

# uv по дефолту жёстко линкует файлы; на разных дисках это падает — копируем.
os.environ.setdefault("UV_LINK_MODE", "copy")


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list) -> int:
    log("\n>>> " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def run_quiet(cmd: list) -> bool:
    return subprocess.run(
        cmd, cwd=str(ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def ensure_pip() -> None:
    if run_quiet([str(PYTHON), "-m", "pip", "--version"]):
        return
    log("pip не найден во встроенном питоне, включаю ensurepip...")
    run([str(PYTHON), "-m", "ensurepip", "--upgrade"])


def ensure_uv() -> bool:
    if run_quiet([str(PYTHON), "-m", "uv", "--version"]):
        return True

    ensure_pip()
    log("uv не найден во встроенном Python, устанавливаю его через python -m pip...")
    if run([str(PYTHON), "-m", "pip", "install", "--upgrade", "uv"]) != 0:
        log("Не удалось установить uv во встроенный Python.")
        return False
    return run_quiet([str(PYTHON), "-m", "uv", "--version"])


def file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def requirements_changed() -> bool:
    if not REQ_FILE.exists():
        return False
    current = file_hash(REQ_FILE)
    if HASH_FILE.exists() and HASH_FILE.read_text(encoding="utf-8").strip() == current:
        return False
    return True


def save_hash() -> None:
    HASH_FILE.write_text(file_hash(REQ_FILE), encoding="utf-8")


def install_requirements() -> bool:
    """Ставит зависимости во встроенный питон. Сначала uv, при неудаче — pip."""
    # 1. Предпочитаем встроенный uv.exe с явным таргетом на наш питон —
    #    без --python uv ищет venv/системный питон и падает с ошибкой про venv.
    if ensure_uv():
        code = run([
            str(PYTHON), "-m", "uv", "pip", "install",
            "-r", str(REQ_FILE),
            "--no-cache-dir",
        ])
        if code == 0:
            return True
        log("\nuv не справился, пробую обычный pip...")

    # 2. Запасной путь — pip встроенного питона (он точно есть в нашей сборке).
    ensure_pip()
    code = run([
        str(PYTHON), "-m", "pip", "install",
        "-r", str(REQ_FILE),
        "--no-cache-dir",
    ])
    return code == 0


def pywin32_postinstall() -> None:
    """pywin32 нужно «прописать» после установки — иначе часть DLL не находится.
    Делаем по возможности, ошибки не критичны."""
    script = ROOT / "libs" / "python" / "Scripts" / "pywin32_postinstall.py"
    if script.exists():
        run_quiet([str(PYTHON), str(script), "-install"])


def main() -> None:
    if not PYZ.exists():
        log(f"Не найден {PYZ.name} рядом с run.py — битый или неполный билд.")
        sys.exit(1)

    if requirements_changed():
        log("=" * 50)
        log("Первый запуск / обновление: ставлю зависимости...")
        log("=" * 50)
        if not install_requirements():
            log("\nНе удалось установить зависимости. Проверь интернет и запусти снова.")
            sys.exit(1)
        pywin32_postinstall()
        save_hash()
    else:
        log("Зависимости уже установлены — пропускаю установку.")

    # Запуск игры с перезапуском после автообновления (код выхода 42).
    while True:
        log("=" * 50)
        log("Запуск NeuroMita...")
        log("=" * 50)
        code = run([str(PYTHON), str(PYZ)])
        if code == 42:
            log("\nОбновление применено, перезапускаю...")
            continue
        sys.exit(code)


if __name__ == "__main__":
    main()
