from collections.abc import Sequence


def normalize_catalog_models(models: object) -> list[str]:
    if not isinstance(models, (list, tuple)):
        return []
    return list(dict.fromkeys(model.strip() for model in models if isinstance(model, str) and model.strip()))


def select_catalog_model(current: str, models: Sequence[str], preferred: str = '') -> str:
    if current in models:
        return current
    if preferred in models:
        return preferred
    return models[0] if models else current
