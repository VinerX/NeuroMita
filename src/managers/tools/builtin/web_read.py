
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
                "default": 1500,
                "minimum": 100,
                "maximum": 8000
            }
        },
        "required": ["url"]
    }

    def run(self, url: str, max_chars: int = 1500, **_):
        url = self._convert_github_raw(url)

        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            if not resp.encoding or resp.encoding.lower() == 'iso-8859-1':
                resp.encoding = resp.apparent_encoding
        except Exception as e:
            return f"[web_reader] Ошибка при загрузке: {e}"

        content_type = resp.headers.get("Content-Type", "")
        if "text" not in content_type and "json" not in content_type:
            return "[web_reader] Неформатируемый бинарный контент."

        text = resp.text

        if "markdown" in content_type or url.endswith((".md", ".markdown")):
            cleaned = self._clean_whitespaces(text)
            return self._truncate(cleaned, max_chars)

        soup = bs4.BeautifulSoup(text, "html.parser")
        for tg in _CLEAN_TAGS:
            for tag in soup.find_all(tg):
                tag.decompose()
        pure_text = self._clean_whitespaces(soup.get_text(" ", strip=True))

        if not pure_text:
            return "[web_reader] Ничего не удалось извлечь."

        return self._truncate(pure_text, max_chars)

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