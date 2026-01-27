import os
import sys
import json
import re
import unicodedata as ud
from collections import Counter

# langdetect (опционально): pip install langdetect
try:
    from langdetect import detect, DetectorFactory, LangDetectException
    DetectorFactory.seed = 0  # детерминированность
    LANGDETECT_AVAILABLE = True
except Exception:
    LANGDETECT_AVAILABLE = False

from num2words import num2words

from main_logger import logger
from managers.settings_manager import SettingsManager
from utils.gpu_utils import check_gpu_provider


# =============================== Базовые утилиты ===============================

def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))


def getTranslationVariant(ru_str, en_str=""):
    if en_str and SettingsManager.get("LANGUAGE") == "EN":
        return en_str
    return ru_str


_ = getTranslationVariant  # Временно, мб


def get_character_voice_paths(character=None, provider=None):
    """
    Возвращает все пути для голосовой модели персонажа.

    Args:
        character: Объект персонажа или словарь с полем/ключом 'short_name'
        provider: GPU провайдер ("NVIDIA", "AMD", и т.д.). Если None, определяется автоматически.

    Returns:
        dict: Словарь с путями:
            - pth_path: путь к файлу модели (.pth или .onnx)
            - index_path: путь к индексному файлу
            - clone_voice_filename: путь к эталонному аудио
            - clone_voice_text: путь к текстовому файлу
            - f5_voice_filename: путь к эталонному аудио для F5-TTS (из папки _Cuts)
            - f5_voice_text: путь к текстовому файлу для F5-TTS (из папки _Cuts)
            - character_name: короткое имя персонажа
    """
    if provider is None:
        provider = check_gpu_provider()

    is_nvidia = provider in ["NVIDIA"]
    model_ext = 'pth' if is_nvidia else 'onnx'
    clone_voice_folder = "Models"

    short_name = "Mila"  # значение по умолчанию

    if character:
        # Проверяем, является ли character словарем
        if isinstance(character, dict):
            short_name = str(character.get('short_name', 'Mila'))
        # Иначе пробуем как объект с атрибутом
        elif hasattr(character, 'short_name'):
            short_name = str(character.short_name)

    return {
        'pth_path': os.path.join(clone_voice_folder, f"{short_name}.{model_ext}"),
        'index_path': os.path.join(clone_voice_folder, f"{short_name}.index"),
        'clone_voice_filename': os.path.join(clone_voice_folder, f"{short_name}.wav"),
        'clone_voice_text': os.path.join(clone_voice_folder, f"{short_name}.txt"),
        'f5_voice_filename': os.path.join(clone_voice_folder, f"{short_name}_Cuts", f"{short_name}_default.wav"),
        'f5_voice_text': os.path.join(clone_voice_folder, f"{short_name}_Cuts", f"{short_name}_default.txt"),
        'character_name': short_name
    }


def load_text_from_file(filename):
    """
    Загружает текст из файла.

    :param filename: Имя файла или относительный путь к файлу.
    :return: Содержимое файла в виде строки. Если файл не найден, возвращает пустую строку.
    """
    logger.info(f"Загружаю {filename}")
    try:
        # Определяем базовый путь в зависимости от того, собрано ли приложение
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)  # PyInstaller
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        filepath = os.path.join(base_path, filename)
        filepath = os.path.normpath(filepath)

        if not os.path.exists(filepath):
            logger.info(f"Файл не найден: {filepath}")
            return ""

        with open(filepath, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        logger.info(f"Ошибка при чтении файла {filename}: {e}")
        return ""


def get_resource_path(filename):
    """
    Возвращает полный путь к файлу рядом с текущим модулем.

    :param filename: Имя файла или относительный путь к файлу.
    :return: Полный путь к файлу или None, если базовая папка не найдена.
    """
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(__file__)

    promts_path = os.path.join(base_path)

    if not os.path.isdir(promts_path):
        logger.info(f"Ошибка: Папка не найдена по пути: {promts_path}")
        return None

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
    file_name = "combined_messages.json"
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
        len(self.tokenizer.encode(msg["content"])) for msg in messages
        if isinstance(msg, dict) and "content" in msg
    )


def SH(s, placeholder="***", percent=0.20):
    """
    Сокращает строку, оставляя % символов в начале и % в конце.
    Средняя часть заменяется на placeholder.
    """
    if not s:
        return s

    length = len(s)
    visible_length = max(1, int(length * percent))  # Минимум 1 символ

    start = s[:visible_length]
    end = s[-visible_length:]
    return f"{start}{placeholder}{end}"


