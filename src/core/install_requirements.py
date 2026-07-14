from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Any, Dict, List, Tuple, FrozenSet
import os
import importlib.util
import importlib.machinery
from pathlib import Path

from core.backends import BackendKind, get_backend_service

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
    kind: str  # python_module | python_module_any | python_dist | file | backend
    required: bool = True

    module: Optional[str] = None
    modules: Tuple[str, ...] = ()

    spec: Optional[str] = None
    dist: Optional[str] = None

    path: Optional[str] = None
    path_fn: Optional[PathFn] = None

    when: Optional[WhenFn] = None
    backend_kind: Optional[BackendKind | str] = None


def _should_check(req: InstallRequirement, ctx: dict) -> bool:
    if req.when is None:
        return True
    try:
        return bool(req.when(ctx))
    except Exception:
        return False


def _target_paths(ctx: Optional[dict] = None) -> list[str]:
    ctx = ctx or {}
    values = [
        ctx.get("libs_dir"),
        ctx.get("lib_dir"),
        ctx.get("target_dir"),
        *(ctx.get("python_paths") or []),
    ]
    if not bool(ctx.get("strict_target", False)):
        values.append(os.environ.get("NEUROMITA_LIB_DIR"))
    result: list[str] = []
    for value in values:
        path = os.path.abspath(str(value or "").strip()) if value else ""
        if path and path not in result and os.path.isdir(path):
            result.append(path)
    return result


def _check_python_module(module: str, ctx: Optional[dict] = None) -> bool:
    if not module:
        return False
    parts = [part for part in str(module).split(".") if part]
    if not parts:
        return False
    # При явном --target сначала проверяем именно управляемый каталог. Иначе
    # пакет из системного/launcher site-packages мог замаскировать отсутствие
    # компонента в Lib либо его несовместимую версию.
    for root in _target_paths(ctx):
        candidate = Path(root).joinpath(*parts)
        if candidate.is_dir() or candidate.with_suffix(".py").is_file():
            return True
        try:
            if importlib.machinery.PathFinder.find_spec(parts[0], [root]) is not None:
                return True
        except Exception:
            pass
    if not bool((ctx or {}).get("strict_target", False)):
        try:
            if importlib.util.find_spec(module) is not None:
                return True
        except Exception:
            pass
    return False


def _check_any_python_module(modules: Tuple[str, ...], ctx: Optional[dict] = None) -> bool:
    return any(_check_python_module(module, ctx) for module in modules if str(module or "").strip())


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
            return _check_python_module(mod, _ctx)

        fn = _mod_check

    _PIP_CHECKERS[(base, ex_key)] = fn


def _get_installed_dist_version(dist: str, ctx: Optional[dict] = None) -> Optional[str]:
    if not dist:
        return None

    dn = dist.strip()
    candidates = [dn, dn.replace("_", "-"), dn.replace("-", "_")]

    wanted = _norm_pkg_name(dn)
    for root in _target_paths(ctx):
        try:
            for distribution in importlib_metadata.distributions(path=[root]):
                name = str(distribution.metadata.get("Name") or "")
                if _norm_pkg_name(name) == wanted:
                    return str(distribution.version)
        except Exception:
            continue

    if bool((ctx or {}).get("strict_target", False)):
        return None

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

        installed = _get_installed_dist_version(base, ctx)
        if installed:
            return True

        module_guess = base.replace("-", "_")
        return _check_python_module(module_guess, ctx)

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

    installed = _get_installed_dist_version(base, ctx)
    if installed:
        if req.specifier:
            try:
                if not bool(req.specifier.contains(installed, prereleases=True)):
                    return False
            except Exception:
                return False
        if fn is None:
            return True
        try:
            return bool(fn(s, ctx))
        except Exception:
            return False

    # Some embedded/portable layouts contain importable modules without usable
    # distribution metadata. Registered module checkers also verify that a
    # matching *.dist-info is not masking a missing or broken import package.
    if fn is not None:
        try:
            return bool(fn(s, ctx))
        except Exception:
            return False
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
    # Пакеты ставятся в --target Lib (он в sys.path с запуска). Но FileFinder
    # кэширует содержимое директорий в sys.path_importer_cache, поэтому пакет,
    # установленный посреди сессии, не виден find_spec/importlib.metadata до
    # перезапуска — из-за чего финальная проверка ложно падала «не найден»
    # (пакет фактически стоял и «повисал» установленным после перезахода).
    # Сбрасываем кэш, чтобы видеть свежую установку в той же сессии.
    try:
        importlib.invalidate_caches()
    except Exception:
        pass

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
            ok = _check_python_module(req.module or "", ctx)

        elif req.kind == "python_module_any":
            modules = tuple(str(item or "").strip() for item in req.modules if str(item or "").strip())
            extra["modules"] = list(modules)
            ok = _check_any_python_module(modules, ctx)

        elif req.kind == "python_dist":
            spec = (req.spec or "").strip()
            dist = (req.dist or "").strip()
            if spec:
                extra["spec"] = spec
                if not dist:
                    try:
                        from packaging.requirements import Requirement

                        dist = Requirement(spec).name
                    except Exception:
                        dist = spec.split(";", 1)[0].split("[", 1)[0].strip()
                if dist:
                    extra["dist"] = dist
                    extra["version"] = _get_installed_dist_version(dist, ctx)
                ok = is_pip_spec_satisfied(spec, ctx=ctx)
            elif dist:
                extra["dist"] = dist
                extra["version"] = _get_installed_dist_version(dist, ctx)
                ok = extra["version"] is not None
            else:
                ok = False
                extra["error"] = "python_dist requires spec or dist"

        elif req.kind == "file":
            p = _resolve_path(req, ctx)
            extra["path"] = p
            ok = bool(p) and os.path.exists(p)

        elif req.kind == "backend":
            backend_kind = req.backend_kind or BackendKind.NONE
            extra["backend_kind"] = str(getattr(backend_kind, "value", backend_kind))
            status = get_backend_service().get_status(backend_kind, ctx=ctx)
            ok = bool(status.ok)
            extra.update(status.as_dict())

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
        # Компонент считается установленным, если на месте все ОБЯЗАТЕЛЬНЫЕ
        # зависимости. Отсутствие опциональной (напр. pyaudio у Google-ASR) не
        # должно ронять is_installed() — иначе post-install check падал с
        # «missing: unknown» и компонент невозможно было поставить.
        # (all_ok здесь включал и опциональные провалы — это и был баг.)
        "ok": len(missing_required) == 0,
        "all_ok": all_ok,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "details": details,
    }


register_pip_checker("silero-vad", module="silero_vad")
register_pip_checker("openai-whisper", module="whisper")
register_pip_checker("onnxruntime-directml", module="onnxruntime")
register_pip_checker("optimum", extras=["onnxruntime"], module="optimum.onnxruntime")
register_pip_checker("g4f", module="g4f")
register_pip_checker("tts-with-rvc", module="tts_with_rvc")
register_pip_checker(
    "tts-with-rvc-onnx",
    fn=lambda _spec, ctx: _check_any_python_module(
        ("tts_with_rvc_onnx", "tts_with_rvc"),
        ctx,
    ),
)
