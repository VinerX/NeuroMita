from __future__ import annotations

import math
from typing import Any


def normalize_tv_observation(value: Any) -> dict:
    if not isinstance(value, dict) or value.get("source") != "youtube":
        return {}
    result = {key: str(value.get(key) or "")[:limit] for key, limit in
              (("title", 500), ("author", 300), ("url", 2000), ("subtitles", 512))}
    result["source"] = "youtube"
    for key, limit in (("time_seconds", 864000), ("frame_spacing_seconds", 2), ("frame_count", 8)):
        try:
            number = float(value.get(key) or 0)
            result[key] = min(limit, max(0, number)) if math.isfinite(number) else 0
        except (TypeError, ValueError, OverflowError):
            result[key] = 0
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
    if tv["subtitles"]:
        text += f'\nHeard on TV (Youtube): {tv["subtitles"]}'
    return text + '\n[/TV observation]'


def tv_observation_part(value: Any) -> dict:
    tv = normalize_tv_observation(value)
    return {"type": "text", "text": format_tv_observation(tv), "tv_observation": tv}
