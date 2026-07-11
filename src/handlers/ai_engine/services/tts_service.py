from __future__ import annotations

import os
import uuid
import asyncio
from typing import Any, Optional, Callable


from handlers.ai_engine.gpu_scheduler import Priority, get_scheduler


class TTSService:
    """
    Универсальный TTS service поверх LocalVoice.
    Не знает про конкретные модели (Fish/F5/Edge).
    Инициализация завершается только после успешного первого синтеза для модели.
    """

    def __init__(self, *, emit_event: Callable[[str, Any], None]):
        self.emit_event = emit_event

        self._local_voice = None
        self._voice_language = "ru"
        self._current_model_id: Optional[str] = None

        self._triton_status_cache = None
        self._warmup_status: dict[str, str] = {}

    def _get_local_voice(self):
        if self._local_voice is None:
            from handlers.local_voice_handler import LocalVoice
            self._local_voice = LocalVoice(voice_language=self._voice_language)
        return self._local_voice

    async def shutdown(self):
        local_voice = self._local_voice
        self._local_voice = None
        self._current_model_id = None
        self._warmup_status.clear()
        if local_voice is not None:
            shutdown = getattr(local_voice, "shutdown", None)
            if callable(shutdown):
                try:
                    await asyncio.to_thread(shutdown)
                except Exception:
                    pass

    async def handle(self, method: str, payload: dict):
        m = str(method or "").strip().lower()

        if m == "ping":
            return True

        if m == "set_language":
            lang = str(payload.get("voice_language") or "ru").strip().lower()
            if not lang:
                return False
            self._voice_language = lang
            lv = await asyncio.to_thread(self._get_local_voice)
            try:
                await asyncio.to_thread(lv.change_voice_language, lang)
            except Exception:
                pass
            return True

        if m == "list_models":
            lv = await asyncio.to_thread(self._get_local_voice)
            return await asyncio.to_thread(lv.get_all_model_configs) or []

        if m == "check_installed":
            model_id = str(payload.get("model_id") or "").strip()
            if not model_id:
                return False
            lv = await asyncio.to_thread(self._get_local_voice)
            return bool(await asyncio.to_thread(lv.is_model_installed, model_id))

        if m == "check_initialized":
            model_id = str(payload.get("model_id") or "").strip()
            if not model_id:
                return False
            lv = await asyncio.to_thread(self._get_local_voice)
            return bool(await asyncio.to_thread(lv.is_model_initialized, model_id))

        if m == "select_model":
            model_id = str(payload.get("model_id") or "").strip()
            if not model_id:
                return False
            lv = await asyncio.to_thread(self._get_local_voice)
            await asyncio.to_thread(lv.select_model, model_id)
            self._current_model_id = model_id
            return True

        if m == "init_model":
            model_id = str(payload.get("model_id") or "").strip()
            do_warmup = bool(payload.get("warmup", True))
            if not model_id:
                return False

            lv = await asyncio.to_thread(self._get_local_voice)
            self.emit_event("log", f"[tts:init] start model_id={model_id} warmup={do_warmup}")
            ok = await get_scheduler().run(Priority.BULK, lv.initialize_model, model_id, init=False)
            if not ok:
                self.emit_event("log", f"[tts:init] initialize_model returned False for model_id={model_id}")
                return False

            self._current_model_id = model_id
            self.emit_event("log", f"[tts:init] runtime initialized for model_id={model_id}")

            if do_warmup and self._warmup_status.get(model_id) != "ready":
                try:
                    warm = await asyncio.wait_for(
                        self._warmup_model(lv, model_id),
                        timeout=120.0,
                    )
                except asyncio.TimeoutError:
                    warm = False
                    self.emit_event(
                        "log",
                        f"[tts:init] warmup timed out for model_id={model_id}",
                    )
                self._warmup_status[model_id] = "ready" if warm else "failed"
                if not warm:
                    self.emit_event(
                        "log",
                        f"[tts:init] warmup failed for model_id={model_id}; initialization rejected",
                    )
                    return False
                self.emit_event("log", f"[tts:init] warmup finished for model_id={model_id}")
            elif do_warmup:
                self.emit_event("log", f"[tts:init] warmup already ready for model_id={model_id}")

            return True

        if m == "synthesize":
            text = str(payload.get("text") or "")
            output_file = str(payload.get("output_file") or "")
            character = payload.get("character")
            model_id = str(payload.get("model_id") or "").strip() or self._current_model_id

            if not text or not output_file:
                raise ValueError("Missing text/output_file")
            if not model_id:
                raise RuntimeError("No voice model selected")

            out_abs = os.path.abspath(output_file)
            os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)

            lv = await asyncio.to_thread(self._get_local_voice)
            # Выбор модели и синтез являются одной критической секцией. Иначе
            # параллельный запрос мог сменить mutable active_model_instance.
            async with get_scheduler().slot(Priority.TTS):
                await asyncio.to_thread(lv.select_model, model_id)
                self._current_model_id = model_id
                return await lv.voiceover(text=text, output_file=out_abs, character=character)

        if m in ("get_triton_status", "refresh_triton_status"):
            if m == "get_triton_status" and self._triton_status_cache is not None:
                return self._triton_status_cache
            st = await asyncio.to_thread(self._compute_triton_status)
            self._triton_status_cache = st
            return st

        raise RuntimeError(f"Unknown tts method: {method}")

    def _compute_triton_status(self) -> dict:
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

        return status

    async def _warmup_model(self, lv, model_id: str) -> bool:
        tmp_dir = os.path.abspath("temp")
        os.makedirs(tmp_dir, exist_ok=True)
        out = os.path.join(tmp_dir, f"tts_warmup_{model_id}_{uuid.uuid4()}.wav")

        produced: Optional[str] = None
        try:
            self.emit_event("log", f"[tts:warmup] synthesizing probe for model_id={model_id} -> {out}")
            produced = await lv.voiceover(
                text="warmup-вармап",
                output_file=out,
                character=None,
            )
            if not produced:
                self.emit_event("log", f"[tts:warmup] no output returned for model_id={model_id}")
                return False
            if not os.path.exists(produced) or os.path.getsize(produced) <= 0:
                self.emit_event("log", f"[tts:warmup] invalid output for model_id={model_id}: {produced}")
                return False
            self.emit_event("log", f"[tts:warmup] probe generated for model_id={model_id}: {produced}")
            return True

        except RuntimeError as e:
            self.emit_event("log", f"[tts:warmup] runtime error for model_id={model_id}: {e}")
            return False
        except Exception as exc:
            self.emit_event("log", f"[tts:warmup] unexpected error for model_id={model_id}: {exc}")
            return False
        finally:
            for p in [out, produced]:
                try:
                    if p and os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass
