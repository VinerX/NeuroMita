from __future__ import annotations

import os
import sys
import asyncio
import traceback
from typing import Any, Callable, Optional


def _ensure_lib_on_path() -> None:
    lib_path = os.environ.get("NEUROMITA_LIB_DIR", os.path.abspath("Lib"))
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def _log(log_queue, level: str, message: str) -> None:
    try:
        log_queue.put({"level": str(level), "message": str(message)})
    except Exception:
        pass


def run_worker_process(service_name: str, cmd_queue, res_queue, log_queue) -> None:
    """
    Универсальный worker-процесс для AI сервисов.
    - service_name: "tts" | "asr" | ...
    - cmd_queue: {"req_id": str, "method": str, "payload": dict}
    - res_queue: ready/response/event
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
        loop.run_until_complete(_worker_loop(service_name, cmd_queue, res_queue, log_queue))
    except Exception:
        _log(log_queue, "error", f"Worker '{service_name}' crashed:\n{traceback.format_exc()}")


async def _worker_loop(service_name: str, cmd_queue, res_queue, log_queue) -> None:
    service = _load_service(service_name, emit_event=lambda ev, data=None: _emit_event(res_queue, ev, data))

    _log(log_queue, "success", f"Worker '{service_name}' started")
    try:
        res_queue.put({"type": "ready", "service": service_name})
    except Exception:
        pass

    while True:
        cmd = await asyncio.to_thread(cmd_queue.get)
        if not isinstance(cmd, dict):
            continue

        req_id = cmd.get("req_id")
        method = str(cmd.get("method") or "").strip()
        payload = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}

        if method == "shutdown":
            try:
                if hasattr(service, "shutdown"):
                    await _maybe_await(service.shutdown())
            except Exception:
                pass
            _log(log_queue, "info", f"Worker '{service_name}' shutdown")
            return

        try:
            res = await service.handle(method, payload)
            res_queue.put({"type": "response", "service": service_name, "req_id": req_id, "ok": True, "result": res})
        except Exception as e:
            _log(log_queue, "error", f"[{service_name}.{method}] failed: {e}\n{traceback.format_exc()}")
            try:
                res_queue.put({"type": "response", "service": service_name, "req_id": req_id, "ok": False, "error": str(e)})
            except Exception:
                pass


def _emit_event(res_queue, event_name: str, data: Any = None) -> None:
    try:
        res_queue.put({"type": "event", "event": str(event_name), "data": data})
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
    raise RuntimeError(f"Unknown service_name: {service_name}")