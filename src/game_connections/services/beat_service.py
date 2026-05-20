from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Dict, Iterable, List, Optional, Tuple

import numpy as np
import soundfile as sf

from core.events import Events, get_event_bus
from main_logger import logger


BEAT_CACHE_VERSION = 2
AUDIO_FILE_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".ogg",
    ".flac",
    ".aac",
    ".m4a",
    ".opus",
    ".wma",
}


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


@dataclass
class BeatBackendStatus:
    beat_this_installed: bool
    beat_this_ready: bool
    active_backend: str
    cache_dir: str
    cache_entries: int
    cache_bytes: int


@dataclass
class BeatCacheBuildSummary:
    root_dir: str
    scanned_files: int
    cache_hits: int
    generated: int
    failed: int
    failed_files: List[str]


class BeatService:
    """Cache-first beat-sync proxy. Heavy backends live in ai_engine worker service='beats'."""

    def __init__(self):
        self._warmup_done = False
        self._warmup_lock = asyncio.Lock()
        self._engine = None
        self._project_root = Path(__file__).resolve().parents[3]
        self._cache_dir = str(self._project_root / "beat_sync_cache")

    async def warmup(self, auto_install: bool = False) -> None:
        if self._warmup_done:
            return
        async with self._warmup_lock:
            if self._warmup_done:
                return
            try:
                await self._engine_call_async("warmup", {"auto_install": bool(auto_install)}, timeout=120.0)
                self._warmup_done = True
            except Exception as exc:
                logger.info(f"[BeatSync] worker warmup skipped: {exc}")

    def reset_runtime_state(self) -> None:
        self._engine = None
        self._warmup_done = False

    async def extract_beats(
        self,
        audio_path: str,
        min_confidence: float = 0.2,
        auto_install: bool = False,
        track_name: str = "",
    ) -> BeatTrackResult:
        await self.warmup(auto_install=auto_install)
        t0 = time.perf_counter()
        result = await asyncio.to_thread(
            self._extract_beats_sync,
            audio_path,
            float(min_confidence),
            str(track_name or ""),
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
        auto_install: bool = False,
        track_name: str = "",
    ) -> AsyncIterator[BeatStreamChunk]:
        result = await self.extract_beats(
            audio_path=audio_path,
            min_confidence=min_confidence,
            auto_install=auto_install,
            track_name=track_name,
        )
        yield BeatStreamChunk(
            beats=result.beats,
            chunk_index=0,
            chunks_total=1,
            progress=1.0,
            duration=result.duration,
            method=result.method,
        )

    def _extract_beats_sync(
        self,
        audio_path: str,
        min_confidence: float,
        track_name: str = "",
    ) -> BeatTrackResult:
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        cached = self._load_cached_result(audio_path)
        if cached is not None:
            logger.info(
                f"[BeatSync] cache-hit track='{_short_path(audio_path)}' method={cached.method} "
                f"beats={len(cached.beats)}"
            )
            return cached

        result = self._extract_uncached_sync(audio_path, min_confidence)
        self._save_cached_result(audio_path, result, track_name=track_name)
        return result

    def _extract_uncached_sync(self, audio_path: str, min_confidence: float) -> BeatTrackResult:
        try:
            payload = self._engine_call_sync(
                "extract_beats",
                {
                    "audio_path": audio_path,
                    "min_confidence": float(min_confidence),
                },
                timeout=3600.0,
            )
            return _coerce_track_result(payload)
        except Exception as exc:
            logger.warning(f"[BeatSync] worker backend failed for '{_short_path(audio_path)}': {exc}")

        mono, sr, duration = self._load_audio_mono(audio_path)
        beats = self._extract_fallback_from_audio(mono, sr, min_confidence, offset_seconds=0.0)
        bpm = _estimate_bpm_from_beats([b["time"] for b in beats])
        return BeatTrackResult(beats=beats, duration=duration, sr=int(sr), method="dsp_fallback", bpm_estimate=bpm)

    def get_backend_status(self) -> BeatBackendStatus:
        cache_stats = self.get_cache_stats()

        beat_this_installed = False
        beat_this_ready = False
        active_backend = "engine_unavailable"

        try:
            payload = self._engine_call_sync("get_backend_status", {}, timeout=2.0)
            beat_this_installed = bool(payload.get("beat_this_installed", False))
            beat_this_ready = bool(payload.get("beat_this_ready", False))
            active_backend = str(payload.get("active_backend") or active_backend)
        except Exception as exc:
            logger.debug(f"[BeatSync] backend status unavailable: {exc}")

        return BeatBackendStatus(
            beat_this_installed=beat_this_installed,
            beat_this_ready=beat_this_ready,
            active_backend=active_backend,
            cache_dir=self._cache_dir,
            cache_entries=int(cache_stats["entries"]),
            cache_bytes=int(cache_stats["bytes"]),
        )

    def get_cache_stats(self) -> Dict[str, int]:
        entries = 0
        total_bytes = 0
        try:
            cache_root = Path(self._cache_dir)
            if not cache_root.exists():
                return {"entries": 0, "bytes": 0}
            for item in cache_root.glob("*.json"):
                try:
                    st = item.stat()
                except OSError:
                    continue
                entries += 1
                total_bytes += int(st.st_size)
        except Exception:
            return {"entries": 0, "bytes": 0}
        return {"entries": entries, "bytes": total_bytes}

    def build_cache_for_directory(
        self,
        directory_path: str,
        *,
        min_confidence: float = 0.2,
        auto_install: bool = False,
    ) -> BeatCacheBuildSummary:
        root = Path(directory_path).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Directory not found: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        try:
            self._engine_call_sync("warmup", {"auto_install": bool(auto_install)}, timeout=120.0)
            self._warmup_done = True
        except Exception as exc:
            logger.info(f"[BeatSync] worker warmup skipped for cache build: {exc}")

        scanned_files = 0
        cache_hits = 0
        generated = 0
        failed = 0
        failed_files: List[str] = []

        for audio_file in self.iter_audio_files(root):
            scanned_files += 1
            try:
                if self._load_cached_result(str(audio_file)) is not None:
                    cache_hits += 1
                    continue
                result = self._extract_uncached_sync(str(audio_file), float(min_confidence))
                self._save_cached_result(str(audio_file), result, track_name=audio_file.stem)
                generated += 1
            except Exception as exc:
                failed += 1
                failed_files.append(f"{audio_file.name}: {exc}")
                logger.error(f"[BeatSync] cache build failed for '{audio_file}': {exc}", exc_info=True)

        return BeatCacheBuildSummary(
            root_dir=str(root),
            scanned_files=scanned_files,
            cache_hits=cache_hits,
            generated=generated,
            failed=failed,
            failed_files=failed_files,
        )

    def iter_audio_files(self, directory_path: Path | str) -> Iterable[Path]:
        root = Path(directory_path)
        for item in sorted(root.rglob("*")):
            if not item.is_file():
                continue
            if item.suffix.lower() not in AUDIO_FILE_EXTENSIONS:
                continue
            yield item

    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        event_bus = get_event_bus()
        try:
            res = event_bus.emit_and_wait(Events.AI.GET_ENGINE, timeout=1.0)
            self._engine = res[0] if res else None
        except Exception:
            self._engine = None
        return self._engine

    async def _engine_call_async(self, method: str, payload: Optional[dict] = None, timeout: float = 30.0):
        eng = self._get_engine()
        if eng is None:
            raise RuntimeError("AI engine not available")
        fut = eng.call("beats", method, payload or {})
        return await asyncio.wait_for(asyncio.wrap_future(fut), timeout=timeout)

    def _engine_call_sync(self, method: str, payload: Optional[dict] = None, timeout: float = 30.0):
        eng = self._get_engine()
        if eng is None:
            raise RuntimeError("AI engine not available")
        fut = eng.call("beats", method, payload or {})
        return fut.result(timeout=timeout)

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

    def _load_cached_result(self, audio_path: str) -> Optional[BeatTrackResult]:
        try:
            source_hash = self._file_content_hash(audio_path)
            cache_path = self._cache_path_for_hash(source_hash)
            if not os.path.exists(cache_path):
                return None

            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if str(data.get("source_hash") or "") != source_hash:
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
        except Exception as exc:
            logger.debug(f"[BeatSync] cache read skipped for '{_short_path(audio_path)}': {exc}")
            return None

    def _save_cached_result(self, audio_path: str, result: BeatTrackResult, *, track_name: str = "") -> None:
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            method = result.method[6:] if result.method.startswith("cache:") else result.method
            source_hash = self._file_content_hash(audio_path)
            data = {
                "version": BEAT_CACHE_VERSION,
                "source_hash": source_hash,
                "track_name": str(track_name or Path(audio_path).stem),
                "source_path": os.path.abspath(audio_path),
                "source_kind": "audio_file",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "beats": result.beats,
                "duration": float(result.duration),
                "sr": int(result.sr),
                "method": method,
                "bpm_estimate": float(result.bpm_estimate),
            }
            cache_path = self._cache_path_for_hash(source_hash)
            tmp_path = cache_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            try:
                os.replace(tmp_path, cache_path)
            except PermissionError:
                # Some Windows environments deny atomic replace even inside the same directory.
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            logger.info(f"[BeatSync] cache-save track='{_short_path(audio_path)}' method={method} beats={len(result.beats)}")
        except Exception as exc:
            logger.debug(f"[BeatSync] cache save skipped for '{_short_path(audio_path)}': {exc}")

    def _cache_path_for_hash(self, source_hash: str) -> str:
        return os.path.join(self._cache_dir, f"{source_hash}.json")

    @staticmethod
    def _file_content_hash(audio_path: str) -> str:
        digest = hashlib.sha256()
        with open(audio_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


def _coerce_track_result(payload: dict) -> BeatTrackResult:
    beats_raw = payload.get("beats") or []
    beats = [
        {"time": float(b.get("time", 0.0)), "confidence": float(b.get("confidence", 0.0))}
        for b in beats_raw
        if isinstance(b, dict)
    ]
    return BeatTrackResult(
        beats=beats,
        duration=float(payload.get("duration", 0.0) or 0.0),
        sr=int(payload.get("sr", 0) or 0),
        method=str(payload.get("method", "unknown") or "unknown"),
        bpm_estimate=float(payload.get("bpm_estimate", 0.0) or 0.0),
    )


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


_service: Optional[BeatService] = None


def get_beat_service() -> BeatService:
    global _service
    if _service is None:
        _service = BeatService()
    return _service
