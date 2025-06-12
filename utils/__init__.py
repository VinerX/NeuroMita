import os
import sys
import json
import re

from num2words import num2words

from Logger import logger
from SettingsManager import SettingsManager


def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))

def getTranslationVariant(ru_str, en_str=""):
    if en_str and SettingsManager.get("LANGUAGE") == "EN":
        return en_str

    return ru_str


_ = getTranslationVariant  # Временно, мб

def load_text_from_file(filename):
    """
    Загружает текст из файла, расположенного в папке 'Crazy'.

    :param filename: Имя файла или относительный путь к файлу.
    :return: Содержимое файла в виде строки. Если файл не найден, возвращает пустую строку.
    """

    logger.info(f"Загружаю {filename}")
    try:
        # Определяем базовый путь в зависимости от того, собрано ли приложение
        if getattr(sys, 'frozen', False):
            # Если приложение собрано (PyInstaller)
            base_path = os.path.dirname(sys.executable)
        else:
            # Если запуск из IDE/скрипта
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Формируем полный путь к файлу
        filepath = os.path.join(base_path, filename)
        filepath = os.path.normpath(filepath)

        # Проверяем, существует ли файл
        if not os.path.exists(filepath):
            logger.info(f"Файл не найден: {filepath}")
            return ""

        # Читаем файл
        with open(filepath, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        logger.info(f"Ошибка при чтении файла {filename}: {e}")
        return ""


def get_resource_path(filename):
    """
    Возвращает полный путь к файлу в папке 'Crazy'.

    :param filename: Имя файла или относительный путь к файлу.
    :return: Полный путь к файлу или None, если папка 'Crazy' не найдена.
    """
    # Определяем базовый путь
    if getattr(sys, 'frozen', False):
        # Если программа "заморожена" (например, с помощью PyInstaller)
        base_path = os.path.dirname(sys.executable)
    else:
        # Если программа запущена как скрипт
        base_path = os.path.dirname(__file__)

    # Формируем путь к папке
    promts_path = os.path.join(base_path)

    # Проверяем, существует ли папка 'Crazy'
    if not os.path.isdir(promts_path):
        logger.info(f"Ошибка: Папка не найдена по пути: {promts_path}")
        return None

    # Возвращаем полный путь к файлу
    return os.path.join(promts_path, filename)


def load_json_file(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        logger.info(f"Файл {filepath} не найден.")
        return {}


def save_combined_messages(combined_messages, output_folder="SavedMessages"):
    os.makedirs(output_folder, exist_ok=True)
    file_name = f"combined_messages.json"
    file_path = os.path.join(output_folder, file_name)
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(combined_messages, file, ensure_ascii=False, indent=4)
    logger.info(f"Сообщения сохранены в файл: {file_path}")


def calculate_cost_for_combined_messages(self, combined_messages, cost_input_per_1000):
    token_count = self.count_tokens(combined_messages)
    cost = (token_count / 1000) * cost_input_per_1000
    return f"Токенов {token_count} Цена {cost}"


def count_tokens(self, messages):
    return sum(
        len(self.tokenizer.encode(msg["content"])) for msg in messages if isinstance(msg, dict) and "content" in msg)


def SH(s, placeholder="***", percent=0.20):
    """
    Сокращает строку, оставляя % символов в начале и % в конце.
    Средняя часть заменяется на placeholder.

    :param percent:
    :param s: Исходная строка.
    :param placeholder: Заполнитель для скрытой части строки (по умолчанию "***").
    :return: Сокращенная строка.
    """
    if not s:
        return s

    length = len(s)
    # Вычисляем 20% от длины строки
    visible_length = max(1, int(length * percent))  # Минимум 1 символ

    # Берем начало и конец строки
    start = s[:visible_length]
    end = s[-visible_length:]

    # Собираем результат
    return f"{start}{placeholder}{end}"

#Замена чисел на слова в русском тексте
def replace_numbers_with_words(text):
    numbers = re.findall(r'\d+', text)
    for number in numbers:
        word = num2words(int(number), lang='ru')
        text = text.replace(number, word)
    return text

def shift_chars(s, shift):
    """
    Сдвигает все символы в строке на заданное число.
    :param s: Исходная строка.
    :param shift: Число, на которое нужно сдвинуть символы.
    :return: Зашифрованная или расшифрованная строка.
    """
    result = []
    for char in s:
        # Сдвигаем символ на shift позиций
        new_char = chr(ord(char) + shift)
        result.append(new_char)
    return ''.join(result)

def process_text_to_voice(text_to_speak: str) -> str:
    if not isinstance(text_to_speak, str):
        logger.warning(f"process_text_to_voice expected string, got {type(text_to_speak)}. Converting to string.")
        text_to_speak = str(text_to_speak)

    clean_text = re.sub(r"<[^>]+>.*?</[^>]+>", "", text_to_speak, flags=re.DOTALL)
    clean_text = re.sub(r"<[^>]+>", "", clean_text)

    try:
        clean_text = replace_numbers_with_words(clean_text)
    except NameError:
        logger.debug("replace_numbers_with_words utility not found or used.")
        pass

    if not clean_text.strip():
        clean_text = "..."
        logger.info("TTS text was empty after cleaning, using default '...'")

    return clean_text.strip()

# text = load_text_from_file("Prompts/Common/None.txt")
# logger.info(text)
# textEncoded = shift_chars(text,1)
# logger.info(textEncoded)
# textDecoded = shift_chars(textEncoded,-1)
# logger.info(textDecoded)
#
