from __future__ import annotations

import asyncio
import hashlib
import json
import importlib.util
import math
import os
import time
from dataclasses import dataclass
from typing import AsyncIterator, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf

from main_logger import logger


@dataclass
class BeatTrackResult:
    beats: List[Dict[str, float]]
    duration: float
    sr: int
    method: str
    bpm_estimate: float


@dataclass
class BeatStreamChunk:
    beats: List[Dict[str, float]]
    chunk_index: int
    chunks_total: int
    progress: float
    duration: float
    method: str


class BeatService:
    """Beat extraction service with optional ML backend and robust DSP fallback."""

    def __init__(self):
        self._warmup_done = False
        self._warmup_lock = asyncio.Lock()
        self._beat_this_file2beats = None
        self._cache_dir = os.path.join("Settings", "beat_cache")

    async def warmup(self, auto_install: bool = True) -> None:
        if self._warmup_done:
            return
        async with self._warmup_lock:
            if self._warmup_done:
                return
            t0 = time.perf_counter()
            await asyncio.to_thread(self._warmup_sync, bool(auto_install))
            self._warmup_done = True
            logger.info(f"[BeatSync] warmup completed in {(time.perf_counter() - t0):.2f}s")

    def _warmup_sync(self, auto_install: bool) -> None:
        if self._init_beat_this(auto_install=auto_install):
            return

        try:
            import librosa  # type: ignore  # noqa: F401

            logger.info("[BeatSync] backend selected: librosa")
            return
        except Exception:
            pass

        logger.info("[BeatSync] backend selected: dsp_fallback")

    async def extract_beats(
        self,
        audio_path: str,
        min_confidence: float = 0.2,
        auto_install: bool = True,
    ) -> BeatTrackResult:
        await self.warmup(auto_install=auto_install)
        t0 = time.perf_counter()
        result = await asyncio.to_thread(
            self._extract_beats_sync,
            audio_path,
            float(min_confidence),
            bool(auto_install),
        )
        logger.info(
            f"[BeatSync] extract_beats method={result.method} track='{_short_path(audio_path)}' "
            f"beats={len(result.beats)} elapsed={(time.perf_counter() - t0):.2f}s"
        )
        return result

    async def extract_beats_streaming(
        self,
        audio_path: str,
        chunk_seconds: float = 8.0,
        min_confidence: float = 0.2,
        auto_install: bool = True,
    ) -> AsyncIterator[BeatStreamChunk]:
        await self.warmup(auto_install=auto_install)

        cached = await asyncio.to_thread(self._load_cached_result, audio_path)
        if cached is not None:
            logger.info(
                f"[BeatSync] cache-hit stream track='{_short_path(audio_path)}' method={cached.method} "
                f"beats={len(cached.beats)}"
            )
            yield BeatStreamChunk(
                beats=cached.beats,
                chunk_index=0,
                chunks_total=1,
                progress=1.0,
                duration=cached.duration,
                method=f"cache:{cached.method}",
            )
            return

        mono, sr, duration = await asyncio.to_thread(self._load_audio_mono, audio_path)

        chunk_seconds = max(1.0, float(chunk_seconds))
        chunk_samples = max(1, int(round(chunk_seconds * sr)))
        chunks_total = max(1, int(math.ceil(len(mono) / float(chunk_samples))))
        all_beats: List[Dict[str, float]] = []
        method = "dsp_stream"

        logger.info(
            f"[BeatSync] stream-start track='{_short_path(audio_path)}' chunks={chunks_total} "
            f"chunk_seconds={chunk_seconds:.1f} min_conf={min_confidence:.2f}"
        )

        for idx in range(chunks_total):
            start = idx * chunk_samples
            end = min(len(mono), start + chunk_samples)
            segment = mono[start:end]
            offset_sec = float(start) / float(sr)

            beats = await asyncio.to_thread(
                self._extract_fallback_from_audio,
                segment,
                sr,
                float(min_confidence),
                offset_sec,
            )
            all_beats.extend(beats)

            yield BeatStreamChunk(
                beats=beats,
                chunk_index=idx,
                chunks_total=chunks_total,
                progress=float(idx + 1) / float(chunks_total),
                duration=duration,
                method=method,
            )

        bpm = _estimate_bpm_from_beats([b["time"] for b in all_beats])
        await asyncio.to_thread(
            self._save_cached_result,
            audio_path,
            BeatTrackResult(beats=all_beats, duration=duration, sr=int(sr), method=method, bpm_estimate=bpm),
        )

    def _extract_beats_sync(self, audio_path: str, min_confidence: float, auto_install: bool) -> BeatTrackResult:
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        cached = self._load_cached_result(audio_path)
        if cached is not None:
            logger.info(
                f"[BeatSync] cache-hit track='{_short_path(audio_path)}' method={cached.method} "
                f"beats={len(cached.beats)}"
            )
            return cached

        res = self._try_beat_this(audio_path, min_confidence, auto_install=auto_install)
        if res is not None:
            self._save_cached_result(audio_path, res)
            return res

        res = self._try_librosa(audio_path, min_confidence)
        if res is not None:
            self._save_cached_result(audio_path, res)
            return res

        mono, sr, duration = self._load_audio_mono(audio_path)
        beats = self._extract_fallback_from_audio(mono, sr, min_confidence, offset_seconds=0.0)
        bpm = _estimate_bpm_from_beats([b["time"] for b in beats])
        result = BeatTrackResult(beats=beats, duration=duration, sr=int(sr), method="dsp_fallback", bpm_estimate=bpm)
        self._save_cached_result(audio_path, result)
        return result

    def _init_beat_this(self, auto_install: bool) -> bool:
        try:
            if self._beat_this_file2beats is not None:
                return True

            if not _module_available("beat_this"):
                if not auto_install:
                    logger.info("[BeatSync] beat_this not installed and auto_install is disabled")
                    return False
                pip_installer = _get_default_pip_installer()
                if pip_installer is None:
                    logger.warning("[BeatSync] PipInstaller unavailable, cannot auto-install beat_this")
                    return False

                logger.info("[BeatSync] installing optional package beat-this...")
                ok = pip_installer.install_package(
                    ["beat-this", "tqdm", "einops", "soxr", "rotary-embedding-torch"],
                    description="Installing optional beat-sync package: beat-this",
                )
                if not ok:
                    logger.warning("[BeatSync] optional beat-this install failed; fallback backend will be used")
                    return False

                logger.info("[BeatSync] optional beat-this package installed")

            from beat_this.inference import File2Beats  # type: ignore

            device = "cpu"
            try:
                import torch  # type: ignore

                if bool(torch.cuda.is_available()):
                    device = "cuda"
            except Exception:
                device = "cpu"

            self._beat_this_file2beats = File2Beats(checkpoint_path="final0", device=device, dbn=False)
            logger.info(f"[BeatSync] beat_this initialized on device={device} checkpoint=final0")
            return True
        except Exception as e:
            logger.warning(f"[BeatSync] beat_this init skipped: {e}")
            return False

    def _try_beat_this(self, audio_path: str, min_confidence: float, auto_install: bool) -> Optional[BeatTrackResult]:
        try:
            if self._beat_this_file2beats is None and not self._init_beat_this(auto_install=auto_install):
                return None

            f2b = self._beat_this_file2beats
            beats_arr, _downbeats_arr = f2b(audio_path)
            beats = [{"time": float(t), "confidence": 1.0} for t in list(beats_arr)]
            beats = [b for b in beats if b["confidence"] >= min_confidence]
            duration = self._probe_duration(audio_path)
            bpm = _estimate_bpm_from_beats([b["time"] for b in beats])
            return BeatTrackResult(beats=beats, duration=duration, sr=0, method="beat_this", bpm_estimate=bpm)
        except Exception as e:
            logger.warning(f"[BeatSync] beat_this backend failed for '{_short_path(audio_path)}': {e}")
        return None

    def _try_librosa(self, audio_path: str, min_confidence: float) -> Optional[BeatTrackResult]:
        try:
            import librosa  # type: ignore

            y, sr = librosa.load(audio_path, sr=22050, mono=True)
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            times = librosa.frames_to_time(beat_frames, sr=sr)
            beats = [{"time": float(t), "confidence": 0.9} for t in times]
            beats = [b for b in beats if b["confidence"] >= min_confidence]
            return BeatTrackResult(
                beats=beats,
                duration=float(len(y) / float(sr)) if sr > 0 else 0.0,
                sr=int(sr),
                method="librosa",
                bpm_estimate=float(tempo) if tempo else _estimate_bpm_from_beats([b["time"] for b in beats]),
            )
        except Exception:
            return None

    def _load_audio_mono(self, audio_path: str, target_sr: int = 22050) -> Tuple[np.ndarray, int, float]:
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

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


    def _load_cached_result(self, audio_path: str) -> Optional[BeatTrackResult]:
        try:
            signature = self._file_signature(audio_path)
            cache_path = self._cache_path_for(audio_path)
            if not os.path.exists(cache_path):
                return None

            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if data.get("signature") != signature:
                return None

            beats_raw = data.get("beats") or []
            beats = [
                {"time": float(b.get("time", 0.0)), "confidence": float(b.get("confidence", 1.0))}
                for b in beats_raw
                if isinstance(b, dict)
            ]
            return BeatTrackResult(
                beats=beats,
                duration=float(data.get("duration", 0.0) or 0.0),
                sr=int(data.get("sr", 0) or 0),
                method=str(data.get("method", "cache") or "cache"),
                bpm_estimate=float(data.get("bpm_estimate", 0.0) or 0.0),
            )
        except Exception as e:
            logger.debug(f"[BeatSync] cache read skipped for '{_short_path(audio_path)}': {e}")
            return None

    def _save_cached_result(self, audio_path: str, result: BeatTrackResult) -> None:
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            method = result.method[6:] if result.method.startswith("cache:") else result.method
            data = {
                "version": 1,
                "signature": self._file_signature(audio_path),
                "source_path": os.path.abspath(audio_path),
                "beats": result.beats,
                "duration": float(result.duration),
                "sr": int(result.sr),
                "method": method,
                "bpm_estimate": float(result.bpm_estimate),
            }
            cache_path = self._cache_path_for(audio_path)
            tmp_path = cache_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_path, cache_path)
            logger.info(f"[BeatSync] cache-save track='{_short_path(audio_path)}' method={method} beats={len(result.beats)}")
        except Exception as e:
            logger.debug(f"[BeatSync] cache save skipped for '{_short_path(audio_path)}': {e}")

    def _cache_path_for(self, audio_path: str) -> str:
        key = hashlib.sha256(os.path.abspath(audio_path).lower().encode("utf-8", errors="ignore")).hexdigest()
        return os.path.join(self._cache_dir, f"{key}.json")

    @staticmethod
    def _file_signature(audio_path: str) -> Dict[str, object]:
        st = os.stat(audio_path)
        return {
            "path": os.path.abspath(audio_path).lower(),
            "size": int(st.st_size),
            "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))),
        }

    @staticmethod
    def _probe_duration(audio_path: str) -> float:
        try:
            info = sf.info(audio_path)
            if info and info.samplerate > 0:
                return float(info.frames) / float(info.samplerate)
        except Exception:
            pass
        return 0.0


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _get_default_pip_installer():
    try:
        from utils.pip_installer import PipInstaller

        return PipInstaller(update_log=logger.info)
    except Exception:
        return None


def _short_path(path: str) -> str:
    if not path:
        return "-"
    return os.path.basename(path) or path


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
    out = np.interp(dst_x, src_x, y).astype(np.float32)
    return out


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


_service: Optional[BeatService] = None


def get_beat_service() -> BeatService:
    global _service
    if _service is None:
        _service = BeatService()
    return _service
