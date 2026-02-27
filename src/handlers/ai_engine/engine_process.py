from __future__ import annotations

import os
import sys
import time
import asyncio
import traceback
import uuid
from typing import Any, Optional


def run_ai_engine_process(cmd_queue, res_queue, log_queue) -> None:
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
        loop.run_until_complete(_engine_loop(cmd_queue, res_queue, log_queue))
    except Exception:
        try:
            log_queue.put({
                "level": "error",
                "message": "AI engine crashed:\n" + traceback.format_exc()
            })
        except Exception:
            pass


def _ensure_lib_on_path() -> None:
    lib_path = os.environ.get("NEUROMITA_LIB_DIR", os.path.abspath("Lib"))
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)


def _log(log_queue, level: str, message: str) -> None:
    try:
        log_queue.put({"level": str(level), "message": str(message)})
    except Exception:
        pass


class EngineState:
    def __init__(self, log_queue):
        self.log_queue = log_queue

        self._local_voice = None
        self._local_voice_lang = None
        self._current_voice_model_id: Optional[str] = None

        self._triton_status_cache = None

    def _get_local_voice(self, voice_language: str = "ru"):
        voice_language = str(voice_language or "ru").strip().lower()

        if self._local_voice is None:
            from handlers.local_voice_handler import LocalVoice
            self._local_voice = LocalVoice(voice_language=voice_language)
            self._local_voice_lang = voice_language
            return self._local_voice

        if self._local_voice_lang != voice_language:
            try:
                self._local_voice.change_voice_language(voice_language)
            except Exception:
                pass
            self._local_voice_lang = voice_language

        return self._local_voice


async def _engine_loop(cmd_queue, res_queue, log_queue) -> None:
    st = EngineState(log_queue)

    _log(log_queue, "success", "AI engine started")
    try:
        res_queue.put({"type": "ready"})
    except Exception:
        pass

    while True:
        cmd = await asyncio.to_thread(cmd_queue.get)
        if not isinstance(cmd, dict):
            continue

        req_id = cmd.get("req_id")
        action = str(cmd.get("action") or "").strip()
        payload = cmd.get("payload") if isinstance(cmd.get("payload"), dict) else {}

        if action == "shutdown":
            _log(log_queue, "info", "Shutdown requested")
            return

        try:
            result = await _handle_action(st, action, payload, log_queue=log_queue)
            res_queue.put({"type": "response", "req_id": req_id, "ok": True, "result": result})
        except Exception as e:
            err = f"{e}"
            _log(log_queue, "error", f"Action '{action}' failed: {err}\n{traceback.format_exc()}")
            try:
                res_queue.put({"type": "response", "req_id": req_id, "ok": False, "error": err})
            except Exception:
                pass


def _has_f5_reference_audio(lv) -> bool:
    try:
        from utils import get_character_voice_paths
        paths = get_character_voice_paths(None, getattr(lv, "provider", None))
        for key in ("f5_voice_filename", "clone_voice_filename"):
            p = str(paths.get(key) or "").strip()
            if p and os.path.exists(p) and os.path.getsize(p) > 0:
                return True
    except Exception:
        return False
    return False


async def _warmup_voice_model(lv, model_id: str, voice_language: str) -> bool:
    if model_id in ("high", "high+low"):
        if not _has_f5_reference_audio(lv):
            return True

    init_text = f"Инициализация модели {model_id}" if voice_language == "ru" else f"{model_id} Model Initialization"
    out_dir = os.path.abspath("temp")
    os.makedirs(out_dir, exist_ok=True)

    warm_path = os.path.join(out_dir, f"warmup_{model_id}_{uuid.uuid4()}.wav")
    produced: Optional[str] = None
    try:
        produced = await lv.voiceover(text=init_text, output_file=warm_path, character=None)
        if not produced:
            return False
        if not os.path.exists(produced) or os.path.getsize(produced) <= 0:
            return False
        return True
    finally:
        for p in [warm_path, produced]:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


