from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import site
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Callable


_SHARED_WORKER = "shared"
_SHARED_SERVICES = ("tts", "asr", "rag", "beats")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return max(minimum, int(default))


def _env_float(name: str, default: float, minimum: float = 0.1) -> float:
    try:
        return max(minimum, float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return max(minimum, float(default))


_DLL_DIRECTORY_HANDLES: list[Any] = []


def _runtime_target_path(paths: list[str]) -> str | None:
    fallback: str | None = None
    for raw_path in paths:
        path = Path(raw_path)
        try:
            manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        if manifest.get("logical_id"):
            return str(path)
        if manifest.get("layer_id"):
            continue
        if "bases" not in {part.casefold() for part in path.parts} and fallback is None:
            fallback = str(path)
    return fallback


def _configure_torch_compile_cache(runtime_root: str) -> None:
    """Configure one persistent TorchInductor/Triton cache for all AI overlays."""
    environment_root = os.path.abspath(
        os.environ.get("NEUROMITA_ENVIRONMENT_DIR")
        or os.path.join(runtime_root, "environment")
    )
    cache_root = os.path.join(environment_root, "cache")

    try:
        os.makedirs(cache_root, exist_ok=True)
    except OSError:
        return

    os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", os.path.join(cache_root, "torchinductor"))
    os.environ.setdefault("TRITON_CACHE_DIR", os.path.join(cache_root, "triton"))
    os.environ.setdefault("TORCHINDUCTOR_FX_GRAPH_CACHE", "1")


def _activate_site_directories(paths: list[str]) -> list[str]:
    """Activate `.pth` entries while preserving managed-layer precedence."""
    declared_by_root: dict[str, list[str]] = {}
    predeclared: list[str] = []
    for root in paths:
        declared: list[str] = []
        try:
            pth_files = sorted(Path(root).glob("*.pth"))
        except OSError:
            pth_files = []
        for pth_file in pth_files:
            try:
                lines = pth_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            except OSError:
                continue
            for raw_line in lines:
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith(("import ", "import\t")):
                    continue
                candidate = os.path.abspath(os.path.join(root, line))
                if os.path.isdir(candidate) and candidate not in declared:
                    declared.append(candidate)
        declared_by_root[root] = declared
        predeclared.extend(declared)

    preseeded = list(dict.fromkeys([*paths, *predeclared]))
    preseeded_normalized = {
        os.path.normcase(os.path.abspath(path)) for path in preseeded
    }
    sys.path[:] = [
        path
        for path in sys.path
        if os.path.normcase(os.path.abspath(path)) not in preseeded_normalized
    ]
    sys.path[:0] = preseeded

    activated_by_root: list[tuple[str, list[str]]] = []

    for root in paths:
        before = {
            os.path.normcase(os.path.abspath(path))
            for path in sys.path
            if path
        }
        site.addsitedir(root)
        additions: list[str] = []
        for path in sys.path:
            normalized = os.path.normcase(os.path.abspath(path))
            if not path or normalized in before:
                continue
            additions.append(os.path.abspath(path))
            before.add(normalized)
        activated_by_root.append((root, [*declared_by_root.get(root, ()), *additions]))

    managed_paths: list[str] = []
    managed_normalized: set[str] = set()
    for root, additions in activated_by_root:
        for path in (root, *additions):
            normalized = os.path.normcase(os.path.abspath(path))
            if normalized in managed_normalized:
                continue
            managed_normalized.add(normalized)
            managed_paths.append(os.path.abspath(path))

    sys.path[:] = [
        path
        for path in sys.path
        if os.path.normcase(os.path.abspath(path)) not in managed_normalized
    ]
    sys.path[:0] = managed_paths
    return managed_paths


def _ensure_lib_on_path(python_paths: tuple[str, ...] | list[str] | None = None) -> None:
    main_core = os.path.abspath(
        os.environ.get("NEUROMITA_CORE_DIR")
        or os.environ.get("NEUROMITA_LIB_DIR")
        or os.path.join("Lib", "core")
    )
    runtime_root = os.path.abspath(
        os.environ.get("NEUROMITA_RUNTIME_ROOT") or os.path.dirname(main_core)
    )
    _configure_torch_compile_cache(runtime_root)
    embedded_python = os.path.abspath(
        os.environ.get("NEUROMITA_PYTHON") or sys.executable
    )
    embedded_site_packages = os.path.abspath(
        os.path.join(os.path.dirname(embedded_python), "Lib", "site-packages")
    )
    explicit_paths = [
        os.path.abspath(str(path))
        for path in (python_paths or ())
        if str(path).strip()
    ]
    ordered = list(dict.fromkeys(
        explicit_paths + ([main_core] if os.path.isdir(main_core) else [])
    ))
    os.environ["NEUROMITA_AI_WORKER"] = "1"
    runtime_target = _runtime_target_path(explicit_paths)
    if runtime_target:
        os.environ["NEUROMITA_RUNTIME_TARGET_DIR"] = runtime_target
    else:
        os.environ.pop("NEUROMITA_RUNTIME_TARGET_DIR", None)
    os.environ["NEUROMITA_RUNTIME_PYTHON_PATHS"] = os.pathsep.join(ordered)

    excluded = {os.path.normcase(path) for path in ordered}
    runtime_root_normalized = os.path.normcase(runtime_root)
    runtime_root_prefix = os.path.normcase(runtime_root + os.sep)
    embedded_site_normalized = os.path.normcase(embedded_site_packages)

    def should_keep(path: str) -> bool:
        absolute = os.path.abspath(path or "")
        normalized = os.path.normcase(absolute)
        if normalized in excluded or normalized == embedded_site_normalized:
            return False
        if normalized == runtime_root_normalized or normalized.startswith(runtime_root_prefix):
            return False
        return True

    sys.path = [
        path for path in sys.path if should_keep(path)
    ]
    sys.path[:0] = ordered
    _activate_site_directories(ordered)

    if os.name == "nt":
        inherited_path = []
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            normalized_entry = os.path.normcase(os.path.abspath(entry or "."))
            if normalized_entry == runtime_root_normalized or normalized_entry.startswith(
                runtime_root_prefix
            ):
                continue
            inherited_path.append(entry)
        os.environ["PATH"] = os.pathsep.join(inherited_path)

        path_entries: list[str] = []
        # Only AI environment roots participate in native DLL lookup. The
        # stable application core is a Python fallback layer and must not
        # shadow backend-specific Torch/ONNX DLLs.
        for root in explicit_paths:
            for candidate in (
                root,
                os.path.join(root, "torch", "lib"),
                os.path.join(root, "onnxruntime", "capi"),
            ):
                if not os.path.isdir(candidate):
                    continue
                path_entries.append(candidate)
                add_dll_directory = getattr(os, "add_dll_directory", None)
                if callable(add_dll_directory):
                    try:
                        _DLL_DIRECTORY_HANDLES.append(add_dll_directory(candidate))
                    except OSError:
                        pass
        if path_entries:
            os.environ["PATH"] = os.pathsep.join(path_entries + [os.environ.get("PATH", "")])


def _log(log_queue, level: str, message: str, *, detail: str | None = None) -> None:
    try:
        payload = {"level": str(level), "message": str(message)}
        if detail:
            payload["detail"] = str(detail)
        log_queue.put_nowait(payload)
    except Exception:
        pass


def _services_for_worker(
    worker_name: str,
    explicit_services: tuple[str, ...] | list[str] | None = None,
) -> tuple[str, ...]:
    if explicit_services:
        normalized = tuple(
            str(service).strip().lower()
            for service in explicit_services
            if str(service).strip()
        )
        if normalized:
            return normalized
    wn = str(worker_name or "").strip().lower()
    if wn == _SHARED_WORKER:
        return _SHARED_SERVICES
    if wn in _SHARED_SERVICES:
        return (wn,)
    raise RuntimeError(f"Unknown worker_name: {worker_name}")


def _probe_runtime_modules(
    probe_modules: tuple[str, ...] | list[str] | None,
    *,
    log_queue=None,
) -> None:
    importlib.invalidate_caches()
    for module_name in tuple(dict.fromkeys(probe_modules or ())):
        normalized = str(module_name or "").strip()
        if not normalized:
            continue
        if log_queue is not None:
            _log(log_queue, "info", f"Bootstrap: importing backend module '{normalized}'")
        try:
            importlib.import_module(normalized)
        except Exception as exc:
            raise RuntimeError(
                f"AI runtime probe failed while importing '{normalized}': {exc}"
            ) from exc


def _runtime_capabilities(
    python_paths: tuple[str, ...] | list[str] | None,
) -> set[str]:
    capabilities: set[str] = set()
    for raw_path in python_paths or ():
        manifest = Path(str(raw_path)).resolve().parent / "manifest.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        capabilities.update(str(item) for item in data.get("capabilities") or ())
    return capabilities


def _configure_openmp_compatibility(
    python_paths: tuple[str, ...] | list[str] | None,
    *,
    log_queue=None,
) -> bool:
    if os.name != "nt":
        return False
    capabilities = _runtime_capabilities(python_paths)
    has_onnx = any(item.startswith("onnx.") for item in capabilities)
    if not has_onnx:
        return False
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    if log_queue is not None:
        _log(
            log_queue,
            "warning",
            "Bootstrap: enabled OpenMP compatibility for Windows ONNX runtime",
        )
    return True


def _probe_runtime_capabilities(
    python_paths: tuple[str, ...] | list[str] | None,
) -> None:
    capabilities = _runtime_capabilities(python_paths)

    if any(item.startswith("torch.") for item in capabilities):
        import torch

        probe = torch.tensor([1.0, 2.0]) + 1.0
        if probe.tolist() != [2.0, 3.0]:
            raise RuntimeError("PyTorch CPU execution probe returned an invalid result")
        if any(item.startswith("torch.cuda") for item in capabilities):
            if not getattr(torch.version, "cuda", None) or not torch.cuda.is_available():
                raise RuntimeError("CUDA backend was installed, but CUDA is unavailable")
            cuda_probe = torch.tensor([1.0], device="cuda") + 1.0
            torch.cuda.synchronize()
            if float(cuda_probe.cpu().item()) != 2.0:
                raise RuntimeError("PyTorch CUDA execution probe returned an invalid result")

    if any(item.startswith("onnx.") for item in capabilities):
        import onnxruntime

        providers = set(onnxruntime.get_available_providers())
        if "CPUExecutionProvider" not in providers:
            raise RuntimeError("ONNX Runtime has no CPUExecutionProvider")
        if "onnx.dml" in capabilities and "DmlExecutionProvider" not in providers:
            raise RuntimeError("ONNX DirectML backend has no DmlExecutionProvider")


def run_worker_process(
    worker_name: str,
    cmd_queue,
    res_queue,
    log_queue,
    service_names: tuple[str, ...] | list[str] | None = None,
    python_paths: tuple[str, ...] | list[str] | None = None,
    probe_modules: tuple[str, ...] | list[str] | None = None,
) -> None:
    """
    Универсальный worker-процесс для AI сервисов.

    worker_name:
      - "tts"    -> отдельный worker только для TTS
      - "asr"    -> отдельный worker только для ASR
      - "shared" -> один worker для TTS + ASR
    """
    try:
        _configure_openmp_compatibility(python_paths, log_queue=log_queue)
        _log(log_queue, "info", "Bootstrap: configuring isolated runtime paths")
        _ensure_lib_on_path(python_paths)
        _log(
            log_queue,
            "info",
            "Bootstrap: using shared TorchInductor cache "
            f"'{os.environ.get('TORCHINDUCTOR_CACHE_DIR', '')}'",
        )
        _probe_runtime_modules(probe_modules, log_queue=log_queue)
        _log(log_queue, "info", "Bootstrap: validating backend capabilities")
        _probe_runtime_capabilities(python_paths)
        _log(log_queue, "info", "Bootstrap: backend ready, starting IPC services")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            _worker_loop(
                worker_name,
                cmd_queue,
                res_queue,
                log_queue,
                service_names=service_names,
            )
        )
    except Exception:
        _log(log_queue, "error", f"Worker '{worker_name}' crashed:\n{traceback.format_exc()}")
        raise


