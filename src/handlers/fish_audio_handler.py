"""Fish Audio cloud TTS. Credentials stay outside shared/exported settings."""
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import wave
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from core.app_paths import base_dir, settings_path

MODELS = ("s2.1-pro", "s2-pro", "s1", "s2.1-pro-free", "drama-3-preview")
ENDPOINT = "https://api.fish.audio/v1/tts"


def voice_id(value: str) -> str:
    value = str(value or "").strip()
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.hostname not in {"fish.audio", "www.fish.audio"}:
            raise ValueError("Нужна ссылка на голос fish.audio или его ID.")
        value = next((p for p in parsed.path.split("/") if re.fullmatch(r"[a-fA-F0-9]{32}", p)), "")
    if not re.fullmatch(r"[a-fA-F0-9]{32}", value):
        raise ValueError("Укажите ID голоса Fish Audio (32 символа) или ссылку на его страницу.")
    return value.lower()


def load_config() -> dict:
    try:
        data = json.loads(settings_path("fish_audio.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as exc:
        raise ValueError("Не удалось прочитать Settings/fish_audio.json.") from exc
    if not isinstance(data, dict):
        raise ValueError("Неверный формат Settings/fish_audio.json.")
    return {"api_key": "", "voice_id": "", "model": "s2.1-pro", "speed": 1.0, **data}


def save_config(config: dict) -> None:
    path = settings_path("fish_audio.json", create_parent=True)
    fd, name = tempfile.mkstemp(prefix=".fish-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(config, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def validate_config(config: dict) -> dict:
    result = dict(config)
    result["api_key"] = str(result.get("api_key") or "").strip()
    if not result["api_key"]:
        raise ValueError("Введите API-ключ Fish Audio в настройках озвучки.")
    result["voice_id"] = voice_id(result.get("voice_id", ""))
    if result.get("model") not in MODELS:
        raise ValueError("Выберите поддерживаемую модель Fish Audio.")
    result["speed"] = float(result.get("speed", 1.0))
    if not 0.5 <= result["speed"] <= 2.0:
        raise ValueError("Скорость должна быть от 0.5 до 2.0.")
    return result


def is_configured() -> bool:
    try:
        validate_config(load_config())
        return True
    except (ValueError, TypeError):
        return False


FISH_AUDIO_TAGS = {
    # Basic emotions (24 expressions)
    "happy", "sad", "angry", "excited", "calm", "nervous", "confident",
    "surprised", "satisfied", "delighted", "scared", "worried", "upset", "frustrated",
    "depressed", "empathetic", "embarrassed", "disgusted", "moved",
    "proud", "relaxed", "grateful", "curious", "sarcastic",
    # Advanced emotions (25 expressions)
    "disdainful", "unhappy", "anxious", "hysterical", "indifferent",
    "uncertain", "doubtful", "confused", "disappointed", "regretful",
    "guilty", "ashamed", "jealous", "envious", "hopeful", "optimistic",
    "pessimistic", "nostalgic", "lonely", "bored", "contemptuous",
    "sympathetic", "compassionate", "determined", "resigned",
    # Tone markers (6 expressions)
    "in a hurry tone", "shouting", "screaming", "whispering", "soft tone", "emphasis",
    # Audio effects & vocal sounds (16 expressions)
    "laughing", "chuckling", "sobbing", "crying loudly", "sighing",
    "groaning", "panting", "gasping", "yawning", "snoring", "clear throat",
    "break", "long-break", "crowd laughing", "background laughter", "audience laughing",
}

NEUROMITA_EMOTION_TO_FISH_TAG = {
    "smile": "happy",
    "smileobvi": "sarcastic",
    "smileteeth": "excited",
    "smilestrange": "curious",
    "smiletonque": "delighted",
    "smilecringe": "embarrassed",
    "happy": "happy",
    "laugh": "laughing",
    "sad": "sad",
    "cry": "sobbing",
    "depressed": "depressed",
    "moved": "moved",
    "sigh": "sighing",
    "angry": "angry",
    "discontent": "frustrated",
    "frustrated": "frustrated",
    "upset": "upset",
    "surprise": "surprised",
    "surpriseo": "surprised",
    "shock": "surprised",
    "surprised": "surprised",
    "gasp": "gasping",
    "shy": "nervous",
    "nervous": "nervous",
    "scared": "scared",
    "worried": "worried",
    "suspicion": "doubtful",
    "doubt": "doubtful",
    "doubtful": "doubtful",
    "sarcasm": "sarcastic",
    "sarcastic": "sarcastic",
    "sleep": "whispering",
    "halfsleep": "soft tone",
    "calm": "calm",
    "relaxed": "relaxed",
    "whisper": "whispering",
    "whispering": "whispering",
    "arrogance": "confident",
    "confident": "confident",
    "emptiness": "indifferent",
    "bored": "bored",
    "curious": "curious",
    "excited": "excited",
    "shout": "shouting",
    "scream": "screaming",
    "quest": "curious",
    "trytoque": "curious",
    "catchquest": "curious",
    "ajar": "curious",
    "love": "soft tone",
    "flirt": "soft tone",
    "flirty": "soft tone",
    "blush": "soft tone",
    "softly": "soft tone",
    "tender": "soft tone",
    "gentle": "soft tone",
    "sob": "sobbing",
    "giggle": "chuckling",
    "snicker": "chuckling",
    "yawn": "yawning",
    "pant": "panting",
}

RUSSIAN_EMOTION_TO_FISH_TAG = {
    "радость": "happy", "радостно": "happy", "весело": "happy",
    "смех": "laughing", "смеется": "laughing", "смеётся": "laughing",
    "хихикает": "chuckling", "усмешка": "chuckling",
    "сарказм": "sarcastic", "саркастично": "sarcastic", "ирония": "sarcastic", "иронично": "sarcastic",
    "грусть": "sad", "грустно": "sad", "печально": "sad", "плач": "sobbing",
    "злость": "angry", "зло": "angry", "сердито": "angry", "гнев": "angry",
    "спокойно": "calm", "спокойствие": "calm", "уверенно": "confident",
    "удивление": "surprised", "удивленно": "surprised", "удивлённо": "surprised", "шок": "surprised",
    "страх": "scared", "испуг": "scared", "испуганно": "scared",
    "тревога": "worried", "беспокойство": "worried",
    "сомнение": "doubtful", "сомнительно": "doubtful", "подозрение": "doubtful", "подозрительно": "doubtful",
    "любопытство": "curious", "любопытно": "curious", "интерес": "curious",
    "восторг": "excited", "возбужденно": "excited", "возбуждённо": "excited",
    "шёпот": "whispering", "шепот": "whispering", "шепотом": "whispering", "шёпотом": "whispering",
    "нежно": "soft tone", "мягко": "soft tone", "мягкий тон": "soft tone", "томно": "soft tone",
    "крик": "shouting", "громко": "shouting", "вздох": "sighing", "зевок": "yawning",
    "пауза": "break", "длинная пауза": "long-break",
    "тихо": "whispering", "тихий голос": "soft tone", "нежный голос": "soft tone",
    "мягкий": "soft tone", "нежный": "soft tone",
    "улыбка": "happy", "улыбается": "happy", "с улыбкой": "happy",
    "смеясь": "laughing", "плачет": "sobbing", "вздыхает": "sighing", "зевает": "yawning",
}

TECHNICAL_TAG_REGEX = re.compile(
    r"^(?:mita\s+|(?:anim|animations|idle_animations|emotions|face_params|custom_fields|target|hint)\s*:|"
    r"(?:attitude|boredom|stress|love)\s*[+\-:=]\s*[-+]?\d)", re.I
)


def is_technical_marker(clean: str) -> bool:
    """Проверяет, является ли содержимое скобок технической командой, анимацией или кодом."""
    return bool(TECHNICAL_TAG_REGEX.search(str(clean or "")))


def resolve_fish_tag(label: str) -> str:
    """
    Нормализует имя тега (английский, русский или внутренний ID игры) в официальный тег Fish Audio.
    Возвращает пустую строку, если тег не относится к известным эмоциям/просодии.
    """
    clean = str(label or "").strip().lower().strip("[]()\"'")
    if not clean:
        return ""
    if clean in FISH_AUDIO_TAGS:
        return clean
    if clean in NEUROMITA_EMOTION_TO_FISH_TAG:
        return NEUROMITA_EMOTION_TO_FISH_TAG[clean]
    if clean in RUSSIAN_EMOTION_TO_FISH_TAG:
        return RUSSIAN_EMOTION_TO_FISH_TAG[clean]
    return ""


def strip_fish_tags(text: str) -> str:
    """
    Удаляет все теги Fish Audio ([tag], (tag)), технические маркеры и режиссёрские ремарки.
    Сохраняет естественный текст диалога и знаки препинания (тире, кавычки, тильды).
    """
    if not text or not isinstance(text, str):
        return "" if not text else str(text)

    def _replace_marker(match: re.Match) -> str:
        raw_bracket = match.group(0)
        is_square = raw_bracket.startswith("[")
        inner = (match.group(1) or match.group(2) or "").strip()
        if not inner:
            return ""
        if is_technical_marker(inner) or resolve_fish_tag(inner):
            return ""
        return raw_bracket

    cleaned = re.sub(r"\[([^\[\]\n]+)\]|\(([^()\n]+)\)", _replace_marker, text)
    cleaned = re.sub(r"\s+([.,!?:;…~»”])", r"\1", cleaned)
    cleaned = re.sub(r'([«“])\s+', r'\1', cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def resolve_fish_emotion(emotions: list | str | None) -> str:
    if not emotions:
        return ""
    if isinstance(emotions, str):
        emotions = [emotions]
    for emo in emotions:
        if not emo or not isinstance(emo, str):
            continue
        tag = resolve_fish_tag(emo)
        if tag:
            return tag
    return ""


def format_text_with_fish_emotions(segments: list, model: str = "s2.1-pro") -> str:
    """
    Преобразует сегменты диалога в речь с нативными тегами эмоций Fish Audio:
    - Для моделей S2 (s2.1-pro, s2-pro, s2.1-pro-free, etc.): [tag]
    - Для моделей S1: (tag)
    """
    if not isinstance(segments, list) or not segments:
        return ""
    parts = []
    use_parens = (model == "s1")
    for seg in segments:
        if isinstance(seg, dict):
            text = str(seg.get("text") or "").strip()
            emo_tag = resolve_fish_emotion(seg.get("emotions"))
        elif isinstance(seg, str):
            text = seg.strip()
            emo_tag = ""
        else:
            continue
        if not text:
            continue
        from utils import extract_clean_dialogue_text
        text = extract_clean_dialogue_text(text)
        if not text:
            continue
        # Срезаем кавычки в начале сегмента, чтобы они не склеивались с тегом эмоции
        text = re.sub(r'^[«"“\']+\s*', '', text)
        text = re.sub(r'\s*[»"”\']+$', '', text)
        if emo_tag:
            prefix = f"({emo_tag})" if use_parens else f"[{emo_tag}]"
            # Если сегмент уже начинается с любого тега эмоции, не дублируем
            if not re.match(r"^\s*(?:\[[^\]]+\]|\([^)]+\))", text):
                parts.append(f"{prefix} {text}")
            else:
                parts.append(text)
        else:
            parts.append(text)
    return " ".join(parts).strip()


def clean_fish_audio_text(text: str, model: str = "s2.1-pro") -> str:
    """Очищает текст для Fish Audio, сохраняя валидные теги эмоций и отсекая технический JSON/код."""
    from utils import extract_clean_dialogue_text, process_text_to_voice
    extracted = extract_clean_dialogue_text(text)
    candidate = extracted

    def normalize_marker(match: re.Match) -> str:
        raw_inner = (match.group(1) or match.group(2) or "").strip()
        if is_technical_marker(raw_inner):
            return " "
        resolved = resolve_fish_tag(raw_inner)
        if resolved:
            return f"({resolved}) " if model == "s1" else f"[{resolved}] "
        if model == "s1":
            return match.group(0) if match.group(2) is not None else " "
        if match.group(1) is not None:
            return f"[{raw_inner}] "
        return match.group(0)

    # Нормализуем маркеры эмоций и убираем технические/анимационные теги
    normalized = re.sub(
        r"\[([^\[\]\n]+)\]|\(([^()\n]+)\)", normalize_marker, candidate,
    )
    # Срезаем кавычки рядом с маркерами, так как кавычки ломают S2 TTS
    normalized = re.sub(r'["«»“”]', ' ', normalized)

    cleaned = process_text_to_voice(normalized, allow_fish_tags=True)
    cleaned = re.sub(r"[\{\}]", " ", cleaned)
    cleaned = re.sub(r"(?:\s*,\s*)+", ", ", cleaned)
    cleaned = re.sub(r"^\s*,\s*", "", cleaned)
    cleaned = re.sub(r"\s*,\s*$", "", cleaned)
    # Гарантируем пробел после закрывающей скобки тега
    cleaned = re.sub(r'(\[[^\]]+\]|\([^)]+\))\s*', r'\1 ', cleaned)
    # Убираем дублирующиеся подряд теги
    cleaned = re.sub(r'(\[[^\]]+\])\s*(?=\1)', '', cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


async def synthesize(text: str, *, config: dict | None = None, output_dir=None, transport=None) -> str:
    config = validate_config(load_config() if config is None else config)
    text = clean_fish_audio_text(text, model=config.get("model", "s2.1-pro"))
    if not text or not text.strip():
        raise ValueError("Нет текста для озвучки.")
    headers = {"Authorization": "Bearer " + config["api_key"], "model": config["model"]}
    payload = {"text": text, "reference_id": config["voice_id"], "format": "pcm",
               "sample_rate": 44100, "prosody": {"speed": config["speed"], "normalize_loudness": True}}
    directory = Path(output_dir) if output_dir is not None else base_dir()
    fd, name = tempfile.mkstemp(prefix="fish_", suffix=".wav", dir=directory)
    os.close(fd)
    try:
        # PCM avoids streaming WAV headers with unknown/incorrect data lengths.
        async with asyncio.timeout(180):
            async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=15), transport=transport,
                                         follow_redirects=False) as client:
                async with client.stream("POST", ENDPOINT, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        messages = {401: "API-ключ не принят", 402: "недостаточно средств или квоты",
                                    403: "нет доступа к голосу или API", 404: "голос не найден",
                                    422: "голос или параметры не поддерживаются выбранной моделью",
                                    429: "лимит запросов, попробуйте позже"}
                        reason = messages.get(response.status_code, "сервис отклонил запрос")
                        raise ValueError(f"Fish Audio: {reason} (HTTP {response.status_code}).")
                    content_type = response.headers.get("content-type", "").lower()
                    if "json" in content_type or "text/" in content_type:
                        raise ValueError("Fish Audio вернул текст вместо аудио.")
                    size = 0
                    buffer = bytearray()
                    with wave.open(name, "wb") as audio:
                        audio.setnchannels(1)
                        audio.setsampwidth(2)
                        audio.setframerate(44100)
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 100 * 1024 * 1024:
                                raise ValueError("Ответ Fish Audio превышает 100 МБ.")
                            buffer.extend(chunk)
                            even_len = len(buffer) - (len(buffer) % 2)
                            if even_len > 0:
                                audio.writeframesraw(buffer[:even_len])
                                del buffer[:even_len]
                        if buffer:
                            raise ValueError("Fish Audio вернул неполный 16-битный PCM фрейм.")
                    if size < 2 or size % 2:
                        raise ValueError("Fish Audio вернул пустое или повреждённое аудио.")
        return str(Path(name).resolve())
    except BaseException as exc:
        Path(name).unlink(missing_ok=True)
        if isinstance(exc, (httpx.HTTPError, TimeoutError)):
            raise ValueError("Fish Audio: ошибка сети или превышено время ожидания.") from None
        raise
