import json
from concurrent.futures import ThreadPoolExecutor
import logging
import os
import datetime
import base64
import re
import uuid
import hashlib
import time
from threading import Lock
from typing import Any, Optional, ClassVar

from main_logger import logger
from managers.database_manager import DatabaseManager
from managers.character_scoped_service import CharacterScopedService


# TODO: Decompose — this class is 1100+ lines. Consider splitting into:
#   history_reader.py (load_history, get_messages, pagination)
#   history_writer.py (add_message, save_history, _insert_history_row)
#   variable_store.py (update_variable, update_variables_batch, load/save vars)
class HistoryManager(CharacterScopedService):
    """
    HistoryManager (SQL):
    - хранит историю в SQLite (таблица history)
    - аккуратно работает со старыми БД: сам добавляет новые колонки и/или
      делает динамические INSERT/SELECT по фактической схеме.
    """

    # Process-wide executor для фоновой векторизации (не блокирует UI).
    # max_workers=1: сохраняем порядок, не устраиваем параллельный инференс/конкуренцию по БД.
    _EMBED_EXECUTOR: ClassVar[Optional[ThreadPoolExecutor]] = None
    _EMBED_EXECUTOR_LOCK: ClassVar[Lock] = Lock()

    # Class-level write locks per character_id to prevent race conditions
    # when multiple HistoryManager instances exist for the same character.
    _CHAR_WRITE_LOCKS: ClassVar[dict[str, Lock]] = {}
    _CHAR_LOCKS_LOCK: ClassVar[Lock] = Lock()

    @classmethod
    def _get_char_write_lock(cls, storage_key: str) -> Lock:
        """Return a shared Lock for the given storage_key (character)."""
        lk = cls._CHAR_WRITE_LOCKS.get(storage_key)
        if lk is not None:
            return lk
        with cls._CHAR_LOCKS_LOCK:
            lk = cls._CHAR_WRITE_LOCKS.get(storage_key)
            if lk is None:
                lk = Lock()
                cls._CHAR_WRITE_LOCKS[storage_key] = lk
            return lk

    # Single source of truth is DatabaseManager.HISTORY_EXTRA_COLUMNS.
    # This property provides backward-compatible access.
    @property
    def _HISTORY_DESIRED_COLUMNS(self) -> dict[str, str]:
        return DatabaseManager.HISTORY_EXTRA_COLUMNS

    # Базовые колонки, которые точно есть в вашей таблице history (по вашему DatabaseManager)
    _HISTORY_BASE_COLUMNS: tuple[str, ...] = (
        "character_id",
        "role",
        "content",
        "timestamp",
        "is_active",
        "meta_data",
    )

    def __init__(self, character_name: str = "", history_file_name: str = "", character_id: str | None = None):
        super().__init__(
            default_character_id=str(character_id or character_name or ""),
            default_character_name=str(character_name or character_id or ""),
        )
        self.db = DatabaseManager()

        # Схема общая для всех персонажей и проверяется один раз на сервис.
        self._history_cols: set[str] = set()

        # Character-local state remains data inside the single service instance.
        self._img_cache_locks: dict[str, Lock] = {}
        self._img_path_caches: dict[str, dict[str, str]] = {}
        self._rags: dict[str, object | None] = {}
        self._rag_initialized: set[str] = set()

        self._ensure_history_schema()

    @property
    def _write_lock(self) -> Lock:
        return self._get_char_write_lock(self.storage_key)

    @property
    def _img_cache_lock(self) -> Lock:
        key = self.storage_key
        lock = self._img_cache_locks.get(key)
        if lock is None:
            lock = Lock()
            self._img_cache_locks[key] = lock
        return lock

    @property
    def _img_path_cache(self) -> dict[str, str]:
        return self._img_path_caches.setdefault(self.storage_key, {})

    @property
    def rag(self):
        key = self.storage_key
        if key in self._rag_initialized:
            return self._rags.get(key)
        self._rag_initialized.add(key)
        try:
            from managers.rag.rag_manager import RAGManager

            self._rags[key] = RAGManager.for_character(key)
        except Exception as exc:
            logger.warning(
                f"RAGManager init failed for {key} (RAG disabled for this session): {exc}",
                exc_info=True,
            )
            self._rags[key] = None
        return self._rags.get(key)

    @rag.setter
    def rag(self, value) -> None:
        key = self.storage_key
        self._rag_initialized.add(key)
        self._rags[key] = value

    # ---------------------------------------------------------------------
    # Embedding async helpers
    # ---------------------------------------------------------------------
    @classmethod
    def shutdown_executor(cls) -> None:
        with cls._EMBED_EXECUTOR_LOCK:
            executor = cls._EMBED_EXECUTOR
            cls._EMBED_EXECUTOR = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    @classmethod
    def _get_embed_executor(cls) -> ThreadPoolExecutor:
        ex = cls._EMBED_EXECUTOR
        if ex is not None:
            return ex
        with cls._EMBED_EXECUTOR_LOCK:
            ex = cls._EMBED_EXECUTOR
            if ex is None:
                cls._EMBED_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-embed")
            return cls._EMBED_EXECUTOR

    # ---------------------------------------------------------------------
    # Schema helpers
    # ---------------------------------------------------------------------
    def _refresh_history_columns(self) -> set[str]:
        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(history)")
            cols = set(row[1] for row in cur.fetchall() if row and len(row) > 1)
            self._history_cols = cols
            return cols
        except Exception as e:
            logger.warning(f"Failed to read history schema: {e}", exc_info=True)
            self._history_cols = set()
            return set()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _ensure_history_schema(self) -> None:
        """
        Пытается добавить недостающие колонки в history.
        Даже если ALTER не получится, код ниже всё равно не упадёт,
        потому что INSERT/SELECT строятся динамически по self._history_cols.
        """
        cols = self._refresh_history_columns()
        if not cols:
            return

        to_add: list[tuple[str, str]] = []
        for col, col_type in self._HISTORY_DESIRED_COLUMNS.items():
            if col not in cols:
                to_add.append((col, col_type))

        if not to_add:
            return

        conn = self.db.get_connection()
        try:
            cur = conn.cursor()
            for col, col_type in to_add:
                try:
                    cur.execute(f"ALTER TABLE history ADD COLUMN {self.db._q_ident(col)} {col_type}")
                    logger.info(f"DB upgrade: added history.{col} {col_type}")
                except Exception as e:
                    # Не валим приложение: просто логируем
                    logger.warning(f"DB upgrade: failed to add history.{col}: {e}")
            conn.commit()
        except Exception as e:
            logger.warning(f"DB upgrade: failed to upgrade history table: {e}", exc_info=True)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # обновим кеш после попытки миграции
        self._refresh_history_columns()

    def dedupe_history(self) -> int:
        """
        Remove duplicate history rows for this character.
        Delegates to DatabaseManager.dedupe_history() for single implementation.
        """
        try:
            self._ensure_history_schema()
            if not self._history_cols:
                return 0
            if "content" not in self._history_cols or "timestamp" not in self._history_cols:
                return 0
            return self.db.dedupe_history(character_id=self.storage_key)
        except Exception as e:
            logger.warning(f"[HistoryManager] Dedup failed (ignored): {e}", exc_info=True)
            return 0

    # Backward-compat: старое приватное имя могло вызываться из других мест
    def _dedupe_existing_history_duplicates(self) -> int:
        return self.dedupe_history()

    # ---------------------------------------------------------------------
    # Helpers: images
    # ---------------------------------------------------------------------
    def _save_base64_image_to_disk(self, base64_string: str) -> str:
        """
        Сохраняет base64 изображение на диск и возвращает относительный путь.
        """
        try:
            match = re.match(r"data:image/(\w+);base64,(.+)", base64_string)
            if not match:
                return base64_string

            ext = (match.group(1) or "").lower()
            img_data_str = match.group(2) or ""
            if ext == "jpeg":
                ext = "jpg"

            histories_dir = os.environ.get("NEUROMITA_HISTORIES_DIR", os.path.join(os.getcwd(), "Histories"))
            save_dir = os.path.join(histories_dir, self.character_name, "Images")
            os.makedirs(save_dir, exist_ok=True)

            # ВАЖНО: убираем пробелы/переводы строк (иногда встречаются)
            clean_b64 = re.sub(r"\s+", "", img_data_str)

            # Детерминированное имя файла:
            # вместо sha по декодированным байтам (дорого) берём sha по ASCII-строке base64.
            # Это позволяет НЕ декодировать заново, если файл уже есть.
            sha = hashlib.sha256(clean_b64.encode("ascii", errors="ignore")).hexdigest()
            filename = f"{sha}.{ext or 'bin'}"
            file_path = os.path.join(save_dir, filename)

            # Быстрый путь: кеш / существующий файл (без base64 decode)
            with self._img_cache_lock:
                cached = self._img_path_cache.get(filename)
                if cached:
                    return cached

            if os.path.exists(file_path):
                # reuse лучше на DEBUG, иначе логи сами начинают тормозить
                logger.debug(f"Image reused (hash match): {file_path}")
                with self._img_cache_lock:
                    self._img_path_cache[filename] = file_path
                return file_path

            # Декодируем ТОЛЬКО когда файла ещё нет
            t0 = time.perf_counter()
            img_bytes = base64.b64decode(clean_b64)
            dt = time.perf_counter() - t0
            if dt > 0.25:
                logger.warning(
                    f"Slow base64 decode: {dt:.3f}s, file={filename}, b64_chars={len(clean_b64)}"
                )

            with open(file_path, "wb") as f:
                f.write(img_bytes)
            logger.info(f"Image saved: {file_path}")

            with self._img_cache_lock:
                self._img_path_cache[filename] = file_path
            return file_path

        except Exception as e:
            logger.error(f"Failed to save base64 image to disk: {e}", exc_info=True)
            return base64_string

    def _image_file_to_base64(self, file_path: str) -> str:
        """
        Читает локальный файл и превращает обратно в data:image/...;base64
        """
        try:
            if not os.path.exists(file_path):
                logger.warning(f"Image file not found: {file_path}")
                return file_path

            ext = os.path.splitext(file_path)[1].replace(".", "").lower()
            if ext == "jpg":
                ext = "jpeg"

            with open(file_path, "rb") as f:
                encoded_string = base64.b64encode(f.read()).decode("utf-8")

            return f"data:image/{ext};base64,{encoded_string}"
        except Exception as e:
            logger.error(f"Error converting file to base64: {e}", exc_info=True)
            return file_path

    # ---------------------------------------------------------------------
    # Helpers: structured fields (participants/tags)
    # ---------------------------------------------------------------------
    def _coerce_text(self, v) -> str | None:
        s = str(v or "").strip()
        return s if s else None

    def _json_dumps_list(self, v) -> str | None:
        """
        participants/tags: храним как JSON list в TEXT.
        Принимаем list | str | None.
        """
        if v is None:
            return None

        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    arr = [str(x).strip() for x in parsed if str(x).strip()]
                    return json.dumps(arr, ensure_ascii=False) if arr else None
            except Exception:
                pass
            arr = [p.strip() for p in s.split(",") if p.strip()]
            return json.dumps(arr, ensure_ascii=False) if arr else None

        if isinstance(v, list):
            arr = [str(x).strip() for x in v if str(x).strip()]
            return json.dumps(arr, ensure_ascii=False) if arr else None

        s = self._coerce_text(v)
        return json.dumps([s], ensure_ascii=False) if s else None

    def _json_loads_list(self, s) -> list[str]:
        if not s:
            return []
        if isinstance(s, list):
            return [str(x).strip() for x in s if str(x).strip()]
        if not isinstance(s, str):
            return []
        raw = s.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
        return [p.strip() for p in raw.split(",") if p.strip()]

    def _coerce_int_or_none(self, value) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _coerce_float_or_none(self, value) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _extract_history_db_fields(self, msg: dict) -> dict:
        if not isinstance(msg, dict):
            return {k: None for k in self._HISTORY_DESIRED_COLUMNS.keys()}

        sd = msg.get("structured_data")
        structured_data_str = None
        if sd is not None:
            if isinstance(sd, str):
                structured_data_str = sd
            else:
                try:
                    structured_data_str = json.dumps(sd, ensure_ascii=False)
                except Exception:
                    structured_data_str = None

        return {
            "target": self._coerce_text(msg.get("target")),
            "participants": self._json_dumps_list(msg.get("participants")),
            "tags": self._json_dumps_list(msg.get("tags")),
            "rag_id": self._coerce_text(msg.get("rag_id")),
            "message_id": self._coerce_text(msg.get("message_id")),
            "speaker": self._coerce_text(msg.get("speaker")),
            "sender": self._coerce_text(msg.get("sender")),
            "event_type": self._coerce_text(msg.get("event_type")),
            "req_id": self._coerce_text(msg.get("req_id")),
            "task_uid": self._coerce_text(msg.get("task_uid")),
            "turn_id": self._coerce_text(msg.get("turn_id")),
            "structured_data": structured_data_str,
            "thinking": self._coerce_text(msg.get("thinking")),
            "llm_prompt_tokens": self._coerce_int_or_none(msg.get("llm_prompt_tokens")),
            "llm_completion_tokens": self._coerce_int_or_none(msg.get("llm_completion_tokens")),
            "llm_total_tokens": self._coerce_int_or_none(msg.get("llm_total_tokens")),
            "llm_reasoning_tokens": self._coerce_int_or_none(msg.get("llm_reasoning_tokens")),
            "llm_cached_prompt_tokens": self._coerce_int_or_none(msg.get("llm_cached_prompt_tokens")),
            "llm_cache_write_tokens": self._coerce_int_or_none(msg.get("llm_cache_write_tokens")),
            "llm_cost": self._coerce_float_or_none(msg.get("llm_cost")),
            "llm_cost_currency": self._coerce_text(msg.get("llm_cost_currency")),
            "llm_cost_source": self._coerce_text(msg.get("llm_cost_source")),
            "llm_model": self._coerce_text(msg.get("llm_model")),
            "llm_provider": self._coerce_text(msg.get("llm_provider")),
        }

    def _normalize_loaded_message(self, msg: dict) -> dict:
        """
        Приводим типы к ожидаемым:
        - participants/tags -> list[str]
        """
        if not isinstance(msg, dict):
            return msg

        if "participants" in msg:
            msg["participants"] = self._json_loads_list(msg.get("participants"))
        if "tags" in msg:
            msg["tags"] = self._json_loads_list(msg.get("tags"))
        if "structured_data" in msg and isinstance(msg["structured_data"], str):
            try:
                msg["structured_data"] = json.loads(msg["structured_data"])
            except Exception:
                pass
        for key in (
            "llm_prompt_tokens",
            "llm_completion_tokens",
            "llm_total_tokens",
            "llm_reasoning_tokens",
            "llm_cached_prompt_tokens",
            "llm_cache_write_tokens",
        ):
            if key in msg:
                coerced = self._coerce_int_or_none(msg.get(key))
                if coerced is not None:
                    msg[key] = coerced
        if "llm_cost" in msg:
            coerced_cost = self._coerce_float_or_none(msg.get("llm_cost"))
            if coerced_cost is not None:
                msg["llm_cost"] = coerced_cost
        return msg

    def _build_extra_meta_for_db(self, msg: dict) -> dict:
        """
        Всё, что нельзя/не удалось положить в отдельные колонки, сохраняем в meta_data.
        Ключевой момент для старых БД: если колонки нет — кладём туда же target/participants/etc.
        """
        if not isinstance(msg, dict):
            return {}

        reserved = {
            "role", "content", "time", "timestamp",
            "_history_row_id",
            *self._HISTORY_DESIRED_COLUMNS.keys(),
        }

        meta: dict = {}
        # старое поле image
        if "image" in msg:
            meta["image"] = msg["image"]

        # если колонок нет — дубль в meta_data, чтобы не терять
        for k in self._HISTORY_DESIRED_COLUMNS.keys():
            if k not in self._history_cols:
                v = msg.get(k)
                if v is not None and v != "" and k not in meta:
                    meta[k] = v

        for k, v in msg.items():
            if k in reserved:
                continue
            if k not in meta:
                meta[k] = v

        return meta

    def _extract_text_for_embedding(self, content: Any) -> str:
        """
        Делает текст для эмбеддинга из content:
        - str -> str
        - list[{"type":"text"}...] -> склеиваем только text части
        - остальное -> строковое представление (как fallback)
        """
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for it in content:
                if not isinstance(it, dict):
                    continue
                if it.get("type") == "text":
                    txt = it.get("text")
                    if txt is None:
                        txt = it.get("content", "")
                    s = str(txt or "").strip()
                    if s:
                        parts.append(s)
            return "\n".join(parts).strip()
        try:
            return json.dumps(content, ensure_ascii=False).strip()
        except Exception:
            return str(content).strip()

    # ---------------------------------------------------------------------
    # Serialization: message <-> db
    # ---------------------------------------------------------------------
    def _prepare_message_for_db(self, role: str, raw_content, raw_meta=None) -> tuple[str, str | None]:
        db_content = ""
        meta_dict = {}

        if raw_meta:
            if isinstance(raw_meta, str):
                try:
                    meta_dict = json.loads(raw_meta)
                except Exception:
                    meta_dict = {}
            elif isinstance(raw_meta, dict):
                meta_dict = raw_meta.copy()

        if isinstance(raw_content, str):
            db_content = raw_content

        elif isinstance(raw_content, list):
            text_parts = []
            other_parts = []

            for item in raw_content:
                if not isinstance(item, dict):
                    continue

                item_type = item.get("type")
                if item_type == "text":
                    text_parts.append(item.get("text", ""))
                elif item_type == "image_url":
                    image_url_dict = item.get("image_url", {}) or {}
                    url_str = image_url_dict.get("url", "")

                    if isinstance(url_str, str) and url_str.startswith("data:image"):
                        saved_path = self._save_base64_image_to_disk(url_str)
                        new_item = item.copy()
                        new_item["image_url"] = image_url_dict.copy()
                        new_item["image_url"]["url"] = saved_path
                        other_parts.append(new_item)
                    else:
                        other_parts.append(item)
                else:
                    other_parts.append(item)

            db_content = "\n".join(text_parts)
            if other_parts:
                meta_dict["multimodal_parts"] = other_parts
            meta_dict["is_multimodal_list"] = True

        # === НАЧАЛО ИЗМЕНЕНИЙ ===
        elif isinstance(raw_content, dict):

            # Пытаемся достать текст, чтобы не писать JSON в content
            # Сначала ищем стандартные ключи

            extracted_text = raw_content.get("text") or raw_content.get("content") or raw_content.get("value")

            # Если это результат сжатия (summary)
            if not extracted_text:
                extracted_text = raw_content.get("summary")

            if extracted_text and isinstance(extracted_text, str):
                db_content = extracted_text.strip()
                # Сохраняем исходный json в мета-данные на всякий случай
                meta_dict["original_json"] = raw_content

            else:
                # Если текст не нашли, тогда уже дампим весь JSON
                db_content = json.dumps(raw_content, ensure_ascii=False)


        else:
            db_content = str(raw_content) if raw_content is not None else ""

        db_meta = json.dumps(meta_dict, ensure_ascii=False) if meta_dict else None
        return db_content, db_meta

    def _reconstruct_message_from_db(self, role, db_content, db_meta_raw):
        meta = {}
        if db_meta_raw:
            try:
                meta = json.loads(db_meta_raw)
            except Exception:
                meta = {}

        content = db_content
        ui_images: list[dict] = []   # populated inside the if-block when needed

        if meta.get("is_multimodal_list", False) or meta.get("multimodal_parts"):
            reconstructed_list = []

            if db_content:
                reconstructed_list.append({"type": "text", "text": str(db_content)})

            # Resolve stored description: prefer new dict format, fall back to legacy string.
            # Dict format: {"normal": "...", "detailed": "..."} — pick best available variant.
            _desc_dict = meta.get("image_descriptions")
            _desc_legacy = meta.get("image_description")
            stored_description: str | None = None
            if isinstance(_desc_dict, dict) and _desc_dict:
                stored_description = (
                    _desc_dict.get("manual")
                    or _desc_dict.get("detailed")
                    or _desc_dict.get("normal")
                    or _desc_dict.get("brief")
                    or next(iter(_desc_dict.values()), None)
                )
            elif isinstance(_desc_legacy, str) and _desc_legacy:
                stored_description = _desc_legacy

            if "multimodal_parts" in meta:
                parts = meta.get("multimodal_parts") or []
                for part in parts:
                    if not isinstance(part, dict):
                        continue

                    part_type = part.get("type")
                    if part_type == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        final_url = url
                        is_local = part.get("is_local_file", False)
                        if is_local or (url and not str(url).startswith("http") and not str(url).startswith("data:")):
                            final_url = self._image_file_to_base64(str(url))

                        clean_part = {
                            "type": "image_url",
                            "image_url": {"url": final_url}
                        }
                        if "detail" in (part.get("image_url") or {}):
                            clean_part["image_url"]["detail"] = part["image_url"]["detail"]
                        if part.get("display_role"):
                            clean_part["display_role"] = part.get("display_role")

                        reconstructed_list.append(clean_part)

                        if stored_description and final_url:
                            ui_images.append({
                                "url": final_url,
                                "description": stored_description,
                                "display_role": part.get("display_role"),
                            })

                    elif part_type == "text":
                        reconstructed_list.append({"type": "text", "text": part.get("text", "")})

            content = reconstructed_list

        msg = {"role": role, "content": content}

        # UI display hint: file paths + descriptions for history rendering.
        # Stored at message level so providers never see it (they only use "content").
        if ui_images:
            msg["_ui_images"] = ui_images

        # переносим meta поля обратно, но фильтруем служебное
        for k, v in meta.items():
            if k not in ["multimodal_parts", "is_multimodal_list", "image"]:
                msg[k] = v

        return msg

    # ---------------------------------------------------------------------
    # DB low-level: dynamic INSERT/SELECT for backward compatibility
    # ---------------------------------------------------------------------
    def _history_select_columns(self) -> list[str]:
        """
        Колонки, которые мы будем SELECT'ить, исходя из фактической схемы.
        """
        base = ["id", "role", "content", "meta_data", "timestamp"]
        for col in self._HISTORY_DESIRED_COLUMNS.keys():
            if col in self._history_cols:
                base.append(col)
        return base

    def _history_not_deleted_clause(self) -> str:
        # старые БД могут ещё не иметь is_deleted — тогда не добавляем условие
        if "is_deleted" in self._history_cols:
            return " AND is_deleted = 0 "
        return ""

    def _content_for_dedupe(self, raw_content) -> str:
        try:
            if raw_content is None:
                return ""
            if isinstance(raw_content, str):
                return raw_content
            if isinstance(raw_content, list):
                parts: list[str] = []
                for it in raw_content:
                    if not isinstance(it, dict):
                        continue
                    if it.get("type") == "text":
                        txt = it.get("text")
                        if txt is None:
                            txt = it.get("content", "")
                        parts.append(str(txt or ""))
                return "\n".join(parts)
            if isinstance(raw_content, dict):
                extracted_text = raw_content.get("text") or raw_content.get("content") or raw_content.get("value") or raw_content.get("summary")
                if isinstance(extracted_text, str) and extracted_text:
                    return extracted_text.strip()
                return json.dumps(raw_content, ensure_ascii=False)
            return str(raw_content)
        except Exception:
            return str(raw_content) if raw_content is not None else ""

    def _build_history_insert_payload(self, *, msg: dict, is_active: int) -> tuple[str, tuple[Any, ...], str]:
        raw_ts = self._coerce_text(msg.get("time")) or self._coerce_text(msg.get("timestamp"))
        ts = self._storage_timestamp(raw_ts)

        db_fields = self._extract_history_db_fields(msg)
        extra_meta = self._build_extra_meta_for_db(msg)
        db_content, db_meta = self._prepare_message_for_db(
            msg.get("role"),
            msg.get("content"),
            extra_meta
        )

        cols: list[str] = []
        vals: list[Any] = []
        cols.extend(["character_id", "role", "content", "is_active", "meta_data", "timestamp"])
        vals.extend([self.storage_key, msg.get("role"), db_content, int(is_active), db_meta, ts])
        if "is_deleted" in self._history_cols:
            cols.append("is_deleted")
            vals.append(0)

        for k in self._HISTORY_DESIRED_COLUMNS.keys():
            if k in self._history_cols:
                cols.append(k)
                vals.append(db_fields.get(k))

        placeholders = ", ".join(["?"] * len(cols))
        sql = f"INSERT INTO history ({', '.join(cols)}) VALUES ({placeholders})"
        return sql, tuple(vals), ts

    def _find_existing_history_row(
        self,
        cursor,
        *,
        message_id: str | None,
    ) -> tuple[int, int] | None:
        normalized_message_id = str(message_id or "").strip()
        if not normalized_message_id or "message_id" not in self._history_cols:
            return None

        not_deleted_clause = " AND is_deleted = 0 " if "is_deleted" in self._history_cols else ""
        cursor.execute(
            f"""
            SELECT id, is_active
            FROM history
            WHERE character_id = ?
              AND message_id = ?
              {not_deleted_clause}
            ORDER BY id DESC
            LIMIT 1
            """,
            (self.storage_key, normalized_message_id),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return None
        return int(row[0]), int(row[1] or 0)

    def _insert_history_row_tx(
        self,
        cursor,
        *,
        msg: dict,
        is_active: int,
        dedupe: bool = True,
    ) -> Optional[int]:
        sql, vals, _ts = self._build_history_insert_payload(msg=msg, is_active=is_active)

        if dedupe:
            try:
                existing = self._find_existing_history_row(
                    cursor,
                    message_id=self._coerce_text(msg.get("message_id")),
                )
                if existing is not None:
                    existing_id, existing_active = existing
                    desired_active = int(is_active)
                    if existing_active != desired_active:
                        cursor.execute(
                            "UPDATE history SET is_active = ? WHERE id = ?",
                            (desired_active, existing_id),
                        )
                    return existing_id
            except Exception:
                pass

        cursor.execute(sql, vals)
        row_id = cursor.lastrowid
        return int(row_id) if row_id else None

    def _insert_history_row_minimal_tx(
        self,
        cursor,
        *,
        msg: dict,
        is_active: int,
    ) -> Optional[int]:
        raw_ts = self._coerce_text(msg.get("time")) or self._coerce_text(msg.get("timestamp"))
        ts = self._storage_timestamp(raw_ts)
        extra_meta = self._build_extra_meta_for_db(msg)
        db_content, db_meta = self._prepare_message_for_db(
            msg.get("role"),
            msg.get("content"),
            extra_meta,
        )
        cursor.execute(
            """
            INSERT INTO history (character_id, role, content, is_active, meta_data, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (self.storage_key, msg.get("role"), db_content, int(is_active), db_meta, ts),
        )
        row_id = cursor.lastrowid
        return int(row_id) if row_id else None

    def _insert_history_row(self, *, msg: dict, is_active: int) -> Optional[int]:
        """
        Вставка строки history без падений на старых БД:
        - берём только существующие колонки
        - всё остальное дублируем в meta_data
        """
        if not self._history_cols:
            self._ensure_history_schema()

        with self._write_lock:
            conn = self.db.get_connection()
            try:
                cur = conn.cursor()
                row_id = self._insert_history_row_tx(cur, msg=msg, is_active=is_active, dedupe=True)
                conn.commit()
                return row_id
            except Exception as e:
                logger.warning(f"History INSERT failed, fallback to minimal insert: {e}", exc_info=True)
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    cur = conn.cursor()
                    row_id = self._insert_history_row_minimal_tx(cur, msg=msg, is_active=is_active)
                    conn.commit()
                    return row_id
                except Exception as e2:
                    logger.error(f"History minimal INSERT failed: {e2}", exc_info=True)
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    return None
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def _parse_timestamp(raw_ts: Any) -> datetime.datetime | None:
        if isinstance(raw_ts, datetime.datetime):
            dt = raw_ts
        else:
            raw = str(raw_ts or "").strip()
            if not raw:
                return None

            iso_candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
            try:
                dt = datetime.datetime.fromisoformat(iso_candidate)
            except ValueError:
                dt = None

            if dt is None:
                for fmt in (
                    "%d.%m.%Y %H:%M:%S",
                    "%d.%m.%Y %H:%M",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M",
                    "%Y/%m/%d %H:%M:%S",
                    "%Y/%m/%d %H:%M",
                ):
                    try:
                        dt = datetime.datetime.strptime(raw, fmt)
                        break
                    except ValueError:
                        continue

            if dt is None and re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", raw):
                time_fmt = "%H:%M:%S" if raw.count(":") == 2 else "%H:%M"
                parsed_time = datetime.datetime.strptime(raw, time_fmt).time()
                dt = datetime.datetime.combine(datetime.date.today(), parsed_time)

        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt

    def _storage_timestamp(self, raw_ts: Any = None) -> str:
        dt = self._parse_timestamp(raw_ts) or datetime.datetime.now()
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def _display_timestamp(self, raw_ts: Any = None) -> str:
        dt = self._parse_timestamp(raw_ts)
        if dt is None:
            return str(raw_ts or "")
        return dt.strftime("%d.%m.%Y %H:%M:%S")

    def data_mormalization(self, final_ts, raw_ts, target_fmt):
        """Backward-compatible timestamp normalizer used by legacy callers."""
        dt = self._parse_timestamp(raw_ts)
        if dt is not None:
            return dt.strftime(target_fmt)
        if final_ts:
            return str(final_ts)
        return datetime.datetime.now().strftime(target_fmt)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def load_history(self):
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            # 1) Переменные
            cursor.execute("SELECT key, value FROM variables WHERE character_id = ?", (self.storage_key,))
            variables = {}
            for row in cursor.fetchall():
                try:
                    variables[row[0]] = json.loads(row[1])
                except Exception:
                    variables[row[0]] = row[1]

            # 2) Сообщения
            # динамический SELECT по фактическим колонкам
            self._ensure_history_schema()
            select_cols = self._history_select_columns()

            sql = f"""
                SELECT {", ".join(select_cols)}
                FROM history
                WHERE character_id = ? AND is_active = 1 {self._history_not_deleted_clause()}
                ORDER BY id ASC
            """
            cursor.execute(sql, (self.storage_key,))
            rows = cursor.fetchall()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        messages: list[dict] = []
        for row in rows:
            rd = dict(zip(select_cols, row))

            msg = self._reconstruct_message_from_db(
                rd.get("role"),
                rd.get("content"),
                rd.get("meta_data"),
            )
            msg["_history_row_id"] = rd.get("id")
            msg["time"] = self._display_timestamp(rd.get("timestamp"))

            # если колонки есть — дополним из колонок, иначе они уже могут быть в meta_data
            for k in self._HISTORY_DESIRED_COLUMNS.keys():
                if k in rd and rd.get(k) is not None and rd.get(k) != "":
                    msg[k] = rd.get(k)

            msg = self._normalize_loaded_message(msg)
            messages.append(msg)

        return {
            "fixed_parts": [],
            "messages": messages,
            "temp_context": [],
            "variables": variables,
        }

    def save_history(self, data):
        messages = data.get("messages", []) or []
        variables = data.get("variables", {}) or {}

        pending_embeddings: list[tuple[int, str]] = []
        if not self._history_cols:
            self._ensure_history_schema()

        with self._write_lock:
            conn = self.db.get_connection()
            try:
                cursor = conn.cursor()

                for k, v in variables.items():
                    val_str = json.dumps(v, ensure_ascii=False)
                    cursor.execute(
                        """
                        INSERT INTO variables (character_id, key, value) VALUES(?, ?, ?)
                        ON CONFLICT(character_id, key) DO UPDATE SET value=excluded.value
                        """,
                        (self.storage_key, k, val_str),
                    )

                cursor.execute(
                    "DELETE FROM history WHERE character_id = ? AND is_active = 1",
                    (self.storage_key,),
                )

                for msg in messages:
                    if not isinstance(msg, dict):
                        continue
                    if not msg.get("role"):
                        logger.warning(
                            f"[HistoryManager] save_history: пропущено сообщение без поля 'role': {str(msg)[:120]}"
                        )
                        continue

                    row_id = self._insert_history_row_tx(cursor, msg=msg, is_active=1, dedupe=False)
                    if row_id:
                        content_text = self._extract_text_for_embedding(msg.get("content"))
                        if content_text:
                            pending_embeddings.append((int(row_id), content_text))

                conn.commit()
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error(f"DB Error saving history atomically: {e}", exc_info=True)
                return
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        if not pending_embeddings or not self.rag:
            return

        rag = self.rag
        items = list(pending_embeddings)

        def _bulk_embed_job():
            for row_id, text in items:
                try:
                    rag.update_history_embedding(int(row_id), str(text))
                except Exception as e:
                    logger.warning(f"RAG failed to update history embedding (ignored): {e}", exc_info=True)

        try:
            self._get_embed_executor().submit(_bulk_embed_job)
        except Exception as e:
            logger.warning(f"[HistoryManager] Failed to schedule embeddings job (ignored): {e}", exc_info=True)

    def save_history_separate(self) -> str:
        """Экспортирует текущую активную историю в JSON-файл (бекап/снапшот).
        Сохраняет в Histories/{storage_key}/Saved/chat_history_{timestamp}.json.
        Возвращает путь к файлу или '' при ошибке."""
        import shutil
        histories_dir = os.environ.get("NEUROMITA_HISTORIES_DIR", os.path.join(os.getcwd(), "Histories"))
        save_dir = os.path.join(histories_dir, self.storage_key, "Saved")
        os.makedirs(save_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%d.%m.%Y_%H.%M.%S")
        target_path = os.path.join(save_dir, f"chat_history_{timestamp}.json")

        try:
            history_data = self.load_history()
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)
            logger.info(f"[HistoryManager] Snapshot сохранён: {target_path}")
            return target_path
        except Exception as e:
            logger.error(f"[HistoryManager] Не удалось сохранить snapshot: {e}", exc_info=True)
            return ""

    def _schedule_message_embedding(self, row_id: int | None, message: dict) -> None:
        if not row_id or not self.rag:
            return

        content_text = self._extract_text_for_embedding(message.get("content"))
        if not content_text:
            return

        rag = self.rag
        rid = int(row_id)
        txt = str(content_text)

        def _embed_job():
            try:
                rag.update_history_embedding(rid, txt)
            except Exception as e:
                logger.warning(
                    f"RAG failed to update embedding for new message (ignored): {e}",
                    exc_info=True,
                )

        try:
            self._get_embed_executor().submit(_embed_job)
        except Exception as e:
            logger.warning(
                f"[HistoryManager] Failed to schedule embedding for message (ignored): {e}",
                exc_info=True,
            )

    def add_messages(self, messages: list[dict]) -> list[int]:
        valid_messages = [msg for msg in messages or [] if isinstance(msg, dict)]
        if not valid_messages:
            return []
        if not self._history_cols:
            self._ensure_history_schema()

        committed: list[tuple[int, dict]] = []
        with self._write_lock:
            conn = self.db.get_connection()
            try:
                cursor = conn.cursor()
                for msg in valid_messages:
                    row_id = self._insert_history_row_tx(
                        cursor,
                        msg=msg,
                        is_active=1,
                        dedupe=True,
                    )
                    if row_id:
                        committed.append((int(row_id), msg))
                conn.commit()
            except Exception as exc:
                committed.clear()
                logger.error(
                    f"History batch INSERT failed; the complete turn was rolled back: {exc}",
                    exc_info=True,
                )
                try:
                    conn.rollback()
                except Exception:
                    pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        for row_id, msg in committed:
            self._schedule_message_embedding(row_id, msg)
        return [row_id for row_id, _msg in committed]

    def add_message(self, message: dict):
        row_id = self._insert_history_row(msg=message, is_active=1)
        self._schedule_message_embedding(row_id, message)
        return row_id

    def update_variable(self, key, value):
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            val_str = json.dumps(value, ensure_ascii=False)
            cursor.execute(
                """
                INSERT INTO variables (character_id, key, value) VALUES(?, ?, ?)
                ON CONFLICT(character_id, key) DO UPDATE SET value=excluded.value
                """,
                (self.storage_key, key, val_str),
            )
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def update_variables_batch(self, variables: dict):
        """Batch-write multiple variables in a single transaction."""
        if not variables:
            return
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            for key, value in variables.items():
                val_str = json.dumps(value, ensure_ascii=False)
                cursor.execute(
                    """
                    INSERT INTO variables (character_id, key, value) VALUES(?, ?, ?)
                    ON CONFLICT(character_id, key) DO UPDATE SET value=excluded.value
                    """,
                    (self.storage_key, key, val_str),
                )
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def save_missed_history(self, missed_messages: list):
        for msg in missed_messages or []:
            if not isinstance(msg, dict):
                continue
            self._insert_history_row(msg=msg, is_active=0)

    def clear_history(self):
        with self.db.connection() as conn:
            cursor = conn.cursor()
            # Mark as inactive AND deleted so RAG stops finding reset messages.
            # RAG searches is_active=0 for archived history; is_deleted=1 excludes them.
            if "is_deleted" in self._history_cols:
                cursor.execute(
                    "UPDATE history SET is_active = 0, is_deleted = 1 WHERE character_id = ?",
                    (self.storage_key,),
                )
            else:
                cursor.execute(
                    "UPDATE history SET is_active = 0 WHERE character_id = ?",
                    (self.storage_key,),
                )
            conn.commit()

    def purge_deleted(self, *, backup: bool = True, backup_dir: str | None = None) -> dict:
        """Physically DELETE is_deleted=1 history rows + their embeddings. Optionally backup to JSON first."""
        if "is_deleted" not in self._history_cols:
            return {"backed_up": None, "purged_history": 0}
        backed_up = None
        if backup:
            backed_up = self.db.backup_deleted_to_json(
                character_id=self.storage_key,
                backup_dir=backup_dir,
                include_history=True,
                include_memories=False,
            )
            logger.info(f"[HistoryManager] Backup written to: {backed_up}")
        with self.db.connection() as conn:
            cur = conn.cursor()
            for emb_table in ("embeddings", "sentence_embeddings"):
                try:
                    cur.execute(
                        f"DELETE FROM {emb_table} WHERE source_table='history' AND character_id=?"
                        " AND source_id IN (SELECT id FROM history WHERE character_id=? AND is_deleted=1)",
                        (self.storage_key, self.storage_key),
                    )
                except Exception as e:
                    logger.warning(f"[HistoryManager] purge_deleted: {emb_table} cleanup failed: {e}")
            cur.execute(
                "DELETE FROM history WHERE character_id=? AND is_deleted=1",
                (self.storage_key,),
            )
            purged = cur.rowcount
            conn.commit()
        logger.info(f"[HistoryManager] Purged {purged} deleted history rows for '{self.storage_key}'")
        return {"backed_up": backed_up, "purged_history": purged}

    def _default_history(self):
        return {"fixed_parts": [], "messages": [], "variables": {}}

    def apply_history_ttl_cleanup(self) -> int:
        """
        Soft-archive old active history messages by setting is_active=0.
        Controlled by HISTORY_TTL_ENABLED, HISTORY_TTL_DAYS.
        Returns count of archived messages.
        """
        from managers.settings_manager import SettingsManager
        try:
            enabled = SettingsManager.get("HISTORY_TTL_ENABLED", False)
            if str(enabled).lower() in ("false", "0", "", "none"):
                return 0
        except Exception:
            return 0

        if "is_active" not in self._history_cols:
            return 0

        try:
            ttl_days = int(SettingsManager.get("HISTORY_TTL_DAYS", 0))
        except Exception:
            ttl_days = 0

        if ttl_days <= 0:
            return 0

        # timestamp is stored as "dd.mm.yyyy HH:MM:SS" — convert for julianday()
        _ts_expr = (
            "CASE WHEN timestamp LIKE '__.__.____ __:__:__' "
            "THEN substr(timestamp,7,4)||'-'||substr(timestamp,4,2)||'-'||substr(timestamp,1,2)||' '||substr(timestamp,12) "
            "ELSE timestamp END"
        )

        total = 0
        try:
            with self.db.connection() as conn:
                cur = conn.cursor()
                not_deleted = " AND is_deleted = 0" if "is_deleted" in self._history_cols else ""
                cur.execute(
                    f"""UPDATE history SET is_active = 0
                        WHERE character_id = ? AND is_active = 1{not_deleted}
                          AND timestamp IS NOT NULL AND TRIM(timestamp) != ''
                          AND julianday('now') - julianday({_ts_expr}) > ?""",
                    (self.storage_key, ttl_days),
                )
                total = cur.rowcount
                if total > 0:
                    conn.commit()
        except Exception as e:
            logger.warning(f"[HistoryManager] apply_history_ttl_cleanup failed: {e}", exc_info=True)

        if total > 0:
            logger.info(f"[HistoryManager] TTL cleanup: archived {total} messages for '{self.storage_key}'")

        return total

    # ---------------------------------------------------------------------
    # Paging
    # ---------------------------------------------------------------------
    def get_total_messages_count(self) -> int:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM history WHERE character_id = ? AND is_active = 1 {self._history_not_deleted_clause()}", (self.storage_key,))
            count = cursor.fetchone()[0]
            return count
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_recent_messages(self, limit: int = 50, offset: int = 0) -> list[dict]:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            self._ensure_history_schema()
            select_cols = self._history_select_columns()

            sql = f"""
                SELECT {", ".join(select_cols)}
                FROM history
                WHERE character_id = ? AND is_active = 1 {self._history_not_deleted_clause()}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
            """
            cursor.execute(sql, (self.storage_key, int(limit), int(offset)))
            rows = cursor.fetchall()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        messages: list[dict] = []
        for row in rows:
            rd = dict(zip(select_cols, row))

            msg = self._reconstruct_message_from_db(
                rd.get("role"),
                rd.get("content"),
                rd.get("meta_data"),
            )
            msg["_history_row_id"] = rd.get("id")
            msg["time"] = self._display_timestamp(rd.get("timestamp"))

            for k in self._HISTORY_DESIRED_COLUMNS.keys():
                if k in rd and rd.get(k) is not None and rd.get(k) != "":
                    msg[k] = rd.get(k)

            msg = self._normalize_loaded_message(msg)
            messages.append(msg)

        return messages[::-1]

    # ---------------------------------------------------------------------
    # Compression helpers
    # ---------------------------------------------------------------------
    def get_messages_for_compression(self, num_messages: int) -> list[dict]:
        full_hist = self.load_history()
        messages = full_hist.get("messages", [])

        if not messages:
            return []

        messages_to_compress = messages[:num_messages]

        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute(
                f"""
                SELECT id FROM history
                WHERE character_id = ? AND is_active = 1
                {self._history_not_deleted_clause()}
                ORDER BY id ASC
                LIMIT ?
                """,
                (self.storage_key, num_messages),
            )
            ids_to_hide = [row[0] for row in cursor.fetchall()]

            if ids_to_hide:
                placeholders = ",".join("?" for _ in ids_to_hide)
                cursor.execute(
                    f"UPDATE history SET is_active = 0 WHERE id IN ({placeholders})",
                    tuple(ids_to_hide),
                )
                conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

        logger.info(f"Archived {len(messages_to_compress)} messages for compression.")
        return messages_to_compress

    def add_summarized_history_to_messages(self, summary_message: dict):
        self.add_message(summary_message)

    def _soft_delete_set_clause(self) -> str:
        if "is_deleted" in self._history_cols:
            return "is_deleted = 1, is_active = 0"
        return "is_active = 0"

    def delete_message(self, message_id: str) -> bool:
        """Удаляет одно активное сообщение по message_id."""
        row_id = self._resolve_message_row_id(message_id)
        if row_id is None:
            return False
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE history SET {self._soft_delete_set_clause()} "
                "WHERE id = ? AND character_id = ?",
                (row_id, self.storage_key),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _set_deleted_by_row_id(self, row_id: int, *, include_target: bool) -> bool:
        not_deleted = " AND is_deleted = 0" if "is_deleted" in self._history_cols else ""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                UPDATE history
                SET {self._soft_delete_set_clause()}
                WHERE character_id = ? AND id {'>=' if include_target else '>'} ?
                  AND is_active = 1{not_deleted}
                """,
                (self.storage_key, int(row_id)),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _resolve_message_row_id(self, message_id: str) -> int | None:
        if not message_id or "message_id" not in self._history_cols:
            return None
        not_deleted = " AND is_deleted = 0" if "is_deleted" in self._history_cols else ""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT id FROM history
                WHERE message_id = ? AND character_id = ?
                  AND is_active = 1{not_deleted}
                ORDER BY id DESC LIMIT 1
                """,
                (message_id, self.storage_key),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def delete_messages_from(self, message_id: str) -> bool:
        """Soft-delete the selected message and all later rows in insertion order."""
        row_id = self._resolve_message_row_id(message_id)
        return False if row_id is None else self._set_deleted_by_row_id(row_id, include_target=True)

    def delete_messages_after(self, message_id: str) -> bool:
        """Soft-delete rows after the selected message while keeping the target row."""
        row_id = self._resolve_message_row_id(message_id)
        return False if row_id is None else self._set_deleted_by_row_id(row_id, include_target=False)

    def delete_messages_from_row(self, row_id: int | None, *, include_target: bool = True) -> bool:
        """Fallback for legacy messages without message_id."""
        if row_id is None:
            return False
        return self._set_deleted_by_row_id(int(row_id), include_target=include_target)

    def append_message(self, message: dict):
        """Добавляет сообщение в конец истории."""
        self.add_message(message)

    def contains_message_id(self, message_id: str) -> bool:
        """Cheap deduplication lookup without loading the full conversation."""
        if not message_id or "message_id" not in self._history_cols:
            return False
        not_deleted = " AND is_deleted = 0" if "is_deleted" in self._history_cols else ""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT 1 FROM history
                WHERE character_id = ? AND message_id = ?
                  AND is_active = 1{not_deleted}
                LIMIT 1
                """,
                (self.storage_key, str(message_id)),
            )
            return cursor.fetchone() is not None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ---------------------------------------------------------------------
    # RAG helpers
    # ---------------------------------------------------------------------
    def get_missing_embeddings_count(self) -> int:
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            # history: учитываем is_deleted, если колонка есть
            try:
                extra = " AND is_deleted = 0 " if "is_deleted" in self._history_cols else ""
                cursor.execute(
                    f"""
                    SELECT COUNT(*) FROM history
                    WHERE character_id = ? AND (embedding IS NULL) AND content != "" AND content IS NOT NULL {extra}
                    """,
                    (self.storage_key,),
                )
                hist_count = cursor.fetchone()[0]
            except Exception:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM history
                    WHERE character_id = ? AND (embedding IS NULL) AND content != "" AND content IS NOT NULL
                    """,
                    (self.storage_key,),
                )
                hist_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*) FROM memories
                WHERE character_id = ? AND (embedding IS NULL) AND is_deleted = 0
                """,
                (self.storage_key,),
            )
            mem_count = cursor.fetchone()[0]

            return hist_count + mem_count
        finally:
            try:
                conn.close()
            except Exception:
                pass
