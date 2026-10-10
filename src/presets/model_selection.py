from collections.abc import Sequence


def select_catalog_model(current: str, models: Sequence[str], preferred: str = '') -> str:
    if current in models:
        return current
    if preferred in models:
        return preferred
    return models[0] if models else current
