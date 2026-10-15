from __future__ import annotations

import math
from typing import Any


def normalize_tv_observation(value: Any) -> dict:
    if not isinstance(value, dict) or value.get("source") != "youtube":
        return {}
    result = {key: str(value.get(key) or "")[:limit] for key, limit in
              (("title", 500), ("author", 300), ("url", 2000), ("subtitles", 4096))}
    result["source"] = "youtube"
    for key, limit in (("time_seconds", 864000), ("frame_spacing_seconds", 1800), ("frame_count", 8)):
        try:
            number = float(value.get(key) or 0)
            result[key] = min(limit, max(0, number)) if math.isfinite(number) else 0
        except (TypeError, ValueError, OverflowError):
            result[key] = 0
    times = value.get("frame_times_seconds")
    if isinstance(times, list):
        clean_times = []
        for time in times[:8]:
            try:
                number = float(time)
                if math.isfinite(number) and number >= 0:
                    clean_times.append(min(864000, number))
            except (TypeError, ValueError, OverflowError):
                pass
        result["frame_times_seconds"] = clean_times
    result["frame_count"] = int(result["frame_count"])
    result["frame_order"] = "oldest_first"
    return result


def format_tv_observation(value: Any) -> str:
    tv = normalize_tv_observation(value)
    if not tv:
        return ""
    seconds = tv["time_seconds"]
    text = (f'[TV observation] You and the player are watching YouTube on the in-game TV. '
            f'Video: {tv["title"]}. Author: {tv["author"] or "unknown"}. '
            f'Playback position: {seconds:.1f} seconds. '
            f'The attached {tv["frame_count"]} frames show the TV screen in chronological order, '
            f'{tv["frame_spacing_seconds"]:.1f} seconds apart. '
            'They are not images uploaded by the player or your own camera view. '
            "Distinguish the player's current words from the video dialogue. "
            'Do not assume that events shown in the video happened to you in the game.')
    if tv.get("frame_times_seconds"):
        text += "\nFrame playback timestamps (seconds, same order as images): " + ", ".join(f"{time:.1f}" for time in tv["frame_times_seconds"])
    if tv["subtitles"]:
        text += f'\nHeard on TV (Youtube): {tv["subtitles"]}'
    return text + '\n[/TV observation]'


def tv_observation_part(value: Any) -> dict:
    tv = normalize_tv_observation(value)
    return {"type": "text", "text": format_tv_observation(tv), "tv_observation": tv}


def is_tv_observation_event(message: dict) -> bool:
    """TV-only incoming context is an observation, not a character utterance."""
    tv = normalize_tv_observation(message.get("tv_observation"))
    if not tv:
        return False
    content = message.get("content")
    parts = content if isinstance(content, list) else [{"type": "text", "text": str(content or "")}]
    context = format_tv_observation(tv)
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            if str(part.get("text") or "").replace(context, "").strip():
                return False
    return True
