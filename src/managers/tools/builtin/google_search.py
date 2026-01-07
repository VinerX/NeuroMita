# src/managers/tools/builtin/google_search.py
import os
import json
from typing import Any

import requests

from core.events import Events
from managers.tools.base import Tool
from main_logger import logger
from managers.settings_manager import SettingsManager

class GoogleSearchTool(Tool):
    name = "google_search"
    description = "Выполняет поиск в Google и возвращает результаты (заголовки, ссылки, сниппеты). Работает при наличии ключа, зато точный."

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Поисковый запрос"
            },
            "max_results": {
                "type": "integer",
                "description": "Количество результатов (1-15)",
                "default": 5,
                "minimum": 1,
                "maximum": 15
            }
        },
        "required": ["query"]
    }


    def run(self, query: str, max_results: int = 5, **_) -> str:

        # TODO переделай поб общий формат
        self.api_key = SettingsManager.get("GOOGLE_API_KEY")
        self.cse_id = SettingsManager.get("GOOGLE_CSE_ID")

        if not self.api_key or not self.cse_id:
            return "[google_search] Ошибка: Не заданы GOOGLE_API_KEY или GOOGLE_CSE_ID."

        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "num": min(max_results, 15)  # API отдает максимум 10 за раз
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            items = data.get("items", [])
            if not items:
                return "[google_search] Ничего не найдено."

            results = []
            for item in items:
                results.append({
                    "title": item.get("title"),
                    "link": item.get("link"),
                    "snippet": item.get("snippet")
                })

            return json.dumps(results, ensure_ascii=False, indent=2)

        except requests.exceptions.RequestException as e:
            logger.error(f"Google Search API error: {e}")
            return f"[google_search] Ошибка сети или API: {e}"
        except Exception as e:
            logger.error(f"Google Search unexpected error: {e}")
            return f"[google_search] Неизвестная ошибка: {e}"

