from types import SimpleNamespace
import base64
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from core.tv_observation import normalize_tv_observation, format_tv_observation, tv_observation_part
from managers.conversation_event_writer import ConversationEventWriter
from managers.history_ui_projector import HistoryUiProjector


TV = {"source": "youtube", "title": "Video", "author": "Channel", "time_seconds": 125,
      "subtitles": "Words from video", "frame_count": 3, "frame_spacing_seconds": 0.3}


def test_tv_context_labels_source_and_separates_player_from_video():
    text = format_tv_observation(TV)
    assert "Video: Video" in text and "Author: Channel" in text
    assert "125.0 seconds" in text and "chronological order" in text
    assert "not images uploaded by the player" in text
    assert "Heard on TV (Youtube): Words from video" in text


def test_tv_metadata_rejects_other_sources_and_nonfinite_numbers():
    assert normalize_tv_observation({"source": "mita_camera"}) == {}
    tv = normalize_tv_observation({**TV, "time_seconds": float("nan"), "frame_count": 999,
                                   "subtitles": "x" * 10000})
    assert tv["time_seconds"] == 0 and tv["frame_count"] == 8
    assert len(tv["subtitles"]) == 4096


def test_tv_observation_survives_history_projection_without_player_text_or_images():
    writer = ConversationEventWriter(character_ref_resolver=lambda _: None)
    message = writer._build_user_event_message(speaker="Crazy", target="Crazy", participants=["Crazy"],
            user_input="", image_data=[], image_source="tv_observer", tv_observation=TV,
            image_descriptions=None, event_type="react", req_id="tv-test", turn_id="tv-turn")
    projected = HistoryUiProjector().project_for_ui([message])
    assert len(projected) == 1
    assert any(part.get("tv_observation", {}).get("author") == "Channel" for part in projected[0]["content"])


def test_player_text_remains_separate_from_tv_observation_in_history():
    writer = ConversationEventWriter(character_ref_resolver=lambda _: None)
    message = writer._build_user_event_message(speaker="Player", target="Crazy", participants=["Crazy"],
            user_input="What do you think?", image_data=[b"frame"], image_source="tv_observer", tv_observation=TV,
            image_descriptions=None, event_type="chat", req_id="tv-test", turn_id="tv-turn")
    assert message["content"][0] == {"type": "text", "text": "What do you think?"}
    assert message["tv_observation"]["source"] == "youtube"
    assert "[TV observation]" in message["content"][1]["text"]
    assert message["content"][2]["type"] == "image_url"


