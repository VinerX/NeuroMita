from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import math
import os
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
from main_logger import logger

import numpy as np
import soundfile as sf


class BeatsService:
    def __init__(self, *, emit_event: Callable[[str, Any], None]):
        self.emit_event = emit_event
        self._warmup_done = False
        self._warmup_lock = threading.RLock()
        self._beat_this_file2beats = None

    async def shutdown(self):
        await asyncio.to_thread(self._shutdown_sync)

    async def handle(self, method: str, payload: dict):
        m = str(method or "").strip().lower()

        if m == "ping":
            return True

        if m == "warmup":
            await asyncio.to_thread(self._warmup_sync)
            return True

        if m == "get_backend_status":
            return await asyncio.to_thread(self._get_backend_status_sync)

        if m == "extract_beats":
            audio_path = str(payload.get("audio_path") or "").strip()
            min_confidence = float(payload.get("min_confidence", 0.2) or 0.2)
            return await asyncio.to_thread(self._extract_beats_sync, audio_path, min_confidence)

        raise RuntimeError(f"Unknown beats method: {method}")

    def _warmup_sync(self) -> None:
        if self._warmup_done:
            return
        with self._warmup_lock:
            if self._warmup_done:
                return
            if self._init_beat_this():
                self._warmup_done = True
                return
            self._warmup_done = True

    def _get_backend_status_sync(self) -> dict:
        if self._beat_this_file2beats is not None:
            active_backend = "beat_this"
        elif _module_available("librosa"):
            active_backend = "librosa"
        else:
            active_backend = "dsp_fallback"

        return {
            "beat_this_installed": _module_available("beat_this"),
            "beat_this_ready": self._beat_this_file2beats is not None,
            "active_backend": active_backend,
        }

    def _extract_beats_sync(self, audio_path: str, min_confidence: float) -> dict:
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        self._warmup_sync()

        result = self._try_beat_this(audio_path, min_confidence)
        if result is None:
            logger.warning(f"beat_this failed for {audio_path}, falling back to librosa or DSP method")
            result = self._try_librosa(audio_path, min_confidence)
        if result is None:
            logger.warning(f"librosa failed for {audio_path}, falling back to DSP method")
            mono, sr, duration = self._load_audio_mono(audio_path)
            beats = self._extract_fallback_from_audio(mono, sr, min_confidence, offset_seconds=0.0)
            result = {
                "beats": beats,
                "duration": duration,
                "sr": int(sr),
                "method": "dsp_fallback",
                "bpm_estimate": _estimate_bpm_from_beats([b["time"] for b in beats]),
            }

        return result

    def _init_beat_this(self) -> bool:
        try:
            if self._beat_this_file2beats is not None:
                return True

            if not _module_available("beat_this"):
                return False

            import importlib

            importlib.invalidate_caches()

            from beat_this.inference import File2Beats  # type: ignore

            device = "cpu"
            try:
                import torch  # type: ignore

                if bool(torch.cuda.is_available()):
                    device = "cuda"
            except Exception:
                device = "cpu"

            self._beat_this_file2beats = File2Beats(checkpoint_path="final0", device=device, dbn=False)
            return True
        except Exception as ex:
            logger.exception(f"Error initializing beat_this: {ex}")    
            return False

    def _try_beat_this(self, audio_path: str, min_confidence: float) -> Optional[dict]:
        try:
            if self._beat_this_file2beats is None and not self._init_beat_this():
                return None

            f2b = self._beat_this_file2beats
            beats_arr, _downbeats_arr = f2b(audio_path)
            beats = [{"time": float(t), "confidence": 1.0} for t in list(beats_arr)]
            beats = [b for b in beats if b["confidence"] >= min_confidence]
            duration = _probe_duration(audio_path)
            return {
                "beats": beats,
                "duration": duration,
                "sr": 0,
                "method": "beat_this",
                "bpm_estimate": _estimate_bpm_from_beats([b["time"] for b in beats]),
            }
        except Exception as ex:
            logger.exception(f"Error in beat_this for {audio_path}: {ex}")
            return None

    def _try_librosa(self, audio_path: str, min_confidence: float) -> Optional[dict]:
        try:
            import librosa  # type: ignore

            y, sr = librosa.load(audio_path, sr=22050, mono=True)
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            times = librosa.frames_to_time(beat_frames, sr=sr)
            beats = [{"time": float(t), "confidence": 0.9} for t in times]
            beats = [b for b in beats if b["confidence"] >= min_confidence]
            return {
                "beats": beats,
                "duration": float(len(y) / float(sr)) if sr > 0 else 0.0,
                "sr": int(sr),
                "method": "librosa",
                "bpm_estimate": float(tempo) if tempo else _estimate_bpm_from_beats([b["time"] for b in beats]),
            }
        except Exception as ex:
            logger.exception(f"Error in librosa for {audio_path}: {ex}")
            return None

    def _load_audio_mono(self, audio_path: str, target_sr: int = 22050) -> Tuple[np.ndarray, int, float]:
        wav, sr = sf.read(audio_path, always_2d=True)
        if wav.size == 0:
            return np.zeros((0,), dtype=np.float32), int(target_sr), 0.0

        mono = np.mean(wav, axis=1).astype(np.float32, copy=False)
        if sr != target_sr:
            mono = _resample_safe(mono, int(sr), int(target_sr))
            sr = target_sr

        duration = float(len(mono) / float(sr)) if sr > 0 else 0.0
        return mono, int(sr), duration

    def _extract_fallback_from_audio(
        self,
        mono: np.ndarray,
        sr: int,
        min_confidence: float,
        offset_seconds: float,
    ) -> List[Dict[str, float]]:
        if mono is None or len(mono) < 4 or sr <= 0:
            return []

        frame = 1024
        hop = 256
        if len(mono) < frame + 2:
            return []

        win = np.hanning(frame).astype(np.float32)
        n_frames = 1 + (len(mono) - frame) // hop
        mags = np.empty((n_frames, frame // 2 + 1), dtype=np.float32)

        valid_n = 0
        for i in range(n_frames):
            start = i * hop
            chunk = mono[start:start + frame]
            if len(chunk) < frame:
                break
            spec = np.fft.rfft(chunk * win)
            mags[i] = np.abs(spec).astype(np.float32)
            valid_n += 1

        if valid_n <= 2:
            return []

        mags = mags[:valid_n]
        diff = np.diff(mags, axis=0)
        diff[diff < 0] = 0
        flux = np.sum(diff, axis=1)
        if flux.size < 8:
            return []

        flux = _smooth(flux, kernel=5)
        local_mean = _moving_mean(flux, window=31)
        local_std = _moving_std(flux, window=31)
        threshold = local_mean + 0.5 * local_std

        peaks: List[int] = []
        min_gap_frames = max(1, int(0.18 * sr / hop))
        last_idx = -10_000
        for i in range(1, len(flux) - 1):
            if flux[i] <= threshold[i]:
                continue
            if flux[i] < flux[i - 1] or flux[i] < flux[i + 1]:
                continue
            if i - last_idx < min_gap_frames:
                if peaks and flux[i] > flux[last_idx]:
                    peaks[-1] = i
                    last_idx = i
                continue
            peaks.append(i)
            last_idx = i

        if not peaks:
            return []

        max_flux = float(np.max(flux)) if np.max(flux) > 1e-8 else 1.0
        beats: List[Dict[str, float]] = []
        for i in peaks:
            t = float((i * hop + frame * 0.5) / sr) + float(offset_seconds)
            conf = float(np.clip(flux[i] / max_flux, 0.0, 1.0))
            if conf >= min_confidence:
                beats.append({"time": t, "confidence": conf})

        return beats

    def _shutdown_sync(self) -> None:
        self._beat_this_file2beats = None
        self._warmup_done = False


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _probe_duration(audio_path: str) -> float:
    try:
        info = sf.info(audio_path)
        if info and info.samplerate > 0:
            return float(info.frames) / float(info.samplerate)
    except Exception:
        pass
    return 0.0


def _smooth(x: np.ndarray, kernel: int = 5) -> np.ndarray:
    kernel = max(1, int(kernel))
    if kernel <= 1:
        return x
    pad = kernel // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    w = np.ones(kernel, dtype=np.float32) / float(kernel)
    return np.convolve(xp, w, mode="valid")


def _moving_mean(x: np.ndarray, window: int = 31) -> np.ndarray:
    window = max(3, int(window) | 1)
    pad = window // 2
    xp = np.pad(x, (pad, pad), mode="edge")
    c = np.cumsum(xp, dtype=np.float64)
    c[window:] = c[window:] - c[:-window]
    return (c[window - 1:] / float(window)).astype(np.float32)


def _moving_std(x: np.ndarray, window: int = 31) -> np.ndarray:
    m = _moving_mean(x, window)
    v = _moving_mean((x - m) ** 2, window)
    v[v < 0] = 0
    return np.sqrt(v).astype(np.float32)


def _resample_safe(y: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr <= 0 or target_sr <= 0 or len(y) == 0:
        return y

    try:
        import soxr  # type: ignore

        return soxr.resample(y, orig_sr, target_sr).astype(np.float32, copy=False)
    except Exception:
        pass

    ratio = float(target_sr) / float(orig_sr)
    n = max(1, int(math.floor(len(y) * ratio)))
    src_x = np.linspace(0.0, 1.0, num=len(y), dtype=np.float64)
    dst_x = np.linspace(0.0, 1.0, num=n, dtype=np.float64)
    return np.interp(dst_x, src_x, y).astype(np.float32)


def _estimate_bpm_from_beats(times: List[float]) -> float:
    if len(times) < 2:
        return 0.0
    arr = np.array(times, dtype=np.float64)
    d = np.diff(arr)
    d = d[(d > 1e-3) & (d < 2.0)]
    if d.size == 0:
        return 0.0
    med = float(np.median(d))
    if med <= 1e-5:
        return 0.0
    bpm = 60.0 / med
    while bpm < 70.0:
        bpm *= 2.0
    while bpm > 190.0:
        bpm *= 0.5
    return float(bpm)
