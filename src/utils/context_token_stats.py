"""Оценка токенов по сообщениям и секциям отправляемого контекста.

Общая утилита для debug-дампов (handlers.chat_handler) и просмотрщика
контекста (ui.dialogs.context_viewer_dialog): обе стороны должны считать
секции и проценты одинаково, а UI не должен импортировать backend-слои.
"""
from core.error_utils import format_exception
from typing import Any, Dict

_SECTION_MARKERS = (
    ("[Available Tools]", "tools"),
    ("[Current Group Conversation]", "group conversation"),
    ("[GAME_MASTER_DIRECTIVE]", "game master directive"),
    ("[NeuroMita World State]", "NeuroMita World State"),
    ("[MiSide World State]", "NeuroMita World State"),
    ("[Character World Context]", "Character World Context"),
    ("[Character Environment]", "Character Environment"),
    ("[System State]", "System State"),
    ("[Behavior State]", "System State"),
    ("[Current State]", "System State"),
    ("[Pending Reminders]", "reminders"),
    ("[HISTORY SUMMARY]", "history"),
    ("[WORKING STATE PROTOCOL]", "working state protocol"),
    ("[WORKING STATE]", "working state"),
    ("[RECENT ACTIONS BEFORE SUMMARY BOUNDARY]", "retained actions"),
    ("[REQUESTED ACTIONS THIS TURN]", "requested actions"),
    ("[Runtime Core Directive", "runtime directives"),
    ("[Core Memory", "core memories"),
    ("<memory_islands>", "memories"),
    ("<active_memory>", "memories"),
    ("<relevant_memories>", "memories"),
    ("# score=RAG", "memories"),
    ("<past_context>", "memories"),
    ("<entity_knowledge>", "memories"),
)


def message_text(msg: Dict[str, Any]) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(c.get("text", "")) for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
    return ""


def count_message_images(msg: Dict[str, Any]) -> int:
    """Число картинок в сообщении. В токен-оценку они не входят (у каждого
    провайдера свой расчёт), но их наличие показываем отдельной пометкой."""
    content = msg.get("content")
    if not isinstance(content, list):
        return 0
    return sum(
        1 for c in content
        if isinstance(c, dict) and c.get("type") in ("image_url", "image")
    )


def classify_message_section(msg: Dict[str, Any], is_last_user: bool,
                             seen_dialogue: bool = False) -> str:
    """Секция сообщения для группировки в просмотрщике контекста.

    Модель областей:
      • «Активный контекст» — ТОЛЬКО блоки, которые мы сами намеренно
        инжектим как контекст хода (память, состояние, [Current/System State],
        NeuroMita World State, контракты/возможности Unity, RAG). У них есть наши
        маркеры-заголовки.
      • «История» — поток разговора: саммари, реплики диалога и прочие
        уже отработанные (отвеченные) реплики/события прошлых ходов, которые
        мы не задавали как контекст-блок.
      • «Промпт» — промпт персонажа: ведущий блок system-сообщений ДО истории.
      • «Ввод игрока» — текущий триггер хода (последнее сообщение игрока):
        реальная реплика игрока ЛИБО idle-событие «игрок молчит», которое
        физически стоит последним и по смыслу заменяет ввод игрока в этом ходе.
        Показываем его внизу, «как если бы игрок написал» (фидбэк).
    """
    text = message_text(msg).lstrip()
    head = text[:80]
    is_runtime_event = head.startswith("[RUNTIME EVENT]")
    # Заголовок без провайдерского префикса — чтобы видеть наш реальный маркер.
    core = head[len("[RUNTIME EVENT]"):].lstrip() if is_runtime_event else head

    # 1) Явно оформленные нами блоки контекста — по маркерам.
    for marker, section in _SECTION_MARKERS:
        if core.startswith(marker) or marker in core:
            return section
    # Статический контракт Unity (Rules/Intent) теперь физически стоит в
    # статической части промпта (до истории) — это часть промпта; если вдруг
    # окажется после истории — считаем рантайм-контекстом. Динамический Unity
    # (Capabilities/Events) — всегда активный контекст текущего хода.
    if "Unity Runtime Rules" in core or "Unity Intent Contract" in core:
        return "Unity contract" if not seen_dialogue else "Unity runtime"
    if "Unity Runtime Capabilities" in core or "Unity Runtime Events" in core:
        return "Unity runtime"

    # 2) Текущий триггер хода и реальный диалог. Последнее «пользовательское»
    # сообщение (is_last_user) — реальная реплика игрока ИЛИ idle-событие «игрок
    # молчит» — это ввод текущего хода: показываем внизу, «как игрок написал».
    role = str(msg.get("role") or "")
    if is_last_user:
        return "user input"
    if role == "user" and not is_runtime_event:
        return "history"
    if role == "assistant":
        return "history"

    # 3) Всё прочее — ведущий безмаркерный system это промпт персонажа; после
    # начала истории безмаркерные system/рантайм-события ПРОШЛЫХ ходов
    # (уже отвеченные, не текущий триггер из п.2) — это история, а не активный
    # контекст (мы их как контекст не задавали).
    if role == "system" and not seen_dialogue and not is_runtime_event:
        return "character prompts"
    return "history"


