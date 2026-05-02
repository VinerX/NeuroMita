"""
Локальный лаунчер для PyCharm (в .gitignore).
1. Собирает fast-билд (build.py)
2. Если requirements.txt изменился — запускает uv pip install
3. Запускает игру
"""
import hashlib
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent


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


env = load_env(PROJECT_DIR / "build.env")

OUTPUT_DIR = Path(env.get("BUILD_OUTPUT_DIR", str(PROJECT_DIR / "build_output")))

# Путь к python игры — можно переопределить через LAUNCH_PYTHON в build.env
_default_python = str(OUTPUT_DIR / "libs" / "python" / "python.exe")
GAME_PYTHON = Path(env.get("LAUNCH_PYTHON", _default_python))

# GPU_VENDOR: none | nvidia | amd  (по умолчанию none)
GPU_VENDOR = env.get("GPU_VENDOR", "none").strip().lower()
_GPU_EXTRA_PKG = {
    "nvidia": "onnxruntime",
    "amd":    "onnxruntime-directml",
}

REQ_FILE = OUTPUT_DIR / "requirements.txt"
HASH_FILE = OUTPUT_DIR / ".req_hash"
UV_EXE = GAME_PYTHON.parent / "Scripts" / "uv.exe"


def file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def requirements_changed() -> bool:
    if not REQ_FILE.exists():
        return False
    current = file_hash(REQ_FILE)
    if HASH_FILE.exists() and HASH_FILE.read_text().strip() == current:
        return False
    return True


def save_hash():
    HASH_FILE.write_text(file_hash(REQ_FILE))


def run(cmd: list, cwd: Path = None):
    print(f"\n>>> {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"Ошибка (код {result.returncode}), прерываю.")
        sys.exit(result.returncode)


def run_quiet(cmd: list, cwd: Path = None) -> bool:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def ensure_pip():
    if run_quiet([str(GAME_PYTHON), "-m", "pip", "--version"], cwd=OUTPUT_DIR):
        return
    print("pip не найден во встроенном Python, включаю ensurepip...")
    run([str(GAME_PYTHON), "-m", "ensurepip", "--upgrade"], cwd=OUTPUT_DIR)


def resolve_uv_cmd() -> list:
    if run_quiet([str(GAME_PYTHON), "-m", "uv", "--version"], cwd=OUTPUT_DIR):
        return [str(GAME_PYTHON), "-m", "uv"]
    if UV_EXE.exists():
        return [str(UV_EXE)]

    print("uv не найден, устанавливаю его во встроенный Python...")
    ensure_pip()
    run([str(GAME_PYTHON), "-m", "pip", "install", "--upgrade", "uv", "--no-cache-dir"], cwd=OUTPUT_DIR)

    if run_quiet([str(GAME_PYTHON), "-m", "uv", "--version"], cwd=OUTPUT_DIR):
        return [str(GAME_PYTHON), "-m", "uv"]
    if UV_EXE.exists():
        return [str(UV_EXE)]

    print("Не удалось подготовить uv, прерываю.")
    sys.exit(1)


if __name__ == "__main__":
    # 1. Сборка
    print("=" * 50)
    print("Шаг 1: сборка (fast)")
    print("=" * 50)
    run([sys.executable, str(PROJECT_DIR / "build.py")])

    uv_cmd = resolve_uv_cmd()

    # 2. Обновление зависимостей если нужно
    if requirements_changed():
        print("=" * 50)
        print("Шаг 2: requirements.txt изменился — обновляю зависимости")
        print("=" * 50)
        _install_scripts = {
            "nvidia": "scripts/install_nvidia.cmd",
            "amd":    "scripts/install_amd.cmd",
        }
        install_script = _install_scripts.get(GPU_VENDOR)
        if install_script:
            script_path = OUTPUT_DIR / install_script
            print(f"GPU_VENDOR={GPU_VENDOR!r}, запускаю {script_path}")
            run(["cmd", "/c", str(script_path)], cwd=OUTPUT_DIR)
        else:
            print("GPU_VENDOR=none, устанавливаю только requirements.txt")
            run(uv_cmd + ["pip", "install",
                 "-r", str(REQ_FILE), "--no-cache-dir"], cwd=OUTPUT_DIR)
        save_hash()
    else:
        print("\nШаг 2: requirements.txt не изменился — пропускаю.")

    # 3. Запуск игры (с перезапуском после автообновления)
    # Exit code 42 означает что updater применил обновление и нужен рестарт.
    game_cmd = uv_cmd + ["run", "NeuroMita.pyz"]
    while True:
        print("=" * 50)
        print("Шаг 3: запуск игры")
        print("=" * 50)
        print(f"\n>>> {' '.join(str(c) for c in game_cmd)}")
        result = subprocess.run(game_cmd, cwd=OUTPUT_DIR)
        if result.returncode == 42:
            print("\nОбновление применено, перезапускаю...")
        elif result.returncode != 0:
            print(f"Ошибка (код {result.returncode}), прерываю.")
            sys.exit(result.returncode)
        else:
            break
