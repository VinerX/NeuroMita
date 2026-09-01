from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.rag.graph.entity_typing import (
    build_typing_prompt,
    parse_typing_response,
    reclassify_untyped_entities,
)


class _FakeStore:
    """Минимальный дубль GraphStore для теста оркестрации."""

    def __init__(self, untyped):
        self._untyped = list(untyped)
        self.updates = {}  # id -> type

    def get_untyped_entities(self, limit=2000):
        return [dict(e) for e in self._untyped]

    def get_entity_relation_context(self, entity_id, limit=5):
        return []

    def set_entity_type(self, entity_id, entity_type):
        if entity_type not in ("person", "place", "thing", "concept"):
            return False
        self.updates[int(entity_id)] = entity_type
        return True


class BuildPromptTests(unittest.TestCase):
    def test_includes_names_and_hints(self):
        prompt = build_typing_prompt([
            {"name": "moscow", "context": ["mita lives in moscow"]},
            {"name": "alice"},
        ])
        self.assertIn("moscow", prompt)
        self.assertIn("hints: mita lives in moscow", prompt)
        self.assertIn("- alice", prompt)

    def test_skips_blank_names(self):
        prompt = build_typing_prompt([{"name": ""}, {"name": "chess"}])
        self.assertIn("- chess", prompt)
        self.assertNotIn("- \n", prompt)


class ParseResponseTests(unittest.TestCase):
    def test_plain_json(self):
        out = parse_typing_response('{"alice":"person","moscow":"place"}')
        self.assertEqual(out, {"alice": "person", "moscow": "place"})

    def test_markdown_wrapped(self):
        raw = "```json\n{\"chess\": \"concept\"}\n```"
        self.assertEqual(parse_typing_response(raw), {"chess": "concept"})

    def test_ignores_invalid_types_and_lowercases_keys(self):
        out = parse_typing_response('{"Alice":"PERSON","weird":"animal"}')
        self.assertEqual(out, {"alice": "person"})

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_typing_response("no json here"), {})
        self.assertEqual(parse_typing_response(""), {})


class ReclassifyTests(unittest.TestCase):
    def test_updates_only_non_thing(self):
        store = _FakeStore([
            {"id": 1, "name": "moscow"},
            {"id": 2, "name": "alice"},
            {"id": 3, "name": "blob"},  # модель вернёт thing → без изменений
        ])

        def generate(prompt):
            return '{"moscow":"place","alice":"person","blob":"thing"}'

        res = reclassify_untyped_entities(store, generate, batch_size=10)
        self.assertEqual(res["total"], 3)
        self.assertEqual(res["updated"], 2)
        self.assertEqual(res["unchanged"], 1)
        self.assertEqual(store.updates, {1: "place", 2: "person"})

    def test_cancel_via_progress_cb_raises_propagates(self):
        store = _FakeStore([{"id": i, "name": f"e{i}"} for i in range(5)])

        def generate(prompt):
            return "{}"

        class _Stop(Exception):
            pass

        def prog(done, total):
            raise _Stop()

        with self.assertRaises(_Stop):
            reclassify_untyped_entities(store, generate, batch_size=2, progress_cb=prog)

    def test_empty_store(self):
        res = reclassify_untyped_entities(_FakeStore([]), lambda p: "{}")
        self.assertEqual(res, {"total": 0, "updated": 0, "unchanged": 0, "batches": 0})


if __name__ == "__main__":
    unittest.main()
