from __future__ import annotations

import asyncio
import importlib
import os
import sys
import traceback
from typing import Any, Callable


_SHARED_WORKER = "shared"
_SHARED_SERVICES = ("tts", "asr", "rag", "beats")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return max(minimum, int(default))


_DLL_DIRECTORY_HANDLES: list[Any] = []


def _ensure_lib_on_path(python_paths: tuple[str, ...] | list[str] | None = None) -> None:
    main_core = os.path.abspath(
        os.environ.get("NEUROMITA_CORE_DIR")
        or os.environ.get("NEUROMITA_LIB_DIR")
        or os.path.join("Lib", "core")
    )
    runtime_root = os.path.abspath(
        os.environ.get("NEUROMITA_RUNTIME_ROOT") or os.path.dirname(main_core)
    )
    explicit_paths = [
        os.path.abspath(str(path))
        for path in (python_paths or ())
        if str(path).strip()
    ]
    ordered = explicit_paths
    os.environ["NEUROMITA_AI_WORKER"] = "1"
    if explicit_paths:
        os.environ["NEUROMITA_RUNTIME_TARGET_DIR"] = ordered[0]
        os.environ["NEUROMITA_RUNTIME_PYTHON_PATHS"] = os.pathsep.join(ordered)
    else:
        os.environ.pop("NEUROMITA_RUNTIME_TARGET_DIR", None)
        os.environ.pop("NEUROMITA_RUNTIME_PYTHON_PATHS", None)

    excluded = {os.path.normcase(path) for path in ordered}
    runtime_root_normalized = os.path.normcase(runtime_root)
    runtime_root_prefix = os.path.normcase(runtime_root + os.sep)

    def should_keep(path: str) -> bool:
        absolute = os.path.abspath(path or "")
        normalized = os.path.normcase(absolute)
        if normalized in excluded:
            return False
        if normalized == runtime_root_normalized or normalized.startswith(runtime_root_prefix):
            return False
        return True

    sys.path = [
        path for path in sys.path if should_keep(path)
    ]
    sys.path[:0] = ordered

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
        for root in ordered:
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


def _log(log_queue, level: str, message: str) -> None:
    try:
        log_queue.put_nowait({"level": str(level), "message": str(message)})
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
) -> None:
    importlib.invalidate_caches()
    for module_name in tuple(dict.fromkeys(probe_modules or ())):
        normalized = str(module_name or "").strip()
        if not normalized:
            continue
        try:
            importlib.import_module(normalized)
        except Exception as exc:
            raise RuntimeError(
                f"AI runtime probe failed while importing '{normalized}': {exc}"
            ) from exc


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
        # torch/MKL (libiomp5md) + onnxruntime (libomp140) в одном процессе дают
        # OMP Error #15 → abort. Ставим до любых тяжёлых импортов. См. __main__.py.
        os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

        _ensure_lib_on_path(python_paths)

        _probe_runtime_modules(probe_modules)

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


def _respond(res_queue, service_name: str, req_id, *, ok: bool, result=None, error=None) -> None:
    try:
        res_queue.put(
            {
                "type": "response",
                "service": service_name,
                "req_id": req_id,
                "ok": bool(ok),
                **({"result": result} if ok else {"error": str(error)}),
            }
        )
    except Exception:
        pass


async def _dispatch(service, service_name: str, method: str, payload: dict, req_id, res_queue, log_queue) -> None:
    try:
        result = await service.handle(method, payload)
        _respond(res_queue, service_name, req_id, ok=True, result=result)
    except Exception as e:
        _log(log_queue, "error", f"[{service_name}.{method}] failed: {e}\n{traceback.format_exc()}")
        _respond(res_queue, service_name, req_id, ok=False, error=e)


async def _dispatch_limited(
    semaphore: asyncio.Semaphore,
    service,
    service_name: str,
    method: str,
    payload: dict,
    req_id,
    res_queue,
    log_queue,
) -> None:
    async with semaphore:
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
        "tts": _env_int("NEUROMITA_TTS_CONCURRENCY", 2),
        "asr": _env_int("NEUROMITA_ASR_CONCURRENCY", 2),
        "rag": _env_int("NEUROMITA_RAG_CONCURRENCY", 4),
        "beats": _env_int("NEUROMITA_BEATS_CONCURRENCY", 2),
    }
    semaphores = {
        service_name: asyncio.Semaphore(service_limits.get(service_name, default_limit))
        for service_name in services
    }
    max_inflight = max(default_limit, sum(service_limits.get(name, 1) for name in services))
    inflight: set[asyncio.Task] = set()

    async def _drain(timeout: float = 30.0) -> None:
        if not inflight:
            return
        tasks = list(inflight)
        done, pending = await asyncio.wait(tasks, timeout=max(0.1, timeout))
        if pending:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        if done:
            await asyncio.gather(*done, return_exceptions=True)

    while True:
        while len(inflight) >= max_inflight:
            await asyncio.wait(list(inflight), return_when=asyncio.FIRST_COMPLETED)
        cmd = await asyncio.to_thread(cmd_queue.get)
        if not isinstance(cmd, dict):
            continue

        req_id = cmd.get("req_id")
        control = str(cmd.get("control") or "").strip().lower()
        service_name = str(cmd.get("service") or "").strip().lower()
        method = str(cmd.get("method") or "").strip()
        payload = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}

        if control == "shutdown" or method == "shutdown":
            await _drain()
            for service in services.values():
                try:
                    if hasattr(service, "shutdown"):
                        await _maybe_await(service.shutdown())
                except Exception:
                    pass
            _log(log_queue, "info", f"Worker '{worker_name}' shutdown")
            return

        if control == "restart_service":
            # Перезапуск сервиса не может ехать параллельно с его же запросами.
            await _drain()
            try:
                services[service_name] = await _restart_service(
                    services,
                    service_name,
                    res_queue=res_queue,
                    log_queue=log_queue,
                )
                _respond(res_queue, service_name, req_id, ok=True, result=True)
            except Exception as e:
                _log(log_queue, "error", f"[{service_name}] restart failed: {e}\n{traceback.format_exc()}")
                _respond(res_queue, service_name, req_id, ok=False, error=e)
            continue

        service = services.get(service_name)
        if service is None:
            _respond(res_queue, service_name, req_id, ok=False, error=f"Unknown service: {service_name}")
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
            )
        )
        inflight.add(task)
        task.add_done_callback(inflight.discard)


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
    try:
        res_queue.put({"type": "ready", "service": str(service_name)})
    except Exception:
        pass


def _emit_event(res_queue, service_name: str, event_name: str, data: Any = None) -> None:
    try:
        res_queue.put(
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

    def _get(self):
        if self._instance is None:
            self._instance = _load_service(self.service_name, self.emit_event)
        return self._instance

    async def handle(self, method: str, payload: dict):
        return await _maybe_await(self._get().handle(method, payload))

    async def shutdown(self):
        if self._instance is None:
            return None
        instance = self._instance
        self._instance = None
        shutdown = getattr(instance, "shutdown", None)
        if callable(shutdown):
            return await _maybe_await(shutdown())
        return None


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
