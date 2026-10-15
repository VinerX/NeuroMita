from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from localization import TrStr


class TrStrTests(unittest.TestCase):
    def test_deepcopy_preserves_translation_sources(self):
        value = TrStr("English", "Русский", "English")

        cloned = copy.deepcopy(value)

        self.assertIs(cloned, value)
        self.assertEqual(cloned.tr_ru, "Русский")
        self.assertEqual(cloned.tr_en, "English")

    def test_repeat_restore_prompt_is_translated_in_every_bundled_locale(self):
        locale_dir = Path(__file__).resolve().parents[2] / "localization" / "locales"
        keys = (
            "Возможно, уже восстановлено",
            "Похоже, этот архив уже восстанавливали. Повторить восстановление?",
        )
        for locale_path in locale_dir.glob("*.json"):
            if locale_path.name.startswith("_"):
                continue
            catalog = json.loads(locale_path.read_text(encoding="utf-8"))
            for key in keys:
                self.assertTrue(
                    catalog.get(key), f"{locale_path.name}: missing {key!r}"
                )

    def test_remote_voice_section_is_translated_in_every_bundled_locale(self):
        locale_dir = Path(__file__).resolve().parents[2] / "localization" / "locales"
        keys = (
            "Где искать голос? Каталог Fish Audio",
            "Общий голос",
            "Голоса персонажей",
            "Профиль сохранён.",
            "Проверка пройдена. Озвучка воспроизведена.",
            "Привет! Я Мита. Давай проверим, как звучит мой голос.",
            "API-ключ не принят",
            "ID голоса должен содержать 32 шестнадцатеричных символа.",
            "Выбрана бесплатная модель. Остальные модели платные.",
            "Выбрана платная модель. Озвучка расходует баланс API.",
            "Проверка отправляет текст провайдеру. Платные модели расходуют баланс API.",
            "недостаточно средств на балансе API; пополните баланс или выберите s2.1-pro-free",
            "Fish Audio: {reason} (HTTP {status}).",
        )
        for locale_path in locale_dir.glob("*.json"):
            if locale_path.name.startswith("_"):
                continue
            catalog = json.loads(locale_path.read_text(encoding="utf-8"))
            for key in keys:
                self.assertTrue(
                    catalog.get(key), f"{locale_path.name}: missing {key!r}"
                )
            self.assertIn("{reason}", catalog[keys[-1]])
            self.assertIn("{status}", catalog[keys[-1]])

    def test_new_settings_text_is_translated_in_every_supported_language(self):
        from string import Formatter
        from localization import BASE_LANGUAGE, LANGUAGE_DISPLAY_NAMES

        locale_dir = Path(__file__).resolve().parents[2] / "localization" / "locales"
        keys = (
            "Укажите URL проверки. Без него можно пользоваться API и проверять ответы в песочнице.",
            "Укажите корректный HTTP или HTTPS URL с адресом сервера.",
            "Не удалось подготовить HTTP-запрос. Проверьте выбранный формат API.",
            "Подключение успешно",
            "Сервер ответил, но вернул не JSON. Проверьте URL проверки — обычно это endpoint списка моделей.",
            "Найдено моделей: {count}",
            "Стандартная обработка сообщений",
            "Шагов обработки сообщений: {count}",
            "Некорректный URL проверки",
            "Проверка не настроена",
            "Укажите HTTP или HTTPS URL с адресом сервера, например http://localhost:1234/v1/models.",
            "URL проверки (необязательно)",
            "GET-адрес для проверки подключения и загрузки списка моделей. Если его нет, проверьте ответы в песочнице.",
            "Формат API и обработка сообщений перед отправкой.",
            "api_id из my.telegram.org",
            "api_hash из my.telegram.org",
            "Номер телефона",
            "HTTPS: необязательная s",
            "Введите s для HTTPS или оставьте пустым для HTTP.",
            "Адрес сервера",
            "Обработка сообщений",
            "Шаги выполняются сверху вниз перед отправкой сообщений.",
            "Дополнительная обработка отключена. Сообщения отправляются без преобразований.",
            "Порядок обработки · {count}",
            "Объединить системные сообщения",
            "Объединяет последовательные системные сообщения в начале диалога.",
            "Завершить диалог сообщением пользователя",
            "Добавляет сообщение «.», если последнее сообщение принадлежит ассистенту.",
            "Перенести системный контекст",
            "Добавляет системные сообщения в начало первого сообщения пользователя.",
            "Чередовать роли в диалоге",
            "Объединяет соседние сообщения одной роли: пользователь и ассистент чередуются.",
            "Сервер отклонил запрос. Проверьте адрес проверки и выбранный формат API.",
            "Сервер не принял авторизацию. Проверьте API-ключ и его срок действия.",
            "Сервер запретил доступ. Проверьте права API-ключа и доступность сервиса для вашей учётной записи.",
            "Адрес проверки не найден. Проверьте URL: для списка моделей обычно используется /v1/models.",
            "Адрес проверки не поддерживает GET-запрос. Укажите endpoint списка моделей вместо endpoint генерации.",
            "Сервер прекратил ожидание запроса. Повторите проверку; если ошибка остаётся, проверьте соединение и нагрузку сервера.",
            "Превышен лимит запросов или квота API. Повторите позже и проверьте лимиты и баланс у провайдера.",
            "На сервере произошла внутренняя ошибка. Повторите позже; для локального сервера проверьте его журнал ошибок.",
            "Шлюз или прокси получил некорректный ответ от сервера. Повторите позже; если используете прокси, проверьте его подключение к API.",
            "Сервис временно недоступен. Он может быть перегружен или на обслуживании. Повторите проверку позже; для локального API проверьте, что сервер запущен и готов принимать запросы.",
            "Шлюз или прокси не дождался ответа сервера. Повторите позже и проверьте доступность API за прокси.",
            "Сервер отклонил запрос. Проверьте адрес, авторизацию и выбранный формат API.",
            "Сервер не смог обработать запрос. Повторите позже; для локального API проверьте журнал сервера.",
            "Сервер вернул неожиданный ответ. Проверьте адрес проверки и выбранный формат API.",
            "Потоковые ответы",
            "Вызов инструментов",
            "Структурированные ответы",
            "Для подключения заполните API ID, API Hash и номер вашего Telegram-аккаунта в международном формате.",
            "Получить API ID и Hash",
            "Инструкция Telegram",
            "Добавить шаг",
            "Переместить выше",
            "Переместить ниже",
            "Удалить шаг",
            "Общие настройки",
            "Базовые параметры интерфейса, приватности, памяти и языка.",
            "Выбор языка интерфейса и подключение кастомных переводов.",
            "Подключение к моделям",
            "Провайдеры, пресеты, ключи и параметры генерации ответов.",
            "Профили, шаблоны поведения и история выбранного персонажа.",
            "Голоса персонажей, подключение и воспроизведение.",
            "Устройства ввода, распознавание речи и проверка микрофона.",
            "Аппаратный профиль, модели, режим workers и обслуживание AI-окружений.",
            "Параметры подключения и обмена данными с игрой.",
            "Модели и поведение",
            "Управление логикой ответа, памятью, мышлением и RAG.",
            "Изображения и камера",
            "Захват экрана, камера, описание изображений и хранение.",
            "Управление обновлением клиента и связанных компонентов.",
            "Сохранение, оценка и экспорт данных для дообучения.",
        )
        formatter = Formatter()
        for language in LANGUAGE_DISPLAY_NAMES:
            if language == BASE_LANGUAGE:
                continue
            locale_path = locale_dir / f"{language.lower()}.json"
            catalog = json.loads(locale_path.read_text(encoding="utf-8"))
            for key in keys:
                with self.subTest(language=language, key=key):
                    translated = catalog.get(key)
                    self.assertIsInstance(translated, str)
                    self.assertTrue(
                        translated.strip(), f"{locale_path.name}: missing {key!r}"
                    )
                    source_fields = {
                        field for _, field, _, _ in formatter.parse(key) if field
                    }
                    translated_fields = {
                        field for _, field, _, _ in formatter.parse(translated) if field
                    }
                    self.assertEqual(source_fields, translated_fields)


if __name__ == "__main__":
    unittest.main()
