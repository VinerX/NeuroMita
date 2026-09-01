from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from handlers.llm_providers.gemini_provider import GeminiProvider


def _format(messages):
    provider = GeminiProvider.__new__(GeminiProvider)
    return provider._format_messages_for_gemini_api(messages)


def _texts(parts):
    return [p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p]


class GeminiMessageOrderTests(unittest.TestCase):
    """Позиция служебных блоков внутри диалога должна доезжать до модели.

    Регрессия: раньше ВСЕ system-сообщения, независимо от места, склеивались в
    system_instruction. Блоки вроде [Current State], которые промпт ставит
    вплотную к реплике игрока, уезжали в начало запроса и теряли смысл.
    """

    def test_leading_system_goes_to_system_instruction(self):
        out = _format([
            {"role": "system", "content": "персона"},
            {"role": "system", "content": "формат ответа"},
            {"role": "user", "content": "привет"},
        ])

        self.assertEqual(["персона", "формат ответа"], _texts(out["system_instruction"]["parts"]))
        self.assertEqual(1, len(out["contents"]))

    def test_system_inside_dialogue_keeps_its_place(self):
        out = _format([
            {"role": "system", "content": "персона"},
            {"role": "user", "content": "привет"},
            {"role": "assistant", "content": "ответ"},
            {"role": "system", "content": "[Current State] Time: 19:43:04"},
            {"role": "user", "content": "вопрос"},
        ])

        roles = [c["role"] for c in out["contents"]]
        self.assertEqual(["user", "model", "user", "user"], roles)

        # блок стоит ровно перед репликой игрока, а не в начале запроса
        self.assertIn("[Current State]", _texts(out["contents"][2]["parts"])[0])
        self.assertEqual(["вопрос"], _texts(out["contents"][3]["parts"]))

        # и не утёк в статическую инструкцию
        self.assertEqual(["персона"], _texts(out["system_instruction"]["parts"]))

    def test_inline_system_is_tagged(self):
        out = _format([
            {"role": "user", "content": "привет"},
            {"role": "system", "content": "служебное"},
        ])
        self.assertEqual("[SYSTEM INFO]\nслужебное", _texts(out["contents"][1]["parts"])[0])

    def test_volatile_block_does_not_touch_system_instruction(self):
        """Статическая часть обязана совпадать между ходами — иначе кэш промахивается."""
        def build(clock):
            return _format([
                {"role": "system", "content": "персона"},
                {"role": "user", "content": "привет"},
                {"role": "system", "content": f"[Current State] Time: {clock}"},
                {"role": "user", "content": "вопрос"},
            ])["system_instruction"]

        self.assertEqual(build("19:43:04"), build("19:44:11"))

    def test_empty_system_does_not_create_empty_message(self):
        out = _format([
            {"role": "user", "content": "привет"},
            {"role": "system", "content": ""},
        ])
        self.assertEqual(1, len(out["contents"]))

    def test_tag_survives_image_only_block(self):
        out = _format([
            {"role": "user", "content": "привет"},
            {"role": "system", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
            ]},
        ])
        parts = out["contents"][1]["parts"]
        self.assertEqual("[SYSTEM INFO]", parts[0].get("text"))
        self.assertIn("inline_data", parts[1])

    def test_assistant_maps_to_model(self):
        out = _format([
            {"role": "user", "content": "привет"},
            {"role": "assistant", "content": "ответ"},
        ])
        self.assertEqual(["user", "model"], [c["role"] for c in out["contents"]])


if __name__ == "__main__":
    unittest.main()
