# src/managers/tools/builtin/web_search.py
import json
from ddgs import DDGS
from managers.tools.base import Tool


class WebSearchTool(Tool):
    name = "web_search"
    description = "Выполняет поиск в интернете через DuckDuckGo и возвращает результаты в формате JSON. Крайне посредственный."

    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Поисковый запрос"},
            "max_results": {
                "type": "integer",
                "description": "Максимальное количество результатов",
                "minimum": 3,
                "maximum": 20,
                "default": 5
            }
        },
        "required": ["query"]
    }

    def __init__(self):
        self.ddgs = DDGS()

    def run(self, query: str, max_results: int = 5, **_) -> str:
        try:
            results = self.ddgs.text(query, max_results=max_results)

            formatted_results = []
            for result in results:
                if 'body' in result:
                    formatted_results.append({
                        "title": result['title'],
                        "url": result['href'],
                        "snippet": result['body']
                    })

            if not formatted_results:
                return "[web_search] Ничего не найдено"

            return json.dumps(formatted_results, ensure_ascii=False, indent=2)

        except Exception as e:
            return f"[web_search] Ошибка: {e}"


def find_sites_test():

    text= "Чай Виды"

    ddgs = DDGS()
    results = ddgs.text(text,region="ru-ru", max_results=7)

    for res in results:
        print(res['title'])
        print(res['href'])
        print("-" * 20)
