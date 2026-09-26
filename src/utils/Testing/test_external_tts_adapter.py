from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


_ADAPTER_PATH = Path(__file__).resolve().parents[3] / "extra" / "external_tts_adapter" / "adapter.py"
_SPEC = importlib.util.spec_from_file_location("external_tts_adapter", _ADAPTER_PATH)
adapter = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(adapter)


class ExternalTTSAdapterTests(unittest.TestCase):
    def test_refuses_start_without_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "NEUROMITA_API_KEY"):
                adapter.require_api_key()

    def test_requires_configured_api_key(self):
        with patch.dict(os.environ, {"NEUROMITA_API_KEY": "long-test-secret"}, clear=True):
            self.assertEqual(adapter.require_api_key(), "long-test-secret")

    def test_health_and_synthesis_share_bearer_auth(self):
        with patch.dict(os.environ, {"NEUROMITA_API_KEY": "secret"}, clear=True):
            with self.assertRaises(adapter.web.HTTPUnauthorized):
                adapter.auth(type("Request", (), {"headers": {}})())
            adapter.auth(type("Request", (), {"headers": {"Authorization": "Bearer secret"}})())
