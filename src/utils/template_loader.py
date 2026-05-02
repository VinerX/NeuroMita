"""Utility for loading optional template files with fallback to defaults."""

import os
from main_logger import logger


def load_optional_template(base_path: str, rel_path: str, default: str) -> str:
    """Load a template file from base_path/rel_path. Return default if not found."""
    if not base_path:
        return default
    full = os.path.join(base_path, rel_path)
    if not os.path.isfile(full):
        return default
    try:
        with open(full, encoding="utf-8") as f:
            content = f.read()
        return content if content.strip() else default
    except Exception as e:
        logger.warning(f"Failed to load template '{full}': {e}")
        return default
