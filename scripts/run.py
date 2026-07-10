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
import shutil
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
PYTHON_SITE_PACKAGES = PYTHON.parent / "Lib" / "site-packages"
BOOTSTRAP_DIR = ROOT / ".bootstrap"
UV_TARGET = BOOTSTRAP_DIR / "uv"
UV_EXE = UV_TARGET / "bin" / ("uv.exe" if os.name == "nt" else "uv")

# uv по дефолту жёстко линкует файлы; на разных дисках это падает — копируем.
os.environ.setdefault("UV_LINK_MODE", "copy")


def log(msg: str) -> None:
    print(msg, flush=True)


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_CONFIG_FILE"] = os.devnull
    return env


def run(cmd: list, *, env: dict[str, str] | None = None) -> int:
    log("\n>>> " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=str(ROOT), env=env or _base_env()).returncode


def run_quiet(
    cmd: list,
    *,
    env: dict[str, str] | None = None,
    timeout: float = 8.0,
) -> bool:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env or _base_env(),
            timeout=max(0.1, float(timeout)),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def ensure_pip() -> None:
    if run_quiet([str(PYTHON), "-m", "pip", "--version"], timeout=5.0):
        return
    log("pip не найден во встроенном питоне, включаю ensurepip...")
    run([str(PYTHON), "-m", "ensurepip", "--upgrade"])


def ensure_uv() -> bool:
    if UV_EXE.is_file() and run_quiet([str(UV_EXE), "--version"], timeout=3.0):
        return True

    ensure_pip()
    if UV_TARGET.exists():
        try:
            shutil.rmtree(UV_TARGET)
        except OSError as exc:
            log(f"Не удалось очистить повреждённый приватный uv: {exc}. Использую pip.")
            return False

    UV_TARGET.mkdir(parents=True, exist_ok=True)
    log(f"uv не найден, устанавливаю изолированно в: {UV_TARGET}")
    install_cmd = [
        str(PYTHON),
        "-m",
        "pip",
        "--isolated",
        "install",
        "--target",
        str(UV_TARGET),
        "--upgrade",
        "--force-reinstall",
        "--no-warn-script-location",
        "uv",
    ]
    if run(install_cmd) != 0:
        log("Не удалось установить приватный uv. Использую встроенный pip.")
        return False
    if not UV_EXE.is_file() or not run_quiet([str(UV_EXE), "--version"], timeout=3.0):
        log("Приватный uv установился некорректно. Использую встроенный pip.")
        return False
    return True


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
    """Ставит зависимости в site-packages именно встроенного Python."""
    PYTHON_SITE_PACKAGES.mkdir(parents=True, exist_ok=True)
    log(f"Python: {PYTHON}")
    log(f"Зависимости: {PYTHON_SITE_PACKAGES}")
    log(f"Приватный uv: {UV_TARGET}")

    if ensure_uv():
        code = run([
            str(UV_EXE), "pip", "install",
            "-r", str(REQ_FILE),
            "--python", str(PYTHON),
            "--target", str(PYTHON_SITE_PACKAGES),
            "--no-cache-dir",
        ])
        if code == 0:
            return True
        log("\nuv не справился, пробую обычный pip...")

    # 2. Запасной путь — pip встроенного питона (он точно есть в нашей сборке).
    ensure_pip()
    code = run([
        str(PYTHON), "-m", "pip", "--isolated", "install",
        "-r", str(REQ_FILE),
        "--target", str(PYTHON_SITE_PACKAGES),
        "--upgrade",
        "--no-cache-dir",
    ])
    return code == 0


def pywin32_postinstall() -> None:
    """pywin32 нужно «прописать» после установки — иначе часть DLL не находится.
    Делаем по возможности, ошибки не критичны."""
    candidates = (
        ROOT / "libs" / "python" / "Scripts" / "pywin32_postinstall.py",
        PYTHON_SITE_PACKAGES / "pywin32_postinstall.py",
    )
    for script in candidates:
        if script.exists():
            run_quiet([str(PYTHON), str(script), "-install"], timeout=20.0)
            break


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
