from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Any, Dict, List, Tuple, FrozenSet
import os
import importlib.util

try:
    from importlib import metadata as importlib_metadata  # py3.8+
except Exception:  # pragma: no cover
    import importlib_metadata  # type: ignore


WhenFn = Callable[[dict], bool]
PathFn = Callable[[dict], str]
PipCheckFn = Callable[[str, dict], bool]


@dataclass(frozen=True)
class InstallRequirement:
    id: str
    kind: str  # "python_module" | "python_dist" | "file"
    required: bool = True

    module: Optional[str] = None

    spec: Optional[str] = None
    dist: Optional[str] = None

    path: Optional[str] = None
    path_fn: Optional[PathFn] = None

    when: Optional[WhenFn] = None


def _should_check(req: InstallRequirement, ctx: dict) -> bool:
    if req.when is None:
        return True
    try:
        return bool(req.when(ctx))
    except Exception:
        return False


def _check_python_module(module: str) -> bool:
    if not module:
        return False
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def _resolve_path(req: InstallRequirement, ctx: dict) -> str:
    if req.path_fn is not None:
        return str(req.path_fn(ctx))
    return str(req.path or "")


_PIP_CHECKERS: Dict[Tuple[str, Optional[FrozenSet[str]]], PipCheckFn] = {}


def _norm_pkg_name(name: str) -> str:
    return (name or "").strip().lower().replace("_", "-")


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

    dn = dist.strip()
    candidates = [dn, dn.replace("_", "-"), dn.replace("-", "_")]

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
    s = str(spec or "").strip()
    if not s:
        return False

    try:
        from packaging.requirements import Requirement
    except Exception:
        base = _norm_pkg_name(s.split(";", 1)[0].strip())
        if not base:
            return False

        fn = _PIP_CHECKERS.get((base, None))
        if fn is not None:
            try:
                return bool(fn(spec, ctx))
            except Exception:
                return False

        installed = _get_installed_dist_version(base)
        if installed:
            return True

        module_guess = base.replace("-", "_")
        return _check_python_module(module_guess)

    try:
        req = Requirement(s)
    except Exception:
        return False

    try:
        if req.marker is not None and not req.marker.evaluate():
            return True
    except Exception:
        pass

    base = _norm_pkg_name(req.name)
    extras_key: Optional[FrozenSet[str]] = frozenset([e.strip().lower() for e in (req.extras or set()) if e.strip()]) or None

    fn = _PIP_CHECKERS.get((base, extras_key))
    if fn is None:
        fn = _PIP_CHECKERS.get((base, None))

    if fn is not None:
        try:
            return bool(fn(s, ctx))
        except Exception:
            return False

    installed = _get_installed_dist_version(base)
    if not installed:
        return False

    if not req.specifier:
        return True

    try:
        return bool(req.specifier.contains(installed, prereleases=True))
    except Exception:
        return False


def missing_pip_specs(specs: List[str], ctx: Optional[dict] = None) -> List[str]:
    ctx = ctx or {}
    missing: List[str] = []
    for s in specs or []:
        ss = str(s or "").strip()
        if not ss:
            continue
        if not is_pip_spec_satisfied(ss, ctx=ctx):
            missing.append(ss)
    return missing


def check_requirements(requirements: list[InstallRequirement], ctx: Optional[dict] = None) -> dict:
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

        elif req.kind == "python_dist":
            spec = (req.spec or "").strip()
            dist = (req.dist or "").strip()
            if spec:
                extra["spec"] = spec
                ok = is_pip_spec_satisfied(spec, ctx=ctx)
                if dist:
                    extra["dist"] = dist
                    extra["version"] = _get_installed_dist_version(dist)
            elif dist:
                extra["dist"] = dist
                extra["version"] = _get_installed_dist_version(dist)
                ok = extra["version"] is not None
            else:
                ok = False
                extra["error"] = "python_dist requires spec or dist"

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


register_pip_checker("silero-vad", module="silero_vad")
register_pip_checker("openai-whisper", module="whisper")
register_pip_checker("onnxruntime-directml", module="onnxruntime")
register_pip_checker("optimum", extras=["onnxruntime"], module="optimum.onnxruntime")