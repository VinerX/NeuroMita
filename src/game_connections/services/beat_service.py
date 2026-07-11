from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

from core.runtime_environments import runtime_environments
from core.services import use
from game_connections.services.beat_backend_spec import (
    BACKEND_AUTO,
    BACKEND_BEAT_THIS,
    normalize_backend_choice,
)
from game_connections.services.beat_worker_client import call_beats_worker_async, call_beats_worker_sync
from main_logger import logger
from services.contracts import AIEngineService

try:
    from managers.settings_manager import SettingsManager
except Exception:
    SettingsManager = None


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
    preferred_backend: str
    resolved_backend: str
    librosa_installed: bool
    librosa_ready: bool
    torch_variant: str
    torch_ready: bool
    backends: Dict[str, Dict[str, Any]]
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
        self._project_root = Path(__file__).resolve().parents[3]
        self._cache_dir = str(self._project_root / "beat_sync_cache")

    def _activate_managed_runtime(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> bool | None:
        preference = normalize_backend_choice(payload.get("backend_preference"))
        if preference not in (BACKEND_AUTO, BACKEND_BEAT_THIS):
            return None

        record = runtime_environments().active_for(
            category="beats",
            item_id=BACKEND_BEAT_THIS,
        )
        if record is None:
            return False if preference == BACKEND_BEAT_THIS else None

        engine = use(AIEngineService).get_engine()
        activate = getattr(engine, "activate_environment", None)
        if not callable(activate):
            return False
        return bool(
            activate(
                "beats",
                BACKEND_BEAT_THIS,
                category="beats",
                runtime_slot="beats",
                timeout=min(30.0, max(1.0, float(timeout))),
                validation_method=method,
                validation_payload=dict(payload),
                validation_timeout=max(1.0, float(timeout)),
            )
        )

    async def warmup(self, auto_install: bool = False) -> None:
        if self._warmup_done:
            return
        async with self._warmup_lock:
            if self._warmup_done:
                return
            try:
                payload = self._worker_payload(auto_install=auto_install)
                managed = await asyncio.to_thread(
                    self._activate_managed_runtime,
                    "warmup",
                    payload,
                    timeout=120.0,
                )
                if managed is False:
                    raise RuntimeError("Managed Beat This environment could not be initialized")
                if managed is None:
                    await call_beats_worker_async(
                        "warmup",
                        payload,
                        timeout=120.0,
                    )
                self._warmup_done = True
            except Exception as exc:
                logger.error(f"[BeatSync] worker warmup failed: {exc}", exc_info=True)

    def reset_runtime_state(self) -> None:
        self._warmup_done = False

    def initialize_backend(self, *, backend_preference: str | None = None) -> bool:
        payload = self._worker_payload(auto_install=False, backend_preference=backend_preference)
        payload["strict"] = True
        try:
            managed = self._activate_managed_runtime(
                "initialize_backend",
                payload,
                timeout=180.0,
            )
            result = (
                managed
                if managed is not None
                else call_beats_worker_sync("initialize_backend", payload, timeout=180.0)
            )
            self._warmup_done = bool(result)
            return bool(result)
        except Exception as exc:
            logger.error(f"[BeatSync] backend initialization failed: {exc}", exc_info=True)
            return False

    async def extract_beats(
        self,
        audio_path: str,
        min_confidence: float = 0.2,
        auto_install: bool = False,
        track_name: str = "",
    ) -> BeatTrackResult:
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        t0 = time.perf_counter()
        cached = self._load_cached_result(audio_path)
        if cached is not None:
            logger.info(
                f"[BeatSync] cache-hit track='{_short_path(audio_path)}' method={cached.method} "
                f"beats={len(cached.beats)}"
            )
            result = cached
        else:
            result = await self._extract_uncached_async(audio_path, float(min_confidence))
            self._save_cached_result(audio_path, result, track_name=str(track_name or ""))

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

    async def _extract_uncached_async(self, audio_path: str, min_confidence: float) -> BeatTrackResult:
        if not self._warmup_done:
            await self.warmup(auto_install=False)
        try:
            payload = await call_beats_worker_async(
                "extract_beats",
                {
                    "audio_path": audio_path,
                    "min_confidence": float(min_confidence),
                    "backend_preference": self._backend_preference(),
                },
                timeout=3600.0,
            )
            return _coerce_track_result(payload)
        except Exception as exc:
            logger.error(f"[BeatSync] worker backend failed for '{_short_path(audio_path)}': {exc}", exc_info=True)
            raise RuntimeError(f"Beat worker request failed for '{_short_path(audio_path)}'") from exc

    def _extract_uncached_sync(self, audio_path: str, min_confidence: float) -> BeatTrackResult:
        if not self._warmup_done:
            self.initialize_backend()
        try:
            payload = call_beats_worker_sync(
                "extract_beats",
                {
                    "audio_path": audio_path,
                    "min_confidence": float(min_confidence),
                    "backend_preference": self._backend_preference(),
                },
                timeout=3600.0,
            )
            return _coerce_track_result(payload)
        except Exception as exc:
            logger.error(f"[BeatSync] worker backend failed for '{_short_path(audio_path)}': {exc}", exc_info=True)
            raise RuntimeError(f"Beat worker request failed for '{_short_path(audio_path)}'") from exc

    def get_backend_status(self) -> BeatBackendStatus:
        cache_stats = self.get_cache_stats()

        beat_this_installed = False
        beat_this_ready = False
        librosa_installed = False
        librosa_ready = False
        torch_variant = "missing"
        torch_ready = False
        active_backend = "engine_unavailable"
        preferred_backend = self._backend_preference()
        resolved_backend = active_backend
        backends: Dict[str, Dict[str, Any]] = {}

        try:
            # First call after a restart can take a few seconds (worker is
            # still importing torch / loading model weights). Give the
            # worker a realistic budget and treat the transient timeout as
            # a warning rather than a hard error.
            payload = call_beats_worker_sync(
                "get_backend_status",
                {"backend_preference": preferred_backend},
                timeout=8.0,
            )
            backends_raw = payload.get("backends")
            backends = backends_raw if isinstance(backends_raw, dict) else {}
            beat_this_state = backends.get("beat_this") if isinstance(backends.get("beat_this"), dict) else {}
            librosa_state = backends.get("librosa") if isinstance(backends.get("librosa"), dict) else {}

            beat_this_installed = bool(beat_this_state.get("installed", False))
            beat_this_ready = bool(beat_this_state.get("ready", False))
            librosa_installed = bool(librosa_state.get("installed", False))
            librosa_ready = bool(librosa_state.get("ready", False))
            active_backend = str(payload.get("active_backend") or active_backend)
            preferred_backend = str(payload.get("preferred_backend") or preferred_backend)
            resolved_backend = str(payload.get("resolved_backend") or active_backend)
            torch_payload = payload.get("torch") if isinstance(payload.get("torch"), dict) else {}
            torch_extra = torch_payload.get("extra") if isinstance(torch_payload.get("extra"), dict) else {}
            torch_variant = str(torch_extra.get("variant") or torch_variant)
            torch_ready = bool(torch_payload.get("ok", False))
        except TimeoutError:
            # Worker is restarting / cold-starting; the UI will refresh
            # again once the next install/restart event fires.
            logger.warning("[BeatSync] backend status request timed out (worker warming up?)")
            active_backend = "engine_warming"
            resolved_backend = active_backend
        except Exception as exc:
            logger.error(f"[BeatSync] backend status unavailable: {exc}", exc_info=True)

        return BeatBackendStatus(
            beat_this_installed=beat_this_installed,
            beat_this_ready=beat_this_ready,
            active_backend=active_backend,
            preferred_backend=preferred_backend,
            resolved_backend=resolved_backend,
            librosa_installed=librosa_installed,
            librosa_ready=librosa_ready,
            torch_variant=torch_variant,
            torch_ready=torch_ready,
            backends=backends,
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

        if not self._warmup_done and not self.initialize_backend():
            logger.error("[BeatSync] worker warmup failed for cache build")

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

    @staticmethod
    def _backend_preference() -> str:
        if SettingsManager is None:
            return BACKEND_AUTO
        return normalize_backend_choice(SettingsManager.get("BEAT_SYNC_BACKEND", BACKEND_AUTO))

    def _worker_payload(self, *, auto_install: bool, backend_preference: str | None = None) -> dict:
        return {
            "auto_install": bool(auto_install),
            "backend_preference": normalize_backend_choice(backend_preference or self._backend_preference()),
        }


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


_service: Optional[BeatService] = None


def get_beat_service() -> BeatService:
    global _service
    if _service is None:
        _service = BeatService()
    return _service
