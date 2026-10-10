"""ASR language capabilities shipped in the app; no runtime/ML dependencies."""

# GigaAM v2/v3 scope: https://github.com/salute-developers/GigaAM#gigaam-overview
# Primary Whisper source (verified 2026-10-09):
# https://raw.githubusercontent.com/openai/whisper/main/whisper/tokenizer.py
# All 100 codes also match lang_to_id in generation_config.json for
# https://huggingface.co/openai/whisper-large-v3
# https://huggingface.co/openai/whisper-large-v3-turbo
# https://huggingface.co/onnx-community/whisper-large-v3-turbo-onnx
_WHISPER_LANGUAGE_SOURCES = (
    ("en", ("Английский", "English")),
    ("zh", ("Китайский", "Chinese")),
    ("de", ("Немецкий", "German")),
    ("es", ("Испанский", "Spanish")),
    ("ru", ("Русский", "Russian")),
    ("ko", ("Корейский", "Korean")),
    ("fr", ("Французский", "French")),
    ("ja", ("Японский", "Japanese")),
    ("pt", ("Португальский", "Portuguese")),
    ("tr", ("Турецкий", "Turkish")),
    ("pl", ("Польский", "Polish")),
    ("ca", ("Каталанский", "Catalan")),
    ("nl", ("Нидерландский", "Dutch")),
    ("ar", ("Арабский", "Arabic")),
    ("sv", ("Шведский", "Swedish")),
    ("it", ("Итальянский", "Italian")),
    ("id", ("Индонезийский", "Indonesian")),
    ("hi", ("Хинди", "Hindi")),
    ("fi", ("Финский", "Finnish")),
    ("vi", ("Вьетнамский", "Vietnamese")),
    ("he", ("Иврит", "Hebrew")),
    ("uk", ("Украинский", "Ukrainian")),
    ("el", ("Греческий", "Greek")),
    ("ms", ("Малайский", "Malay")),
    ("cs", ("Чешский", "Czech")),
    ("ro", ("Румынский", "Romanian")),
    ("da", ("Датский", "Danish")),
    ("hu", ("Венгерский", "Hungarian")),
    ("ta", ("Тамильский", "Tamil")),
    ("no", ("Норвежский", "Norwegian")),
    ("th", ("Тайский", "Thai")),
    ("ur", ("Урду", "Urdu")),
    ("hr", ("Хорватский", "Croatian")),
    ("bg", ("Болгарский", "Bulgarian")),
    ("lt", ("Литовский", "Lithuanian")),
    ("la", ("Латынь", "Latin")),
    ("mi", ("Маори", "Maori")),
    ("ml", ("Малаялам", "Malayalam")),
    ("cy", ("Валлийский", "Welsh")),
    ("sk", ("Словацкий", "Slovak")),
    ("te", ("Телугу", "Telugu")),
    ("fa", ("Персидский", "Persian")),
    ("lv", ("Латышский", "Latvian")),
    ("bn", ("Бенгальский", "Bengali")),
    ("sr", ("Сербский", "Serbian")),
    ("az", ("Азербайджанский", "Azerbaijani")),
    ("sl", ("Словенский", "Slovenian")),
    ("kn", ("Каннада", "Kannada")),
    ("et", ("Эстонский", "Estonian")),
    ("mk", ("Македонский", "Macedonian")),
    ("br", ("Бретонский", "Breton")),
    ("eu", ("Баскский", "Basque")),
    ("is", ("Исландский", "Icelandic")),
    ("hy", ("Армянский", "Armenian")),
    ("ne", ("Непальский", "Nepali")),
    ("mn", ("Монгольский", "Mongolian")),
    ("bs", ("Боснийский", "Bosnian")),
    ("kk", ("Казахский", "Kazakh")),
    ("sq", ("Албанский", "Albanian")),
    ("sw", ("Суахили", "Swahili")),
    ("gl", ("Галисийский", "Galician")),
    ("mr", ("Маратхи", "Marathi")),
    ("pa", ("Панджаби", "Punjabi")),
    ("si", ("Сингальский", "Sinhala")),
    ("km", ("Кхмерский", "Khmer")),
    ("sn", ("Шона", "Shona")),
    ("yo", ("Йоруба", "Yoruba")),
    ("so", ("Сомали", "Somali")),
    ("af", ("Африкаанс", "Afrikaans")),
    ("oc", ("Окситанский", "Occitan")),
    ("ka", ("Грузинский", "Georgian")),
    ("be", ("Белорусский", "Belarusian")),
    ("tg", ("Таджикский", "Tajik")),
    ("sd", ("Синдхи", "Sindhi")),
    ("gu", ("Гуджарати", "Gujarati")),
    ("am", ("Амхарский", "Amharic")),
    ("yi", ("Идиш", "Yiddish")),
    ("lo", ("Лаосский", "Lao")),
    ("uz", ("Узбекский", "Uzbek")),
    ("fo", ("Фарерский", "Faroese")),
    ("ht", ("Гаитянский креольский", "Haitian Creole")),
    ("ps", ("Пушту", "Pashto")),
    ("tk", ("Туркменский", "Turkmen")),
    ("nn", ("Нюнорск", "Nynorsk")),
    ("mt", ("Мальтийский", "Maltese")),
    ("sa", ("Санскрит", "Sanskrit")),
    ("lb", ("Люксембургский", "Luxembourgish")),
    ("my", ("Бирманский", "Myanmar")),
    ("bo", ("Тибетский", "Tibetan")),
    ("tl", ("Тагальский", "Tagalog")),
    ("mg", ("Малагасийский", "Malagasy")),
    ("as", ("Ассамский", "Assamese")),
    ("tt", ("Татарский", "Tatar")),
    ("haw", ("Гавайский", "Hawaiian")),
    ("ln", ("Лингала", "Lingala")),
    ("ha", ("Хауса", "Hausa")),
    ("ba", ("Башкирский", "Bashkir")),
    ("jw", ("Яванский", "Javanese")),
    ("su", ("Сунданский", "Sundanese")),
    ("yue", ("Кантонский", "Cantonese")),
)

