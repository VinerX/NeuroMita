"""Backwards-compatible shim. The real implementation lives in
`ui.windows.ai_hub` (split into dialog/widgets/constants/helpers) and styles
in `styles.ai_hub_styles`."""
from __future__ import annotations

from .ai_hub import AIHubDialog

__all__ = ["AIHubDialog"]