def test_series_widget_is_compact_and_subtitles_can_expand():
    from PyQt6.QtGui import QPixmap, QColor, QFont, QFontDatabase
    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtWidgets import QApplication, QPushButton, QScrollArea
    from ui.chat.image_series_widget import ImageSeriesWidget
    app = QApplication.instance() or QApplication([])
    font_path = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "segoeui.ttf")
    if os.path.exists(font_path):
        QFontDatabase.addApplicationFont(font_path)
    app.setFont(QFont("Segoe UI", 10))
    pixmap = QPixmap(512, 288)
    pixmap.fill(QColor("#8455a2"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    url = "data:image/png;base64," + base64.b64encode(bytes(buffer.data())).decode()
    widget = ImageSeriesWidget([{"url": url}] * 4, tv_observation=TV)
    widget.resize(580, widget.sizeHint().height())
    widget.show()
    app.processEvents()
    assert len(widget._viewers) == 4
    assert widget.height() < 300
    assert widget.findChild(QScrollArea) is not None
    button = widget.findChild(QPushButton)
    button.click()
    assert button.isChecked()
    app.processEvents()
    widget.grab().save(os.path.join(os.environ["TEMP"], "tv-series-preview.png"))
    widget.close()


def test_tv_card_survives_database_codec_roundtrip():
    from core.message_content import MessageContentCodec
    writer = ConversationEventWriter(character_ref_resolver=lambda _: None)
    message = writer._build_user_event_message(speaker="Player", target="Crazy", participants=["Crazy"],
            user_input="My words", image_data=[], image_source="tv_observer", tv_observation=TV,
            image_descriptions=None, event_type="chat", req_id="tv-test", turn_id="tv-turn")
    text, parts = MessageContentCodec.split_for_db(message["content"])
    reconstructed = {**message, "content": MessageContentCodec.merge_from_db(text, parts)}
    projected = HistoryUiProjector().project_for_ui([reconstructed])[0]
    visible_text = [part for part in projected["content"] if part.get("type") == "text" and not part.get("tv_observation")]
    assert visible_text == [{"type": "text", "text": "My words"}]
    assert len([part for part in projected["content"] if part.get("tv_observation")]) == 1


def test_frame_window_preserves_wide_spacing_and_timestamps():
    value = {**TV, "frame_spacing_seconds": 15, "frame_times_seconds": [95, 110, 125]}
    normalized = normalize_tv_observation(value)
    assert normalized["frame_spacing_seconds"] == 15
    assert normalized["frame_times_seconds"] == [95, 110, 125]
    assert "95.0, 110.0, 125.0" in format_tv_observation(value)


def test_tv_system_visibility_keeps_player_words(monkeypatch):
    from PyQt6.QtWidgets import QApplication, QWidget
    from ui.chat import message_renderer as renderer
    from ui.chat.image_series_widget import ImageSeriesWidget
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    widgets = []
    text = []
    class Bubble(QWidget):
        def __init__(self, **kwargs):
            super().__init__(kwargs.get("parent"))
            text.append(kwargs["content_text"])
    monkeypatch.setattr(renderer, "MessageWidget", Bubble)
    settings = {"SHOW_SYSTEM_MESSAGES": False, "SHOW_STRUCTURED_IN_GUI": False}
    gui = SimpleNamespace(_get_setting=lambda key, default=None: settings.get(key, default),
        chat_window=SimpleNamespace(get_layout_parent=lambda: host,
            add_message_widget=lambda widget, **kwargs: widgets.append(widget)))
    content = [{"type": "text", "text": "Player words"}, tv_observation_part(TV)]
    renderer.insert_message(gui, "user", content)
    assert text == ["Player words"]
    assert not host.findChildren(ImageSeriesWidget)
    settings["SHOW_SYSTEM_MESSAGES"] = True
    renderer.insert_message(gui, "user", [tv_observation_part(TV)])
    assert len(host.findChildren(ImageSeriesWidget)) == 1
    host.close()


def test_history_removes_duplicate_system_tv_snapshot_and_marks_past_observation():
    from controllers.history_controller import HistoryController
    controller = HistoryController.__new__(HistoryController)
    controller._time_gap_marker_threshold_seconds = lambda: 0
    controller._action_memory_enabled = lambda: False
    context = format_tv_observation(TV)
    messages = [{"role": "system", "content": context},
        {"role": "user", "content": [{"type": "text", "text": context}], "tv_observation": TV},
        {"role": "assistant", "content": "Already commented"}]
    projected = controller._sanitize_history_for_llm(SimpleNamespace(char_id="Crazy"), messages)
    assert len(projected) == 2
    assert "Past TV observation" in str(projected[0]["content"])
    assert str(projected).count("[TV observation]") == 1
    assert len(messages) == 3


def test_legacy_self_authored_tv_event_is_not_assistant_history():
    from controllers.history_controller import HistoryController
    controller = HistoryController.__new__(HistoryController)
    controller._time_gap_marker_threshold_seconds = lambda: 0
    controller._action_memory_enabled = lambda: False
    original = {"role": "assistant", "speaker": "Crazy", "target": "Crazy",
                "content": [{"type": "text", "text": format_tv_observation(TV)},
                            {"type": "image_url", "image_url": {"url": "frame"}}], "tv_observation": TV}
    projected = controller._sanitize_history_for_llm(SimpleNamespace(char_id="Crazy"), [original])
    assert projected[0]["role"] == "user"
    assert "[To:" not in str(projected) and "Собеседник" not in str(projected)
    assert projected[0]["content"][1]["image_url"]["url"] == "frame"
    assert original["role"] == "assistant"
    ui = HistoryUiProjector().project_for_ui([original])[0]
    assert ui["role"] == "user" and "Crazy →" not in str(ui["content"])


def test_tv_event_classification_preserves_actual_player_words():
    from core.tv_observation import is_tv_observation_event
    assert not is_tv_observation_event({"tv_observation": TV, "content": [
        {"type": "text", "text": "What do you think?"}, tv_observation_part(TV)]})
