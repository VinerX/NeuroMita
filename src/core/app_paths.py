from __future__ import annotations

import os
from pathlib import Path


def base_dir() -> Path:
    configured = str(os.environ.get("NEUROMITA_BASE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def settings_dir(*, create: bool = False) -> Path:
    path = base_dir() / "Settings"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path(*parts: str, create_parent: bool = False) -> Path:
    path = settings_dir(create=create_parent).joinpath(*parts)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def prompts_dir() -> Path:
    configured = str(os.environ.get("NEUROMITA_PROMPTS_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (base_dir() / "Prompts").resolve()


def prompt_path(configured: str | os.PathLike[str]) -> Path:
    """Резолвит путь к файлу промпта, заданный настройкой.

    Каталог промптов бывает вынесен из базовой папки (NEUROMITA_PROMPTS_DIR),
    поэтому относительный путь ищется сначала в нём — и с ведущим `Prompts/`,
    и без него, — и только потом рядом с базовой папкой. Отдаёт первый
    существующий вариант, иначе самый вероятный (он же попадёт в лог ошибки).
    """
    candidate = Path(configured).expanduser()
    if candidate.is_absolute():
        return candidate

    root = prompts_dir()
    variants = []
    parts = candidate.parts
    if parts and parts[0].lower() in {"prompts", root.name.lower()}:
        variants.append(root.joinpath(*parts[1:]))
    variants.append(root / candidate)
    variants.append(base_dir() / candidate)

    for variant in variants:
        if variant.is_file():
            return variant
    return variants[0]


def runtime_log_path() -> Path:
    configured = str(os.environ.get("NEUROMITA_LOG_PATH", "") or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = base_dir() / path
        return path.resolve()
    return base_dir() / "NeuroMitaLogs.log"