def shift_chars(s, shift):
    """
    Сдвигает все символы в строке на заданное число.
    :param s: Исходная строка.
    :param shift: Число, на которое нужно сдвинуть символы.
    :return: Зашифрованная или расшифрованная строка.
    """
    result = []
    for char in s:
        new_char = chr(ord(char) + shift)
        result.append(new_char)
    return ''.join(result)


# =========================== Детекция языка для TTS ============================

SAFE_PUNCT = ".,-:;!?\""

# Максимально расширенная карта "скрипт → предполагаемый язык".
# Для LATIN осознанно НЕ выбираем язык — для латиницы лучше использовать статистику.
SCRIPT_TO_LANG = {
    "CYRILLIC": "ru",
    "ARABIC": "ar",
    "HEBREW": "he",
    "GREEK": "el",
    "ARMENIAN": "hy",
    "GEORGIAN": "ka",
    "DEVANAGARI": "hi",
    "BENGALI": "bn",
    "GURMUKHI": "pa",   # панджаби
    "GUJARATI": "gu",
    "ORIYA": "or",      # одия
    "TAMIL": "ta",
    "TELUGU": "te",
    "KANNADA": "kn",
    "MALAYALAM": "ml",
    "SINHALA": "si",
    "THAI": "th",
    "LAO": "lo",
    "KHMER": "km",
    "TIBETAN": "bo",
    "MONGOLIAN": "mn",
    "ETHIOPIC": "am",   # амхарский
    "CJK": "zh",        # Han (кандзи/ханзи)
    "HIRAGANA": "ja",
    "KATAKANA": "ja",
    "HANGUL": "ko",
    "BOPOMOFO": "zh",
    # "LATIN": "en",    # не доверяем на 100% латинице — пусть решит модель
}

# Нормализация кодов языка (из langdetect → для num2words и общего использования)
LANG_NORMALIZATION = {
    "zh-cn": "zh",
    "zh-tw": "zh",
    "pt-br": "pt_BR",
    "pt-pt": "pt",
    "iw": "he",   # устаревшее обозначение иврита
    "in": "id",   # индонезийский
}

def _script_token(ch: str) -> str | None:
    """Возвращает маркер скрипта по символу (упрощённо, по имени в Unicode)."""
    try:
        name = ud.name(ch)
    except ValueError:
        return None
    # Берём первый токен: 'CYRILLIC CAPITAL LETTER A' -> 'CYRILLIC'
    token = name.split()[0]
    # Объединяем все 'CJK UNIFIED IDEOGRAPH-xxxx' в 'CJK'
    if token == "CJK":
        return "CJK"
    return token


def guess_lang_by_script(text: str, threshold: float = 0.6) -> str | None:
    """
    Пытается угадать язык по доминирующему юникод-скрипту.
    Возвращает ISO-код языка или None, если уверенности недостаточно.
    """
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return None

    scripts = [_script_token(ch) for ch in letters]
    scripts = [s for s in scripts if s]  # убираем None
    if not scripts:
        return None

    counts = Counter(scripts)
    script, cnt = counts.most_common(1)[0]
    share = cnt / len(scripts)

    # Спец. правила для CJK/JA/KR
    if counts.get("HIRAGANA", 0) + counts.get("KATAKANA", 0) >= max(3, 0.1 * len(scripts)):
        return "ja"
    if counts.get("HANGUL", 0) >= max(3, 0.1 * len(scripts)):
        return "ko"
    if counts.get("CJK", 0) >= max(3, 0.2 * len(scripts)):
        # Если CJK без явной хираганы/катаканы — скорее китайский
        return "zh"

    if share >= threshold:
        # Не доверяем латинице — много языков делят один скрипт.
        if script == "LATIN":
            return None
        return SCRIPT_TO_LANG.get(script)

    return None


def guess_lang_statistically(text: str) -> str | None:
    """
    Определяет язык с помощью langdetect (если установлен).
    Лучше работает на латинице и смешанных языках.
    """
    if not LANGDETECT_AVAILABLE:
        return None
    sample = text.strip()
    # langdetect плохо на очень коротких строках
    if len(sample) < 20:
        return None
    sample = sample[:800]  # ограничим для скорости
    try:
        code = detect(sample)  # 'ru', 'en', 'fr', 'zh-cn', ...
        return code
    except LangDetectException:
        return None
    except Exception as e:
        logger.debug(f"langdetect error: {e}")
        return None


