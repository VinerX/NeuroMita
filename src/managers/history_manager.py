import json
import logging
import os
import datetime
from main_logger import logger
from managers.database_manager import DatabaseManager


class HistoryManager:
    def __init__(self, character_name: str = "Common", history_file_name: str = "", character_id: str | None = None):
        self.character_name = str(character_name or "Common")
        self.character_id = str(character_id or "").strip()
        self.storage_key = self.character_id or self.character_name

        self.db = DatabaseManager()

    def _prepare_message_for_db(self, role: str, raw_content, raw_meta=None) -> tuple[str, str | None]:
        """
        Преобразует контент и метаданные для записи в БД.
        - Если content - строка: пишет как есть.
        - Если content - список (мультимодальный): извлекает текст в content, остальное в meta_data.
        """
        db_content = ""
        meta_dict = {}

        # 1. Загружаем существующую метадату (если есть)
        if raw_meta:
            if isinstance(raw_meta, str):
                try:
                    meta_dict = json.loads(raw_meta)
                except:
                    pass
            elif isinstance(raw_meta, dict):
                meta_dict = raw_meta.copy()

        # 2. Обрабатываем контент
        if isinstance(raw_content, str):
            db_content = raw_content

        elif isinstance(raw_content, list):
            # Это мультимодальный список [{'type': 'text', ...}, {'type': 'image_url', ...}]
            text_parts = []
            other_parts = []

            for item in raw_content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    else:
                        # Картинки и прочее сохраняем для метадаты
                        other_parts.append(item)

            # Собираем весь текст в одну строку для БД (чтобы было читаемо и искалось)
            db_content = "\n".join(text_parts)

            # Если были нетекстовые части, сохраняем их в мету
            if other_parts:
                meta_dict["multimodal_parts"] = other_parts

            # Маркер, что это был список, чтобы при загрузке восстановить формат списка
            # даже если там был только текст (как в твоем логе)
            meta_dict["is_multimodal_list"] = True

        elif isinstance(raw_content, dict):
            # Редкий кейс, если контент словарь - просто дампаем
            db_content = json.dumps(raw_content, ensure_ascii=False)

        else:
            db_content = str(raw_content) if raw_content is not None else ""

        # 3. Сериализуем метадату
        db_meta = json.dumps(meta_dict, ensure_ascii=False) if meta_dict else None

        return db_content, db_meta

    def _reconstruct_message_from_db(self, role, db_content, db_meta_raw):
        """
        Восстанавливает исходную структуру сообщения из БД.
        """
        meta = {}
        if db_meta_raw:
            try:
                meta = json.loads(db_meta_raw)
            except:
                pass

        content = db_content

        # Если это было мультимодальное сообщение (список), восстанавливаем список
        if meta.get("is_multimodal_list", False) or meta.get("multimodal_parts"):
            reconstructed_list = []

            # 1. Добавляем текстовую часть (которую мы хранили в колонке content)
            if db_content:
                reconstructed_list.append({"type": "text", "text": db_content})

            # 2. Добавляем остальные части (картинки и т.д.)
            if "multimodal_parts" in meta:
                reconstructed_list.extend(meta["multimodal_parts"])

            content = reconstructed_list

            # Чистим служебные поля из меты перед отдачей в программу (опционально)
            # meta.pop("multimodal_parts", None)
            # meta.pop("is_multimodal_list", None)

        msg = {
            "role": role,
            "content": content
        }

        # Вливаем остальные поля метадаты (например, image пути из старой версии)
        for k, v in meta.items():
            if k not in ["multimodal_parts", "is_multimodal_list"]:
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
            role = row[0]
            db_content = row[1]
            db_meta = row[2]

            msg = self._reconstruct_message_from_db(role, db_content, db_meta)
            messages.append(msg)

        conn.close()

        return {
            "fixed_parts": [],
            "messages": messages,
            "temp_context": [],
            "variables": variables,
        }

    def save_history(self, data):
        """
        Режим ПОЛНОЙ ПЕРЕЗАПИСИ активной истории.
        """
        messages = data.get("messages", [])
        variables = data.get("variables", {})

        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # 1. Сохраняем переменные
            for k, v in variables.items():
                val_str = json.dumps(v, ensure_ascii=False)
                cursor.execute('''
                    INSERT INTO variables (character_id, key, value) VALUES(?, ?, ?)
                    ON CONFLICT(character_id, key) DO UPDATE SET value=excluded.value
                ''', (self.storage_key, k, val_str))

            # 2. Перезаписываем сообщения
            cursor.execute('DELETE FROM history WHERE character_id = ? AND is_active = 1', (self.storage_key,))

            for msg in messages:
                raw_content = msg.get("content")

                # Извлекаем спец поля типа image во временную мету
                temp_meta = {}
                if "image" in msg:
                    temp_meta["image"] = msg["image"]

                # Подготовка данных (разделение текста и структуры)
                db_content, db_meta = self._prepare_message_for_db(msg.get("role"), raw_content, temp_meta)

                cursor.execute('''
                    INSERT INTO history (character_id, role, content, is_active, meta_data, timestamp)
                    VALUES (?, ?, ?, 1, ?, ?)
                ''', (self.storage_key, msg.get("role"), db_content, db_meta, datetime.datetime.now().isoformat()))

            conn.commit()
        except Exception as e:
            logger.error(f"DB Error saving history: {e}", exc_info=True)
        finally:
            conn.close()

    def add_message(self, message: dict):
        """
        Точечное добавление сообщения.
        """
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
        ''', (self.storage_key, message.get("role"), db_content, db_meta, datetime.datetime.now().isoformat()))

        conn.commit()
        conn.close()

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

    def save_history_separate(self):
        try:
            backup_dir = os.path.join("Histories", self.storage_key, "Saved")
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%d.%m.%Y_%H.%M")
            dst_db = os.path.join(backup_dir, f"world_backup_{timestamp}.db")

            conn = self.db.get_connection()
            conn.execute(f"VACUUM INTO '{dst_db}'")
            conn.close()
            logger.info(f"Database backup created at {dst_db}")
        except Exception as e:
            logger.error(f"Backup failed: {e}")

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
            ''', (self.storage_key, msg.get("role"), db_content, db_meta, datetime.datetime.now().isoformat()))
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

    def get_messages_for_compression(self, num_messages: int) -> list[dict]:
        """
        Возвращает старые сообщения для сжатия и помечает их is_active=0.
        """
        # Загружаем полную историю, чтобы вернуть объекты в правильном формате (восстановленные из меты)
        full_hist = self.load_history()
        messages = full_hist.get("messages", [])

        if not messages:
            return []

        messages_to_compress = messages[:num_messages]

        # Теперь скрываем их в БД по ID
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