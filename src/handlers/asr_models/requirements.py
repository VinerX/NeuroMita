# src/handlers/asr_models/requirements.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Any, Dict, List, Tuple, FrozenSet
import os
import re
import importlib.util

try:
    from importlib import metadata as importlib_metadata  # py3.8+
except Exception:  # pragma: no cover
    import importlib_metadata  # type: ignore


WhenFn = Callable[[dict], bool]
PathFn = Callable[[dict], str]
PipCheckFn = Callable[[str, dict], bool]


@dataclass(frozen=True)
class AsrRequirement:
    id: str
    kind: str  # "python_module" | "file"
    required: bool = True

    module: Optional[str] = None

    path: Optional[str] = None
    path_fn: Optional[PathFn] = None

    when: Optional[WhenFn] = None


def _should_check(req: AsrRequirement, ctx: dict) -> bool:
    if req.when is None:
        return True
    try:
        return bool(req.when(ctx))
    except Exception:
        return False


def _check_python_module(module: str) -> bool:
    """
    Важно: find_spec("a.b") может кинуть ModuleNotFoundError,
    если нет пакета "a". Нам нужна безопасная проверка: True/False без исключений.
    """
    if not module:
        return False
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def _resolve_path(req: AsrRequirement, ctx: dict) -> str:
    if req.path_fn is not None:
        return str(req.path_fn(ctx))
    return str(req.path or "")


def check_requirements(requirements: list[AsrRequirement], ctx: Optional[dict] = None) -> dict:
    """
    Возвращает:
    {
      "ok": bool,
      "missing_required": [req_id...],
      "missing_optional": [req_id...],
      "details": [{"id":..,"kind":..,"required":..,"ok":..,"extra":{...}}]
    }
    """
    ctx = ctx or {}
    missing_required: list[str] = []
    missing_optional: list[str] = []
    details: list[dict[str, Any]] = []

    all_ok = True

    for req in requirements or []:
        if not _should_check(req, ctx):
            details.append({"id": req.id, "kind": req.kind, "required": req.required, "ok": True, "skipped": True})
            continue

        ok = True
        extra: dict[str, Any] = {}

        if req.kind == "python_module":
            extra["module"] = req.module
            ok = _check_python_module(req.module or "")

        elif req.kind == "file":
            p = _resolve_path(req, ctx)
            extra["path"] = p
            ok = bool(p) and os.path.exists(p)

        else:
            ok = False
            extra["error"] = f"Unknown requirement kind: {req.kind}"

        details.append({"id": req.id, "kind": req.kind, "required": req.required, "ok": ok, "extra": extra})

        if not ok:
            all_ok = False
            if req.required:
                missing_required.append(req.id)
            else:
                missing_optional.append(req.id)

    return {
        "ok": all_ok and len(missing_required) == 0,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "details": details,
    }


_PIP_CHECKERS: Dict[Tuple[str, Optional[FrozenSet[str]]], PipCheckFn] = {}


def _norm_pkg_name(name: str) -> str:
    return (name or "").strip().lower().replace("_", "-")


def _parse_pip_spec(spec: str) -> Tuple[str, FrozenSet[str], Optional[str]]:
    s = str(spec or "").strip()
    if not s:
        return "", frozenset(), None

    s = s.split(";", 1)[0].strip()

    m = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*(\[[A-Za-z0-9_,.\-]+\])?\s*(.*)$", s)
    if not m:
        return _norm_pkg_name(s), frozenset(), None

    base = _norm_pkg_name(m.group(1) or "")
    extras_raw = (m.group(2) or "").strip()
    rest = (m.group(3) or "").strip()

    extras: List[str] = []
    if extras_raw.startswith("[") and extras_raw.endswith("]"):
        inner = extras_raw[1:-1].strip()
        if inner:
            extras = [x.strip().lower() for x in inner.split(",") if x.strip()]

    pinned = None
    mv = re.search(r"==\s*([A-Za-z0-9_.+\-]+)", rest)
    if mv:
        pinned = (mv.group(1) or "").strip()

    return base, frozenset(extras), pinned


def register_pip_checker(
    package: str,
    *,
    extras: Optional[List[str]] = None,
    module: Optional[str] = None,
    fn: Optional[PipCheckFn] = None,
) -> None:
    base = _norm_pkg_name(package)
    ex_key = None if extras is None else frozenset([e.strip().lower() for e in extras if e.strip()])

    if fn is None:
        mod = str(module or "").strip()
        if not mod:
            raise ValueError("register_pip_checker: either module or fn must be provided")

        def _mod_check(_spec: str, _ctx: dict) -> bool:
            return _check_python_module(mod)

        fn = _mod_check

    _PIP_CHECKERS[(base, ex_key)] = fn


def _get_installed_dist_version(dist: str) -> Optional[str]:
    if not dist:
        return None
    candidates = []
    dn = dist.strip()
    if dn:
        candidates.append(dn)
        candidates.append(dn.replace("_", "-"))
        candidates.append(dn.replace("-", "_"))

    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            return str(importlib_metadata.version(c))
        except Exception:
            continue
    return None


def is_pip_spec_satisfied(spec: str, ctx: Optional[dict] = None) -> bool:
    ctx = ctx or {}
    base, extras, pinned = _parse_pip_spec(spec)
    if not base:
        return False

    fn = _PIP_CHECKERS.get((base, extras))
    if fn is None:
        fn = _PIP_CHECKERS.get((base, None))

    if fn is not None:
        try:
            return bool(fn(spec, ctx))
        except Exception:
            return False

    if pinned:
        installed = _get_installed_dist_version(base)
        if installed:
            installed_core = installed.split("+", 1)[0].strip()
            pinned_core = pinned.split("+", 1)[0].strip()
            if installed_core != pinned_core:
                return False
        else:
            return False

    module_guess = base.replace("-", "_")
    return _check_python_module(module_guess)


def missing_pip_specs(specs: List[str], ctx: Optional[dict] = None) -> List[str]:
    missing: List[str] = []
    for s in specs or []:
        if not is_pip_spec_satisfied(str(s), ctx=ctx):
            missing.append(str(s))
    return missing


register_pip_checker("silero-vad", module="silero_vad")
register_pip_checker("openai-whisper", module="whisper")
register_pip_checker("onnxruntime-directml", module="onnxruntime")
register_pip_checker("optimum", extras=["onnxruntime"], module="optimum.onnxruntime")