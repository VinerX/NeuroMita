"""URL helpers for user-supplied OpenAI-compatible gateways."""
from urllib.parse import parse_qsl, urlsplit, urlunsplit


def models_url(endpoint: str) -> str:
    parsed = urlsplit(str(endpoint or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Укажите HTTP(S) URL API без логина и пароля в адресе.")
    if parsed.query:
        sensitive_keys = {"key", "api_key", "token", "secret", "auth", "password", "bearer"}
        for k, _ in parse_qsl(parsed.query, keep_blank_values=True):
            if k.strip().lower() in sensitive_keys:
                raise ValueError("Не передавайте API-ключи или токены в параметрах URL.")
    path = parsed.path.rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/models"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path + "/models", parsed.query, ""))
