from __future__ import annotations

import os
import uuid
import asyncio
from typing import Any, Optional, Callable


class TTSService:
    """
    Универсальный TTS service поверх LocalVoice.
    Не знает про конкретные модели (Fish/F5/Edge).
    Warmup best-effort: если модель требует внешние артефакты (например reference audio)
    и warmup падает "предсказуемо", считаем warmup skipped, а init успешным.
    """

    def __init__(self, *, emit_event: Callable[[str, Any], None]):
        self.emit_event = emit_event

        self._local_voice = None
        self._voice_language = "ru"
        self._current_model_id: Optional[str] = None

        self._triton_status_cache = None

    def _get_local_voice(self):
        if self._local_voice is None:
            from handlers.local_voice_handler import LocalVoice
            self._local_voice = LocalVoice(voice_language=self._voice_language)
        return self._local_voice

    async def shutdown(self):
        try:
            self._local_voice = None
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
            lv = self._get_local_voice()
            try:
                lv.change_voice_language(lang)
            except Exception:
                pass
            return True

        if m == "list_models":
            lv = self._get_local_voice()
            return lv.get_all_model_configs() or []

        if m == "check_installed":
            model_id = str(payload.get("model_id") or "").strip()
            if not model_id:
                return False
            lv = self._get_local_voice()
            return bool(lv.is_model_installed(model_id))

        if m == "check_initialized":
            model_id = str(payload.get("model_id") or "").strip()
            if not model_id:
                return False
            lv = self._get_local_voice()
            return bool(lv.is_model_initialized(model_id))

        if m == "select_model":
            model_id = str(payload.get("model_id") or "").strip()
            if not model_id:
                return False
            lv = self._get_local_voice()
            lv.select_model(model_id)
            self._current_model_id = model_id
            return True

        if m == "init_model":
            model_id = str(payload.get("model_id") or "").strip()
            do_warmup = bool(payload.get("warmup", True))
            if not model_id:
                return False

            lv = self._get_local_voice()
            ok = await asyncio.to_thread(lv.initialize_model, model_id, init=False)
            if not ok:
                return False

            self._current_model_id = model_id

            if do_warmup:
                warm = await self._best_effort_warmup(lv, model_id)
                if not warm:
                    return False

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

            lv = self._get_local_voice()
            lv.select_model(model_id)
            self._current_model_id = model_id

            out_abs = os.path.abspath(output_file)
            os.makedirs(os.path.dirname(out_abs) or ".", exist_ok=True)

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

    async def _best_effort_warmup(self, lv, model_id: str) -> bool:
        tmp_dir = os.path.abspath("temp")
        os.makedirs(tmp_dir, exist_ok=True)
        out = os.path.join(tmp_dir, f"tts_warmup_{model_id}_{uuid.uuid4()}.wav")

        produced: Optional[str] = None
        try:
            produced = await lv.voiceover(
                text="warmup",
                output_file=out,
                character=None,
            )
            if not produced:
                return False
            if not os.path.exists(produced) or os.path.getsize(produced) <= 0:
                return False
            return True

        except FileNotFoundError:
            # "нет reference" или файлов модели — для warmup это допустимо, init уже прошёл
            return True
        except RuntimeError as e:
            msg = str(e).lower()
            # generic: "requires reference audio" и т.п.
            if "reference" in msg and ("audio" in msg or "voice" in msg):
                return True
            return False
        except Exception:
            return False
        finally:
            for p in [out, produced]:
                try:
                    if p and os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass