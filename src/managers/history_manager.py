import json
import os
import datetime
import shutil

from main_logger import logger


def _safe_dirname(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return "Unknown"
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_ ")
    cleaned = "".join(ch if ch in allowed else "_" for ch in value)
    cleaned = cleaned.strip(" ._")
    return cleaned or "Unknown"


class HistoryManager:
    """Файловая история. Ключевая правка: хранение должно быть уникальным по character_id (char_id)."""

    def __init__(self, character_name: str = "Common", history_file_name: str = "", character_id: str | None = None):
        self.character_name = str(character_name or "Common")
        self.character_id = str(character_id or "").strip()

        storage_key = self.character_id or self.character_name
        storage_key = _safe_dirname(storage_key)

        self.history_dir = os.path.join("Histories", storage_key)
        self.history_file_path = os.path.join(self.history_dir, f"{storage_key}_history.json")

        os.makedirs(self.history_dir, exist_ok=True)

        if self.history_file_path:
            self.load_history()

    def load_history(self):
        """Загружаем историю из файла, создаем пустую структуру, если файл пуст или не существует."""
        try:
            with open(self.history_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if self.history_format_correct(data):
                    return data

                logger.info("Ошибка загрузки истории, копия сохранена в резерв, текущая сброшена")
                self.save_history_separate()
                return self._default_history()

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка загрузки истории {e} , создается бекап")
            self.save_history_separate()
            return self._default_history()
        except FileNotFoundError:
            logger.warning("Файл истории пуст или не существует")
            return self._default_history()

    def history_format_correct(self, data):
        checks = [
            (isinstance(data.get("fixed_parts"), list), "fixed_parts должен быть списком"),
            (isinstance(data.get("messages"), list), "messages должен быть списком"),
            (isinstance(data.get("variables"), dict), "variables должен быть словарем"),
        ]

        if all(check[0] for check in checks):
            return True

        for condition, error_message in checks:
            if not condition:
                logger.info(f"Ошибка: {error_message}")
        return False

    def save_history(self, data):
        """Сохраняем историю в файл с явной кодировкой utf-8."""
        history_data = {
            "meta": {
                "character_id": self.character_id,
                "character_name": self.character_name,
                "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            },
            "fixed_parts": data.get("fixed_parts", []),
            "messages": data.get("messages", []),
            "temp_context": data.get("temp_context", []),
            "variables": data.get("variables", {}),
        }

        os.makedirs(self.history_dir, exist_ok=True)
        with open(self.history_file_path, "w", encoding="utf-8") as f:
            json.dump(history_data, f, ensure_ascii=False, indent=4)

    def save_history_separate(self):
        """Сохраняем текущую историю отдельным файлом (бекап)."""
        logger.info("save_chat_history")

        target_folder = os.path.join(self.history_dir, "Saved")
        os.makedirs(target_folder, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%d.%m.%Y_%H.%M")
        target_file = f"chat_history_{timestamp}.json"
        target_path = os.path.join(target_folder, target_file)

        try:
            if os.path.exists(self.history_file_path):
                shutil.copy(self.history_file_path, target_path)
                logger.info(f"Файл сохранён как {target_path}")
        except Exception as e:
            logger.error(f"Не удалось сохранить бекап истории: {e}", exc_info=True)

    def save_missed_history(self, missed_messages: list):
        """
        Сохраняет "потерянные" сообщения в отдельный файл.
        Файл живёт рядом с историей конкретного storage_key (т.е. конкретного char_id).
        """
        os.makedirs(self.history_dir, exist_ok=True)
        missed_file_path = os.path.join(self.history_dir, "missed_history.json")

        existing_missed_messages = []
        if os.path.exists(missed_file_path):
            try:
                with open(missed_file_path, "r", encoding="utf-8") as f:
                    existing_missed_messages = json.load(f)
                    if not isinstance(existing_missed_messages, list):
                        logger.warning(
                            f"Файл пропущенной истории {missed_file_path} поврежден или имеет неверный формат. Создаю новый."
                        )
                        existing_missed_messages = []
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning(
                    f"Не удалось загрузить существующую пропущенную историю из {missed_file_path}. Создаю новый файл."
                )
                existing_missed_messages = []

        existing_missed_messages.extend(missed_messages)

        try:
            with open(missed_file_path, "w", encoding="utf-8") as f:
                json.dump(existing_missed_messages, f, ensure_ascii=False, indent=4)
            logger.info(f"Пропущенные сообщения сохранены в {missed_file_path}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении пропущенных сообщений в {missed_file_path}: {e}", exc_info=True)

    def clear_history(self):
        logger.info("Сброс файла истории")
        self.save_history(self._default_history())

    def _default_history(self):
        logger.info("Созданная пустая история")
        return {
            "fixed_parts": [],
            "messages": [],
            "temp_context": [],
            "variables": {},
        }

    def get_messages_for_compression(self, num_messages: int) -> list[dict]:
        history_data = self.load_history()
        messages = history_data.get("messages", [])

        messages_to_compress = messages[:num_messages]
        remaining_messages = messages[num_messages:]

        history_data["messages"] = remaining_messages
        self.save_history(history_data)

        logger.info(f"Извлечено {len(messages_to_compress)} сообщений для сжатия.")
        return messages_to_compress

    def add_summarized_history_to_messages(self, summary_message: dict):
        history_data = self.load_history()
        history_data["messages"].insert(0, summary_message)
        self.save_history(history_data)

    def delete_message(self, message_id: str) -> bool:
        """Удаляет сообщение по message_id. Возвращает True если удалено."""
        history_data = self.load_history()
        messages = history_data.get("messages", [])
        new_messages = [m for m in messages if m.get("message_id") != message_id]
        if len(new_messages) == len(messages):
            return False
        history_data["messages"] = new_messages
        self.save_history(history_data)
        return True

    def delete_messages_from(self, message_id: str) -> bool:
        """Удаляет сообщение с message_id и все последующие."""
        history_data = self.load_history()
        messages = history_data.get("messages", [])
        idx = next((i for i, m in enumerate(messages) if m.get("message_id") == message_id), None)
        if idx is None:
            return False
        history_data["messages"] = messages[:idx]
        self.save_history(history_data)
        return True

    def append_message(self, message: dict):
        """Добавляет сообщение в конец истории."""
        history_data = self.load_history()
        history_data.setdefault("messages", []).append(message)
        self.save_history(history_data)