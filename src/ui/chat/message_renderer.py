"""
message_renderer — widget-based message rendering for the chat.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt
from utils import _
from ui.chat.chat_delegate import ChatMessageDelegate
from ui.chat.message_widget import MessageWidget, ThinkBlockWidget, ImageWidget, AVATAR_SIZE, _get_avatar_pixmap
from ui.chat.message_actions_presentation import (
    DeleteChatMessage,
    EditChatMessage,
    RateChatSample,
    RegenerateChat,
    RegenerateChatFrom,
    ViewChatSampleContext,
)
from ui.chat.structured_panel import StructuredOutputPanel

def _strip_hidden_image_descriptions(text: str) -> str:
    import re

    if not text:
        return ""

    cleaned = str(text)
    cleaned = re.sub(
        r"<image_description\b[^>]*>.*?</image_description\s*>",
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(r"^\s*\[Scene:[^\n]*\]\s*$", "", cleaned, flags=re.MULTILINE)

    lines = cleaned.splitlines()
    kept: list[str] = []
    skipping_image_block = False

    for line in lines:
        stripped = line.strip()
        if not skipping_image_block and re.match(r"^\[Image(?:\s+\d+)?:", stripped):
            needs_multiline_skip = (not stripped.endswith("]")) or ("{" in stripped and not stripped.endswith("}]"))
            if needs_multiline_skip:
                skipping_image_block = True
            continue

        if skipping_image_block:
            if stripped.endswith("}]") or stripped == "]" or stripped.endswith("]"):
                skipping_image_block = False
            continue

        kept.append(line)

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

def _wrap_panel_aligned(panel, role="assistant", parent=None, avatar_pixmap=None):
    """
    Wrap a structured/think panel in a container to align perfectly with the message text bubble.
    Math: Avatar(36) + LayoutSpacing(8) + Tail(8) = 52px.
    """
    wrapper = QWidget(parent)
    wrapper.setStyleSheet("background: transparent; border: none;")
    lay = QHBoxLayout(wrapper)

    # Расчет точного отступа, чтобы рамка панели совпала с рамкой пузырька
    indent = AVATAR_SIZE + 16  # 36 + 8 (spacing) + 8 (tail)

    if role == "assistant":
        if avatar_pixmap is not None:
            lay.setContentsMargins(0, 2, 0, 4)
            avatar = QLabel(wrapper)
            avatar.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
            avatar.setStyleSheet("background: transparent; border: none;")
            avatar.setPixmap(avatar_pixmap)
            lay.setSpacing(8)
            lay.addWidget(avatar, 0, Qt.AlignmentFlag.AlignBottom)
        else:
            lay.setContentsMargins(indent, 2, 0, 4)
            lay.setSpacing(0)
        lay.addWidget(panel)
        lay.addStretch()
    elif role == "user":
        lay.setContentsMargins(0, 2, indent, 4)
        lay.setSpacing(0)
        lay.addStretch()
        lay.addWidget(panel)
    else:
        lay.setContentsMargins(0, 2, 0, 4)
        lay.addWidget(panel)

    return wrapper

STRUCTURED_MODE_OFF   = "Выкл"
STRUCTURED_MODE_BRIEF = "Кратко"
STRUCTURED_MODE_JSON  = "JSON"
_STRUCTURED_MODE_OFF_EN   = "Off"
_STRUCTURED_MODE_BRIEF_EN = "Brief"

def _pop_sample_id_if_collecting(gui) -> str | None:
    return gui.chat_message_actions.consume_pending_sample_id()

def _should_show_rating_controls(gui) -> bool:
    try:
        if not bool(gui._get_setting("SHOW_MESSAGE_RATING_CONTROLS", False)):
            return False
        return gui.chat_message_actions.collection_enabled()
    except Exception:
        return False

def _get_delegate(gui) -> ChatMessageDelegate:
    if hasattr(gui, "chat_delegate") and gui.chat_delegate:
        return gui.chat_delegate
    d = ChatMessageDelegate()
    setattr(gui, "chat_delegate", d)
    return d

def _get_font_size(gui) -> int:
    return int(getattr(gui, '_chat_font_size', None) or gui._get_setting("CHAT_FONT_SIZE", 12))

def _struct_mode(gui) -> str:
    return gui._get_setting("SHOW_STRUCTURED_IN_GUI", STRUCTURED_MODE_OFF)

def _is_struct_off(mode) -> bool:
    return mode in (STRUCTURED_MODE_OFF, _STRUCTURED_MODE_OFF_EN, "", False, None)

def _get_think_blocks(gui) -> dict:
    if not hasattr(gui, '_think_block_widgets'):
        gui._think_block_widgets = {}
        gui._think_block_counter = 0
    return gui._think_block_widgets

def toggle_think_block(gui, block_id: int):
    blocks = _get_think_blocks(gui)
    widget = blocks.get(block_id)
    if widget and hasattr(widget, 'toggle'):
        widget.toggle()

def _group_segments_by_target(segments: list) -> list:
    if not segments:
        return []
    groups = []
    cur_target = segments[0].get("target") or "Player"
    cur_texts = [segments[0].get("text", "")]
    for seg in segments[1:]:
        t = seg.get("target") or "Player"
        if t == cur_target:
            cur_texts.append(seg.get("text", ""))
        else:
            groups.append((cur_target, list(cur_texts)))
            cur_target = t
            cur_texts = [seg.get("text", "")]
    groups.append((cur_target, cur_texts))
    return groups

def _connect_widget_signals(gui, widget: MessageWidget, message_id: str, character_id: str):
    actions = gui.chat_message_actions
    if actions is None or actions.is_closed:
        raise RuntimeError("Chat message actions ViewModel is not attached")

    def on_delete(mid):
        actions.dispatch(DeleteChatMessage(str(mid), str(character_id)))
    def on_edit(mid):
        actions.dispatch(EditChatMessage(str(mid), str(character_id)))
    def on_regenerate(mid):
        actions.dispatch(RegenerateChat(str(character_id)))
    def on_regenerate_from(mid):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
        dlg = QDialog()
        dlg.setWindowTitle(_("Регенерировать", "Regenerate"))
        dlg.setModal(True)
        dlg.setFixedWidth(360)
        dlg.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QLabel { color: #e0e0e0; background: transparent; border: none; }
            QPushButton { background-color: #2a2a2a; color: #e0e0e0; border: 1px solid #444; border-radius: 4px; padding: 6px 16px; font-size: 12px; }
            QPushButton:hover { background-color: #383838; }
            QPushButton#AcceptBtn { background-color: #2a4a2a; border-color: #4a8a4a; color: #90ee90; }
            QPushButton#AcceptBtn:hover { background-color: #3a5a3a; }
        """)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(12)
        lbl = QLabel(_("Все сообщения после этого будут удалены, и Мита ответит заново. Продолжить?", "All messages after this will be deleted and Mita will respond again. Continue?"))
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        no_btn = QPushButton(_("Отмена", "Cancel"))
        no_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(no_btn)
        yes_btn = QPushButton(_("Продолжить", "Continue"))
        yes_btn.setObjectName("AcceptBtn")
        yes_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(yes_btn)
        lay.addLayout(btn_row)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            actions.dispatch(RegenerateChatFrom(str(mid), str(character_id)))

    def on_view_context(sample_id: str, initial_tab: str = "request"):
        actions.dispatch(
            ViewChatSampleContext(str(sample_id or ""), str(initial_tab or "request"))
        )

    def on_view_response_context(sample_id: str):
        on_view_context(sample_id, initial_tab="response")

    widget.delete_requested.connect(on_delete)
    widget.edit_requested.connect(on_edit)
    widget.regenerate_requested.connect(on_regenerate)
    widget.regenerate_from_requested.connect(on_regenerate_from)
    widget.view_context_requested.connect(on_view_context)
    widget.view_response_context_requested.connect(on_view_response_context)

