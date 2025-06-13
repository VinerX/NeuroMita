import json
import os
import datetime
import shutil

from Logger import logger


class HistoryManager:
    """ В работе, пока неактивно"""

    def __init__(self, character_name="Common", history_file_name=""):

        self.character_name = character_name

        self.history_dir = f"Histories\\{character_name}"
        self.history_file_path = os.path.join(self.history_dir, f"{character_name}_history.json")

        os.makedirs(self.history_dir, exist_ok=True)

        if self.history_file_path != "":
            self.load_history()

    def load_history(self):
        """Загружаем историю из файла, создаем пустую структуру, если файл пуст или не существует."""
        try:
            with open(self.history_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if self.history_format_correct(data):
                    return data

                else:
                    logger.info("Ошибка загрузки истории, копия сохранена в резерв, текущая сброшена")
                    self.save_history_separate()
                    return self._default_history()

        except (json.JSONDecodeError, FileNotFoundError):
            # Если файл пуст или не существует, возвращаем структуру по умолчанию
            logger.info("Ошибка загрузки истории")
            return self._default_history()

    def history_format_correct(self, data):
        # Проверяем, что все ключи присутствуют и имеют правильный тип
        checks = [
            (isinstance(data.get('fixed_parts'), list), "fixed_parts должен быть списком"),
            (isinstance(data.get('messages'), list), "messages должен быть списком"),
            #(isinstance(data.get('temp_context'), list), "temp_context должен быть списком"),
            (isinstance(data.get('variables'), dict), "variables должен быть словарем")
        ]

        # Проверяем все условия
        if all(check[0] for check in checks):
            return True
        else:
            # Выводим сообщения об ошибках для тех условий, которые не выполнены
            for condition, error_message in checks:
                if not condition:
                    logger.info(f"Ошибка: {error_message}")
            return False

    def save_history(self, data):
        """Сохраняем историю в файл с явной кодировкой utf-8."""
        # Убедимся, что структура данных включает 'messages', 'currentInfo' и 'MitaSystemMessages'
        history_data = {
            'fixed_parts': data.get('fixed_parts', []),
            'messages': data.get('messages', []),
            'temp_context': data.get('temp_context', []),
            'variables': data.get('variables', {})
        }
        # Проверяем, существует ли папка SavedHistories, и создаём её, если нет
        os.makedirs(self.history_dir, exist_ok=True)
        with open(self.history_file_path, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, ensure_ascii=False, indent=4)

    def save_history_separate(self):
        """Нужно, чтобы история сохранилась отдельно"""
        logger.info("save_chat_history")
        # Папка для сохранения историй
        target_folder = f"Histories\\{self.character_name}\\Saved"
        # Проверяем, существует ли папка SavedHistories, и создаём её, если нет
        os.makedirs(target_folder, exist_ok=True)

        # Формируем имя файла с таймингом
        timestamp = datetime.datetime.now().strftime("%d.%m.%Y_%H.%M")
        target_file = f"chat_history_{timestamp}.json"

        # Полный путь к новому файлу
        target_path = os.path.join(target_folder, target_file)

        # Копируем файл
        shutil.copy(self.history_file_path, target_path)
        logger.info(f"Файл сохранён как {target_path}")

    def save_missed_history(self, missed_messages: list):
        """
        Сохраняет "потерянные" сообщения в отдельный файл для персонажа.
        Сообщения добавляются к существующему файлу, если он есть.
        """
        missed_dir = os.path.join("Histories", self.character_name)
        os.makedirs(missed_dir, exist_ok=True)
        missed_file_path = os.path.join(missed_dir, f"{self.character_name}_missed_history.json")

        existing_missed_messages = []
        if os.path.exists(missed_file_path):
            try:
                with open(missed_file_path, 'r', encoding='utf-8') as f:
                    existing_missed_messages = json.load(f)
                    if not isinstance(existing_missed_messages, list):
                        logger.warning(f"Файл пропущенной истории {missed_file_path} поврежден или имеет неверный формат. Создаю новый.")
                        existing_missed_messages = []
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning(f"Не удалось загрузить существующую пропущенную историю из {missed_file_path}. Создаю новый файл.")
                existing_missed_messages = []

        # Добавляем новые пропущенные сообщения
        existing_missed_messages.extend(missed_messages)

        try:
            with open(missed_file_path, 'w', encoding='utf-8') as f:
                json.dump(existing_missed_messages, f, ensure_ascii=False, indent=4)
            logger.info(f"Пропущенные сообщения сохранены в {missed_file_path}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении пропущенных сообщений в {missed_file_path}: {e}", exc_info=True)

    def clear_history(self):
        logger.info("Сброс файла истории")

        self.save_history(self._default_history())

    def _default_history(self):
        logger.info("Созданная пустая история")
        """Создаем структуру истории по умолчанию."""
        return {
            'fixed_parts': [],
            'messages': [],
            'temp_context': [],
            'variables': {}
        }

    def get_messages_for_compression(self, num_messages: int) -> list[dict]:
        """Возвращает num_messages самых старых сообщений из истории, предназначенных для сжатия, и удаляет их из основной истории."""
        messages_to_compress = self.load_history()['messages'][:num_messages]
        self.load_history()['messages'] = self.load_history()['messages'][num_messages:]
        self.save_history(self.load_history())
        return messages_to_compress

    def add_summarized_history_to_messages(self, summary_message: dict):
        """Добавляет сжатую сводку обратно в список сообщений истории (если HISTORY_COMPRESSION_OUTPUT_TARGET = "reduced_history")."""
        history_data = self.load_history()
        history_data['messages'].insert(0, summary_message)
        self.save_history(history_data)
