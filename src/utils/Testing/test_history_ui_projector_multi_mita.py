from __future__ import annotations

import ast
import sys
import textwrap
import unittest
from pathlib import Path


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
