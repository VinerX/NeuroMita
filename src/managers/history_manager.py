import json
import logging
import os
import datetime
import base64
import re
import uuid
from main_logger import logger
from managers.database_manager import DatabaseManager
from managers.rag_manager import RAGManager


class HistoryManager:
    def __init__(self, character_name: str = "Common", history_file_name: str = "", character_id: str | None = None):
        self.character_name = str(character_name or "Common")
        self.character_id = str(character_id or "").strip()
        self.storage_key = self.character_id or self.character_name

        self.db = DatabaseManager()
        self.rag = RAGManager(self.storage_key)

    def _save_base64_image_to_disk(self, base64_string: str) -> str:
        """
        Сохраняет base64 изображение на диск и возвращает относительный путь.
        """
        try:
            # 1. Парсим заголовок data:image/jpeg;base64,
            match = re.match(r'data:image/(\w+);base64,(.+)', base64_string)
            if not match:
                return base64_string

            ext = match.group(1)
            img_data_str = match.group(2)
            if ext == "jpeg": ext = "jpg"

            # [ИЗМЕНЕНИЕ] Папка Histories/<Name>/Images
            save_dir = os.path.join("Histories", self.character_name, "Images")
            os.makedirs(save_dir, exist_ok=True)

            filename = f"{uuid.uuid4()}.{ext}"
            file_path = os.path.join(save_dir, filename)

            img_bytes = base64.b64decode(img_data_str)
            with open(file_path, "wb") as f:
                f.write(img_bytes)

            logger.info(f"Image saved: {file_path}")
            return file_path

        except Exception as e:
            logger.error(f"Failed to save base64 image to disk: {e}")
            return base64_string

    def _image_file_to_base64(self, file_path: str) -> str:
        """
        Читает локальный файл и превращает обратно в data:image/...;base64
        Нужно для обратной совместимости при загрузке истории.
        """
        try:
            if not os.path.exists(file_path):
                logger.warning(f"Image file not found: {file_path}")
                return file_path  # Возвращаем путь, если файл потерян, чтобы не крашить

            # Определяем расширение
            ext = os.path.splitext(file_path)[1].replace(".", "").lower()
            if ext == "jpg": ext = "jpeg"

            with open(file_path, "rb") as f:
                encoded_string = base64.b64encode(f.read()).decode('utf-8')

            return f"data:image/{ext};base64,{encoded_string}"
        except Exception as e:
            logger.error(f"Error converting file to base64: {e}")
            return file_path

    def _prepare_message_for_db(self, role: str, raw_content, raw_meta=None) -> tuple[str, str | None]:
        db_content = ""
        meta_dict = {}

        if raw_meta:
            if isinstance(raw_meta, str):
                try:
                    meta_dict = json.loads(raw_meta)
                except:
                    pass
            elif isinstance(raw_meta, dict):
                meta_dict = raw_meta.copy()

        if isinstance(raw_content, str):
            db_content = raw_content

        elif isinstance(raw_content, list):
            text_parts = []
            other_parts = []

            for item in raw_content:
                if isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type == "text":
                        text_parts.append(item.get("text", ""))
                    elif item_type == "image_url":
                        image_url_dict = item.get("image_url", {})
                        url_str = image_url_dict.get("url", "")

                        if url_str.startswith("data:image"):
                            # Сохраняем файл на диск
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

        elif isinstance(raw_content, dict):
            db_content = json.dumps(raw_content, ensure_ascii=False)
        else:
            db_content = str(raw_content) if raw_content is not None else ""

        db_meta = json.dumps(meta_dict, ensure_ascii=False) if meta_dict else None
        return db_content, db_meta

    def _reconstruct_message_from_db(self, role, db_content, db_meta_raw):
        """
        Восстановление ИЗ БАЗЫ для API (Path -> Base64).
        Строго фильтрует ключи.
        """
        meta = {}
        if db_meta_raw:
            try:
                meta = json.loads(db_meta_raw)
            except:
                pass

        content = db_content

        # Проверяем флаги мультимодальности
        if meta.get("is_multimodal_list", False) or meta.get("multimodal_parts"):
            reconstructed_list = []

            # 1. Текст
            if db_content:
                reconstructed_list.append({"type": "text", "text": str(db_content)})

            # 2. Мультимедиа части
            if "multimodal_parts" in meta:
                parts = meta["multimodal_parts"]
                for part in parts:
                    part_type = part.get("type")

                    if part_type == "image_url":
                        url = part.get("image_url", {}).get("url", "")

                        # Логика восстановления Base64
                        final_url = url
                        is_local = part.get("is_local_file", False)

                        # Если помечено как локальный или не похоже на http/data
                        if is_local or (url and not url.startswith("http") and not url.startswith("data:")):
                            final_url = self._image_file_to_base64(url)

                        # [ВАЖНО] Создаем ЧИСТЫЙ словарь для API.
                        # Никаких лишних полей типа 'is_local_file' здесь быть не должно.
                        clean_part = {
                            "type": "image_url",
                            "image_url": {
                                "url": final_url
                            }
                        }
                        # Если API поддерживает detail, можно добавить, но лучше не рисковать лишним
                        if "detail" in part.get("image_url", {}):
                            clean_part["image_url"]["detail"] = part["image_url"]["detail"]

                        reconstructed_list.append(clean_part)

                    elif part_type == "text":
                        # На случай если текст попал в parts
                        reconstructed_list.append({
                            "type": "text",
                            "text": part.get("text", "")
                        })
                    else:
                        # Неизвестные типы пропускаем или добавляем как есть, но очищая от мусора
                        # Для безопасности лучше пропускать, если API строгое
                        pass

            content = reconstructed_list

        msg = {
            "role": role,
            "content": content
        }

        # Восстанавливаем остальные поля метадаты (например, имя пользователя если есть),
        # но фильтруем служебные поля DB
        for k, v in meta.items():
            if k not in ["multimodal_parts", "is_multimodal_list", "image"]:
                msg[k] = v

        return msg
    def load_history(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # 1. Переменные
        cursor.execute('SELECT key, value FROM variables WHERE character_id = ?', (self.storage_key,))
        variables = {}
        for row in cursor.fetchall():
            try:
                variables[row[0]] = json.loads(row[1])
            except:
                variables[row[0]] = row[1]


        # 2. Сообщения
        cursor.execute('''
            SELECT role, content, meta_data, timestamp 
            FROM history 
            WHERE character_id = ? AND is_active = 1
            ORDER BY id ASC
        ''', (self.storage_key,))

        messages = []
        for row in cursor.fetchall():
            db_timestamp = row[3]

            msg = self._reconstruct_message_from_db(row[0], row[1], row[2])

            msg["time"] = db_timestamp if db_timestamp else ""
            messages.append(msg)

        conn.close()

        return {
            "fixed_parts": [],
            "messages": messages,
            "temp_context": [],
            "variables": variables,
        }

    def save_history(self, data):
        messages = data.get("messages", [])
        variables = data.get("variables", {})

        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # 1. Переменные
            for k, v in variables.items():
                val_str = json.dumps(v, ensure_ascii=False)
                cursor.execute('''
                      INSERT INTO variables (character_id, key, value) VALUES(?, ?, ?)
                      ON CONFLICT(character_id, key) DO UPDATE SET value=excluded.value
                  ''', (self.storage_key, k, val_str))

            # 2. История
            # Удаляем активные, чтобы перезаписать актуальным состоянием
            cursor.execute('DELETE FROM history WHERE character_id = ? AND is_active = 1', (self.storage_key,))

            for msg in messages:
                raw_content = msg.get("content")

                temp_meta = {}
                if "image" in msg:
                    temp_meta["image"] = msg["image"]

                db_content, db_meta = self._prepare_message_for_db(msg.get("role"), raw_content, temp_meta)

                # Вставляем сообщение
                cursor.execute('''
                      INSERT INTO history (character_id, role, content, is_active, meta_data, timestamp)
                      VALUES (?, ?, ?, 1, ?, ?)
                  ''', (self.storage_key, msg.get("role"), db_content, db_meta,
                        datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")))

                # [ИСПРАВЛЕНИЕ] Сразу генерируем вектор для вставленной строки!
                new_row_id = cursor.lastrowid
                if new_row_id and db_content:
                    # Важно: это синхронный вызов. При сохранении большой истории может быть микро-фриз,
                    # но зато данные будут целостными.
                    # Если RAGManager инициализирован корректно, он обновит запись.
                    try:
                        self.rag.update_history_embedding(new_row_id, str(db_content))
                    except Exception as e:
                        logger.error(f"Failed to update embedding inside save_history: {e}")

            conn.commit()
        except Exception as e:
            logger.error(f"DB Error saving history: {e}", exc_info=True)
        finally:
            conn.close()

    def add_message(self, message: dict):
        conn = self.db.get_connection()
        cursor = conn.cursor()

        raw_content = message.get("content")
        temp_meta = {}
        if "image" in message:
            temp_meta["image"] = message["image"]

        db_content, db_meta = self._prepare_message_for_db(message.get("role"), raw_content, temp_meta)

        cursor.execute('''
            INSERT INTO history (character_id, role, content, is_active, meta_data, timestamp)
            VALUES (?, ?, ?, 1, ?, ?)
        ''', (self.storage_key, message.get("role"), db_content, db_meta, datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")))

        new_row_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Генерируем вектор асинхронно или синхронно (пока синхронно для простоты)
        content_text = message.get("content", "")
        if isinstance(content_text, str) and content_text:
            self.rag.update_history_embedding(new_row_id, content_text)

    def update_variable(self, key, value):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        val_str = json.dumps(value, ensure_ascii=False)
        cursor.execute('''
            INSERT INTO variables (character_id, key, value) VALUES(?, ?, ?)
            ON CONFLICT(character_id, key) DO UPDATE SET value=excluded.value
        ''', (self.storage_key, key, val_str))
        conn.commit()
        conn.close()



    def save_missed_history(self, missed_messages: list):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        for msg in missed_messages:
            raw_content = msg.get("content")
            temp_meta = {}
            if "image" in msg:
                temp_meta["image"] = msg["image"]

            db_content, db_meta = self._prepare_message_for_db(msg.get("role"), raw_content, temp_meta)

            cursor.execute('''
                INSERT INTO history (character_id, role, content, is_active, meta_data, timestamp)
                VALUES (?, ?, ?, 0, ?, ?)
            ''', (self.storage_key, msg.get("role"), db_content, db_meta, datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")))
        conn.commit()
        conn.close()

    def clear_history(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE history SET is_active = 0 WHERE character_id = ?', (self.storage_key,))
        conn.commit()
        conn.close()

    def _default_history(self):
        return {"fixed_parts": [], "messages": [], "variables": {}}

    def get_total_messages_count(self) -> int:
        """Возвращает общее количество активных сообщений."""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM history WHERE character_id = ? AND is_active = 1', (self.storage_key,))
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def get_recent_messages(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """
        Возвращает срез сообщений (для пагинации).
        offset - сколько сообщений пропустить с КОНЦА (от новых к старым).
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Получаем данные в обратном порядке (сначала новые), применяем лимит и оффсет
        cursor.execute('''
              SELECT role, content, meta_data, timestamp 
              FROM history 
              WHERE character_id = ? AND is_active = 1
              ORDER BY id DESC
              LIMIT ? OFFSET ?
          ''', (self.storage_key, limit, offset))

        rows = cursor.fetchall()
        conn.close()

        messages = []
        for row in rows:
            msg = self._reconstruct_message_from_db(row[0], row[1], row[2])
            msg["time"] = row[3] if row[3] else ""
            messages.append(msg)

        # Разворачиваем обратно, чтобы они шли хронологически (от старых к новым)
        return messages[::-1]

    def get_messages_for_compression(self, num_messages: int) -> list[dict]:
        full_hist = self.load_history()
        messages = full_hist.get("messages", [])

        if not messages:
            return []

        messages_to_compress = messages[:num_messages]

        conn = self.db.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id FROM history 
            WHERE character_id = ? AND is_active = 1 
            ORDER BY id ASC 
            LIMIT ?
        ''', (self.storage_key, num_messages))

        ids_to_hide = [row[0] for row in cursor.fetchall()]

        if ids_to_hide:
            placeholders = ','.join('?' for _ in ids_to_hide)
            cursor.execute(f'''
                UPDATE history SET is_active = 0 
                WHERE id IN ({placeholders})
            ''', tuple(ids_to_hide))
            conn.commit()

        conn.close()
        logger.info(f"Archived {len(messages_to_compress)} messages for compression.")
        return messages_to_compress

    def add_summarized_history_to_messages(self, summary_message: dict):
        self.add_message(summary_message)

    def get_missing_embeddings_count(self) -> int:
        """Считает, сколько записей (history + memories) не имеют вектора."""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Считаем историю (только текстовые сообщения)
        cursor.execute('''
               SELECT COUNT(*) FROM history 
               WHERE character_id = ? AND (embedding IS NULL) AND content != "" AND content IS NOT NULL
           ''', (self.storage_key,))
        hist_count = cursor.fetchone()[0]

        # Считаем воспоминания
        cursor.execute('''
               SELECT COUNT(*) FROM memories 
               WHERE character_id = ? AND (embedding IS NULL) AND is_deleted = 0
           ''', (self.storage_key,))
        mem_count = cursor.fetchone()[0]

        conn.close()
        return hist_count + mem_count