from __future__ import annotations
from core.error_utils import format_exception

import asyncio
import hashlib
import importlib.util
import math
import os
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from game_connections.services.beat_backend_spec import (
    BACKEND_AUTO,
    BACKEND_BEAT_THIS,
    BACKEND_DSP,
    BACKEND_LIBROSA,
    backend_attempt_order,
    get_backend_status_snapshot,
    normalize_backend_choice,
)
from main_logger import logger

import numpy as np
import soundfile as sf


class BeatsService:
    def __init__(self, *, emit_event: Callable[[str, Any], None]):
        self.emit_event = emit_event
        self._warmup_done = False
        self._warmup_lock = threading.RLock()
        self._beat_this_file2beats = None
        self._librosa_ready = False

    async def shutdown(self):
        await asyncio.to_thread(self._shutdown_sync)

    async def handle(self, method: str, payload: dict):
        m = str(method or "").strip().lower()

        if m == "ping":
            return True

        if m == "warmup":
            preferred_backend = str(payload.get("backend_preference") or BACKEND_AUTO)
            await asyncio.to_thread(self._warmup_sync, preferred_backend)
            return True

        if m == "get_backend_status":
            preferred_backend = str(payload.get("backend_preference") or BACKEND_AUTO)
            return await asyncio.to_thread(self._get_backend_status_sync, preferred_backend)

        if m == "initialize_backend":
            preferred_backend = str(payload.get("backend_preference") or BACKEND_AUTO)
            strict = bool(payload.get("strict", False))
            return await asyncio.to_thread(self._initialize_backend_sync, preferred_backend, strict)

        if m == "extract_beats":
            audio_path = str(payload.get("audio_path") or "").strip()
            min_confidence = float(payload.get("min_confidence", 0.2) or 0.2)
            preferred_backend = str(payload.get("backend_preference") or BACKEND_AUTO)
            return await asyncio.to_thread(self._extract_beats_sync, audio_path, min_confidence, preferred_backend)

        raise RuntimeError(f"Unknown beats method: {method}")

    def _warmup_sync(self, preferred_backend: str = BACKEND_AUTO) -> None:
        if self._warmup_done:
            return
        with self._warmup_lock:
            if self._warmup_done:
                return
            self._initialize_backend_sync(preferred_backend, strict=False)
            self._warmup_done = True

    def _get_backend_status_sync(self, preferred_backend: str = BACKEND_AUTO) -> dict:
        snapshot = get_backend_status_snapshot(preferred_backend)
        backends = snapshot.get("backends") if isinstance(snapshot.get("backends"), dict) else {}
        beat_this_state = backends.get(BACKEND_BEAT_THIS)
        if isinstance(beat_this_state, dict):
            beat_this_state["ready"] = self._beat_this_file2beats is not None
        librosa_state = backends.get(BACKEND_LIBROSA)
        if isinstance(librosa_state, dict):
            librosa_state["ready"] = self._librosa_ready
        dsp_state = backends.get(BACKEND_DSP)
        if isinstance(dsp_state, dict):
            dsp_state["ready"] = True

        snapshot["beat_this_installed"] = bool(beat_this_state.get("installed", False)) if isinstance(beat_this_state, dict) else False
        snapshot["beat_this_ready"] = bool(beat_this_state.get("ready", False)) if isinstance(beat_this_state, dict) else False
        snapshot["librosa_installed"] = bool(librosa_state.get("installed", False)) if isinstance(librosa_state, dict) else False
        snapshot["librosa_ready"] = bool(librosa_state.get("ready", False)) if isinstance(librosa_state, dict) else False
        snapshot["active_backend"] = str(snapshot.get("resolved_backend") or BACKEND_DSP)
        return snapshot

    def _extract_beats_sync(self, audio_path: str, min_confidence: float, preferred_backend: str = BACKEND_AUTO) -> dict:
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        selected_backend = normalize_backend_choice(preferred_backend)
        self._warmup_sync(selected_backend)

        for backend_id in backend_attempt_order(selected_backend):
            if backend_id == BACKEND_BEAT_THIS:
                result = self._try_beat_this(audio_path, min_confidence)
                if result is not None:
                    return result
                logger.warning(f"beat_this failed for {audio_path}, falling back to next backend")
                continue

            if backend_id == BACKEND_LIBROSA:
                result = self._try_librosa(audio_path, min_confidence)
                if result is not None:
                    return result
                logger.warning(f"librosa failed for {audio_path}, falling back to DSP method")
                continue

            return self._extract_dsp_fallback(audio_path, min_confidence)

        return self._extract_dsp_fallback(audio_path, min_confidence)

    def _initialize_backend_sync(self, preferred_backend: str = BACKEND_AUTO, strict: bool = False) -> bool:
        selected_backend = normalize_backend_choice(preferred_backend)
        errors: list[str] = []

        with self._warmup_lock:
            snapshot = get_backend_status_snapshot(selected_backend)
            backends = snapshot.get("backends") if isinstance(snapshot.get("backends"), dict) else {}

            for backend_id in backend_attempt_order(selected_backend):
                backend_state = backends.get(backend_id) if isinstance(backends, dict) else None

                if backend_id == BACKEND_BEAT_THIS:
                    if not isinstance(backend_state, dict) or not backend_state.get("available"):
                        errors.append(self._backend_issue_text(BACKEND_BEAT_THIS, backend_state))
                        continue
                    if self._init_beat_this():
                        self._warmup_done = True
                        return True
                    errors.append("beat_this runtime initialization failed")
                    continue

                if backend_id == BACKEND_LIBROSA:
                    if not isinstance(backend_state, dict) or not backend_state.get("available"):
                        errors.append(self._backend_issue_text(BACKEND_LIBROSA, backend_state))
                        continue
                    if self._warmup_librosa():
                        self._warmup_done = True
                        return True
                    errors.append("librosa runtime initialization failed")
                    continue

                if backend_id == BACKEND_DSP:
                    self._warmup_done = True
                    return True

            self._warmup_done = True

        if strict:
            detail = "; ".join([e for e in errors if e]) or "no available backend"
            raise RuntimeError(f"Failed to initialize requested beat backend: {detail}")
        return False

    def _init_beat_this(self) -> bool:
        try:
            if self._beat_this_file2beats is not None:
                return True

            snapshot = get_backend_status_snapshot(BACKEND_BEAT_THIS)
            backends = snapshot.get("backends") if isinstance(snapshot.get("backends"), dict) else {}
            beat_this_state = backends.get(BACKEND_BEAT_THIS)
            if not isinstance(beat_this_state, dict) or not beat_this_state.get("available"):
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
            logger.exception(f"Error initializing beat_this: {format_exception(ex)}")
            return False

    def _warmup_librosa(self) -> bool:
        try:
            if self._librosa_ready:
                return True

            snapshot = get_backend_status_snapshot(BACKEND_LIBROSA)
            backends = snapshot.get("backends") if isinstance(snapshot.get("backends"), dict) else {}
            librosa_state = backends.get(BACKEND_LIBROSA)
            if not isinstance(librosa_state, dict) or not librosa_state.get("available"):
                return False

            import librosa  # type: ignore

            test_audio = np.zeros((22050,), dtype=np.float32)
            librosa.beat.beat_track(y=test_audio, sr=22050)
            self._librosa_ready = True
            return True
        except Exception as ex:
            logger.exception(f"Error initializing librosa backend: {format_exception(ex)}")
            self._librosa_ready = False
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
            logger.exception(f"Error in beat_this for {audio_path}: {format_exception(ex)}")
            return None

    def _try_librosa(self, audio_path: str, min_confidence: float) -> Optional[dict]:
        try:
            if not self._warmup_librosa():
                return None

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
            logger.exception(f"Error in librosa for {audio_path}: {format_exception(ex)}")
            return None

    def _extract_dsp_fallback(self, audio_path: str, min_confidence: float) -> dict:
        mono, sr, duration = self._load_audio_mono(audio_path)
        beats = self._extract_fallback_from_audio(mono, sr, min_confidence, offset_seconds=0.0)
        return {
            "beats": beats,
            "duration": duration,
            "sr": int(sr),
            "method": BACKEND_DSP,
            "bpm_estimate": _estimate_bpm_from_beats([b["time"] for b in beats]),
        }

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
        self._librosa_ready = False
        self._warmup_done = False

    @staticmethod
    def _backend_issue_text(backend_id: str, backend_state: Any) -> str:
        if not isinstance(backend_state, dict):
            return f"{backend_id} status unavailable"
        missing = backend_state.get("missing_required")
        if isinstance(missing, list) and missing:
            return f"{backend_id} missing: {', '.join(str(x) for x in missing)}"
        return f"{backend_id} is not available"


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
