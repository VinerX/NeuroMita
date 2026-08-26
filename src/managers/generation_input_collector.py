from __future__ import annotations
from core.error_utils import format_exception

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from main_logger import logger


class GenerationInputCollector:
    """Stores pre-prompt generation ingress for runtime debugging and replay."""

    instance: Optional["GenerationInputCollector"] = None

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = os.environ.get("NEUROMITA_BASE_DIR", os.getcwd())
        self.base_dir = Path(base_dir)
        self.saved_dir = self.base_dir / "SavedMessages"
        self.saved_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def is_enabled(self) -> bool:
        try:
            from managers.settings_manager import SettingsManager
            return bool(SettingsManager.get("DEBUG_CAPTURE_GENERATION_INPUT_ENABLED", False))
        except Exception:
            return False

    def save_capture(self, payload: Dict[str, Any]) -> Optional[str]:
        if not self.is_enabled():
            return None

        try:
            now = datetime.now(tz=timezone.utc)
            capture_id = str(uuid.uuid4())
            record = {
                "id": capture_id,
                "timestamp": now.isoformat(),
                **dict(payload or {}),
            }

            last_path = self.saved_dir / "last_generation_input.json"
            log_path = self.saved_dir / f"generation_inputs_{now.strftime('%Y%m')}.jsonl"

            with self._lock:
                with open(last_path, "w", encoding="utf-8") as f:
                    json.dump(record, f, ensure_ascii=False, indent=2)
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

            return capture_id
        except Exception as e:
            logger.error(f"[GenerationInputCollector] Failed to save capture: {format_exception(e)}", exc_info=True)
            return None