async def _respond(res_queue, service_name: str, req_id, *, ok: bool, result=None, error=None) -> None:
    message = {
        "type": "response",
        "service": service_name,
        "req_id": req_id,
        "ok": bool(ok),
        **({"result": result} if ok else {"error": str(error)}),
    }

    def _put() -> None:
        try:
            res_queue.put(message, True, 2.0)
        except TypeError:
            res_queue.put(message)

    try:
        await asyncio.to_thread(_put)
    except Exception:
        pass


async def _dispatch(service, service_name: str, method: str, payload: dict, req_id, res_queue, log_queue) -> None:
    try:
        result = await service.handle(method, payload)
        await _respond(res_queue, service_name, req_id, ok=True, result=result)
    except asyncio.CancelledError:
        await _respond(res_queue, service_name, req_id, ok=False, error="Request cancelled")
        raise
    except Exception as e:
        _log(
            log_queue,
            "error",
            f"[{service_name}.{method}] failed: {e}",
            detail=traceback.format_exc(),
        )
        await _respond(res_queue, service_name, req_id, ok=False, error=e)


async def _dispatch_limited(
    semaphore: asyncio.Semaphore,
    service,
    service_name: str,
    method: str,
    payload: dict,
    req_id,
    res_queue,
    log_queue,
    blocked_reason: Callable[[], str | None] | None = None,
) -> None:
    async with semaphore:
        reason = blocked_reason() if blocked_reason is not None else None
        if reason:
            await _respond(
                res_queue,
                service_name,
                req_id,
                ok=False,
                error=f"Service '{service_name}' is quarantined: {reason}",
            )
            return
        await _dispatch(service, service_name, method, payload, req_id, res_queue, log_queue)