async def _handle_action(st: EngineState, action: str, payload: dict, *, log_queue) -> Any:
    if action == "ping":
        return {"pong": True, "ts": time.time()}

    if action == "warmup":
        warm_torch = bool(payload.get("torch", True))
        warm_tf = bool(payload.get("transformers", False))

        if warm_torch:
            import importlib
            importlib.invalidate_caches()
            import torch  # noqa: F401

        if warm_tf:
            import importlib
            importlib.invalidate_caches()
            import transformers  # noqa: F401

        return True

    if action == "get_all_local_model_configs":
        lang = str(payload.get("voice_language") or "ru")
        lv = st._get_local_voice(lang)
        return lv.get_all_model_configs() or []

    if action == "check_voice_model_installed":
        model_id = str(payload.get("model_id") or "").strip()
        lang = str(payload.get("voice_language") or "ru")
        if not model_id:
            return False
        lv = st._get_local_voice(lang)
        return bool(lv.is_model_installed(model_id))

    if action == "check_voice_model_initialized":
        model_id = str(payload.get("model_id") or "").strip()
        lang = str(payload.get("voice_language") or "ru")
        if not model_id:
            return False
        lv = st._get_local_voice(lang)
        return bool(lv.is_model_initialized(model_id))

    if action == "select_voice_model":
        model_id = str(payload.get("model_id") or "").strip()
        lang = str(payload.get("voice_language") or "ru")
        if not model_id:
            return False
        lv = st._get_local_voice(lang)
        lv.select_model(model_id)
        st._current_voice_model_id = model_id
        return True

    if action == "init_voice_model":
        model_id = str(payload.get("model_id") or "").strip()
        do_warmup = bool(payload.get("init", True))
        lang = str(payload.get("voice_language") or "ru").strip().lower()
        if not model_id:
            return False

        lv = st._get_local_voice(lang)

        ok = await asyncio.to_thread(lv.initialize_model, model_id, init=False)
        if not ok:
            return False

        st._current_voice_model_id = model_id

        if do_warmup:
            warm_ok = await _warmup_voice_model(lv, model_id, lang)
            if not warm_ok:
                try:
                    if lv.active_model_instance:
                        lv.active_model_instance.cleanup_state()
                except Exception:
                    pass
                return False

        return True

    if action == "change_voice_language":
        lang = str(payload.get("voice_language") or "ru").strip().lower()
        lv = st._get_local_voice(lang)
        try:
            lv.change_voice_language(lang)
        except Exception:
            pass
        return True

    if action == "local_voiceover":
        text = str(payload.get("text") or "")
        output_file = str(payload.get("output_file") or "")
        character = payload.get("character")
        model_id = str(payload.get("model_id") or "").strip()
        voice_language = str(payload.get("voice_language") or "ru").strip().lower()

        if not text or not output_file:
            raise ValueError("Missing text/output_file")

        lv = st._get_local_voice(voice_language)

        use_model = model_id or st._current_voice_model_id
        if not use_model:
            raise RuntimeError("No voice model selected")

        lv.select_model(use_model)
        st._current_voice_model_id = use_model

        out_abs = os.path.abspath(output_file)
        os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)

        path = await lv.voiceover(text=text, output_file=out_abs, character=character)
        return path

    if action in ("get_triton_status", "refresh_triton_status"):
        if action == "get_triton_status" and st._triton_status_cache is not None:
            return st._triton_status_cache

        status = {
            "cuda_found": False,
            "winsdk_found": False,
            "msvc_found": False,
            "triton_installed": False,
            "triton_checks_performed": False,
        }

        try:
            import importlib
            importlib.invalidate_caches()
            import triton  # noqa: F401
            status["triton_installed"] = True

            if os.name == "nt":
                try:
                    from triton.windows_utils import find_cuda, find_winsdk, find_msvc

                    cuda_result = find_cuda()
                    if isinstance(cuda_result, (tuple, list)) and len(cuda_result) >= 1:
                        cuda_path = cuda_result[0]
                        status["cuda_found"] = bool(cuda_path and os.path.exists(str(cuda_path)))

                    winsdk_result = find_winsdk(False)
                    if isinstance(winsdk_result, (tuple, list)) and len(winsdk_result) >= 1:
                        winsdk_paths = winsdk_result[0]
                        status["winsdk_found"] = isinstance(winsdk_paths, list) and bool(winsdk_paths)

                    msvc_result = find_msvc(False)
                    cl_path = None
                    inc_paths, lib_paths = [], []
                    if isinstance(msvc_result, (tuple, list)):
                        if len(msvc_result) >= 1:
                            cl_path = msvc_result[0]
                        if len(msvc_result) >= 2:
                            inc_paths = msvc_result[1] or []
                        if len(msvc_result) >= 3:
                            lib_paths = msvc_result[2] or []
                    status["msvc_found"] = bool((cl_path and os.path.exists(str(cl_path))) or inc_paths or lib_paths)

                    status["triton_checks_performed"] = True
                except Exception:
                    pass

        except Exception:
            pass

        st._triton_status_cache = status
        return status

    raise ValueError(f"Unknown action: {action}")