def insert_message(gui, role, content, insert_at_start=False, message_time="", structured_data=None, message_id=None, character_id=None, ui_images=None, sample_id=None):
    font_size = _get_font_size(gui)
    max_bw = int(gui._get_setting("CHAT_MAX_BUBBLE_WIDTH", 600))
    chat_parent = gui.chat_window.get_layout_parent()

    if role == "structured":
        if not gui._get_setting("SHOW_STRUCTURED_IN_GUI", True):
            return
        sd = {}
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "structured":
                    sd = item.get("data") or {}
                    break
        elif isinstance(content, dict):
            sd = content
        if sd:
            mode = _struct_mode(gui)
            display_mode = "json" if mode in (STRUCTURED_MODE_JSON, "JSON") else "brief"
            panel = StructuredOutputPanel(sd, font_size, max_bw, start_expanded=True, mode=display_mode, parent=chat_parent)
            gui.chat_window.add_message_widget(panel, at_start=insert_at_start)
        return

    if role == "think":
        think_text = ""
        speaker_name = ""
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    think_text += item.get("text", "") or item.get("content", "")
                elif isinstance(item, dict) and item.get("type") == "meta":
                    speaker_name = str(item.get("speaker") or item.get("character_name") or item.get("name") or "")
        elif isinstance(content, str):
            think_text = content

        if not speaker_name and hasattr(gui, "_get_character_name"):
            speaker_name = gui._get_character_name()

        block = ThinkBlockWidget(speaker_name, think_text, is_streaming=False, font_size=font_size, max_bubble_width=max_bw, parent=chat_parent)
        blocks = _get_think_blocks(gui)
        gui._think_block_counter += 1
        blocks[gui._think_block_counter - 1] = block

        wrapped = _wrap_panel_aligned(
            block,
            "assistant",
            parent=chat_parent,
            avatar_pixmap=_get_avatar_pixmap(speaker_name, "assistant"),
        )
        gui.chat_window.add_message_widget(wrapped, at_start=insert_at_start)
        return

    _SYS_PREFIX = "[Системное]:"
    if role == "user":
        raw = content if isinstance(content, str) else ""
        if not raw and isinstance(content, list):
            for _item in content:
                if isinstance(_item, dict) and _item.get("type") == "text":
                    raw = _item.get("text") or _item.get("content", "")
                    break
        if isinstance(raw, str) and raw.lstrip().startswith(_SYS_PREFIX):
            role = "system"

    # System notes (engine/context messages like "[Easel drawing]…") are hidden
    # by default — they aren't part of the conversation. Optional via the setting.
    if role == "system" and not bool(gui._get_setting("SHOW_SYSTEM_MESSAGES", False)):
        return

    text_parts = []
    speaker_name = ""
    images = []

    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "meta":
                speaker_name = str(item.get("speaker") or item.get("character_name") or item.get("name") or "")
            elif item.get("type") == "text":
                text_parts.append(item.get("text") or item.get("content", ""))
            elif item.get("type") == "image_url":
                image_url = item.get("image_url", {}).get("url", "")
                if image_url:
                    images.append({
                        "url": image_url,
                        "display_role": item.get("display_role"),
                    })
    elif isinstance(content, str):
        text_parts.append(content)

    if not speaker_name:
        if role == "user":
            speaker_name = _("Вы", "You")
        elif role == "assistant" and hasattr(gui, "_get_character_name"):
            speaker_name = gui._get_character_name()
        elif role in ("system", "event"):
            speaker_name = _("ⓘ Система", "ⓘ System")

    full_text = "".join(text_parts).strip()
    has_any_images = bool(images or ui_images)

    # When ui_images are provided the real images will be shown as bubbles below.
    # Strip the "[Image: ...]" placeholder text so it doesn't clutter the chat.
    if has_any_images:
        full_text = _strip_hidden_image_descriptions(full_text)

    hide_tags = gui._get_setting("HIDE_CHAT_TAGS", False)
    if hide_tags:
        import re
        full_text = re.sub(r'(<([^>]+)>)(.*?)(</\2>)|(<([^>]+)>)', "", full_text, flags=re.DOTALL)
        full_text = re.sub(r' +', ' ', full_text).strip()

    show_ts = bool(gui._get_setting("SHOW_CHAT_TIMESTAMPS", True))
    # System/event notes read cleaner without a timestamp row.
    if role in ("system", "event"):
        show_ts = False
    mode = _struct_mode(gui)
    _pending_struct_panel = None

    if role == "assistant" and structured_data and not _is_struct_off(mode):
        display_mode = "json" if mode in (STRUCTURED_MODE_JSON, "JSON") else "brief"
        start_expanded = bool(gui._get_setting("STRUCTURED_EXPANDED_DEFAULT", False))
        _pending_struct_panel = StructuredOutputPanel(
            structured_data, font_size, max_bw, start_expanded=start_expanded, mode=display_mode, parent=chat_parent
        )
        _think_blocks = _get_think_blocks(gui)
        gui._think_block_counter += 1
        _think_blocks[gui._think_block_counter - 1] = _pending_struct_panel

    _ft_sample_id = sample_id
    if role == "assistant" and not _ft_sample_id:
        _ft_sample_id = _pop_sample_id_if_collecting(gui)
    _show_rating_controls = role == "assistant" and _should_show_rating_controls(gui)

    segments = (structured_data.get("segments") or []) if isinstance(structured_data, dict) else []
    target_groups = _group_segments_by_target(segments) if role == "assistant" and len(segments) > 0 else []

    if len(target_groups) > 1:
        for i, (target, texts) in enumerate(target_groups):
            group_text = " ".join(t.strip() for t in texts).strip()
            if has_any_images:
                group_text = _strip_hidden_image_descriptions(group_text)
            if hide_tags:
                import re
                group_text = re.sub(r'(<([^>]+)>)(.*?)(</\2>)|(<([^>]+)>)', "", group_text, flags=re.DOTALL)
                group_text = re.sub(r' +', ' ', group_text).strip()

            if not group_text:
                continue

            is_last = (i == len(target_groups) - 1)
            is_self = target and speaker_name.lower().startswith(target.lower())
            display_name = f"{speaker_name} → {target}" if target and target.lower() != "player" and not is_self else speaker_name

            # Show avatar only on the last bubble of the split sequence to avoid spam
            show_av = is_last and (role not in ("system", "event", "think", "structured"))

            w = MessageWidget(
                role=role, speaker_name=display_name, content_text=group_text,
                show_avatar=show_av, font_size=font_size, message_time=message_time if is_last else "",
                show_timestamp=show_ts and is_last, max_bubble_width=max_bw,
                sample_id=_ft_sample_id if is_last else None,
                message_id=message_id if is_last else None,
                show_rating_controls=_show_rating_controls if is_last else False,
                rating_callback=lambda sample_id, rating: gui.chat_message_actions.dispatch(
                    RateChatSample(str(sample_id), int(rating))
                ),
                parent=chat_parent
            )
            if message_id and is_last:
                _connect_widget_signals(gui, w, message_id, character_id or "")
            if is_last and _pending_struct_panel is not None:
                w.set_structured_ref(_pending_struct_panel)
            gui.chat_window.add_message_widget(w, at_start=insert_at_start)
    elif full_text:
        msg_widget = MessageWidget(
            role=role, speaker_name=speaker_name, content_text=full_text,
            show_avatar=(role not in ("system", "event", "think", "structured")),
            font_size=font_size, message_time=message_time, show_timestamp=show_ts,
            max_bubble_width=max_bw, sample_id=_ft_sample_id, message_id=message_id,
            show_rating_controls=_show_rating_controls,
            rating_callback=lambda sample_id, rating: gui.chat_message_actions.dispatch(
                RateChatSample(str(sample_id), int(rating))
            ),
            parent=chat_parent
        )
        if message_id:
            _connect_widget_signals(gui, msg_widget, message_id, character_id or "")
        if _pending_struct_panel is not None:
            msg_widget.set_structured_ref(_pending_struct_panel)
        gui.chat_window.add_message_widget(msg_widget, at_start=insert_at_start)

    if _pending_struct_panel is not None:
        wrapped = _wrap_panel_aligned(_pending_struct_panel, role, parent=chat_parent)
        gui.chat_window.add_message_widget(wrapped, at_start=insert_at_start)

    ui_image_entries = list(ui_images or [])
    ui_image_by_url = {
        str(img.get("url") or ""): img
        for img in ui_image_entries
        if isinstance(img, dict) and img.get("url")
    }
    rendered_urls = set()

    # Images from the current live message or reconstructed history.
    for image_entry in images:
        image_url = image_entry.get("url", "") if isinstance(image_entry, dict) else str(image_entry or "")
        image_key = str(image_url or "")
        img_info = ui_image_by_url.get(image_key, {})
        image_role = (
            img_info.get("display_role")
            or (image_entry.get("display_role") if isinstance(image_entry, dict) else None)
            or role
        )
        img_widget = ImageWidget(
            image_url,
            role=image_role,
            max_bubble_width=max_bw,
            description=img_info.get("description", ""),
            parent=chat_parent,
        )
        wrapped_img = _wrap_panel_aligned(img_widget, image_role, parent=chat_parent)
        gui.chat_window.add_message_widget(wrapped_img, at_start=insert_at_start)
        if image_key:
            rendered_urls.add(image_key)

    # Legacy fallback for history entries that still only have UI-side image metadata.
    for img_info in ui_image_entries:
        image_url = str(img_info.get("url", "") or "")
        if not image_url or image_url in rendered_urls:
            continue
        img_widget = ImageWidget(
            image_url,
            role=img_info.get("display_role") or role,
            max_bubble_width=max_bw,
            description=img_info.get("description", ""),
            parent=chat_parent,
        )
        wrapped_img = _wrap_panel_aligned(img_widget, img_info.get("display_role") or role, parent=chat_parent)
        gui.chat_window.add_message_widget(wrapped_img, at_start=insert_at_start)


