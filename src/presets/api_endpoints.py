from urllib.parse import urlsplit, urlunsplit

CUSTOM_ENDPOINT_POLICY = {"url_editable": True, "test_url_editable": True}


def server_address(template: dict, api_url: str) -> str:
    path = str(template.get("request_path") or "")
    if template.get("url_editable") and path and api_url.rstrip("/").endswith(path):
        return api_url.rstrip("/")[: -len(path)]
    return api_url.rstrip("/")


def resolve_api_url(template: dict, value: str) -> str:
    if template.get("url_editable") and template.get("request_path"):
        return server_address(template, value.strip()) + str(template["request_path"])
    return value.strip()


def resolve_test_url(template: dict, api_url: str, custom_test_url: str = "") -> str:
    if not template:
        return custom_test_url.strip()
    test_url = str(template.get("test_url") or "")
    if template.get("test_url_editable") and custom_test_url.strip():
        return custom_test_url.strip()
    if not template.get("url_editable") or not api_url:
        return test_url
    if template.get("test_path"):
        return server_address(template, api_url.strip()) + str(template["test_path"])
    target = urlsplit(api_url)
    source = urlsplit(str(template.get("url") or ""))
    check = urlsplit(test_url)
    prefix = (
        target.path[: -len(source.path)]
        if source.path and target.path.endswith(source.path)
        else ""
    )
    return urlunsplit(
        (target.scheme, target.netloc, prefix + check.path, check.query, "")
    )
