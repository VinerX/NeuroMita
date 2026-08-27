"""
Локальный лаунчер для PyCharm (в .gitignore).
1. Собирает fast-билд (build.py)
2. Отдаёт запуск боевому scripts/run.py во встроенном python билда —
   тот сам ставит зависимости в Lib/core и запускает игру (с рестартом по коду 42).

Раньше launch.py дублировал установку (uv pip install в site-packages) и запуск
(uv run NeuroMita.pyz). Это расходилось с боевым путём: run.py ставит core в
Lib/core и запускает `python -S` (site-packages намеренно отключён), поэтому
dev-запуск тестировал не то окружение, что едет пользователю. Теперь единая точка
правды — run.py.
"""
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

RUN_PY = OUTPUT_DIR / "run.py"


def run(cmd: list, cwd: Path = None):
    print(f"\n>>> {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"Ошибка (код {result.returncode}), прерываю.")
        sys.exit(result.returncode)


if __name__ == "__main__":
    # 1. Сборка (fast) — build.py положит в OUTPUT_DIR pyz, requirements.txt,
    #    Launcher.exe и run.py.
    print("=" * 50)
    print("Шаг 1: сборка (fast)")
    print("=" * 50)
    run([sys.executable, str(PROJECT_DIR / "build.py")])

    if not GAME_PYTHON.exists():
        print(f"Не найден встроенный python: {GAME_PYTHON}")
        print("Проверь BUILD_OUTPUT_DIR/libs или задай LAUNCH_PYTHON в build.env.")
        sys.exit(1)
    if not RUN_PY.exists():
        print(f"Не найден {RUN_PY} — проверь BUILD_ROOT_SCRIPTS (scripts/run.py).")
        sys.exit(1)

    # 2. Установка зависимостей + запуск игры — боевой run.py.
    #    Установку в Lib/core и рестарт по коду 42 он делает сам.
    print("=" * 50)
    print("Шаг 2: установка зависимостей и запуск (run.py)")
    print("=" * 50)
    run([str(GAME_PYTHON), str(RUN_PY)], cwd=OUTPUT_DIR)
