# src/handlers/llm_providers/message_transforms.py
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterator, List, Optional, Tuple


def _as_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:
        return ""


def _summarize_messages(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    roles = [m.get("role") for m in msgs if m.get("role")]

    total_chars = 0
    for m in msgs:
        c = m.get("content")
        if isinstance(c, str):
            total_chars += len(c)
        elif isinstance(c, list):
            for chunk in c:
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    total_chars += len(_as_text(chunk.get("text", "")))

    return {
        "count": len(msgs),
        "roles": roles[:24],
        "last_role": roles[-1] if roles else None,
        "approx_text_chars": total_chars,
    }


def merge_system_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []
    seen_non_system = False

    for m in messages or []:
        if not isinstance(m, dict):
            continue
        if not seen_non_system and m.get("role") == "system":
            c = m.get("content", "")
            t = _as_text(c).strip()
            if t:
                system_parts.append(t)
        else:
            seen_non_system = True
            out.append(m)

    if not system_parts:
        return list(messages or [])

    merged = {"role": "system", "content": "\n\n".join(system_parts)}
    return [merged] + out


def ensure_last_message_user(messages: List[Dict[str, Any]], fallback_user_text: str = ".") -> List[Dict[str, Any]]:
    out = list(messages or [])
    if not out:
        return [{"role": "user", "content": fallback_user_text}]

    last = out[-1]
    if isinstance(last, dict) and last.get("role") == "assistant":
        out.append({"role": "user", "content": fallback_user_text})
    return out


def ensure_alternating_roles(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge consecutive messages with the same role so user/assistant strictly alternate.

    System messages at the very beginning (before the first user message) are
    kept as-is and never merged with non-system messages.  Two adjacent system
    messages are merged together.

    For user/assistant runs: all consecutive messages of the same role are
    collapsed into one by joining their text content with "\\n\\n".
    """

    def _to_list(content: Any) -> list:
        if not content and content != 0:
            return []
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        if isinstance(content, list):
            return content
        return [{"type": "text", "text": _as_text(content)}]

    def _merge_two(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
        content_a = a.get("content", "")
        content_b = b.get("content", "")

        # Both plain strings — keep simple string output
        if isinstance(content_a, str) and isinstance(content_b, str):
            merged_content: Any = "\n\n".join(t for t in [content_a, content_b] if t)
        else:
            # At least one is a list (multimodal) — concatenate block arrays
            # so non-text blocks (images, files) are never lost
            merged_content = _to_list(content_a) + _to_list(content_b)

        merged = dict(a)
        merged["content"] = merged_content

        # Preserve tool_calls from both messages
        tc_a = a.get("tool_calls") or []
        tc_b = b.get("tool_calls") or []
        if tc_a or tc_b:
            merged["tool_calls"] = tc_a + tc_b

        return merged

    out: List[Dict[str, Any]] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if not out:
            out.append(dict(msg))
            continue
        if out[-1].get("role") == msg.get("role"):
            out[-1] = _merge_two(out[-1], msg)
        else:
            out.append(dict(msg))
    return out


def system_to_user_prefix(messages: List[Dict[str, Any]], tag: str = "[SYSTEM CONTEXT]") -> List[Dict[str, Any]]:
    system_texts: List[str] = []
    out: List[Dict[str, Any]] = []

    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "system":
            c = m.get("content", "")
            t = _as_text(c).strip()
            if t:
                system_texts.append(t)
            continue
        out.append(m)

    if not system_texts:
        return out

    prefix = "\n\n".join(f"{tag} {t}" for t in system_texts).strip()

    for m in out:
        if m.get("role") != "user":
            continue

        content = m.get("content")

        if isinstance(content, list):
            inserted = False
            for chunk in content:
                if isinstance(chunk, dict) and chunk.get("type") == "text":
                    chunk["text"] = f"{prefix}\n\n{_as_text(chunk.get('text', ''))}"
                    inserted = True
                    break
            if not inserted:
                content.insert(0, {"type": "text", "text": prefix})
            return out

        if isinstance(content, str):
            m["content"] = f"{prefix}\n\n{content}"
            return out

        m["content"] = f"{prefix}\n\n{_as_text(content)}"
        return out

    out.append({"role": "user", "content": prefix})
    return out


def iter_positioned_messages(messages: List[Dict[str, Any]]) -> Iterator[Tuple[Dict[str, Any], bool]]:
    """Yield each message and whether it is a system block inside the dialogue."""
    dialogue_started = False
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "system":
            dialogue_started = True
        yield message, dialogue_started and message.get("role") == "system"


def system_messages_to_user(messages: List[Dict[str, Any]], tag: str = "[SYSTEM INFO]") -> List[Dict[str, Any]]:
    """Keep leading instructions; convert later system blocks at their positions."""
    out = []
    for source, inline_system in iter_positioned_messages(messages):
        message = deepcopy(source)
        if message.get("role") != "system":
            out.append(message)
            continue

        content = message.get("content")
        if isinstance(content, list):
            has_payload = any(
                isinstance(part, dict) and (
                    part.get("type") != "text" or _as_text(part.get("text")).strip()
                ) for part in content
            )
        else:
            has_payload = bool(_as_text(content).strip())
        if not has_payload:
            continue
        if inline_system:
            message["role"] = "user"
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        part["text"] = f"{tag}\n{_as_text(part.get('text'))}"
                        break
                else:
                    content.insert(0, {"type": "text", "text": tag})
            else:
                message["content"] = f"{tag}\n{_as_text(content)}"
        out.append(message)
    return out


def normalize_system_messages(messages: List[Dict[str, Any]], tag: str = "[SYSTEM INFO]") -> List[Dict[str, Any]]:
    positioned = system_messages_to_user(messages, tag)
    leading_count = 0
    for message in positioned:
        if message.get("role") != "system":
            break
        leading_count += 1
    if leading_count < 2:
        return positioned
    contents = [message.get("content", "") for message in positioned[:leading_count]]
    merged = dict(positioned[0])
    if all(isinstance(content, str) for content in contents):
        merged["content"] = "\n\n".join(contents)
    else:
        parts = []
        for content in contents:
            if parts:
                parts.append({"type": "text", "text": "\n\n"})
            parts.extend(content if isinstance(content, list) else [{"type": "text", "text": _as_text(content)}])
        merged["content"] = parts
    return [merged] + positioned[leading_count:]


def trailing_system_to_user_prefix(messages: List[Dict[str, Any]], tag: str = "[SYSTEM INFO]") -> List[Dict[str, Any]]:
    out = [dict(m) for m in (messages or []) if isinstance(m, dict)]
    if not out:
        return out

    last = out[-1]
    if last.get("role") != "system":
        return out

    content = _as_text(last.get("content", "")).strip()
    if not content:
        return out[:-1]

    out[-1] = {"role": "user", "content": f"{tag} {content}"}
    return out


# --- Catalog (for UI) ---
_TRANSFORM_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "normalize_system_messages",
        "title": "One system instruction, positioned context",
        "title_ru": "Одна системная инструкция, контекст на своих местах",
        "description_ru": "Объединяет начальные системные инструкции. Последующие системные блоки становятся сообщениями пользователя с меткой [SYSTEM INFO], сохраняя своё место в диалоге.",
        "description": "Merge leading system instructions. Convert later system blocks to user messages tagged [SYSTEM INFO], keeping their positions in the conversation.",
        "help_ru": (
            "Что меняется: начальные служебные инструкции для Миты объединяются в одно системное сообщение. "
            "Служебные блоки после начала переписки — например, текущее время и состояние игры — становятся "
            "сообщениями пользователя с меткой [SYSTEM INFO] и остаются рядом с той репликой, к которой относятся.\n\n"
            "Когда включать: если локальная модель или сервер принимает только одно системное сообщение в начале "
            "и выдаёт ошибку «System message must be at the beginning». Подходит и для диалога с историей.\n\n"
            "Пример: инструкции 1 + инструкции 2 → одна инструкция; после старого ответа «сейчас 18:00» → "
            "служебное сообщение пользователя на том же месте, перед новым вопросом. "
            "Порядок реплик и изображения сохраняются. Соседние сообщения пользователя этот шаг не объединяет."
        ),
        "help": (
            "What changes: leading instructions for Mita are combined into one system message. "
            "System blocks after the conversation starts, such as the current time or game state, become user "
            "messages tagged [SYSTEM INFO] and stay next to the turn they describe.\n\n"
            "When to use: a local model or server accepts only one system message at the beginning and reports "
            "'System message must be at the beginning'. Works with conversation history too.\n\n"
            "Example: instructions 1 + instructions 2 → one instruction; after an old answer, 'it is 18:00' → "
            "a tagged user message at that same position, before the new question. "
            "Turn order and images are preserved. This step does not merge adjacent user messages."
        ),
        "params_schema": {"tag": "str"},
    },
    {
        "id": "merge_system_messages",
        "title": "Merge system messages",
        "title_ru": "Объединить системные сообщения",
        "description_ru": "Объединяет последовательные системные сообщения в начале диалога.",
        "description": "Combine only the leading contiguous system messages into a single system message at the top.",
        "help_ru": (
            "Что меняется: несколько системных сообщений подряд в самом начале запроса объединяются в одно. "
            "Это служебные инструкции для модели: персонаж, правила поведения и формат ответа.\n\n"
            "Когда включать: если сервер требует одну начальную инструкцию вместо нескольких отдельных блоков.\n\n"
            "Пример: «ты Мита» + «отвечай в заданном формате» → одно системное сообщение с обоими текстами.\n\n"
            "Системные блоки после начала переписки остаются на своих местах и сохраняют системную роль. "
            "Если сервер запрещает такие блоки, выберите «Одна системная инструкция, контекст на своих местах»."
        ),
        "help": (
            "What changes: consecutive system messages at the start of the request become one message. "
            "These are instructions for the model: persona, behavior rules and response format.\n\n"
            "When to use: a server requires one leading instruction instead of several separate blocks.\n\n"
            "Example: 'you are Mita' + 'use the required response format' → one system message containing both texts.\n\n"
            "System blocks after the conversation starts keep their positions and system role. "
            "If the server rejects these blocks, choose 'One system instruction, positioned context'."
        ),
        "params_schema": None,
    },
    {
        "id": "ensure_last_message_user",
        "title": "Ensure last message is user",
        "title_ru": "Завершить диалог сообщением пользователя",
        "description_ru": "Добавляет сообщение «.», если последнее сообщение принадлежит ассистенту.",
        "description": "If last message is assistant, append a dummy user message ('.').",
        "help_ru": (
            "Что меняется: если запрос заканчивается ответом модели, в конец добавляется короткое сообщение "
            "пользователя «.». Если последнее сообщение уже от пользователя или имеет другую роль, ничего не добавляется.\n\n"
            "Когда включать: если сервер отказывается продолжать диалог, который заканчивается ответом модели.\n\n"
            "Пример: вопрос игрока → ответ Миты становится: вопрос игрока → ответ Миты → сообщение пользователя «.».\n\n"
            "Это техническая реплика, а не реальное сообщение игрока. При заданном параметре шага вместо точки "
            "используется указанный текст."
        ),
        "help": (
            "What changes: if the request ends with a model reply, a short user message '.' is appended. "
            "Nothing is appended if the last message is already from the user or has another role.\n\n"
            "When to use: a server refuses to continue a conversation ending with a model reply.\n\n"
            "Example: player question → Mita reply becomes: player question → Mita reply → user message '.'.\n\n"
            "This is a technical prompt, not a real player message. If the step has a custom fallback text, "
            "that text is used instead of the dot."
        ),
        "params_schema": {"fallback_user_text": "str"},
    },
    {
        "id": "system_to_user_prefix",
        "title": "System → user prefix",
        "title_ru": "Перенести системный контекст",
        "description_ru": "Добавляет системные сообщения в начало первого сообщения пользователя.",
        "description": "Move system messages into the first user message as a text prefix.",
        "help_ru": (
            "Что меняется: все системные сообщения, включая блоки после истории, собираются и добавляются "
            "в начало первого сообщения пользователя с меткой [SYSTEM CONTEXT]. Отдельных системных сообщений не остаётся.\n\n"
            "Когда включать: если провайдер не принимает системную роль и инструкции приходится передавать "
            "внутри обычного сообщения пользователя.\n\n"
            "Пример: «ты Мита» + вопрос игрока «привет» → одно сообщение пользователя с инструкцией и приветствием.\n\n"
            "В диалоге с историей даже текущее время и состояние игры переместятся к первой старой реплике. "
            "Чтобы сохранить положение текущего контекста, выберите «Одна системная инструкция, контекст на своих местах»."
        ),
        "help": (
            "What changes: all system messages, including blocks after the history, are collected and placed "
            "at the start of the first user message, tagged [SYSTEM CONTEXT]. No separate system messages remain.\n\n"
            "When to use: a provider does not accept the system role, so instructions must be sent inside an ordinary user message.\n\n"
            "Example: 'you are Mita' + the player's 'hello' → one user message containing the instruction and greeting.\n\n"
            "With conversation history, even the current time and game state move to the first old turn. "
            "To keep current context in place, choose 'One system instruction, positioned context'."
        ),
        "params_schema": {"tag": "str"},
    },
    {
        "id": "ensure_alternating_roles",
        "title": "Ensure alternating roles",
        "title_ru": "Чередовать роли в диалоге",
        "description_ru": "Объединяет соседние сообщения одной роли: пользователь и ассистент чередуются.",
        "description": "Merge consecutive messages with the same role so user/assistant strictly alternate.",
        "help_ru": (
            "Что меняется: соседние сообщения одной роли объединяются в одно, сохраняя порядок их содержимого. "
            "Несколько реплик пользователя подряд становятся одной; несколько ответов модели подряд — тоже одной.\n\n"
            "Когда включать: если сервер требует чередования сообщений пользователя и модели. "
            "Также полезно после шага, который превращает служебные блоки в сообщения пользователя.\n\n"
            "Пример: пользователь «время 18:00» → пользователь «привет» → ответ Миты становится: "
            "одно сообщение пользователя с обоими текстами → ответ Миты. Изображения сохраняются.\n\n"
            "Системная роль не заменяется пользовательской. Если нужны оба преобразования, сначала добавьте "
            "перенос системных блоков, а затем этот шаг."
        ),
        "help": (
            "What changes: adjacent messages with the same role are combined while preserving their content order. "
            "Several user turns in a row become one; several model replies in a row also become one.\n\n"
            "When to use: a server requires alternating user and model messages. Also useful after a step "
            "that converts system blocks into user messages.\n\n"
            "Example: user 'time is 18:00' → user 'hello' → Mita reply becomes: "
            "one user message containing both texts → Mita reply. Images are preserved.\n\n"
            "This does not replace the system role with the user role. If both operations are needed, "
            "add system block conversion first, then this step."
        ),
        "params_schema": None,
    },
]


def get_transform_catalog() -> List[Dict[str, Any]]:
    return list(_TRANSFORM_CATALOG)


_TRANSFORMS = {
    "normalize_system_messages": lambda msgs, params: normalize_system_messages(
        msgs, tag=str((params or {}).get("tag", "[SYSTEM INFO]"))
    ),
    "merge_system_messages": lambda msgs, params: merge_system_messages(msgs),
    "ensure_last_message_user": lambda msgs, params: ensure_last_message_user(
        msgs, fallback_user_text=str((params or {}).get("fallback_user_text", "."))
    ),
    "system_to_user_prefix": lambda msgs, params: system_to_user_prefix(
        msgs, tag=str((params or {}).get("tag", "[SYSTEM CONTEXT]"))
    ),
    "ensure_alternating_roles": lambda msgs, params: ensure_alternating_roles(msgs),
}


def apply_transforms(
    messages: List[Dict[str, Any]],
    specs: Optional[List[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    out = list(messages or [])
    trace: List[Dict[str, Any]] = []

    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        tid = spec.get("id")
        params = spec.get("params") or {}
        fn = _TRANSFORMS.get(tid)
        if not fn:
            trace.append({"id": tid, "skipped": True, "reason": "unknown_transform"})
            continue

        before = _summarize_messages(out)
        out2 = fn(out, params)
        after = _summarize_messages(out2)

        trace.append({"id": tid, "params": params, "before": before, "after": after, "changed": before != after})
        out = out2

    return out, trace
