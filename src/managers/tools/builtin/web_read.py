
import re, requests, bs4
from managers.tools.base import Tool

_CLEAN_TAGS = ["script", "style", "noscript", "iframe", "header",
               "footer", "nav", "aside", "form"]

class WebPageReaderTool(Tool):
    name = "web_reader"
    description = "Скачивает веб-страницу (или raw-файл GitHub) и возвращает очищенный текст."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Полный URL страницы (http/https)"},
            "max_chars": {
                "type": "integer",
                "description": "Максимальное число символов (по умолчанию 1500)",
                "default": 10000,
                "minimum": 100,
                "maximum": 20000
            }
        },
        "required": ["url"]
    }

    def run(self, url: str, max_chars: int = 10000, **_):
        url = self._convert_github_raw(url)
        # Jina AI Reader: возвращает уже готовый Markdown/текст даже для SPA/JS-сайтов.
        reader_url = f"https://r.jina.ai/{url}"

        try:
            resp = requests.get(reader_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            if not resp.encoding or resp.encoding.lower() == 'iso-8859-1':
                resp.encoding = resp.apparent_encoding
        except Exception as e:
            return f"[web_reader] Ошибка при загрузке: {e}"

        text = (resp.text or "").strip()
        if not text:
            return "[web_reader] Ничего не удалось извлечь."

        return self._truncate(text, max_chars)

    def _truncate(self, txt: str, max_len: int) -> str:
        return txt if len(txt) <= max_len else txt[:max_len] + " …"

    def _clean_whitespaces(self, s: str) -> str:
        return re.sub(r"\s{2,}", " ", s).strip()

    def _convert_github_raw(self, url: str) -> str:
        if "github.com" in url and "/blob/" in url:
            m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/blob/(.+)", url)
            if m:
                owner, repo, path = m.groups()
                return f"https://raw.githubusercontent.com/{owner}/{repo}/{path}"
        return url


def single_test_run():
    """Выполняет один тестовый прогон инструмента с имитацией успешного ответа."""

    test_url = "https://github.com/VinerX/NeuroMita"
    # 2. Создаем экземпляр и запускаем метод
    tool_instance = WebPageReaderTool()
    print(f"Вызов инструмента для URL: {test_url}")
    result = tool_instance.run(test_url)

    # 3. Проверяем результат
    print(result)


# Запуск единичного теста
if __name__ == '__main__':
    single_test_run()
