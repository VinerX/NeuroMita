"""Стриминговый пузырь должен получать message_id и sample_id при финализации.

Регресс: пузырь создаётся на первом чанке, когда ответ ещё не записан в историю
и не сохранён как finetune-сэмпл, — то есть без message_id. А сигналы меню
подключаются только при наличии message_id, поэтому у стримингового сообщения
«Регенерировать» и «Просмотреть контекст запроса» молча ничего не делали, а
пункт «Регенерировать отсюда» вообще не появлялся.
"""
import os
import sys
import unittest
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[2]
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.chat import message_renderer
from ui.chat.message_actions_presentation import ViewChatSampleContext
from ui.chat.message_widget import MessageWidget

_app = QApplication.instance() or QApplication([])


class _Actions:
    is_closed = False

    def __init__(self, pending=None):
        self._pending = pending
        self.dispatched = []

    def consume_pending_sample_id(self):
        sid, self._pending = self._pending, None
        return sid

    def dispatch(self, intent):
        self.dispatched.append(intent)


class _ChatWindow:
    def __init__(self):
        self.removed = []
        self.added = []

    def add_message_widget(self, widget, at_start=False):
        self.added.append(widget)

    def remove_widget(self, widget):
        self.removed.append(widget)

    def get_layout_parent(self):
        return None

    def scroll_to_bottom(self):
        pass


class _Gui:
    def __init__(self, pending_sample=None):
        self.chat_window = _ChatWindow()
        self.chat_message_actions = _Actions(pending_sample)

    def _get_setting(self, key, default=None):
        return default


class FinishStreamBindingTests(unittest.TestCase):
    def _stream_with(self, message, pending_sample=None):
        gui = _Gui(pending_sample)
        gui._stream_render_states = {"default": {"role": "assistant", "message": message, "think_block": None}}
        return gui

    def test_finish_binds_message_id_and_connects_menu(self):
        widget = MessageWidget(role="assistant", speaker_name="Mita", content_text="Привет")
        self.assertIsNone(widget._message_id)  # так пузырь и рождается при стриминге

        gui = self._stream_with(widget)
        message_renderer.finish_stream_slot(gui, "default", message_id="msg-1", character_id="Crazy")

        self.assertEqual(widget._message_id, "msg-1")

        # сигнал теперь доходит до ViewModel, а не в пустоту
        widget.regenerate_requested.emit(widget._message_id)
        self.assertEqual(len(gui.chat_message_actions.dispatched), 1)

    def test_finish_binds_sample_id_collected_after_the_answer(self):
        widget = MessageWidget(role="assistant", speaker_name="Mita", content_text="Привет")
        gui = self._stream_with(widget, pending_sample="smp-9")

        message_renderer.finish_stream_slot(gui, "default", message_id="msg-1", character_id="Crazy")

        self.assertEqual(widget._sample_id, "smp-9")

    def test_explicit_sample_id_wins_over_collector_pop(self):
        # Надёжный id из payload должен использоваться напрямую, а не выдёргиваться
        # из глобального _pending_sample_id коллектора (который мог устареть).
        widget = MessageWidget(role="assistant", speaker_name="Mita", content_text="Привет")
        gui = self._stream_with(widget, pending_sample="stale-pop")

        message_renderer.finish_stream_slot(
            gui, "default", message_id="msg-1", character_id="Crazy", sample_id="reliable-7"
        )

        self.assertEqual(widget._sample_id, "reliable-7")
        # pop не тронут — резервный источник остаётся нетронутым
        self.assertEqual(gui.chat_message_actions._pending, "stale-pop")

    def test_missing_message_id_leaves_widget_untouched(self):
        widget = MessageWidget(role="assistant", speaker_name="Mita", content_text="Привет")
        gui = self._stream_with(widget)

        message_renderer.finish_stream_slot(gui, "default", message_id="", character_id="")

        self.assertIsNone(widget._message_id)
        self.assertEqual(gui.chat_message_actions.dispatched, [])

    def test_finish_without_message_does_not_raise(self):
        gui = _Gui()
        gui._stream_render_states = {"default": {"role": "think", "message": None, "think_block": None}}

        message_renderer.finish_stream_slot(gui, "default", message_id="msg-1", character_id="Crazy")

        self.assertNotIn("default", gui._stream_render_states)

    def test_finish_binds_context_to_every_split_part(self):
        first = MessageWidget(
            role="assistant",
            speaker_name="Crazy Mita",
            content_text="First",
            show_tail=False,
        )
        last = MessageWidget(
            role="assistant",
            speaker_name="Crazy Mita",
            content_text="Last",
        )
        gui = self._stream_with(last)
        gui._stream_render_states["default"]["message_parts"] = [first, last]

        message_renderer.finish_stream_slot(
            gui,
            "default",
            message_id="msg-1",
            character_id="Crazy",
            context_snapshot_id="ctx-1",
        )

        self.assertEqual(first._context_snapshot_id, "ctx-1")
        self.assertEqual(last._context_snapshot_id, "ctx-1")
        self.assertIsNone(first._message_id)
        self.assertEqual(last._message_id, "msg-1")

        first.view_context_requested.emit(first._context_snapshot_id)
        intent = gui.chat_message_actions.dispatched[-1]
        self.assertIsInstance(intent, ViewChatSampleContext)
        self.assertEqual(intent.sample_id, "ctx-1")


class MessageWidgetSetterTests(unittest.TestCase):
    def test_setters_normalize_empty_to_none(self):
        widget = MessageWidget(role="assistant", speaker_name="Mita", content_text="x")
        widget.set_message_id("")
        widget.set_sample_id("")
        self.assertIsNone(widget._message_id)
        self.assertIsNone(widget._sample_id)

    def test_split_part_hides_tail_but_keeps_tail_alignment(self):
        widget = MessageWidget(
            role="assistant",
            speaker_name="Mita",
            content_text="Part",
            show_tail=False,
        )

        self.assertIsNone(widget._card._tail_side)
        self.assertEqual(widget._card._tail_gutter_side, "left")


class SplitMessageRenderingTests(unittest.TestCase):
    def test_loaded_split_parts_share_context_and_only_last_has_tail(self):
        gui = _Gui()

        message_renderer.insert_message(
            gui,
            "assistant",
            [
                {"type": "meta", "speaker": "Crazy Mita"},
                {"type": "text", "text": "Full response"},
            ],
            structured_data={
                "segments": [
                    {"text": "To Kind", "target": "Kind"},
                    {"text": "To Mila", "target": "Mila"},
                ]
            },
            message_id="msg-2",
            character_id="Crazy",
            context_snapshot_id="ctx-2",
        )

        parts = [item for item in gui.chat_window.added if isinstance(item, MessageWidget)]
        self.assertEqual(len(parts), 2)
        first, last = parts
        self.assertIsNone(first._card._tail_side)
        self.assertEqual(last._card._tail_side, "left")
        self.assertEqual(first._context_snapshot_id, "ctx-2")
        self.assertEqual(last._context_snapshot_id, "ctx-2")

        first.view_context_requested.emit(first._context_snapshot_id)
        intent = gui.chat_message_actions.dispatched[-1]
        self.assertIsInstance(intent, ViewChatSampleContext)
        self.assertEqual(intent.sample_id, "ctx-2")


if __name__ == "__main__":
    unittest.main()
