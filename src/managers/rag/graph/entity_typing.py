"""
Переклассификация сущностей графа: определить тип у сущностей, осевших на
дефолтном 'thing' (ранний extraction ленился проставлять тип).

Логика чистая и тестируемая: сборка промпта + разбор ответа + оркестрация
батчами. Сам LLM-вызов инъектируется как callable ``generate(prompt) -> str``,
доступ к БД — через ``GraphStore`` (см. `graph_store.get_untyped_entities`,
`set_entity_type`, `get_entity_relation_context`).
"""
from __future__ import annotations

import json
import re
from typing import Callable, Dict, List, Optional

from main_logger import logger

_VALID_TYPES = ("person", "place", "thing", "concept")

_TYPING_PROMPT = """You classify knowledge-graph entities by type.
For each entity below output its type — exactly one of: person, place, thing, concept.

- person  — a named individual or character (alice, mita, player, mom)
- place   — a location or space (moscow, kitchen, school, forest)
- concept — an abstract idea, topic, activity, emotion or event (chess, friendship, birthday, fear)
- thing   — a concrete physical object that is none of the above (knife, phone, cake, door)

Use the relation hints in parentheses to disambiguate. If genuinely unsure, use "thing".

Output ONLY a valid JSON object mapping each entity name to its type. No commentary, no markdown:
{"alice":"person","moscow":"place","chess":"concept","knife":"thing"}

Entities:
{items}"""


def build_typing_prompt(items: List[Dict]) -> str:
    """Собрать промпт классификации по списку сущностей [{name, context?}]."""
    lines: List[str] = []
    for it in items:
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        ctx = it.get("context") or []
        if ctx:
            hint = "; ".join(str(c) for c in list(ctx)[:5])
            lines.append(f"- {name}  (hints: {hint})")
        else:
            lines.append(f"- {name}")
    return _TYPING_PROMPT.replace("{items}", "\n".join(lines))


def parse_typing_response(raw: str) -> Dict[str, str]:
    """Из ответа модели вытащить {name(lower) -> type}. Мусор игнорируется."""
    if not raw:
        return {}
    # Обрезаем markdown-обёртку и берём первый JSON-объект.
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, str] = {}
    for key, val in data.items():
        etype = str(val).strip().lower()
        if etype in _VALID_TYPES:
            out[str(key).strip().lower()] = etype
    return out


def reclassify_untyped_entities(
    graph_store,
    generate: Callable[[str], str],
    *,
    batch_size: int = 40,
    max_entities: int = 2000,
    progress_cb: Optional[Callable[[int, int], bool]] = None,
) -> Dict[str, int]:
    """Пройтись по 'thing'-сущностям персонажа и переклассифицировать через LLM.

    ``generate(prompt) -> str`` — синхронный LLM-вызов (см. GenerationService).
    ``progress_cb(done, total)`` — вернувший False прерывает проход.
    Возвращает сводку {total, updated, unchanged, batches}.
    """
    ents = graph_store.get_untyped_entities(limit=max_entities)
    total = len(ents)
    result = {"total": total, "updated": 0, "unchanged": 0, "batches": 0}
    if not ents:
        return result

    # Подтягиваем контекст-подсказки (связи) — по возможности.
    for e in ents:
        try:
            e["context"] = graph_store.get_entity_relation_context(e["id"], limit=5)
        except Exception:
            e["context"] = []

    done = 0
    for start in range(0, total, batch_size):
        batch = ents[start:start + batch_size]
        prompt = build_typing_prompt(batch)
        try:
            raw = generate(prompt) or ""
        except Exception as ex:
            logger.warning(f"[entity_typing] LLM generate failed for batch: {ex}")
            raw = ""
        mapping = parse_typing_response(raw)
        result["batches"] += 1

        for e in batch:
            name = str(e.get("name") or "").strip().lower()
            new_type = mapping.get(name)
            if new_type and new_type != "thing":
                try:
                    if graph_store.set_entity_type(e["id"], new_type):
                        result["updated"] += 1
                        continue
                except Exception as ex:
                    logger.warning(
                        f"[entity_typing] set_entity_type({e.get('id')}, {new_type}) failed: {ex}"
                    )
            result["unchanged"] += 1

        done += len(batch)
        if progress_cb is not None:
            # Исключение из progress_cb (напр. запрос отмены воркером) намеренно
            # НЕ глотаем — оно должно прервать проход.
            keep_going = progress_cb(done, total)
            if keep_going is False:
                break

    logger.info(
        f"[entity_typing] reclassified: {result['updated']}/{total} updated "
        f"({result['batches']} batch(es))"
    )
    return result
