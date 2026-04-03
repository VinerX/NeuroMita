# src/managers/finetune_collector.py
"""
FineTuneCollector — сбор данных для дообучения моделей.

Каждый успешный запрос-ответ сохраняется как самодостаточная запись JSONL
с полным контекстом (messages), метаданными модели/провайдера и опциональным рейтингом.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from main_logger import logger


class FineTuneCollector:
    """Синглтон для сбора данных дообучения."""

    instance: Optional["FineTuneCollector"] = None

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = os.environ.get("NEUROMITA_BASE_DIR", os.getcwd())
        self.data_dir = Path(base_dir) / "FineTuneData"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._pending_sample_id: Optional[str] = None

    # ── Settings integration ──────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        try:
            from managers.settings_manager import SettingsManager
            return bool(SettingsManager.get("FINETUNE_COLLECTION_ENABLED", False))
        except Exception:
            return False

    # ── Core save ────────────────────────────────────────────────────────────

    def save_sample(
        self,
        req: Any,
        response_text: str,
        character_id: str,
        character_name: str,
        game_connected: bool = False,
    ) -> Optional[str]:
        """
        Сохраняет пару запрос-ответ в JSONL.
        Возвращает sample_id или None при ошибке.
        """
        if not self.is_enabled():
            return None

        try:
            sample_id = str(uuid.uuid4())
            now = datetime.now(tz=timezone.utc)

            extra = getattr(req, "extra", {}) or {}

            record: Dict[str, Any] = {
                "id": sample_id,
                "timestamp": now.isoformat(),
                "character_id": character_id,
                "character_name": character_name,
                "model": getattr(req, "model", None),
                "provider_name": getattr(req, "provider_name", None),
                "protocol_id": getattr(req, "protocol_id", None),
                "dialect_id": getattr(req, "dialect_id", None),
                "temperature": extra.get("temperature"),
                "top_p": extra.get("top_p"),
                "top_k": extra.get("top_k"),
                "presence_penalty": extra.get("presence_penalty"),
                "frequency_penalty": extra.get("frequency_penalty"),
                "max_tokens": extra.get("max_tokens"),
                "game_connected": game_connected,
                "messages": getattr(req, "messages", []),
                "response": response_text,
                "rating": None,
            }

            file_path = self.data_dir / f"samples_{now.strftime('%Y%m')}.jsonl"

            with self._lock:
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                self._pending_sample_id = sample_id

            logger.debug(f"[FineTuneCollector] Saved sample {sample_id} to {file_path.name}")
            return sample_id

        except Exception as e:
            logger.error(f"[FineTuneCollector] Failed to save sample: {e}", exc_info=True)
            return None

    # ── Rating ────────────────────────────────────────────────────────────────

    def update_rating(self, sample_id: str, rating: int) -> bool:
        """Обновляет рейтинг записи. rating: 1 (👍) или -1 (👎)."""
        try:
            with self._lock:
                for file_path in sorted(self.data_dir.glob("samples_*.jsonl"), reverse=True):
                    lines = file_path.read_text(encoding="utf-8").splitlines()
                    new_lines = []
                    found = False
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            if rec.get("id") == sample_id:
                                rec["rating"] = rating
                                new_lines.append(json.dumps(rec, ensure_ascii=False))
                                found = True
                            else:
                                new_lines.append(line)
                        except json.JSONDecodeError:
                            new_lines.append(line)
                    if found:
                        file_path.write_text(
                            "\n".join(new_lines) + "\n", encoding="utf-8"
                        )
                        logger.debug(f"[FineTuneCollector] Rated {sample_id} = {rating}")
                        return True
            return False
        except Exception as e:
            logger.error(f"[FineTuneCollector] Failed to update rating: {e}", exc_info=True)
            return False

    # ── Pending sample_id (for UI rating buttons) ─────────────────────────────

    def pop_pending_sample_id(self) -> Optional[str]:
        """Потребляет и возвращает последний сохранённый sample_id."""
        with self._lock:
            sid = self._pending_sample_id
            self._pending_sample_id = None
            return sid

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику по всем записям."""
        total = 0
        by_character: Dict[str, int] = {}
        by_model: Dict[str, int] = {}
        rated = 0
        positive = 0
        negative = 0

        try:
            for file_path in sorted(self.data_dir.glob("samples_*.jsonl")):
                for line in file_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        total += 1
                        char_id = rec.get("character_id") or "unknown"
                        by_character[char_id] = by_character.get(char_id, 0) + 1
                        model = rec.get("model") or "unknown"
                        by_model[model] = by_model.get(model, 0) + 1
                        r = rec.get("rating")
                        if r is not None:
                            rated += 1
                            if r > 0:
                                positive += 1
                            elif r < 0:
                                negative += 1
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            logger.error(f"[FineTuneCollector] get_stats error: {e}", exc_info=True)

        return {
            "total": total,
            "rated": rated,
            "positive": positive,
            "negative": negative,
            "by_character": by_character,
            "by_model": by_model,
        }

    # ── Load / filter samples ─────────────────────────────────────────────────

    def load_samples(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """
        Загружает записи с фильтрацией.

        filters keys:
          date_from: datetime (UTC)
          date_to: datetime (UTC)
          characters: List[str] — character_id whitelist (empty = all)
          models: List[str] — model whitelist (empty = all)
          min_rating: None = all, 0 = rated+unrated, 1 = only positive
        """
        filters = filters or {}
        date_from: Optional[datetime] = filters.get("date_from")
        date_to: Optional[datetime] = filters.get("date_to")
        characters: List[str] = filters.get("characters") or []
        models: List[str] = filters.get("models") or []
        min_rating: Optional[int] = filters.get("min_rating")

        results: List[Dict] = []
        try:
            for file_path in sorted(self.data_dir.glob("samples_*.jsonl")):
                for line in file_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Date filter
                    if date_from or date_to:
                        ts_str = rec.get("timestamp", "")
                        try:
                            ts = datetime.fromisoformat(ts_str)
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            if date_from and ts < date_from:
                                continue
                            if date_to and ts > date_to:
                                continue
                        except (ValueError, TypeError):
                            pass

                    # Character filter
                    if characters and rec.get("character_id") not in characters:
                        continue

                    # Model filter
                    if models and rec.get("model") not in models:
                        continue

                    # Rating filter
                    if min_rating is not None:
                        r = rec.get("rating")
                        if min_rating == 1 and r != 1:
                            continue
                        if min_rating == 0 and (r is not None and r < 0):
                            continue

                    results.append(rec)
        except Exception as e:
            logger.error(f"[FineTuneCollector] load_samples error: {e}", exc_info=True)

        return results

    # ── Export formats ────────────────────────────────────────────────────────

    def export_sharegpt(self, samples: List[Dict], output_path: str) -> int:
        """
        Экспортирует в формат ShareGPT (Unsloth).
        Каждый sample → одна строка JSONL с полем "conversations".
        Возвращает кол-во экспортированных записей.
        """
        count = 0
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                for sample in samples:
                    messages: List[Dict] = sample.get("messages") or []
                    response: str = sample.get("response") or ""

                    conversations = []
                    for msg in messages:
                        role = msg.get("role", "")
                        content = msg.get("content", "")
                        # content может быть списком (multipart)
                        if isinstance(content, list):
                            parts = []
                            for part in content:
                                if isinstance(part, dict):
                                    parts.append(
                                        part.get("text") or part.get("content", "")
                                    )
                            content = " ".join(p for p in parts if p)

                        if role == "system":
                            from_val = "system"
                        elif role == "user":
                            from_val = "human"
                        elif role == "assistant":
                            from_val = "gpt"
                        else:
                            continue

                        conversations.append({"from": from_val, "value": content})

                    # Финальный ответ как gpt-ход
                    if response:
                        conversations.append({"from": "gpt", "value": response})

                    if conversations:
                        record = {"conversations": conversations}
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        count += 1
        except Exception as e:
            logger.error(f"[FineTuneCollector] export_sharegpt error: {e}", exc_info=True)
        return count

    def clear_all(self) -> int:
        """Удаляет все JSONL-файлы из FineTuneData/. Возвращает кол-во удалённых файлов."""
        count = 0
        try:
            with self._lock:
                for file_path in list(self.data_dir.glob("samples_*.jsonl")):
                    file_path.unlink()
                    count += 1
                self._pending_sample_id = None
        except Exception as e:
            logger.error(f"[FineTuneCollector] clear_all error: {e}", exc_info=True)
        return count

    def export_raw_jsonl(self, samples: List[Dict], output_path: str) -> int:
        """Экспортирует сырые записи как JSONL."""
        count = 0
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                for sample in samples:
                    f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    count += 1
        except Exception as e:
            logger.error(f"[FineTuneCollector] export_raw_jsonl error: {e}", exc_info=True)
        return count
