"""Оценка токенов по сообщениям и секциям отправляемого контекста.

Общая утилита для debug-дампов (handlers.chat_handler) и просмотрщика
контекста (ui.dialogs.context_viewer_dialog): обе стороны должны считать
секции и проценты одинаково, а UI не должен импортировать backend-слои.
"""
from typing import Any, Dict

_SECTION_MARKERS = (
    ("[Available Tools]", "tools"),
    ("[MiSide World State]", "MiSide World State"),
    ("[System State]", "System State"),
    ("[Behavior State]", "System State"),
    ("[Current State]", "System State"),
    ("[Pending Reminders]", "reminders"),
    ("[HISTORY SUMMARY]", "history"),
    ("[Core Memory", "core memories"),
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
        MiSide World State, контракты/возможности Unity, RAG). У них есть наши
        маркеры-заголовки.
      • «История» — поток разговора: саммари, реплики диалога И прочие
        system/рантайм-события хода (idle/«игрок молчит», напоминания и т.п.),
        которые мы не задавали как контекст-блок. Системное ≠ активный
        контекст, пока мы явно его так не оформили (фидбэк).
      • «Промпт» — промпт персонажа: ведущий блок system-сообщений ДО истории.
      • «Ввод игрока» — текущий ввод (последнее реальное user-сообщение).
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

    # 2) Реальный диалог.
    role = str(msg.get("role") or "")
    if role == "user" and not is_runtime_event:
        return "user input" if is_last_user else "history"
    if role == "assistant":
        return "history"

    # 3) Всё прочее — ведущий безмаркерный system это промпт персонажа; после
    # начала истории любые system/рантайм-события хода (idle/«игрок молчит»,
    # напоминания, конвертированные не-Unity [RUNTIME EVENT]) — это история,
    # а не активный контекст (мы их как контекст не задавали).
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
        return {"available": False, "note": f"ContextCounter unavailable: {e}"}

    # Текущий ввод игрока — последнее НАСТОЯЩЕЕ user-сообщение (не [RUNTIME EVENT],
    # который провайдер тоже делает role="user"), и только если после него нет
    # ответа ассистента. В idle-ходе («игрок молчит N секунд») текущего ввода
    # нет вовсе: последний user — из истории, и помечать его «Вводом» нельзя,
    # иначе он разрывает блок «История».
    def _is_runtime_event(msg: Dict[str, Any]) -> bool:
        return message_text(msg).lstrip().startswith("[RUNTIME EVENT]")

    last_user_idx = -1
    for i, m in enumerate(messages):
        if isinstance(m, dict) and str(m.get("role")) == "user" and not _is_runtime_event(m):
            last_user_idx = i
    current_input_idx = last_user_idx
    if last_user_idx >= 0:
        for m in messages[last_user_idx + 1:]:
            if isinstance(m, dict) and str(m.get("role")) == "assistant":
                current_input_idx = -1  # на этот user уже есть ответ → это история
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