async def _worker_loop(
    worker_name: str,
    cmd_queue,
    res_queue,
    log_queue,
    *,
    service_names: tuple[str, ...] | list[str] | None = None,
) -> None:
    services = {
        service_name: _LazyService(
            service_name,
            emit_event=lambda ev, data=None, _sn=service_name: _emit_event(res_queue, _sn, ev, data),
        )
        for service_name in _services_for_worker(worker_name, service_names)
    }

    _log(log_queue, "success", f"Worker '{worker_name}' started for services: {', '.join(sorted(services.keys()))}")
    for service_name in services.keys():
        _emit_ready(res_queue, service_name)

    default_limit = _env_int("NEUROMITA_AI_WORKER_CONCURRENCY", 8)
    service_limits = {
        "tts": _env_int("NEUROMITA_TTS_CONCURRENCY", 1),
        "asr": _env_int("NEUROMITA_ASR_CONCURRENCY", 2),
        "rag": _env_int("NEUROMITA_RAG_CONCURRENCY", 4),
        "beats": _env_int("NEUROMITA_BEATS_CONCURRENCY", 2),
    }
    semaphores = {
        service_name: asyncio.Semaphore(service_limits.get(service_name, default_limit))
        for service_name in services
    }
    max_inflight = max(default_limit, sum(service_limits.get(name, 1) for name in services))
    inflight: dict[str, tuple[str, asyncio.Task[Any]]] = {}
    blocked_services: dict[str, str] = {}

    async def _heartbeat_loop() -> None:
        interval = _env_float("NEUROMITA_AI_HEARTBEAT_INTERVAL", 2.0, minimum=0.5)
        while True:
            try:
                res_queue.put_nowait(
                    {
                        "type": "heartbeat",
                        "worker": str(worker_name),
                    }
                )
            except Exception:
                pass
            await asyncio.sleep(interval)

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    async def _drain(timeout: float = 30.0) -> None:
        if not inflight:
            return
        tasks = [task for _service, task in inflight.values()]
        done, pending = await asyncio.wait(tasks, timeout=max(0.1, timeout))
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        if done:
            await asyncio.gather(*done, return_exceptions=True)

    async def _drain_service(service_name: str, timeout: float = 30.0) -> bool:
        tasks = [
            task
            for task_service, task in inflight.values()
            if task_service == service_name and not task.done()
        ]
        if not tasks:
            return True
        done, pending = await asyncio.wait(tasks, timeout=max(0.1, timeout))
        if done:
            await asyncio.gather(*done, return_exceptions=True)
        # A task awaiting a native/to_thread call must not be cancelled: the
        # underlying thread would continue while the scheduler slot is released.
        return not pending

    while True:
        while len(inflight) >= max_inflight:
            await asyncio.wait(
                [task for _service, task in inflight.values()],
                return_when=asyncio.FIRST_COMPLETED,
            )
        cmd = await asyncio.to_thread(cmd_queue.get)
        if not isinstance(cmd, dict):
            continue

        req_id = cmd.get("req_id")
        control = str(cmd.get("control") or "").strip().lower()
        service_name = str(cmd.get("service") or "").strip().lower()
        method = str(cmd.get("method") or "").strip()
        payload = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}

        if control == "cancel_request":
            # The caller no longer needs the result. Do not cancel a task that
            # may already be inside a native CUDA/to_thread call.
            continue

        if control == "quarantine_service":
            reason = str(payload.get("reason") or "request timeout")
            if service_name in services:
                blocked_services[service_name] = reason
                _log(log_queue, "warning", f"Service '{service_name}' quarantined: {reason}")
            continue

        if control == "shutdown" or method == "shutdown":
            await _drain()
            for service in services.values():
                try:
                    if hasattr(service, "shutdown"):
                        await _maybe_await(service.shutdown())
                except Exception:
                    pass
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            _log(log_queue, "info", f"Worker '{worker_name}' shutdown")
            return

        if control == "restart_service":
            if service_name not in services:
                await _respond(res_queue, service_name, req_id, ok=False, error=f"Unknown service: {service_name}")
                continue
            blocked_services[service_name] = "restart in progress"
            drained = await _drain_service(
                service_name,
                    timeout=_env_float(
                        "NEUROMITA_AI_SERVICE_DRAIN_TIMEOUT",
                        30.0,
                        minimum=1.0,
                    ),
            )
            if not drained:
                await _respond(
                    res_queue,
                    service_name,
                    req_id,
                    ok=False,
                    error=f"Service '{service_name}' is still executing a native request",
                )
                continue
            try:
                services[service_name] = await _restart_service(
                    services,
                    service_name,
                    res_queue=res_queue,
                    log_queue=log_queue,
                )
                blocked_services.pop(service_name, None)
                await _respond(res_queue, service_name, req_id, ok=True, result=True)
            except Exception as e:
                _log(log_queue, "error", f"[{service_name}] restart failed: {e}\n{traceback.format_exc()}")
                await _respond(res_queue, service_name, req_id, ok=False, error=e)
            continue

        service = services.get(service_name)
        if service is None:
            await _respond(res_queue, service_name, req_id, ok=False, error=f"Unknown service: {service_name}")
            continue

        quarantine_reason = blocked_services.get(service_name)
        if quarantine_reason:
            await _respond(
                res_queue,
                service_name,
                req_id,
                ok=False,
                error=f"Service '{service_name}' is quarantined: {quarantine_reason}",
            )
            continue

        task = asyncio.create_task(
            _dispatch_limited(
                semaphores[service_name],
                service,
                service_name,
                method,
                payload,
                req_id,
                res_queue,
                log_queue,
                blocked_reason=lambda sn=service_name: blocked_services.get(sn),
            )
        )
        request_key = str(req_id)
        inflight[request_key] = (service_name, task)
        task.add_done_callback(lambda _task, key=request_key: inflight.pop(key, None))