def normalize_lang_code(code: str | None) -> str | None:
    if not code:
        return None
    c = code.lower()
    c = LANG_NORMALIZATION.get(c, c)
    # num2words чаще ожидает базовые коды ('en', 'ru', 'fr', 'pt', 'pt_BR', ...)
    return c


def detect_language(text: str) -> str | None:
    """
    Комбинирует две стратегии:
      1) эвристика по скриптам (для не-латиницы, CJK, арабской графики и т.п.);
      2) статистическая модель (langdetect) — для латиницы и смешанных текстов.
    Возвращает ISO-код языка (возможно нормализованный) или None.
    """
    lang = guess_lang_by_script(text)
    if lang:
        return normalize_lang_code(lang)
    lang = guess_lang_statistically(text)
    return normalize_lang_code(lang)


# ===================== Числа → слова с учётом языка ===========================

def replace_numbers_with_words(text: str, lang: str | None = None) -> str:
    """
    Заменяет числа на слова с учётом языка (если поддержан).
    Безопасный фолбэк на английский при NotImplementedError.
    """
    # Пытаемся нормализовать код языка сразу
    lang = normalize_lang_code(lang) or "en"

    cache: dict[str, str] = {}

    def _repl(m: re.Match) -> str:
        token = m.group(0)
        if token in cache:
            return cache[token]
        try:
            # int() съест лидирующие нули, минусы учтём
            num = int(token)
            try:
                word = num2words(num, lang=lang)
            except NotImplementedError:
                # Фолбэк на английский
                word = num2words(num, lang="en")
                if lang != "en":
                    logger.debug(f"num2words: язык '{lang}' не поддержан, используем 'en'.")
        except Exception:
            # На случай чего-то странного — вернём исходное
            word = token
        cache[token] = word
        return word

    # Меняем только целые числа (знаки минуса поддержаны)
    return re.sub(r"[-+]?\d+", _repl, text)


# ========================== Основная очистка для TTS ==========================

def process_text_to_voice(text_to_speak: str) -> str:
    """
    Очищает текст перед TTS:
      1) удаляет HTML/markup;
      2) определяет язык (эвристика по скриптам + langdetect);
      3) переводит числа в слова на соответствующем языке (если поддержан);
      4) оставляет только буквы Юникода, пробелы и знаки из SAFE_PUNCT;
      5) схлопывает пробелы; при пустом результате возвращает '...'.
    """
    if not isinstance(text_to_speak, str):
        logger.warning(
            "process_text_to_voice expected str, got %s. Converting.", type(text_to_speak)
        )
        text_to_speak = str(text_to_speak)

    # 1) Удаляем HTML/markup
    clean_text = re.sub(r"<[^>]+>.*?</[^>]+>", "", text_to_speak, flags=re.DOTALL)
    clean_text = re.sub(r"<[^>]+>", "", clean_text)

    # 2) Определяем язык
    lang_code = detect_language(clean_text)
    if lang_code:
        logger.debug(f"Detected language: {lang_code}")
    else:
        logger.debug("Language detection failed, using default 'en' for numbers.")

    # 3) Цифры → слова
    clean_text = replace_numbers_with_words(clean_text, lang=lang_code or "en")

    # 4) Фильтрация символов: оставляем буквы, пробелы и безопасные знаки
    filtered_chars = [
        ch if ch.isalpha() or ch.isspace() or ch in SAFE_PUNCT else " "
        for ch in clean_text
    ]
    clean_text = "".join(filtered_chars)

    # 5) Схлопываем пробелы и обрезаем
    clean_text = re.sub(r"\s{2,}", " ", clean_text).strip()

    if not clean_text:
        clean_text = "..."
        logger.info("TTS text was empty after cleaning, using default '...'")

    return clean_text

def render_qss(template: str, variables: dict) -> str:
    """
    Рендерит QSS/CSS-шаблон, заменяя плейсхолдеры вида {name} на значения из словаря variables.
    - Не трогает обычные блочные скобки QSS ({ ... }), т.к. матчится только на {слово}.
    - Если ключ не найден в словаре — плейсхолдер остаётся без изменений.

    :param template: Строка QSS/СSS с плейсхолдерами {var}.
    :param variables: Словарь с заменами.
    :return: Рендеренная строка.
    """
    if not isinstance(template, str):
        template = str(template)
    if not isinstance(variables, dict):
        raise TypeError("variables must be a dict")

    pattern = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

    def _repl(m: re.Match) -> str:
        key = m.group(1)
        return str(variables.get(key, m.group(0)))

    return pattern.sub(_repl, template)