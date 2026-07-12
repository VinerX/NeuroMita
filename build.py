import pathlib
import zipfile
import os
import shutil
import stat
import time
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

# Переменные окружения переопределяют build.env — удобно для разовой сборки
# (например, BUILD_OUTPUT_DIR в другую папку, если штатная занята запущенной игрой).
for _k, _v in os.environ.items():
    if _k.startswith("BUILD_") or _k in ("NEUROMITA_BACKEND", "LAUNCH_PYTHON"):
        env[_k] = _v

OUTPUT_DIR = Path(env.get("BUILD_OUTPUT_DIR", str(PROJECT_DIR / "build_output")))
BUILD_MODE = env.get("BUILD_MODE", "full").lower()
STRIP_EMBEDDED_UV = env.get("BUILD_STRIP_EMBEDDED_UV", "1") == "1"

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
    (PROJECT_DIR / "docs" / "wiki", OUTPUT_DIR / "docs" / "wiki"),
]

# Файлы, нужные в рантайме в ЛЮБОМ режиме сборки. init.py запускается шагом
# инициализации Triton/Fish Speech (subprocess из корня билда) — без него
# fast/промптерский билд падал с "can't open file init.py".
_always_files_raw = env.get("BUILD_ALWAYS_COPY_FILES", "extra/init.py")
ALWAYS_FILES_TO_COPY: List[Tuple[Path, Path]] = [
    (resolve_path(f.strip(), PROJECT_DIR), OUTPUT_DIR / Path(f.strip()).name)
    for f in _always_files_raw.split(",") if f.strip()
]

# Файлы только для full-режима: поддержка абсолютных путей
_copy_files_raw = env.get("BUILD_COPY_FILES", "extra/Icon.png")
FILES_TO_COPY: List[Tuple[Path, Path]] = [
    (resolve_path(f.strip(), PROJECT_DIR), OUTPUT_DIR / Path(f.strip()).name)
    for f in _copy_files_raw.split(",") if f.strip()
]

# Скрипты запуска/установки для копирования в корень билда.
# Launcher.exe — нативная (C) кнопка запуска: находит свою папку, проверяет
# libs\python\python.exe и запускает run.py (см. scripts/launcher.c). Копируется
# как есть, бинарь; вся логика установки/запуска — в run.py. run.bat оставляем
# как запасной вариант запуска без .exe.
_root_scripts_raw = env.get(
    "BUILD_ROOT_SCRIPTS",
    "scripts/Launcher.exe,scripts/run.bat,scripts/run.py,scripts/init_triton.bat",
)
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
EXCLUDE_MANAGED_BACKENDS = env.get("BUILD_EXCLUDE_MANAGED_BACKENDS", "1") == "1"

# В корневой Lib игра докладывает тяжёлые runtime/backend-пакеты уже на машине
# пользователя. В релизный zip не должны утекать следы локальной dev-среды:
# stale torch/torchaudio dist-info, CUDA-runtime и маркеры установленных
# бэкендов. Иначе первый запуск начинает "реактивный" reinstall того, что
# случайно попало в билд с машины сборки.
MANAGED_BACKEND_NAMES = {
    ".neuromita_backends.json",
    "torch",
    "torchaudio",
    "torchvision",
    "torchtext",
    "torchdata",
    "nvidia",
    "triton",
    "pytorch_triton",
}

# Чистить выходную папку перед сборкой, чтобы не тащить в зип мусор от прошлых
# сборок и запусков (Logs, Histories, Settings разработчика, scripts и т.п.).
# 1 — включено (по умолчанию), 0 — выключено.
CLEAN_OUTPUT = env.get("BUILD_CLEAN_OUTPUT", "1") == "1"