async def _restart_service(services: dict[str, Any], service_name: str, *, res_queue, log_queue):
    service = services.get(service_name)
    if service is None:
        raise RuntimeError(f"Unknown service: {service_name}")

    try:
        if hasattr(service, "shutdown"):
            await _maybe_await(service.shutdown())
    except Exception as e:
        _log(log_queue, "warning", f"[{service_name}] shutdown before restart failed: {e}")

    new_service = _LazyService(
        service_name,
        emit_event=lambda ev, data=None, _sn=service_name: _emit_event(res_queue, _sn, ev, data),
    )
    _emit_ready(res_queue, service_name)
    _log(log_queue, "info", f"Service '{service_name}' restarted inside worker")
    return new_service


def _emit_ready(res_queue, service_name: str) -> None:
    message = {"type": "ready", "service": str(service_name)}
    try:
        try:
            res_queue.put(message, True, 1.0)
        except TypeError:
            res_queue.put(message)
    except Exception:
        pass


def _emit_event(res_queue, service_name: str, event_name: str, data: Any = None) -> None:
    try:
        res_queue.put_nowait(
            {
                "type": "event",
                "service": str(service_name),
                "event": str(event_name),
                "data": data,
            }
        )
    except Exception:
        pass


async def _maybe_await(x):
    if asyncio.iscoroutine(x):
        return await x
    return x


