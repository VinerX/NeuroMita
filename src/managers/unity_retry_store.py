from __future__ import annotations

import base64
import binascii
import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from main_logger import logger


class UnityRetryStore:
    """Bounded, per-character outbox for Unity-originated player turns."""

    VERSION = 1
    MAX_RECORDS = 100
    MAX_BYTES = 64 * 1024 * 1024
    MAX_AGE_SECONDS = 30 * 24 * 60 * 60
    RETRYABLE_STATUSES = {"needs_generation", "generated_pending_delivery"}
    _lock = threading.RLock()
    _delivered_in_process: set[tuple[str, str]] = set()
    _unreadable_paths: set[str] = set()
    _session_id = uuid.uuid4().hex

    @classmethod
    def _root(cls) -> Path:
        return Path(os.environ.get("NEUROMITA_HISTORIES_DIR") or Path.cwd() / "Histories")

    @classmethod
    def _path(cls, character_id: str) -> Path:
        safe_character = "".join(
            ch if ch.isalnum() or ch in "-_" else "_"
            for ch in str(character_id or "").strip()
        ).strip("-_") or "unknown"
        return cls._root() / safe_character / "unity_retry_outbox.json"

    @classmethod
    def _read(cls, character_id: str) -> list[dict[str, Any]]:
        path = cls._path(character_id)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != cls.VERSION:
                raise ValueError("Unsupported Unity retry outbox format")
            if not isinstance(payload.get("records"), list):
                raise ValueError("Invalid Unity retry outbox records")
            return [item for item in payload["records"] if isinstance(item, dict)]
        except Exception as exc:
            logger.warning("Unable to load Unity retry outbox %s: %s", path, exc)
            quarantine = path.with_name(
                f"{path.name}.corrupt-{int(time.time())}-{uuid.uuid4().hex[:8]}"
            )
            try:
                os.replace(path, quarantine)
                logger.error("Quarantined corrupt Unity retry outbox at %s", quarantine)
            except OSError:
                cls._unreadable_paths.add(str(path))
                logger.exception("Could not quarantine Unity retry outbox %s", path)
            return []

    @classmethod
    def _write(cls, character_id: str, records: list[dict[str, Any]]) -> bool:
        path = cls._path(character_id)
        if str(path) in cls._unreadable_paths:
            logger.error("Refusing to overwrite unreadable Unity retry outbox %s", path)
            return False
        temp_path = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(
                {"version": cls.VERSION, "records": records},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(content.encode("utf-8")) > cls.MAX_BYTES:
                return False
            fd, temp_path = tempfile.mkstemp(prefix=".unity-retry-", suffix=".tmp", dir=path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_path, path)
            return True
        except Exception:
            logger.exception("Unable to persist Unity retry outbox %s", path)
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            return False

    @classmethod
    def _prune(cls, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cutoff = time.time() - cls.MAX_AGE_SECONDS
        retained = []
        for item in records:
            try:
                created_at = float(item.get("created_at", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                item["status"] = "unretryable"
                item["error"] = "Повреждена дата исходного Unity-запроса."
                retained.append(item)
                continue
            if created_at >= cutoff:
                retained.append(item)
        return retained

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, bytes):
            return {"__unity_retry_bytes__": base64.b64encode(value).decode("ascii")}
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @classmethod
    def _restore_bytes(cls, value: Any) -> Any:
        if isinstance(value, dict):
            if set(value) == {"__unity_retry_bytes__"}:
                return base64.b64decode(value["__unity_retry_bytes__"], validate=True)
            return {key: cls._restore_bytes(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._restore_bytes(item) for item in value]
        return value

    @classmethod
    def _read_records_locked(cls, character_id: str) -> tuple[list[dict[str, Any]], bool]:
        source = cls._read(character_id)
        source_state = [
            (item.get("status"), item.get("error"), item.get("created_at"))
            for item in source
        ]
        records = cls._prune(source)
        changed = len(source) != len(records) or source_state != [
            (item.get("status"), item.get("error"), item.get("created_at"))
            for item in records
        ]
        for item in records:
            try:
                cls._restore_bytes(item)
            except (ValueError, TypeError, binascii.Error):
                item["status"] = "unretryable"
                item["error"] = "В данных Unity-запроса повреждено изображение; повтор отключён."
                item.pop("request", None)
                item.pop("task_data", None)
                changed = True
            if str(item.get("status") or "") in {
                "generated_pending_voiceover",
                "generated_pending_delivery",
            }:
                result = item.get("result")
                response = result.get("response") if isinstance(result, dict) else None
                if not isinstance(response, str) or not response.strip():
                    item["status"] = "unretryable"
                    item["error"] = "Сохранённый Unity-ответ повреждён или не содержит текста; повтор отключён."
                    changed = True
        return records, changed

    @classmethod
    def add(cls, character_id: str, record: dict[str, Any]) -> bool:
        with cls._lock:
            records, _ = cls._read_records_locked(character_id)
            message_id = str(record.get("message_id") or "")
            if message_id and any(str(item.get("message_id") or "") == message_id for item in records):
                return True
            if len(records) >= cls.MAX_RECORDS:
                logger.warning("Unity retry outbox is full for character %s", character_id)
                return False
            stored = cls._json_safe(dict(record))
            stored.setdefault("created_at", time.time())
            stored.setdefault("status", "generating")
            stored.setdefault("active_task_uid", "")
            stored["session_id"] = cls._session_id
            saved = cls._write(character_id, [*records, stored])
            if not saved:
                logger.warning("Unity retry outbox size limit reached for character %s", character_id)
            return saved

    @classmethod
    def list_for_character(cls, character_id: str) -> list[dict[str, Any]]:
        with cls._lock:
            records, changed = cls._read_records_locked(character_id)
            if changed and not cls._write(character_id, records):
                logger.error("Unable to persist sanitized Unity retry outbox for %s", character_id)
            restored = []
            for item in records:
                if (str(character_id or ""), str(item.get("message_id") or "")) in cls._delivered_in_process:
                    continue
                try:
                    restored.append(cls._restore_bytes(item))
                except (ValueError, TypeError, binascii.Error):
                    restored.append(dict(item))
            return restored

    @classmethod
    def recover_interrupted_attempts(cls) -> int:
        """Called exactly once on application startup, never during a normal read."""
        recovered = 0
        with cls._lock:
            for path in cls._root().glob("*/unity_retry_outbox.json"):
                character_id = path.parent.name
                records, changed = cls._read_records_locked(character_id)
                for item in records:
                    if str(item.get("session_id") or "") == cls._session_id:
                        continue
                    status = str(item.get("status") or "")
                    if status == "generating":
                        item["status"] = "needs_generation"
                        item["active_task_uid"] = ""
                        item["error"] = "Предыдущая генерация была прервана. Можно отправить запрос снова."
                        changed = True
                    elif status == "pending":
                        item["status"] = "needs_generation"
                        item["active_task_uid"] = ""
                        item["error"] = "Предыдущая попытка была прервана. Можно отправить запрос снова."
                        changed = True
                    elif status in {"delivery_retrying", "generated_pending_voiceover"}:
                        item["status"] = "generated_pending_delivery"
                        item["active_task_uid"] = ""
                        item["error"] = "Ответ уже сгенерирован, но доставка не завершилась. Повтор отправит тот же ответ."
                        changed = True
                    elif status == "generated_pending_delivery" and not str(item.get("error") or "").strip():
                        item["error"] = "Ответ уже сгенерирован, но доставка не была подтверждена. Повтор отправит тот же ответ."
                        changed = True
                    item["session_id"] = cls._session_id
                    changed = True
                if changed:
                    if cls._write(character_id, records):
                        recovered += 1
                    else:
                        logger.error("Unable to recover Unity retry outbox for %s", character_id)
        return recovered

    @classmethod
    def get(cls, character_id: str, message_id: str) -> dict[str, Any] | None:
        target = str(message_id or "")
        return next(
            (item for item in cls.list_for_character(character_id)
             if str(item.get("message_id") or "") == target),
            None,
        )

    @classmethod
    def is_superseded_attempt(cls, character_id: str, message_id: str, task_uid: str) -> bool:
        key = (str(character_id or ""), str(message_id or ""))
        with cls._lock:
            if key in cls._delivered_in_process:
                return True
            record = cls.get(character_id, message_id)
            return bool(
                record is not None
                and str(record.get("active_task_uid") or "")
                and str(record.get("active_task_uid") or "") != str(task_uid or "")
            )

    @classmethod
    def update(cls, character_id: str, message_id: str, **changes: Any) -> bool:
        with cls._lock:
            records, _ = cls._read_records_locked(character_id)
            for item in records:
                if str(item.get("message_id") or "") == str(message_id or ""):
                    item.update(cls._json_safe(changes))
                    if not cls._write(character_id, records):
                        logger.error("Unable to update Unity retry outbox record %s", message_id)
                        return False
                    return True
            return False

    @classmethod
    def update_request_context(
        cls,
        character_id: str,
        message_id: str,
        *,
        player_message_source: str,
        previous_player_message_source: str,
    ) -> bool:
        with cls._lock:
            records, _ = cls._read_records_locked(character_id)
            for item in records:
                if str(item.get("message_id") or "") != str(message_id or ""):
                    continue
                item["previous_player_message_source"] = previous_player_message_source
                request = item.get("request")
                if isinstance(request, dict):
                    request["player_message_source"] = player_message_source
                    request["previous_player_message_source"] = previous_player_message_source
                task_data = item.get("task_data")
                if isinstance(task_data, dict):
                    task_data["player_message_source"] = player_message_source
                    task_data["previous_player_message_source"] = previous_player_message_source
                if not cls._write(character_id, records):
                    logger.error("Unable to save Unity retry source context %s", message_id)
                    return False
                return True
            return False

    @classmethod
    def transition(
        cls,
        character_id: str,
        message_id: str,
        *,
        expected_statuses: set[str],
        status: str,
        error: str = "",
        task_uid: str | None = None,
        expected_task_uid: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> bool:
        with cls._lock:
            records, _ = cls._read_records_locked(character_id)
            for item in records:
                if str(item.get("message_id") or "") != str(message_id or ""):
                    continue
                if str(item.get("status") or "") not in expected_statuses:
                    return False
                if (
                    expected_task_uid is not None
                    and str(item.get("active_task_uid") or "") != str(expected_task_uid or "")
                ):
                    return False
                item["status"] = str(status)
                item["error"] = str(error or "")
                if task_uid is not None:
                    item["active_task_uid"] = str(task_uid)
                if result is not None:
                    item["result"] = cls._json_safe(result)
                if not cls._write(character_id, records):
                    logger.error("Unable to transition Unity retry outbox record %s", message_id)
                    return False
                return True
            return False

    @classmethod
    def claim(cls, character_id: str, message_id: str) -> dict[str, Any] | None:
        """Atomically claim only an explicitly retryable record."""
        with cls._lock:
            key = (str(character_id or ""), str(message_id or ""))
            if key in cls._delivered_in_process:
                return None
            records, _ = cls._read_records_locked(character_id)
            for item in records:
                if str(item.get("message_id") or "") != str(message_id or ""):
                    continue
                prior_status = str(item.get("status") or "")
                if prior_status not in cls.RETRYABLE_STATUSES:
                    return None
                item["claimed_from_status"] = prior_status
                item["status"] = (
                    "generating" if prior_status == "needs_generation" else "delivery_retrying"
                )
                item["error"] = ""
                item["active_task_uid"] = ""
                if not cls._write(character_id, records):
                    logger.error("Unable to claim Unity retry outbox record %s", message_id)
                    return None
                try:
                    return cls._restore_bytes(item)
                except (ValueError, TypeError, binascii.Error):
                    return None
            return None

    @classmethod
    def set_active_task(cls, character_id: str, message_id: str, task_uid: str) -> bool:
        return cls.update(character_id, message_id, active_task_uid=str(task_uid or ""))

    @classmethod
    def finish_failed_attempt(
        cls,
        character_id: str,
        message_id: str,
        task_uid: str,
        error: str,
    ) -> bool:
        with cls._lock:
            records, _ = cls._read_records_locked(character_id)
            for item in records:
                if (
                    str(item.get("message_id") or "") != str(message_id or "")
                    or str(item.get("active_task_uid") or "") != str(task_uid or "")
                ):
                    continue
                from_status = str(item.get("claimed_from_status") or "needs_generation")
                generated_response = (
                    isinstance(item.get("result"), dict)
                    and isinstance(item["result"].get("response"), str)
                    and bool(item["result"].get("response").strip())
                )
                item["status"] = (
                    "generated_pending_delivery"
                    if from_status == "generated_pending_delivery" or generated_response
                    else "needs_generation"
                )
                item["error"] = str(error or "Не удалось получить ответ.")
                item["active_task_uid"] = ""
                item.pop("claimed_from_status", None)
                if not cls._write(character_id, records):
                    logger.error("Unable to persist failed Unity retry %s", message_id)
                    return False
                return True
            return False

    @classmethod
    def mark_delivery_failed(
        cls,
        character_id: str,
        message_id: str,
        task_uid: str,
        error: str,
    ) -> bool:
        with cls._lock:
            records, _ = cls._read_records_locked(character_id)
            for item in records:
                if (
                    str(item.get("message_id") or "") != str(message_id or "")
                    or str(item.get("active_task_uid") or "") != str(task_uid or "")
                    or not isinstance(item.get("result"), dict)
                ):
                    continue
                item["status"] = "generated_pending_delivery"
                item["error"] = str(error or "Не удалось доставить ответ в игру.")
                if not cls._write(character_id, records):
                    logger.error("Unable to persist Unity result delivery failure %s", message_id)
                    return False
                return True
            return False

    @classmethod
    def mark_voiceover_failed(
        cls,
        character_id: str,
        message_id: str,
        task_uid: str,
        error: str,
    ) -> bool:
        return cls.transition(
            character_id,
            message_id,
            expected_statuses={"generated_pending_voiceover"},
            status="generated_pending_delivery",
            error=error or "Не удалось озвучить ответ; сохранённый текст можно отправить в игру.",
            task_uid=task_uid,
            expected_task_uid=task_uid,
        )

    @classmethod
    def complete_delivery(cls, character_id: str, message_id: str, task_uid: str) -> bool:
        with cls._lock:
            records, _ = cls._read_records_locked(character_id)
            remaining = [
                item for item in records
                if not (
                    str(item.get("message_id") or "") == str(message_id or "")
                    and str(item.get("active_task_uid") or "") == str(task_uid or "")
                )
            ]
            if len(remaining) == len(records):
                logger.error("Unity retry delivery completion did not match active task %s", task_uid)
                return False
            if not cls._write(character_id, remaining):
                cls._delivered_in_process.add((str(character_id or ""), str(message_id or "")))
                logger.error("Unable to persist Unity retry delivery completion %s", message_id)
                return False
            cls._delivered_in_process.add((str(character_id or ""), str(message_id or "")))
            return True

    @classmethod
    def remove(cls, character_id: str, message_id: str) -> bool:
        with cls._lock:
            records, _ = cls._read_records_locked(character_id)
            remaining = [item for item in records if str(item.get("message_id") or "") != str(message_id or "")]
            if len(remaining) == len(records):
                return False
            if not cls._write(character_id, remaining):
                logger.error("Unable to remove Unity retry outbox record %s", message_id)
                return False
            return True
