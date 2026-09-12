"""URL helpers for user-supplied OpenAI-compatible gateways."""
from urllib.parse import urlsplit, urlunsplit


def models_url(endpoint: str) -> str:
    parsed = urlsplit(str(endpoint or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Укажите HTTP(S) URL API без логина и пароля в адресе.")
    path = parsed.path.rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/models"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path + "/models", parsed.query, ""))
