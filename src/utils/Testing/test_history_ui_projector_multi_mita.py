from __future__ import annotations

import ast
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import Mock


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.history_ui_projector import HistoryUiProjector


def _load_fix_projected_ui_message():
    code = (PROJECT_SRC / "controllers" / "model_controller.py").read_text(encoding="utf-8")
    module = ast.parse(code)
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "ModelController":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_fix_projected_ui_message":
                    method_src = ast.get_source_segment(code, item)
                    namespace: dict[str, object] = {}
                    exec(
                        "class Dummy:\n" + textwrap.indent(textwrap.dedent(method_src), "    "),
                        namespace,
                    )
                    return namespace["Dummy"]()._fix_projected_ui_message
    raise RuntimeError("_fix_projected_ui_message not found")


def _load_history_method():
    code = (PROJECT_SRC / "controllers" / "model_controller.py").read_text(encoding="utf-8")
    module = ast.parse(code)
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "ModelController":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_on_load_history":
                    method_src = ast.get_source_segment(code, item)
                    namespace = {"Event": object}
                    exec(
                        "class Dummy:\n" + textwrap.indent(textwrap.dedent(method_src), "    "),
                        namespace,
                    )
                    return namespace["Dummy"]()
    raise RuntimeError("_on_load_history not found")


class MultiMitaHistoryProjectionTests(unittest.TestCase):
    def test_non_player_user_role_is_rendered_as_assistant_when_speaker_is_other_mita(self):
        projector = HistoryUiProjector()

        projected = projector.project_for_ui(
            [
                {
                    "role": "user",
                    "speaker": "Crazy Mita",
                    "sender": "Crazy Mita",
                    "target": "Kind Mita",
                    "content": "Ты серьёзно?",
                }
            ]
        )

        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["role"], "assistant")
        self.assertEqual(projected[0]["content"][0]["type"], "meta")
        self.assertEqual(projected[0]["content"][0]["speaker"], "Crazy Mita → Kind Mita")

    def test_filtered_history_rows_do_not_change_the_next_message_identity(self):
        projector = HistoryUiProjector()

        projected = projector.project_for_ui(
            [
                {"role": "user", "speaker": "Player", "content": "   "},
                {
                    "role": "assistant",
                    "speaker": "Kind Mita",
                    "sender": "Kind Mita",
                    "content": "I am Kind Mita",
                },
            ]
        )

        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["role"], "assistant")
        self.assertEqual(projected[0]["speaker"], "Kind Mita")

    def test_initial_history_load_keeps_projected_rows_aligned_with_their_identity(self):
        load_history = _load_history_method()
        raw_messages = [
            {"role": "user", "speaker": "Player", "content": "   "},
            {
                "role": "assistant",
                "speaker": "Kind Mita",
                "sender": "Kind Mita",
                "content": "I am Kind Mita",
            },
        ]
        history_manager = Mock()
        history_manager.get_total_messages_count.return_value = len(raw_messages)
        history_manager.get_recent_messages.return_value = raw_messages
        character = Mock(history_manager=history_manager)
        emitted = []
        controller = load_history
        controller._get_current_character_ref = lambda: character
        controller.lazy_load_batch_size = 50
        controller.ui_projector = HistoryUiProjector()
        controller.event_bus = Mock()
        controller.event_bus.emit.side_effect = lambda name, payload: emitted.append((name, payload))

        controller._on_load_history(None)

        payload = emitted[0][1]
        self.assertEqual(payload["messages"][0]["role"], "assistant")
        self.assertEqual(payload["messages"][0]["speaker"], "Kind Mita")

    def test_fix_helper_keeps_other_mita_messages_off_player_side(self):
        fix_message = _load_fix_projected_ui_message()

        fixed = fix_message(
            {"role": "user", "speaker": "Crazy Mita", "sender": "Crazy Mita"},
            {"role": "assistant", "speaker": "Crazy Mita", "sender": "Crazy Mita", "content": "text"},
        )

        self.assertEqual(fixed["role"], "assistant")
        self.assertEqual(fixed["speaker"], "Crazy Mita")

    def test_fix_helper_still_restores_legacy_player_messages(self):
        fix_message = _load_fix_projected_ui_message()

        fixed = fix_message(
            {"role": "user"},
            {"role": "assistant", "content": "Привет"},
        )

        self.assertEqual(fixed["role"], "user")
        self.assertEqual(fixed["speaker"], "Player")
        self.assertEqual(fixed["sender"], "Player")


if __name__ == "__main__":
    unittest.main()