# Google Web Speech demo catalogue (verified 2026-10-10), plus legacy zh-CN:
# https://www.google.com/intl/en/chrome/demos/speech.html
_GOOGLE_LANGUAGE_SOURCES = (
    ("ru-RU", ("Русский", "Russian")),
    ("uk-UA", ("Украинский", "Ukrainian")),
    ("en-US", ("Английский (США)", "English (US)")),
    ("en-GB", ("Английский (Великобритания)", "English (UK)")),
    ("de-DE", ("Немецкий", "German")),
    ("fr-FR", ("Французский", "French")),
    ("es-ES", ("Испанский", "Spanish")),
    ("ja-JP", ("Японский", "Japanese")),
    ("zh-CN", ("Китайский", "Chinese")),
    ("af-ZA", ("Африкаанс", "Afrikaans")),
    ("am-ET", ("Амхарский", "Amharic")),
    ("az-AZ", ("Азербайджанский", "Azerbaijani")),
    ("bn-BD", ("Бенгальский (Бангладеш)", "Bengali (Bangladesh)")),
    ("bn-IN", ("Бенгальский (Индия)", "Bengali (India)")),
    ("id-ID", ("Индонезийский", "Indonesian")),
    ("ms-MY", ("Малайский", "Malay")),
    ("ca-ES", ("Каталанский", "Catalan")),
    ("cs-CZ", ("Чешский", "Czech")),
    ("da-DK", ("Датский", "Danish")),
    ("en-AU", ("Английский (Австралия)", "English (Australia)")),
    ("en-CA", ("Английский (Канада)", "English (Canada)")),
    ("en-IN", ("Английский (Индия)", "English (India)")),
    ("en-KE", ("Английский (Кения)", "English (Kenya)")),
    ("en-TZ", ("Английский (Танзания)", "English (Tanzania)")),
    ("en-GH", ("Английский (Гана)", "English (Ghana)")),
    ("en-NZ", ("Английский (Новая Зеландия)", "English (New Zealand)")),
    ("en-NG", ("Английский (Нигерия)", "English (Nigeria)")),
    ("en-ZA", ("Английский (ЮАР)", "English (South Africa)")),
    ("en-PH", ("Английский (Филиппины)", "English (Philippines)")),
    ("es-AR", ("Испанский (Аргентина)", "Spanish (Argentina)")),
    ("es-BO", ("Испанский (Боливия)", "Spanish (Bolivia)")),
    ("es-CL", ("Испанский (Чили)", "Spanish (Chile)")),
    ("es-CO", ("Испанский (Колумбия)", "Spanish (Colombia)")),
    ("es-CR", ("Испанский (Коста-Рика)", "Spanish (Costa Rica)")),
    ("es-EC", ("Испанский (Эквадор)", "Spanish (Ecuador)")),
    ("es-SV", ("Испанский (Сальвадор)", "Spanish (El Salvador)")),
    ("es-US", ("Испанский (США)", "Spanish (US)")),
    ("es-GT", ("Испанский (Гватемала)", "Spanish (Guatemala)")),
    ("es-HN", ("Испанский (Гондурас)", "Spanish (Honduras)")),
    ("es-MX", ("Испанский (Мексика)", "Spanish (Mexico)")),
    ("es-NI", ("Испанский (Никарагуа)", "Spanish (Nicaragua)")),
    ("es-PA", ("Испанский (Панама)", "Spanish (Panama)")),
    ("es-PY", ("Испанский (Парагвай)", "Spanish (Paraguay)")),
    ("es-PE", ("Испанский (Перу)", "Spanish (Peru)")),
    ("es-PR", ("Испанский (Пуэрто-Рико)", "Spanish (Puerto Rico)")),
    ("es-DO", ("Испанский (Доминиканская Республика)", "Spanish (Dominican Republic)")),
    ("es-UY", ("Испанский (Уругвай)", "Spanish (Uruguay)")),
    ("es-VE", ("Испанский (Венесуэла)", "Spanish (Venezuela)")),
    ("eu-ES", ("Баскский", "Basque")),
    ("fil-PH", ("Филиппинский", "Filipino")),
    ("jv-ID", ("Яванский", "Javanese")),
    ("gl-ES", ("Галисийский", "Galician")),
    ("gu-IN", ("Гуджарати", "Gujarati")),
    ("hr-HR", ("Хорватский", "Croatian")),
    ("zu-ZA", ("Зулу", "Zulu")),
    ("is-IS", ("Исландский", "Icelandic")),
    ("it-IT", ("Итальянский (Италия)", "Italian (Italy)")),
    ("it-CH", ("Итальянский (Швейцария)", "Italian (Switzerland)")),
    ("kn-IN", ("Каннада", "Kannada")),
    ("km-KH", ("Кхмерский", "Khmer")),
    ("lv-LV", ("Латышский", "Latvian")),
    ("lt-LT", ("Литовский", "Lithuanian")),
    ("ml-IN", ("Малаялам", "Malayalam")),
    ("mr-IN", ("Маратхи", "Marathi")),
    ("hu-HU", ("Венгерский", "Hungarian")),
    ("lo-LA", ("Лаосский", "Lao")),
    ("nl-NL", ("Нидерландский", "Dutch")),
    ("ne-NP", ("Непальский", "Nepali")),
    ("nb-NO", ("Норвежский букмол", "Norwegian Bokmal")),
    ("pl-PL", ("Польский", "Polish")),
    ("pt-BR", ("Португальский (Бразилия)", "Portuguese (Brazil)")),
    ("pt-PT", ("Португальский (Португалия)", "Portuguese (Portugal)")),
    ("ro-RO", ("Румынский", "Romanian")),
    ("si-LK", ("Сингальский", "Sinhala")),
    ("sl-SI", ("Словенский", "Slovenian")),
    ("su-ID", ("Сунданский", "Sundanese")),
    ("sk-SK", ("Словацкий", "Slovak")),
    ("fi-FI", ("Финский", "Finnish")),
    ("sv-SE", ("Шведский", "Swedish")),
    ("sw-TZ", ("Суахили (Танзания)", "Swahili (Tanzania)")),
    ("sw-KE", ("Суахили (Кения)", "Swahili (Kenya)")),
    ("ka-GE", ("Грузинский", "Georgian")),
    ("hy-AM", ("Армянский", "Armenian")),
    ("ta-IN", ("Тамильский (Индия)", "Tamil (India)")),
    ("ta-SG", ("Тамильский (Сингапур)", "Tamil (Singapore)")),
    ("ta-LK", ("Тамильский (Шри-Ланка)", "Tamil (Sri Lanka)")),
    ("ta-MY", ("Тамильский (Малайзия)", "Tamil (Malaysia)")),
    ("te-IN", ("Телугу", "Telugu")),
    ("vi-VN", ("Вьетнамский", "Vietnamese")),
    ("tr-TR", ("Турецкий", "Turkish")),
    ("ur-PK", ("Урду (Пакистан)", "Urdu (Pakistan)")),
    ("ur-IN", ("Урду (Индия)", "Urdu (India)")),
    ("el-GR", ("Греческий", "Greek")),
    ("bg-BG", ("Болгарский", "Bulgarian")),
    ("sr-RS", ("Сербский", "Serbian")),
    ("ko-KR", ("Корейский", "Korean")),
    ("cmn-Hans-CN", ("Севернокитайский (материковый Китай)", "Mandarin (Mainland China)")),
    ("cmn-Hans-HK", ("Севернокитайский (Гонконг)", "Mandarin (Hong Kong)")),
    ("cmn-Hant-TW", ("Севернокитайский (Тайвань)", "Mandarin (Taiwan)")),
    ("yue-Hant-HK", ("Кантонский (Гонконг)", "Cantonese (Hong Kong)")),
    ("hi-IN", ("Хинди", "Hindi")),
    ("th-TH", ("Тайский", "Thai")),
)

