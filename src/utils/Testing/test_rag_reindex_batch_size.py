from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.rag.rag_manager import RAGManager


class RAGReindexBatchSizeTests(unittest.TestCase):
    def test_uses_active_embedding_preset_batch_size(self) -> None:
        rag = RAGManager.__new__(RAGManager)
        rag._get_int_setting = lambda _key, default: default

        with patch(
            "handlers.embedding_presets.resolve_full_config",
            return_value={"extra": {"batch_size": 100}},
        ):
            self.assertEqual(rag._get_reindex_batch_size(), 100)


if __name__ == "__main__":
    unittest.main()
