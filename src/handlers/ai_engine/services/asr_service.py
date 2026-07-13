from __future__ import annotations

import asyncio
import gc
from typing import Any, Callable, Optional

import numpy as np

from handlers.asr_audio_capture import AudioCaptureConfig, AudioCaptureService


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
            max_speech_duration = float(vad_cfg.get("max_speech_duration", 30.0) or 30.0)

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
                max_speech_duration=max_speech_duration,
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
        max_speech_duration: float,
    ) -> bool:
        self._engine_id = engine_id
        self._engine_settings = engine_settings or {}

        rec = await asyncio.to_thread(self._get_recognizer, engine_id)
        if rec is None:
            return False

        try:
            if hasattr(rec, "apply_settings"):
                await asyncio.to_thread(rec.apply_settings, self._engine_settings)
        except Exception:
            pass

        if hasattr(rec, "status"):
            try:
                status = await asyncio.to_thread(
                    rec.status,
                    {"engine_settings": dict(self._engine_settings)},
                )
                if not bool(status.ready):
                    return False
            except Exception:
                return False

        # Most legacy recognizer ``init`` implementations are declared async but
        # perform imports, model loading and filesystem/network work
        # synchronously. Run their private event loop off the shared AI loop.
        ok = await asyncio.to_thread(lambda: asyncio.run(rec.init()))
        if not ok:
            return False

        vad_model = await self._get_vad_model()
        capture = AudioCaptureService(self._logger)

        self._active = True
        service_loop = asyncio.get_running_loop()
        capture_ready = service_loop.create_future()

        def _mark_capture_ready() -> None:
            def _resolve() -> None:
                if not capture_ready.done():
                    capture_ready.set_result(True)

            service_loop.call_soon_threadsafe(_resolve)

        async def _handle_text(text: str):
            t = (text or "").strip()
            if t:
                self.emit_event("text", {"text": t})

        def _active_flag():
            return bool(self._active)

        def _speech_probability(audio: np.ndarray, rate: int) -> float:
            import torch

            tensor = torch.from_numpy(np.asarray(audio, dtype=np.float32))
            return float(vad_model(tensor, rate).item())

        async def _transcribe_segment(audio: np.ndarray, rate: int) -> None:
            text = await rec.transcribe(audio, rate)
            if text:
                await _handle_text(text)

        async def _runner():
            failed = False
            try:
                await asyncio.to_thread(
                    lambda: asyncio.run(
                        capture.run(
                            microphone_index=mic_index,
                            config=AudioCaptureConfig(
                                sample_rate=sample_rate,
                                chunk_size=chunk_size,
                                vad_threshold=vad_threshold,
                                silence_timeout=silence_timeout,
                                pre_buffer_duration=pre_buffer_duration,
                                max_speech_duration=max_speech_duration,
                            ),
                            is_active=_active_flag,
                            speech_probability=_speech_probability,
                            on_segment=_transcribe_segment,
                            on_ready=_mark_capture_ready,
                        )
                    )
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                failed = True
                if not capture_ready.done():
                    capture_ready.set_exception(e)
                else:
                    self.emit_event("error", {"message": f"{type(e).__name__}: {e}"})
            finally:
                self._active = False
                if not capture_ready.done():
                    capture_ready.set_exception(
                        RuntimeError("Audio capture stopped before the microphone became ready")
                    )
                elif not failed:
                    self.emit_event("status", {"running": False})

        self._task = asyncio.create_task(_runner())
        try:
            await asyncio.wait_for(asyncio.shield(capture_ready), timeout=10.0)
        except asyncio.CancelledError:
            self._active = False
            if not capture_ready.done():
                capture_ready.cancel()
            if self._task is not None:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
            raise
        except Exception as exc:
            self._active = False
            if not capture_ready.done():
                capture_ready.cancel()
            task = self._task
            if task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                except asyncio.TimeoutError:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                except Exception:
                    pass
            self._task = None
            if isinstance(exc, asyncio.TimeoutError):
                message = (
                    f"Микрофон {mic_index} не передал аудиоданные за 10 секунд; "
                    "устройство или аудиодрайвер не отвечает"
                )
            else:
                message = str(exc).strip() or f"Не удалось запустить микрофон {mic_index}"
            raise RuntimeError(message) from exc

        if self._task.done() or not self._active:
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
            raise RuntimeError(
                f"ASR audio capture on microphone {mic_index} stopped during startup"
            )

        self.emit_event("status", {"running": True})
        return True

    async def _stop_live_internal(self):
        self._active = False

        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
            except Exception:
                pass
            finally:
                self._task = None

        if self._recognizer is not None:
            try:
                await asyncio.to_thread(self._recognizer.cleanup)
            except Exception:
                pass
            finally:
                self._recognizer = None

        self._unload_vad_model()
        self.emit_event("status", {"running": False})

    async def _get_vad_model(self):
        if self._vad_model is not None:
            return self._vad_model

        def load() -> Any:
            import torch  # noqa: F401

            try:
                from silero_vad import load_silero_vad
            except Exception as e:
                raise RuntimeError(f"silero_vad not available: {e}") from None
            return load_silero_vad()

        self._vad_model = await asyncio.to_thread(load)
        return self._vad_model

    def _unload_vad_model(self):
        self._vad_model = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def _get_recognizer(self, engine_id: str):
        if self._recognizer is not None and self._engine_id == engine_id:
            return self._recognizer

        from handlers.asr_models.registry import create_recognizer, engine_class

        normalized = str(engine_id or "").strip()
        if engine_class(normalized) is None:
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

        self._recognizer = create_recognizer(
            normalized,
            self._pip_installer,
            self._logger,
        )
        return self._recognizer
