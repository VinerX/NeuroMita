from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional


class ASRService:
    """
    ASR service, живёт в отдельном процессе.
    Поддерживает live recognition и отдаёт события в GUI через emit_event():
      - event="text": {"text": "..."}
      - event="status": {"running": bool}
    """

    def __init__(self, *, emit_event: Callable[[str, Any], None]):
        self.emit_event = emit_event

        self._recognizer = None
        self._engine_id: str = "google"
        self._engine_settings: dict = {}

        self._active: bool = False
        self._task: Optional[asyncio.Task] = None

        self._vad_model = None

        self._pip_installer = None
        self._logger = None

    async def shutdown(self):
        await self._stop_live_internal()

    async def handle(self, method: str, payload: dict):
        m = str(method or "").strip().lower()

        if m == "ping":
            return True

        if m == "get_status":
            return {"running": bool(self._active)}

        if m == "start_live":
            engine_id = str(payload.get("engine_id") or "google").strip()
            mic_index = int(payload.get("microphone_index", 0) or 0)
            engine_settings = payload.get("engine_settings") if isinstance(payload.get("engine_settings"), dict) else {}

            vad_cfg = payload.get("vad") if isinstance(payload.get("vad"), dict) else {}
            sample_rate = int(vad_cfg.get("sample_rate", 16000) or 16000)
            chunk_size = int(vad_cfg.get("chunk_size", 512) or 512)
            vad_threshold = float(vad_cfg.get("vad_threshold", 0.5) or 0.5)
            silence_timeout = float(vad_cfg.get("silence_timeout", 0.15) or 0.15)
            pre_buffer_duration = float(vad_cfg.get("pre_buffer_duration", 0.3) or 0.3)

            await self._stop_live_internal()

            ok = await self._start_live_internal(
                engine_id=engine_id,
                mic_index=mic_index,
                engine_settings=engine_settings,
                sample_rate=sample_rate,
                chunk_size=chunk_size,
                vad_threshold=vad_threshold,
                silence_timeout=silence_timeout,
                pre_buffer_duration=pre_buffer_duration,
            )
            return bool(ok)

        if m == "stop_live":
            await self._stop_live_internal()
            return True

        raise RuntimeError(f"Unknown asr method: {method}")

    async def _start_live_internal(
        self,
        *,
        engine_id: str,
        mic_index: int,
        engine_settings: dict,
        sample_rate: int,
        chunk_size: int,
        vad_threshold: float,
        silence_timeout: float,
        pre_buffer_duration: float,
    ) -> bool:
        self._engine_id = engine_id
        self._engine_settings = engine_settings or {}

        rec = self._get_recognizer(engine_id)
        if rec is None:
            return False

        try:
            if hasattr(rec, "apply_settings"):
                rec.apply_settings(self._engine_settings)
        except Exception:
            pass

        if hasattr(rec, "is_installed"):
            try:
                if not rec.is_installed():
                    return False
            except Exception:
                pass

        ok = await rec.init()
        if not ok:
            return False

        vad_model = None
        if engine_id != "google":
            vad_model = await self._get_vad_model()

        self._active = True
        self.emit_event("status", {"running": True})

        async def _handle_text(text: str):
            t = (text or "").strip()
            if t:
                self.emit_event("text", {"text": t})

        def _active_flag():
            return bool(self._active)

        async def _runner():
            try:
                await rec.live_recognition(
                    mic_index,
                    _handle_text,
                    vad_model,
                    _active_flag,
                    sample_rate=sample_rate,
                    chunk_size=chunk_size,
                    vad_threshold=vad_threshold,
                    silence_timeout=silence_timeout,
                    pre_buffer_duration=pre_buffer_duration,
                )
            finally:
                self._active = False
                self.emit_event("status", {"running": False})

        self._task = asyncio.create_task(_runner())
        return True

    async def _stop_live_internal(self):
        self._active = False
        try:
            if self._recognizer is not None:
                try:
                    self._recognizer.cleanup()
                except Exception:
                    pass
        finally:
            self._recognizer = None

        if self._task is not None:
            try:
                self._task.cancel()
                await asyncio.sleep(0)
            except Exception:
                pass
        self._task = None
        self.emit_event("status", {"running": False})

    async def _get_vad_model(self):
        if self._vad_model is not None:
            return self._vad_model

        try:
            import torch
        except Exception as e:
            raise RuntimeError(f"torch not available for VAD: {e}") from None

        try:
            from silero_vad import load_silero_vad
        except Exception as e:
            raise RuntimeError(f"silero_vad not available: {e}") from None

        self._vad_model = load_silero_vad()
        return self._vad_model

    def _get_recognizer(self, engine_id: str):
        if self._recognizer is not None and self._engine_id == engine_id:
            return self._recognizer

        # Ленивая загрузка классов
        from handlers.asr_models.google_recognizer import GoogleRecognizer
        from handlers.asr_models.gigaam_recognizer import GigaAMRecognizer
        from handlers.asr_models.gigaam_onnx_recognizer import GigaAMOnnxRecognizer
        from handlers.asr_models.whisper_recognizer import WhisperRecognizer
        from handlers.asr_models.whisper_onnx_recognizer import WhisperOnnxRecognizer

        reg = {
            "google": GoogleRecognizer,
            "gigaam": GigaAMRecognizer,
            "gigaam_onnx": GigaAMOnnxRecognizer,
            "whisper": WhisperRecognizer,
            "whisper_onnx": WhisperOnnxRecognizer,
        }

        cls = reg.get(str(engine_id or "").strip())
        if not cls:
            return None

        if self._logger is None:
            from main_logger import logger as _logger
            self._logger = _logger

        if self._pip_installer is None:
            try:
                from utils.pip_installer import PipInstaller
                self._pip_installer = PipInstaller(
                    update_log=self._logger.info,
                )
            except Exception:
                self._pip_installer = None

        self._recognizer = cls(self._pip_installer, self._logger)
        return self._recognizer