def _stream_states(gui) -> dict:
    states = getattr(gui, "_stream_render_states", None)
    if not isinstance(states, dict):
        states = {}
        gui._stream_render_states = states
    return states


def _stream_state(gui, stream_id: str, *, create: bool = False) -> dict | None:
    key = str(stream_id or "default")
    states = _stream_states(gui)
    state = states.get(key)
    if state is None and create:
        state = {
            "role": None,
            "first_chunk": True,
            "speaker_name": "",
            "message": None,
            "think_block": None,
        }
        states[key] = state
    return state


def prepare_stream_slot(gui, role="assistant", stream_id="default", speaker_name=""):
    state = _stream_state(gui, stream_id, create=True)
    prev_role = state.get("role")
    font_size = _get_font_size(gui)
    max_bw = int(gui._get_setting("CHAT_MAX_BUBBLE_WIDTH", 600))
    chat_parent = gui.chat_window.get_layout_parent()

    if prev_role == role:
        return
    if prev_role == "think":
        _finalize_streaming_think_block(gui, stream_id, state=state)

    state["role"] = role
    state["first_chunk"] = True
    if speaker_name:
        state["speaker_name"] = str(speaker_name)

    if role == "think":
        name = str(state.get("speaker_name") or "")
        if not name and hasattr(gui, "_get_character_name"):
            name = gui._get_character_name()

        block = ThinkBlockWidget(
            name,
            "",
            is_streaming=True,
            font_size=font_size,
            max_bubble_width=max_bw,
            parent=chat_parent,
        )
        _get_think_blocks(gui)
        gui._think_block_counter += 1
        _get_think_blocks(gui)[gui._think_block_counter - 1] = block
        state["think_block"] = block

        wrapped = _wrap_panel_aligned(block, "assistant", parent=chat_parent)
        gui.chat_window.add_message_widget(wrapped)
        return

    name = str(state.get("speaker_name") or "")
    if not name and role == "assistant" and hasattr(gui, "_get_character_name"):
        name = gui._get_character_name()
    elif not name and role == "user":
        name = _("Вы", "You")

    show_ts = bool(gui._get_setting("SHOW_CHAT_TIMESTAMPS", True))
    sample_id = _pop_sample_id_if_collecting(gui) if role == "assistant" else None
    message = MessageWidget(
        role=role,
        speaker_name=name,
        content_text="",
        show_avatar=(role not in ("system", "event", "think", "structured")),
        font_size=font_size,
        show_timestamp=show_ts,
        max_bubble_width=max_bw,
        sample_id=sample_id,
        show_rating_controls=(
            role == "assistant" and _should_show_rating_controls(gui)
        ),
        rating_callback=lambda sample_id, rating: gui.chat_message_actions.dispatch(
            RateChatSample(str(sample_id), int(rating))
        ),
        parent=chat_parent,
    )
    state["message"] = message
    gui.chat_window.add_message_widget(message)