def clean_output_dir() -> None:
    """Полностью очищает OUTPUT_DIR перед сборкой. С защитой от опасных путей."""
    out = OUTPUT_DIR.resolve()

    # Защита: не даём случайно снести проект, диск целиком или короткий путь.
    if out == PROJECT_DIR.resolve():
        raise SystemExit("BUILD_OUTPUT_DIR совпадает с папкой проекта — очистка отменена.")
    if out == out.anchor or len(out.parts) < 3:
        raise SystemExit(f"BUILD_OUTPUT_DIR слишком близко к корню диска ({out}) — очистка отменена.")
    if PROJECT_DIR.resolve() in out.parents:
        raise SystemExit(f"BUILD_OUTPUT_DIR внутри проекта ({out}) — очистка отменена.")

    if out.exists():
        print(f"Очищаю выходную папку: {out}")
        _rmtree_robust(out)
    out.mkdir(parents=True, exist_ok=True)


def _clear_readonly_and_retry(func, path, _exc):
    """onexc/onerror-обработчик: снимает read-only и повторяет операцию.

    Если файл реально занят (запущенная игra/uv, антивирус) — повтор
    выбросит исключение, и _rmtree_robust перейдёт к следующей попытке.
    """
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    func(path)


def _rmtree_robust(target: Path, attempts: int = 4) -> None:
    """rmtree, устойчивый к read-only и временным блокировкам (антивирус)."""
    for attempt in range(1, attempts + 1):
        try:
            try:
                shutil.rmtree(target, onexc=_clear_readonly_and_retry)  # py3.12+
            except TypeError:
                shutil.rmtree(target, onerror=_clear_readonly_and_retry)  # py<3.12
            return
        except Exception as e:
            if attempt == attempts:
                raise SystemExit(
                    f"Не удалось очистить выходную папку {target}: {e}\n"
                    f"Похоже, файл занят — закрой запущенную игру/uv из этой папки "
                    f"(или временно антивирус) и собери снова."
                )
            print(f"  Попытка {attempt}/{attempts} не удалась ({e}); повтор через 1.5с...")
            time.sleep(1.5)


def make_copy_ignore():
    """Возвращает ignore-функцию для shutil.copytree."""
    if not EXCLUDE_DOT_DIRS and not EXCLUDE_CHECKPOINTS and not EXCLUDE_MANAGED_BACKENDS:
        return None
    def ignore(directory, contents):
        ignored = []
        dir_name = Path(directory).name.lower()
        for name in contents:
            if EXCLUDE_DOT_DIRS and name.startswith("."):
                ignored.append(name)
            elif EXCLUDE_CHECKPOINTS and name == "checkpoints":
                ignored.append(name)
            elif EXCLUDE_MANAGED_BACKENDS and dir_name in ("lib", "libs"):
                lower = name.lower()
                if (
                    lower in MANAGED_BACKEND_NAMES
                    or lower.startswith("torch-")
                    or lower.startswith("torchaudio-")
                    or lower.startswith("torchvision-")
                    or lower.startswith("torchtext-")
                    or lower.startswith("torchdata-")
                    or lower.startswith("nvidia-")
                    or lower.startswith("triton-")
                    or lower.startswith("pytorch_triton-")
                ):
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


