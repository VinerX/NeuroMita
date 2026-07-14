from __future__ import annotations

import os
import time
from typing import Any, Dict, List

from core.events import Events
from core.services import use
from services.contracts import SettingsService
from game_connections.handlers.registry import RequestContext
from game_connections.services.beat_service import get_beat_service
from main_logger import logger


class GetMusicBeatsAction:
    async def handle(self, request: Dict[str, Any], ctx: RequestContext) -> None:
        t0 = time.perf_counter()

        audio_path = str(request.get("audio_path") or "").strip()
        track_name = str(request.get("track_name") or "").strip()
        request_id = str(request.get("request_id") or "").strip()
        stream = bool(request.get("stream", True))

        try:
            chunk_seconds = float(request.get("chunk_seconds", 8.0) or 8.0)
        except Exception:
            chunk_seconds = 8.0

        try:
            min_confidence = float(request.get("min_confidence", 0.2) or 0.2)
        except Exception:
            min_confidence = 0.2

        beat_enabled = bool(use(SettingsService).get("BEAT_SYNC_ENABLED", False))

        req_tag = request_id[:8] if request_id else "-"
        track_for_log = track_name or os.path.basename(audio_path) or "unknown"
        logger.info(
            f"[BeatSync] request req={req_tag} track='{track_for_log}' stream={stream} "
            f"chunk={chunk_seconds:.1f}s min_conf={min_confidence:.2f} "
            "cache_first=True backend=ai_engine"
        )

        if not beat_enabled:
            logger.warning(f"[BeatSync] rejected req={req_tag}: BEAT_SYNC_ENABLED is OFF")
            await ctx.server.send_json(ctx.writer, {
                "type": "music_beats_error",
                "body": {
                    "track_name": track_name,
                    "audio_path": audio_path,
                    "request_id": request_id,
                    "error": "BEAT_SYNC_ENABLED is OFF",
                },
            })
            return

        if not audio_path:
            logger.warning(f"[BeatSync] rejected req={req_tag}: empty audio_path")
            await ctx.server.send_json(ctx.writer, {
                "type": "music_beats_error",
                "body": {
                    "track_name": track_name,
                    "audio_path": audio_path,
                    "request_id": request_id,
                    "error": "audio_path is required",
                },
            })
            return

        await ctx.server.send_json(ctx.writer, {
            "type": "music_beats_job_started",
            "body": {
                "track_name": track_name,
                "audio_path": audio_path,
                "request_id": request_id,
                "stream": stream,
            },
        })

        service = get_beat_service()
        try:
            if stream:
                all_beats: List[Dict[str, float]] = []
                duration = 0.0
                method = "dsp_stream"
                chunks_sent = 0

                async for ch in service.extract_beats_streaming(
                    audio_path=audio_path,
                    chunk_seconds=chunk_seconds,
                    min_confidence=min_confidence,
                    auto_install=False,
                    track_name=track_name,
                ):
                    all_beats.extend(ch.beats)
                    duration = ch.duration
                    method = ch.method
                    chunks_sent += 1

                    await ctx.server.send_json(ctx.writer, {
                        "type": "music_beats_chunk",
                        "body": {
                            "track_name": track_name,
                            "audio_path": audio_path,
                            "request_id": request_id,
                            "chunk_index": ch.chunk_index,
                            "chunks_total": ch.chunks_total,
                            "progress": ch.progress,
                            "beats": ch.beats,
                            "method": ch.method,
                        },
                    })

                    if ch.chunk_index == 0 or ch.chunk_index + 1 == ch.chunks_total or (ch.chunk_index + 1) % 10 == 0:
                        logger.info(
                            f"[BeatSync] chunk req={req_tag} idx={ch.chunk_index + 1}/{ch.chunks_total} "
                            f"beats={len(ch.beats)} progress={ch.progress:.2f} method={ch.method}"
                        )

                bpm_estimate = 0.0
                if len(all_beats) >= 2:
                    times = [float(x.get("time", 0.0)) for x in all_beats]
                    intervals = [b - a for a, b in zip(times, times[1:]) if 1e-3 < (b - a) < 2.0]
                    if intervals:
                        med = sorted(intervals)[len(intervals) // 2]
                        if med > 1e-5:
                            bpm_estimate = 60.0 / med
                            while bpm_estimate < 70.0:
                                bpm_estimate *= 2.0
                            while bpm_estimate > 190.0:
                                bpm_estimate *= 0.5

                await ctx.server.send_json(ctx.writer, {
                    "type": "music_beats_ready",
                    "body": {
                        "track_name": track_name,
                        "audio_path": audio_path,
                        "request_id": request_id,
                        "duration": duration,
                        "beats_count": len(all_beats),
                        "method": method,
                        "bpm_estimate": bpm_estimate,
                    },
                })

                elapsed = time.perf_counter() - t0
                logger.info(
                    f"[BeatSync] ready req={req_tag} method={method} bpm={bpm_estimate:.1f} "
                    f"beats={len(all_beats)} chunks={chunks_sent} duration={duration:.2f}s elapsed={elapsed:.2f}s"
                )
                return

            result = await service.extract_beats(
                audio_path,
                min_confidence=min_confidence,
                auto_install=False,
                track_name=track_name,
            )
            await ctx.server.send_json(ctx.writer, {
                "type": "music_beats_ready",
                "body": {
                    "track_name": track_name,
                    "audio_path": audio_path,
                    "request_id": request_id,
                    "duration": result.duration,
                    "beats": result.beats,
                    "beats_count": len(result.beats),
                    "method": result.method,
                    "bpm_estimate": result.bpm_estimate,
                },
            })

            elapsed = time.perf_counter() - t0
            logger.info(
                f"[BeatSync] ready req={req_tag} method={result.method} bpm={result.bpm_estimate:.1f} "
                f"beats={len(result.beats)} duration={result.duration:.2f}s elapsed={elapsed:.2f}s"
            )
        except Exception as e:
            elapsed = time.perf_counter() - t0
            logger.error(f"[BeatSync] failed req={req_tag} after {elapsed:.2f}s: {e}", exc_info=True)
            await ctx.server.send_json(ctx.writer, {
                "type": "music_beats_error",
                "body": {
                    "track_name": track_name,
                    "audio_path": audio_path,
                    "request_id": request_id,
                    "error": str(e),
                },
            })