def append_stream_chunk_slot(gui, chunk, role="assistant", stream_id="default"):
    if not chunk:
        return
    state = _stream_state(gui, stream_id, create=False)
    if state is None or state.get("role") != role:
        prepare_stream_slot(gui, role=role, stream_id=stream_id)
        state = _stream_state(gui, stream_id, create=False)
    if state is None:
        return

    if state.get("first_chunk", False):
        state["first_chunk"] = False
        chunk = str(chunk).lstrip("\n")
        if not chunk:
            return

    if role == "think":
        block = state.get("think_block")
        if block:
            block.append_content(chunk)
    else:
        message = state.get("message")
        if message:
            message.append_text(chunk)
    gui.chat_window.scroll_to_bottom()


def _finalize_streaming_think_block(gui, stream_id="default", *, state=None):
    state = state or _stream_state(gui, stream_id, create=False)
    if state is None:
        return
    block = state.get("think_block")
    if block:
        block.finalize()
    state["think_block"] = None


def attach_structured_to_stream(gui, structured_data: dict, stream_id="default"):
    mode = _struct_mode(gui)
    if _is_struct_off(mode):
        return
    state = _stream_state(gui, stream_id, create=False)
    message = state.get("message") if state else None
    if not message:
        return

    font_size = _get_font_size(gui)
    max_bw = int(gui._get_setting("CHAT_MAX_BUBBLE_WIDTH", 600))
    chat_parent = gui.chat_window.get_layout_parent()
    display_mode = "json" if mode in (STRUCTURED_MODE_JSON, "JSON") else "brief"
    start_expanded = bool(gui._get_setting("STRUCTURED_EXPANDED_DEFAULT", False))

    panel = StructuredOutputPanel(
        structured_data,
        font_size,
        max_bw,
        start_expanded=start_expanded,
        mode=display_mode,
        parent=chat_parent,
    )
    _get_think_blocks(gui)
    gui._think_block_counter += 1
    _get_think_blocks(gui)[gui._think_block_counter - 1] = panel

    segments = (structured_data.get("segments") or []) if isinstance(structured_data, dict) else []
    target_groups = _group_segments_by_target(segments) if segments else []
    speaker_name = getattr(message, "_speaker_name", "") or ""
    stream_sample_id = getattr(message, "_sample_id", None)
    hide_tags = gui._get_setting("HIDE_CHAT_TAGS", False)
    show_ts = bool(gui._get_setting("SHOW_CHAT_TIMESTAMPS", True))

    if len(target_groups) > 1:
        gui.chat_window.remove_widget(message)
        for index, (target, texts) in enumerate(target_groups):
            group_text = " ".join(text.strip() for text in texts).strip()
            if hide_tags:
                import re

                group_text = re.sub(
                    r"(<([^>]+)>)(.*?)(</\2>)|(<([^>]+)>)",
                    "",
                    group_text,
                    flags=re.DOTALL,
                )
                group_text = re.sub(r" +", " ", group_text).strip()

            is_last = index == len(target_groups) - 1
            is_self = target and speaker_name.lower().startswith(target.lower())
            display_name = (
                f"{speaker_name} → {target}"
                if target and target.lower() != "player" and not is_self
                else speaker_name
            )
            widget = MessageWidget(
                role="assistant",
                speaker_name=display_name,
                content_text=group_text,
                show_avatar=is_last,
                font_size=font_size,
                show_timestamp=show_ts and is_last,
                max_bubble_width=max_bw,
                sample_id=stream_sample_id if is_last else None,
                show_rating_controls=(
                    _should_show_rating_controls(gui) and is_last
                ),
                rating_callback=lambda sample_id, rating: gui.chat_message_actions.dispatch(
                    RateChatSample(str(sample_id), int(rating))
                ),
                parent=chat_parent,
            )
            if is_last:
                widget.set_structured_ref(panel)
            gui.chat_window.add_message_widget(widget)
    elif len(target_groups) == 1:
        target, _ = target_groups[0]
        if (
            target
            and target.lower() != "player"
            and not speaker_name.lower().startswith(target.lower())
        ):
            message.set_speaker_name(f"{speaker_name} → {target}")
        message.set_structured_ref(panel)
    else:
        message.set_structured_ref(panel)

    wrapped = _wrap_panel_aligned(panel, "assistant", parent=chat_parent)
    gui.chat_window.add_message_widget(wrapped)
    gui.chat_window.scroll_to_bottom()


def finish_stream_slot(gui, stream_id="default"):
    key = str(stream_id or "default")
    states = _stream_states(gui)
    state = states.get(key)
    if state is None:
        return
    if state.get("role") == "think" or state.get("think_block") is not None:
        _finalize_streaming_think_block(gui, key, state=state)
    states.pop(key, None)