def compute_token_usage(messages: Any) -> Dict[str, Any]:
    """Per-message and per-section token *estimates* for the debug dump.

    Counts come from the shared ContextCounter/tiktoken (an OpenAI encoding),
    so they are only an estimate for other providers (Gemini, Anthropic, local
    models tokenize differently). Fields are named ``estimated_*`` to reflect
    that. Providers with an unknown tokenizer degrade gracefully: counts are
    omitted with a clear note rather than raising or blocking the dump.
    """
    if not isinstance(messages, list) or not messages:
        return {"available": False, "note": "no messages"}
    try:
        from managers.context_counter import ContextCounter
        counter = ContextCounter()
    except Exception as e:
        return {"available": False, "note": f"ContextCounter unavailable: {format_exception(e)}"}

    # Текущий триггер хода — последнее сообщение игрока: реальная реплика ЛИБО
    # idle-событие «игрок молчит», которое физически стоит последним и по смыслу
    # заменяет ввод игрока в этом ходе. Провайдер делает событие role="user" с
    # префиксом [RUNTIME EVENT] (при кастомном обработчике — оставляет
    # role="event"). Помечаем его «Вводом игрока», чтобы было видно, что реально
    # шло последним. Условие «нет ответа ассистента после» отсекает уже
    # отработанные ходы (они остаются историей и не рвут её блок).
    def _is_player_turn(msg: Dict[str, Any]) -> bool:
        return str(msg.get("role")) in ("user", "event")

    last_user_idx = -1
    for i, m in enumerate(messages):
        if isinstance(m, dict) and _is_player_turn(m):
            last_user_idx = i
    current_input_idx = last_user_idx
    if last_user_idx >= 0:
        for m in messages[last_user_idx + 1:]:
            if isinstance(m, dict) and str(m.get("role")) == "assistant":
                current_input_idx = -1  # на этот ход уже есть ответ → это история
                break

    per_message = []
    by_section: Dict[str, int] = {}
    total = 0
    images_total = 0
    # Прошли ли мы ведущий блок промпта (началась история/диалог). После этого
    # безмаркерные system-сообщения считаем рантайм-контекстом, не промптом.
    seen_dialogue = False
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        try:
            n = int(counter.count_tokens([m]))
        except Exception:
            n = 0
        images = count_message_images(m)
        images_total += images
        section = classify_message_section(m, i == current_input_idx, seen_dialogue)
        if section in ("history", "user input"):
            seen_dialogue = True
        entry = {"index": i, "role": m.get("role"), "section": section, "estimated_tokens": n}
        if images:
            entry["images"] = images
        per_message.append(entry)
        by_section[section] = by_section.get(section, 0) + n
        total += n

    method = counter.method
    if counter.is_exact:
        note = (f"estimated via {counter.encoding_model} tokenizer; "
                "actual provider tokenization may differ; images not counted")
    else:
        note = ("rough heuristic estimate (no tokenizer available); "
                "actual provider tokenization will differ; images not counted")
    return {
        "available": True,
        "estimated": True,
        "exact": counter.is_exact,
        "method": method,
        "encoding": counter.encoding_model,
        "note": note,
        "estimated_total": total,
        "estimated_by_section": by_section,
        "images_total": images_total,
        "per_message": per_message,
    }


__all__ = [
    "classify_message_section",
    "compute_token_usage",
    "count_message_images",
    "message_text",
]