_GOOGLE_PRIMARY_CODES = (
    "ru-RU", "uk-UA", "en-US", "de-DE", "fr-FR", "es-ES",
    "it-IT", "pt-BR", "ja-JP", "zh-CN", "ko-KR",
)
_WHISPER_PRIMARY_CODES = tuple(code.split("-")[0] for code in _GOOGLE_PRIMARY_CODES)

_HELP_SOURCES = {
    "google": ("Требуется интернет.", "Internet connection required."),
    "fixed": ("Эта модель распознаёт только русский язык.", "This model recognizes Russian only."),
    "whisper": ("Поддерживается автоопределение языка.", "Automatic language detection is supported."),
    "auto": ("Автоопределение", "Automatic detection"),
}

def _primary_first(languages: tuple, primary_codes: tuple) -> tuple:
    by_code = {row[0]: row for row in languages}
    return tuple(by_code[code] for code in primary_codes) + tuple(
        row for row in languages if row[0] not in primary_codes
    )


def _languages(engine_id: str) -> tuple:
    if engine_id == "google":
        return _primary_first(_GOOGLE_LANGUAGE_SOURCES, _GOOGLE_PRIMARY_CODES)
    if engine_id in ("whisper", "whisper_onnx"):
        return _primary_first(_WHISPER_LANGUAGE_SOURCES, _WHISPER_PRIMARY_CODES)
    if engine_id in ("gigaam", "gigaam_onnx"):
        return (("ru", ("Русский", "Russian")),)
    raise ValueError(f"Unknown ASR engine: {engine_id!r}")


def asr_language_names(engine_id: str) -> list[str]:
    return [english for _, (_, english) in _languages(engine_id)]


def asr_language_field(engine_id: str) -> dict:
    languages = _languages(engine_id)
    options = [code for code, _ in languages]
    sources = dict(languages)
    labels = {code: f"{russian} ({code})" for code, (russian, _) in languages}
    fixed = engine_id in ("gigaam", "gigaam_onnx")
    if engine_id == "google":
        help_ru, help_en = _HELP_SOURCES["google"]
    elif fixed:
        help_ru, help_en = _HELP_SOURCES["fixed"]
    else:
        options.insert(0, "auto")
        sources["auto"] = _HELP_SOURCES["auto"]
        labels["auto"] = "Автоопределение (auto)"
        help_ru, help_en = _HELP_SOURCES["whisper"]
    return {
        "key": "language", "label_ru": "Язык", "label_en": "Language",
        "type": "combobox", "options": options, "option_labels": labels,
        "option_label_sources": sources, "option_label_format": "{label} ({value})",
        "default": "ru-RU" if engine_id == "google" else "ru",
        "enabled": not fixed, "help_ru": help_ru, "help_en": help_en,
    }
