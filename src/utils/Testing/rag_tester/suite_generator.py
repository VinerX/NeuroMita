"""Automated test suite generation for RAG evaluation via OpenAI-compatible LLM API.

Generates test queries with expected document IDs and relevance grades by analyzing
scenario data through sliding windows. Compatible with any OpenAI-compatible API:
- OpenRouter (free models: Gemini Flash, Qwen, Llama)
- Google AI Studio (Gemini)
- Ollama / LM Studio (local models)
- Any OpenAI-compatible endpoint

Usage::

    python rag_tester_cli.py generate-suite \\
        --scenario fixtures/crazy_scenario_full.json \\
        --output fixtures/generated_suite.json \\
        --api-base http://localhost:11434/v1 \\
        --model gemma2:9b \\
        --num-cases 40
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


SYSTEM_PROMPT = """Ты генерируешь тест-кейсы для системы RAG-поиска по истории диалога.
Тебе дают набор сообщений с их message_id. Ты должен создать тестовые запросы,
которые пользователь мог бы задать, и указать какие сообщения должны быть найдены."""

WINDOW_PROMPT_TEMPLATE = """Ниже сообщения из диалога. Каждое имеет уникальный message_id.

Сообщения:
{formatted_messages}

Сгенерируй JSON-массив тест-кейсов. Формат:
```json
[
  {{
    "query": "естественный запрос на языке сообщений",
    "expected_ids": ["message_id_1", "message_id_2"],
    "relevance_grades": {{"message_id_1": 3, "message_id_2": 1}},
    "description": "почему эти сообщения релевантны"
  }}
]
```

Правила:
- Сгенерируй {n_positive} положительных запросов (с expected_ids) и {n_negative} отрицательных (expected_ids: [])
- expected_ids ТОЛЬКО из показанных message_id
- Grades: 3=точное совпадение по теме, 2=релевантно, 1=косвенно связано
- Запросы на том же языке, что и сообщения
- Разнообразие типов: точные ("Что говорил про X?"), семантические ("Какие игры нравятся?"), парафразы
- Отрицательные запросы — про темы, которых НЕТ в сообщениях
- Верни ТОЛЬКО JSON-массив, без пояснений"""


def _extract_text(content: Any) -> str:
    """Extract plain text from message content (string or list of parts)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text", ""))
            elif isinstance(p, str):
                parts.append(p)
        return " ".join(parts).strip()
    return str(content or "").strip()


def _format_message(msg: dict) -> str:
    """Format a single message for the LLM prompt."""
    mid = msg.get("message_id", "?")
    speaker = msg.get("speaker", msg.get("role", "?"))
    text = _extract_text(msg.get("content", ""))
    # Truncate very long messages
    if len(text) > 500:
        text = text[:500] + "..."
    return f"[{mid}] {speaker}: {text}"


def _parse_json_from_response(text: str) -> list[dict]:
    """Extract JSON array from LLM response, handling markdown fences and thinking blocks."""
    # Strip <think>...</think> blocks (Qwen3, DeepSeek-R1, etc.)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    # Try to find JSON in code fences first
    fence_match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try to find JSON array
    arr_match = re.search(r'\[.*\]', text, re.DOTALL)
    if arr_match:
        try:
            return json.loads(arr_match.group(0))
        except json.JSONDecodeError:
            pass

    # Last resort: try parsing the whole thing
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    return []


def _jaccard_tokens(a: str, b: str) -> float:
    """Token-level Jaccard similarity between two strings."""
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class GeneratorConfig:
    """Configuration for suite generation."""
    api_base: str = "http://localhost:11434/v1"
    model: str = "gemma2:9b"
    api_key: str = "dummy"
    window_size: int = 20
    window_overlap: int = 5
    positive_per_window: int = 3
    negative_per_window: int = 1
    num_cases: int = 40  # target total test cases
    dedup_threshold: float = 0.6  # Jaccard similarity threshold for dedup
    temperature: float = 0.7
    max_tokens: int = 4096


def generate_suite(
    scenario_path: str,
    config: GeneratorConfig,
    *,
    progress_callback=None,
) -> dict:
    """Generate a test suite from a scenario file using an LLM.

    Args:
        scenario_path: path to scenario JSON
        config: GeneratorConfig
        progress_callback: fn(window_num, total_windows, cases_so_far)

    Returns:
        TestSuite dict ready for JSON serialization
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "openai package is required for suite generation. "
            "Install with: pip install openai"
        )

    # Load scenario
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario = json.load(f)

    character_id = scenario.get("character_id", "RAG_TEST")
    history = scenario.get("history", [])
    if not history:
        raise ValueError("Scenario has no history messages to generate tests from")

    # Collect all valid message_ids for validation
    all_ids: Set[str] = set()
    for m in history + scenario.get("context", []):
        mid = m.get("message_id", "")
        if mid:
            all_ids.add(str(mid))

    # Build sliding windows
    step = max(1, config.window_size - config.window_overlap)
    windows: list[list[dict]] = []
    for start in range(0, len(history), step):
        window = history[start:start + config.window_size]
        if len(window) >= 3:  # skip tiny windows
            windows.append(window)

    # Initialize OpenAI client
    client = OpenAI(
        base_url=config.api_base,
        api_key=config.api_key,
    )

    all_cases: list[dict] = []
    seen_queries: list[str] = []

    for wi, window in enumerate(windows):
        if len(all_cases) >= config.num_cases:
            break

        if progress_callback:
            progress_callback(wi + 1, len(windows), len(all_cases))

        # Format messages for the prompt
        formatted = "\n\n".join(_format_message(m) for m in window)
        prompt = WINDOW_PROMPT_TEMPLATE.format(
            formatted_messages=formatted,
            n_positive=config.positive_per_window,
            n_negative=config.negative_per_window,
        )

        try:
            response = client.chat.completions.create(
                model=config.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )

            reply = response.choices[0].message.content or ""
            cases = _parse_json_from_response(reply)

            for case in cases:
                if not isinstance(case, dict):
                    continue
                query = str(case.get("query", "")).strip()
                if not query:
                    continue

                expected_ids = case.get("expected_ids", [])
                relevance_grades = case.get("relevance_grades", {})
                description = str(case.get("description", ""))

                # Validate: remove IDs not in scenario
                valid_ids = [eid for eid in expected_ids if str(eid) in all_ids]
                valid_grades = {k: v for k, v in relevance_grades.items() if k in all_ids}

                # Deduplication: skip if too similar to existing query
                is_dup = any(
                    _jaccard_tokens(query, existing) > config.dedup_threshold
                    for existing in seen_queries
                )
                if is_dup:
                    continue

                tc: dict = {
                    "query": query,
                    "expected_ids": valid_ids,
                    "description": description,
                }
                if valid_grades:
                    tc["relevance_grades"] = valid_grades

                all_cases.append(tc)
                seen_queries.append(query)

                if len(all_cases) >= config.num_cases:
                    break

        except Exception as e:
            print(f"  Window {wi+1}: LLM error: {e}", file=sys.stderr)
            continue

    # Build suite
    suite = {
        "name": f"Generated RAG Suite ({len(all_cases)} cases)",
        "character_id": character_id,
        "cases": all_cases,
    }

    return suite