class _LazyService:
    def __init__(self, service_name: str, emit_event: Callable[[str, Any], None]) -> None:
        self.service_name = str(service_name)
        self.emit_event = emit_event
        self._instance = None
        self._load_lock = threading.Lock()

    def _get_sync(self):
        if self._instance is not None:
            return self._instance
        with self._load_lock:
            if self._instance is None:
                self._instance = _load_service(self.service_name, self.emit_event)
        return self._instance

    async def _get(self):
        return await asyncio.to_thread(self._get_sync)

    async def handle(self, method: str, payload: dict):
        instance = await self._get()
        handler = instance.handle
        if inspect.iscoroutinefunction(handler):
            return await handler(method, payload)
        result = await asyncio.to_thread(handler, method, payload)
        return await _maybe_await(result)

    async def shutdown(self):
        if self._instance is None:
            return None
        instance = self._instance
        self._instance = None
        shutdown = getattr(instance, "shutdown", None)
        if not callable(shutdown):
            return None
        if inspect.iscoroutinefunction(shutdown):
            return await shutdown()
        return await asyncio.to_thread(shutdown)


def _load_service(service_name: str, emit_event: Callable[[str, Any], None]):
    sn = str(service_name or "").strip().lower()
    if sn == "tts":
        from handlers.ai_engine.services.tts_service import TTSService

        return TTSService(emit_event=emit_event)
    if sn == "asr":
        from handlers.ai_engine.services.asr_service import ASRService

        return ASRService(emit_event=emit_event)
    if sn == "rag":
        from handlers.ai_engine.services.rag_service import RAGService

        return RAGService(emit_event=emit_event)
    if sn == "beats":
        from handlers.ai_engine.services.beats_service import BeatsService

        return BeatsService(emit_event=emit_event)
    raise RuntimeError(f"Unknown service_name: {service_name}")
