from __future__ import annotations

import asyncio
import os
import sys
import traceback
from typing import Any, Callable


_SHARED_WORKER = "shared"
_SHARED_SERVICES = ("tts", "asr", "rag")


def _ensure_lib_on_path() -> None:
    lib_path = os.environ.get("NEUROMITA_LIB_DIR", os.path.abspath("Lib"))
    lib_path_norm = os.path.normcase(os.path.abspath(lib_path))
    sys.path = [
        p for p in sys.path
        if os.path.normcase(os.path.abspath(p or "")) != lib_path_norm
    ]
    sys.path.insert(0, lib_path)


def _log(log_queue, level: str, message: str) -> None:
    try:
        log_queue.put({"level": str(level), "message": str(message)})
    except Exception:
        pass


def _services_for_worker(worker_name: str) -> tuple[str, ...]:
    wn = str(worker_name or "").strip().lower()
    if wn == _SHARED_WORKER:
        return _SHARED_SERVICES
    if wn in _SHARED_SERVICES:
        return (wn,)
    raise RuntimeError(f"Unknown worker_name: {worker_name}")


def run_worker_process(worker_name: str, cmd_queue, res_queue, log_queue) -> None:
    """
    Универсальный worker-процесс для AI сервисов.

    worker_name:
      - "tts"    -> отдельный worker только для TTS
      - "asr"    -> отдельный worker только для ASR
      - "shared" -> один worker для TTS + ASR
    """
    try:
        _ensure_lib_on_path()

        try:
            import importlib

            importlib.invalidate_caches()
            import onnxruntime  # noqa: F401
        except Exception:
            pass

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_worker_loop(worker_name, cmd_queue, res_queue, log_queue))
    except Exception:
        _log(log_queue, "error", f"Worker '{worker_name}' crashed:\n{traceback.format_exc()}")


async def _worker_loop(worker_name: str, cmd_queue, res_queue, log_queue) -> None:
    services = {
        service_name: _load_service(
            service_name,
            emit_event=lambda ev, data=None, _sn=service_name: _emit_event(res_queue, _sn, ev, data),
        )
        for service_name in _services_for_worker(worker_name)
    }

    _log(log_queue, "success", f"Worker '{worker_name}' started for services: {', '.join(sorted(services.keys()))}")
    for service_name in services.keys():
        _emit_ready(res_queue, service_name)

    while True:
        cmd = await asyncio.to_thread(cmd_queue.get)
        if not isinstance(cmd, dict):
            continue

        req_id = cmd.get("req_id")
        control = str(cmd.get("control") or "").strip().lower()
        service_name = str(cmd.get("service") or "").strip().lower()
        method = str(cmd.get("method") or "").strip()
        payload = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}

        if control == "shutdown" or method == "shutdown":
            for service in services.values():
                try:
                    if hasattr(service, "shutdown"):
                        await _maybe_await(service.shutdown())
                except Exception:
                    pass
            _log(log_queue, "info", f"Worker '{worker_name}' shutdown")
            return

        if control == "restart_service":
            try:
                services[service_name] = await _restart_service(
                    services,
                    service_name,
                    res_queue=res_queue,
                    log_queue=log_queue,
                )
                res_queue.put(
                    {
                        "type": "response",
                        "service": service_name,
                        "req_id": req_id,
                        "ok": True,
                        "result": True,
                    }
                )
            except Exception as e:
                _log(log_queue, "error", f"[{service_name}] restart failed: {e}\n{traceback.format_exc()}")
                try:
                    res_queue.put(
                        {
                            "type": "response",
                            "service": service_name,
                            "req_id": req_id,
                            "ok": False,
                            "error": str(e),
                        }
                    )
                except Exception:
                    pass
            continue

        service = services.get(service_name)
        if service is None:
            try:
                res_queue.put(
                    {
                        "type": "response",
                        "service": service_name,
                        "req_id": req_id,
                        "ok": False,
                        "error": f"Unknown service: {service_name}",
                    }
                )
            except Exception:
                pass
            continue

        try:
            res = await service.handle(method, payload)
            res_queue.put(
                {
                    "type": "response",
                    "service": service_name,
                    "req_id": req_id,
                    "ok": True,
                    "result": res,
                }
            )
        except Exception as e:
            _log(log_queue, "error", f"[{service_name}.{method}] failed: {e}\n{traceback.format_exc()}")
            try:
                res_queue.put(
                    {
                        "type": "response",
                        "service": service_name,
                        "req_id": req_id,
                        "ok": False,
                        "error": str(e),
                    }
                )
            except Exception:
                pass


async def _restart_service(services: dict[str, Any], service_name: str, *, res_queue, log_queue):
    service = services.get(service_name)
    if service is None:
        raise RuntimeError(f"Unknown service: {service_name}")

    try:
        if hasattr(service, "shutdown"):
            await _maybe_await(service.shutdown())
    except Exception as e:
        _log(log_queue, "warning", f"[{service_name}] shutdown before restart failed: {e}")

    new_service = _load_service(
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
    raise RuntimeError(f"Unknown service_name: {service_name}")
