from __future__ import annotations

import sys
from unittest.mock import patch

from handlers.llm_providers.base import LLMRequest
from handlers.llm_providers.g4f_provider import G4FProvider


def test_missing_g4f_is_not_installed_implicitly() -> None:
    request = LLMRequest(
        model="gpt-3.5-turbo",
        messages=[],
        provider_name="g4f",
    )

    with patch.dict(sys.modules, {"g4f": None, "g4f.client": None}):
        assert G4FProvider()._get_client(request) is None