def _remove_file_if_exists(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    path.unlink(missing_ok=True)
    return True


def _remove_tree_if_exists(path: Path) -> bool:
    if not path.exists():
        return False
    _rmtree_robust(path)
    return True


def strip_embedded_uv_runtime() -> None:
    """Drop uv artifacts from the copied embedded runtime.

    Build output must not contain a half-installed uv state where Scripts/uv.exe
    exists but the Python module/dist-info is missing. That combination makes the
    runtime try to self-heal via pip and often fails on Windows with Access
    Denied while uv.exe is locked. We either ship uv fully or not at all; for
    release builds the safer default is to strip it and let pip handle installs.
    """
    py_root = OUTPUT_DIR / "libs" / "python"
    if not py_root.exists():
        print("embedded python не найден — пропускаю очистку uv runtime.")
        return

    removed: list[str] = []

    scripts_dir = py_root / "Scripts"
    for name in ("uv.exe", "uvx.exe", "uv", "uvx"):
        path = scripts_dir / name
        if _remove_file_if_exists(path):
            removed.append(str(path.relative_to(OUTPUT_DIR)))

    site_packages = py_root / "Lib" / "site-packages"
    exact_paths = [
        site_packages / "uv",
        site_packages / "uv.py",
    ]
    for path in exact_paths:
        if path.is_dir() and _remove_tree_if_exists(path):
            removed.append(str(path.relative_to(OUTPUT_DIR)))
        elif path.is_file() and _remove_file_if_exists(path):
            removed.append(str(path.relative_to(OUTPUT_DIR)))

    if site_packages.exists():
        for pattern in ("uv-*.dist-info", "uv-*.data"):
            for path in sorted(site_packages.glob(pattern)):
                if path.is_dir() and _remove_tree_if_exists(path):
                    removed.append(str(path.relative_to(OUTPUT_DIR)))
                elif path.is_file() and _remove_file_if_exists(path):
                    removed.append(str(path.relative_to(OUTPUT_DIR)))

    if removed:
        print("Удалены uv-артефакты из embedded runtime:")
        for item in removed:
            print(f"  - {item}")
    else:
        print("uv-артефакты в embedded runtime не найдены.")


def create_flat_zip_from_directory(source_dir: Path, archive_base: Path) -> Path:
    """Create a zip archive whose root contains source_dir contents, not source_dir itself.

    This matches launcher update expectations: extracting the archive over an
    existing install should replace runtime files in-place instead of creating
    an extra top-level folder such as `neuromita_ci_build/`.
    """
    archive_path = archive_base.parent / f"{archive_base.name}.zip"
    if archive_path.exists():
        archive_path.unlink()

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            arcname = path.relative_to(source_dir)
            zf.write(path, arcname.as_posix())
    return archive_path


if __name__ == "__main__":
    print(f"Режим сборки        : {BUILD_MODE}")
    print(f"Выходная папка      : {OUTPUT_DIR}")
    print(f"Фильтр dot-папок    : {'вкл' if EXCLUDE_DOT_DIRS else 'выкл'}")
    print(f"Фильтр checkpoints  : {'вкл' if EXCLUDE_CHECKPOINTS else 'выкл'}")
    print(f"Фильтр backend Lib  : {'вкл' if EXCLUDE_MANAGED_BACKENDS else 'выкл'}")
    print(f"Очистка embedded uv : {'вкл' if STRIP_EMBEDDED_UV else 'выкл'}")
    print(f"Очистка output      : {'вкл' if CLEAN_OUTPUT else 'выкл'}")

    if CLEAN_OUTPUT:
        clean_output_dir()
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
    copy_entries(ALWAYS_FILES_TO_COPY)

    if ROOT_SCRIPTS:
        print("\nКопирую скрипты запуска...")
        copy_entries(ROOT_SCRIPTS)

    if STRIP_EMBEDDED_UV:
        print("\nОчищаю uv из embedded Python...")
        strip_embedded_uv_runtime()

    if env.get("BUILD_ARCHIVE", "0") == "1":
        archive_path = env.get("BUILD_ARCHIVE_PATH")
        if not archive_path:
            print("\nПредупреждение: BUILD_ARCHIVE=1, но BUILD_ARCHIVE_PATH не задан — архив не создан.")
        else:
            archive_base = Path(archive_path)
            archive_base.parent.mkdir(parents=True, exist_ok=True)
            print(f"\nУпаковываю {OUTPUT_DIR} -> {archive_base}.zip ...")
            archive_file = create_flat_zip_from_directory(OUTPUT_DIR, archive_base)
            print(f"Архив готов: {archive_file}")

    print(f"\nСборка завершена! Результат: {OUTPUT_DIR}")
