"""
message_renderer — widget-based message rendering for the chat.

Creates MessageWidget / ThinkBlockWidget / StructuredOutputPanel instances
and adds them to the ChatWidget scroll area. Replaces the old QTextBrowser
cursor-manipulation approach with proper QWidget controls.

Public API (same function signatures as the old renderer for compatibility):
  insert_message(gui, role, content, ...)
  prepare_stream_slot(gui, role)
  append_stream_chunk_slot(gui, chunk, role)
  finish_stream_slot(gui)
  attach_structured_to_stream(gui, structured_data)
  toggle_think_block(gui, block_id)   — compat stub (widgets toggle themselves)
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout
from PyQt6.QtCore import Qt
from utils import _
from main_logger import logger
from ui.chat.chat_delegate import ChatMessageDelegate
from ui.chat.message_widget import MessageWidget, ThinkBlockWidget, ImageWidget, AVATAR_SIZE
from ui.chat.structured_panel import StructuredOutputPanel
from core.events import get_event_bus, Events


def _wrap_panel_aligned(panel, role="assistant", parent=None, extra_left=0):
    """Wrap a structured panel in a container with left margin to align under message bubble."""
    wrapper = QWidget(parent)  # parent set immediately to avoid HWND flash on Windows
    wrapper.setStyleSheet("background: transparent; border: none;")
    lay = QHBoxLayout(wrapper)
    lay.setContentsMargins(AVATAR_SIZE + 4 + extra_left, 0, 0, 0)  # offset past avatar
    lay.setSpacing(0)
    lay.addWidget(panel)
    lay.addStretch()
    return wrapper


# ── Display mode values (must match combobox options in general_settings.py) ──
STRUCTURED_MODE_OFF   = "Выкл"
STRUCTURED_MODE_BRIEF = "Кратко"
STRUCTURED_MODE_JSON  = "JSON"
_STRUCTURED_MODE_OFF_EN   = "Off"
_STRUCTURED_MODE_BRIEF_EN = "Brief"


def _pop_sample_id_if_collecting() -> str | None:
    """Returns the pending sample_id if finetune collection is active, else None."""
    try:
        from managers.finetune_collector import FineTuneCollector
        fc = FineTuneCollector.instance
        if fc and fc.is_enabled():
            return fc.pop_pending_sample_id()
    except Exception:
        pass
    return None


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


# ─── Think block registry (for toggle_think_block compat) ────────────────────

def _get_think_blocks(gui) -> dict:
    if not hasattr(gui, '_think_block_widgets'):
        gui._think_block_widgets = {}
        gui._think_block_counter = 0
    return gui._think_block_widgets


def toggle_think_block(gui, block_id: int):
    """Compat: toggle a think/structured block by id."""
    blocks = _get_think_blocks(gui)
    widget = blocks.get(block_id)
    if widget and hasattr(widget, 'toggle'):
        widget.toggle()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _group_segments_by_target(segments: list) -> list:
    """Group consecutive segments by target. Returns list of (target, [text, ...]) tuples."""
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


# ─── Public message renderer API ─────────────────────────────────────────────

def _connect_widget_signals(widget: MessageWidget, message_id: str, character_id: str):
    """Connect context menu signals to the event bus."""
    bus = get_event_bus()

    def on_delete(mid):
        bus.emit(Events.Chat.DELETE_MESSAGE, {"message_id": mid, "character_id": character_id})

    def on_edit(mid):
        bus.emit(Events.Chat.DELETE_MESSAGES_FROM, {"message_id": mid, "character_id": character_id, "edit_mode": True})

    def on_regenerate(mid):
        bus.emit(Events.Chat.REGENERATE, {"character_id": character_id})

    def on_regenerate_from(mid):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
        dlg = QDialog()
        dlg.setWindowTitle(_("Регенерировать", "Regenerate"))
        dlg.setModal(True)
        dlg.setFixedWidth(360)
        dlg.setStyleSheet("""
            QDialog { background-color: #1e1e1e; }
            QLabel { color: #e0e0e0; background: transparent; border: none; }
            QPushButton {
                background-color: #2a2a2a;
                color: #e0e0e0;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #383838; }
            QPushButton#AcceptBtn {
                background-color: #2a4a2a;
                border-color: #4a8a4a;
                color: #90ee90;
            }
            QPushButton#AcceptBtn:hover { background-color: #3a5a3a; }
        """)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(12)
        lbl = QLabel(_("Все сообщения после этого будут удалены, и Мита ответит заново. Продолжить?",
                       "All messages after this will be deleted and Mita will respond again. Continue?"))
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
            bus.emit(Events.Chat.REGENERATE_FROM, {"message_id": mid, "character_id": character_id})

    widget.delete_requested.connect(on_delete)
    widget.edit_requested.connect(on_edit)
    widget.regenerate_requested.connect(on_regenerate)
    widget.regenerate_from_requested.connect(on_regenerate_from)


def insert_message(gui, role, content, insert_at_start=False, message_time="", structured_data=None,
                   message_id=None, character_id=None):
    """Insert a complete message into the chat as a widget."""

    font_size = _get_font_size(gui)
    chat_parent = gui.chat_window.get_layout_parent()

    # ── Legacy structured role ──────────────────────────────────────────────
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
            panel = StructuredOutputPanel(sd, font_size, start_expanded=True, mode=display_mode, parent=chat_parent)
            gui.chat_window.add_message_widget(panel, at_start=insert_at_start)
        return

    # ── Think role: collapsible block ───────────────────────────────────────
    if role == "think":
        think_text = ""
        speaker_name = ""
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "meta":
                    speaker_name = str(
                        item.get("speaker")
                        or item.get("character_name")
                        or item.get("name")
                        or ""
                    )
                elif item.get("type") == "text":
                    txt = item.get("text") or item.get("content", "")
                    think_text += txt or ""
        elif isinstance(content, str):
            think_text = content

        if not speaker_name and hasattr(gui, "_get_character_name"):
            speaker_name = gui._get_character_name()

        max_bw = int(gui._get_setting("CHAT_MAX_BUBBLE_WIDTH", 600))
        block = ThinkBlockWidget(speaker_name, think_text, is_streaming=False,
                                 font_size=font_size, max_bubble_width=max_bw, parent=chat_parent)
        blocks = _get_think_blocks(gui)
        block_id = gui._think_block_counter
        gui._think_block_counter += 1
        blocks[block_id] = block

        # Отступ слева (10px от края аватарки — чтобы визуально ровнялось с текстом пузыря)
        wrapped = _wrap_panel_aligned(block, "assistant", parent=chat_parent, extra_left=10)
        gui.chat_window.add_message_widget(wrapped, at_start=insert_at_start)
        return

    # ── Other roles (user, assistant, system) ───────────────────────────────

    # Detect user messages sent with [Системное]: prefix (as_user mode) and
    # render them visually as system bubbles so they look distinct in the chat.
    _SYS_PREFIX = "[Системное]:"
    if role == "user":
        raw = content if isinstance(content, str) else ""
        if not raw and isinstance(content, list):
            for _item in content:
                if isinstance(_item, dict) and _item.get("type") == "text":
                    raw = _item.get("text") or _item.get("content", "")
                    break
        if isinstance(raw, str) and raw.lstrip().startswith(_SYS_PREFIX):
            logger.debug(f"[MessageRenderer] Detected system-as-user message: {raw[:50]}...")
            role = "system"
            # Keep the prefix visible in content, just change role for display
            # (prefix helps understand it's a system message)
            logger.debug(f"[MessageRenderer] Changed role to 'system', content kept as-is: {raw[:50]}...")

    text_parts = []
    speaker_name = ""
    images = []

    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "meta":
                speaker_name = str(
                    item.get("speaker")
                    or item.get("character_name")
                    or item.get("name")
                    or ""
                )
            elif item.get("type") == "text":
                txt = item.get("text")
                if txt is None:
                    txt = item.get("content", "")
                text_parts.append(txt)
            elif item.get("type") == "image_url":
                image_url = item.get("image_url", {}).get("url", "")
                if image_url:
                    images.append(image_url)
    elif isinstance(content, str):
        text_parts.append(content)
    else:
        return

    if not speaker_name:
        if role == "user":
            speaker_name = _("Вы", "You")
        elif role == "assistant" and hasattr(gui, "_get_character_name"):
            speaker_name = gui._get_character_name()
        elif role == "system":
            speaker_name = _("Система", "System")

    full_text = "".join(text_parts).strip()

    # Optionally hide tags
    hide_tags = gui._get_setting("HIDE_CHAT_TAGS", False)
    if hide_tags:
        import re
        pattern = r'(<([^>]+)>)(.*?)(</\2>)|(<([^>]+)>)'
        full_text = re.sub(pattern, "", full_text, flags=re.DOTALL)
        full_text = re.sub(r' +', ' ', full_text).strip()

    show_ts = bool(gui._get_setting("SHOW_CHAT_TIMESTAMPS", True))
    max_bw = int(gui._get_setting("CHAT_MAX_BUBBLE_WIDTH", 600))

    # Build structured panel once (attached to last bubble)
    mode = _struct_mode(gui)
    _pending_struct_panel = None
    if role == "assistant" and structured_data and not _is_struct_off(mode):
        display_mode = "json" if mode in (STRUCTURED_MODE_JSON, "JSON") else "brief"
        start_expanded = bool(gui._get_setting("STRUCTURED_EXPANDED_DEFAULT", False))
        _pending_struct_panel = StructuredOutputPanel(
            structured_data, font_size, start_expanded=start_expanded, mode=display_mode,
            attached_to_message=True, parent=chat_parent
        )
        blocks = _get_think_blocks(gui)
        block_id = gui._think_block_counter
        gui._think_block_counter += 1
        blocks[block_id] = _pending_struct_panel

    # Pop finetune sample_id once per assistant message (only when collection is on)
    _ft_sample_id = _pop_sample_id_if_collecting() if role == "assistant" else None

    # Split into multiple bubbles when segments have different consecutive targets
    segments = (structured_data.get("segments") or []) if isinstance(structured_data, dict) else []
    target_groups = _group_segments_by_target(segments) if role == "assistant" and len(segments) > 0 else []

    if len(target_groups) > 1:
        for i, (target, texts) in enumerate(target_groups):
            group_text = " ".join(t.strip() for t in texts).strip()
            if hide_tags:
                import re
                pattern = r'(<([^>]+)>)(.*?)(</\2>)|(<([^>]+)>)'
                group_text = re.sub(pattern, "", group_text, flags=re.DOTALL)
                group_text = re.sub(r' +', ' ', group_text).strip()
            is_last = (i == len(target_groups) - 1)
            is_self = target and speaker_name.lower().startswith(target.lower())
            display_name = f"{speaker_name} → {target}" if target and target.lower() != "player" and not is_self else speaker_name
            w = MessageWidget(
                role=role,
                speaker_name=display_name,
                content_text=group_text,
                show_avatar=(role not in ("system", "think", "structured")),
                font_size=font_size,
                message_time=message_time if is_last else "",
                show_timestamp=show_ts and is_last,
                max_bubble_width=max_bw,
                sample_id=_ft_sample_id if is_last else None,
                message_id=message_id if is_last else None,
                parent=chat_parent
            )
            if message_id and is_last:
                _connect_widget_signals(w, message_id, character_id or "")
            if is_last and _pending_struct_panel is not None:
                w.set_structured_ref(_pending_struct_panel)
            gui.chat_window.add_message_widget(w, at_start=insert_at_start)
    else:
        msg_widget = MessageWidget(
            role=role,
            speaker_name=speaker_name,
            content_text=full_text,
            show_avatar=(role not in ("system", "think", "structured")),
            font_size=font_size,
            message_time=message_time,
            show_timestamp=show_ts,
            max_bubble_width=max_bw,
            sample_id=_ft_sample_id,
            message_id=message_id,
            parent=chat_parent
        )
        if message_id:
            _connect_widget_signals(msg_widget, message_id, character_id or "")
        if _pending_struct_panel is not None:
            msg_widget.set_structured_ref(_pending_struct_panel)
        gui.chat_window.add_message_widget(msg_widget, at_start=insert_at_start)

    # Add structured panel as separate widget right after the last bubble
    if _pending_struct_panel is not None:
        wrapped = _wrap_panel_aligned(_pending_struct_panel, role,
                                       parent=gui.chat_window.get_layout_parent())
        gui.chat_window.add_message_widget(wrapped, at_start=insert_at_start)

    # Add images as separate widgets
    for image_data in images:
        img_widget = ImageWidget(image_data, role=role, parent=chat_parent)
        gui.chat_window.add_message_widget(img_widget, at_start=insert_at_start)


# ─── Streaming API ───────────────────────────────────────────────────────────

def prepare_stream_slot(gui, role="assistant"):
    """Create a new message widget for the incoming stream."""
    prev_role = getattr(gui, "_stream_current_render_role", None)
    font_size = _get_font_size(gui)
    chat_parent = gui.chat_window.get_layout_parent()

    if prev_role is not None and prev_role != role:
        if prev_role == "think":
            _finalize_streaming_think_block(gui)

    gui._stream_current_render_role = role
    gui._stream_is_first_chunk = True

    if role == "think":
        name = str(getattr(gui, "_stream_speaker_name", "") or "")
        if not name and hasattr(gui, "_get_character_name"):
            name = gui._get_character_name()

        max_bw = int(gui._get_setting("CHAT_MAX_BUBBLE_WIDTH", 600))
        block = ThinkBlockWidget(name, "", is_streaming=True, font_size=font_size, max_bubble_width=max_bw, parent=chat_parent)
        blocks = _get_think_blocks(gui)
        block_id = gui._think_block_counter
        gui._think_block_counter += 1
        blocks[block_id] = block
        gui._current_streaming_think_block = block

        # Сдвигаем блок размышлений при стриминге еще на 20px правее
        wrapped = _wrap_panel_aligned(block, "assistant", parent=chat_parent, extra_left=10)
        gui.chat_window.add_message_widget(wrapped)
    else:
        speaker_name = str(getattr(gui, "_stream_speaker_name", "") or "")
        if not speaker_name and role == "assistant" and hasattr(gui, "_get_character_name"):
            speaker_name = gui._get_character_name()
        elif not speaker_name and role == "user":
            speaker_name = _("Вы", "You")

        show_ts = bool(gui._get_setting("SHOW_CHAT_TIMESTAMPS", True))
        max_bw = int(gui._get_setting("CHAT_MAX_BUBBLE_WIDTH", 600))
        _ft_stream_sample_id = _pop_sample_id_if_collecting() if role == "assistant" else None
        msg = MessageWidget(
            role=role,
            speaker_name=speaker_name,
            content_text="",
            show_avatar=(role not in ("system", "think", "structured")),
            font_size=font_size,
            show_timestamp=show_ts,
            max_bubble_width=max_bw,
            sample_id=_ft_stream_sample_id,
            parent=chat_parent
        )
        gui._current_stream_message = msg
        gui.chat_window.add_message_widget(msg)


def append_stream_chunk_slot(gui, chunk, role="assistant"):
    """Append a text chunk to the current streaming message."""
    if getattr(gui, '_stream_is_first_chunk', False):
        gui._stream_is_first_chunk = False
        chunk = chunk.lstrip('\n')
        if not chunk:
            return

    if role == "think":
        block = getattr(gui, '_current_streaming_think_block', None)
        if block:
            block.append_content(chunk)
    else:
        msg = getattr(gui, '_current_stream_message', None)
        if msg:
            msg.append_text(chunk)

    # Auto-scroll
    gui.chat_window.scroll_to_bottom()


def _finalize_streaming_think_block(gui):
    block = getattr(gui, '_current_streaming_think_block', None)
    if block:
        block.finalize()
    gui._current_streaming_think_block = None


def attach_structured_to_stream(gui, structured_data: dict):
    """Retroactively attach structured output panel to the just-finished stream message.

    Also handles per-target bubble splitting: if structured_data has segments with multiple
    distinct targets, replaces the single stream bubble with per-target MessageWidgets.
    """
    mode = _struct_mode(gui)
    if _is_struct_off(mode):
        return

    msg = getattr(gui, '_current_stream_message', None)
    if not msg:
        return

    font_size = _get_font_size(gui)
    display_mode = "json" if mode in (STRUCTURED_MODE_JSON, "JSON") else "brief"
    start_expanded = bool(gui._get_setting("STRUCTURED_EXPANDED_DEFAULT", False))
    chat_parent = gui.chat_window.get_layout_parent()
    show_ts = bool(gui._get_setting("SHOW_CHAT_TIMESTAMPS", True))
    max_bw = int(gui._get_setting("CHAT_MAX_BUBBLE_WIDTH", 600))
    hide_tags = gui._get_setting("HIDE_CHAT_TAGS", False)

    panel = StructuredOutputPanel(
        structured_data, font_size, start_expanded=start_expanded, mode=display_mode,
        attached_to_message=True, parent=chat_parent
    )

    blocks = _get_think_blocks(gui)
    block_id = gui._think_block_counter
    gui._think_block_counter += 1
    blocks[block_id] = panel

    # Check if we need to split into multiple per-target bubbles
    segments = (structured_data.get("segments") or []) if isinstance(structured_data, dict) else []
    target_groups = _group_segments_by_target(segments) if segments else []
    speaker_name = getattr(msg, '_speaker_name', '') or ''

    # Carry over the finetune sample_id from the original stream widget
    _stream_sample_id = getattr(msg, '_sample_id', None)

    if len(target_groups) > 1:
        # Replace the single stream bubble with per-target bubbles
        gui.chat_window.remove_widget(msg)
        for i, (target, texts) in enumerate(target_groups):
            group_text = " ".join(t.strip() for t in texts).strip()
            if hide_tags:
                import re
                pattern = r'(<([^>]+)>)(.*?)(</\2>)|(<([^>]+)>)'
                group_text = re.sub(pattern, "", group_text, flags=re.DOTALL)
                group_text = re.sub(r' +', ' ', group_text).strip()
            is_last = (i == len(target_groups) - 1)
            is_self = target and speaker_name.lower().startswith(target.lower())
            display_name = f"{speaker_name} → {target}" if target and target.lower() != "player" and not is_self else speaker_name
            w = MessageWidget(
                role="assistant",
                speaker_name=display_name,
                content_text=group_text,
                show_avatar=True,
                font_size=font_size,
                show_timestamp=show_ts and is_last,
                max_bubble_width=max_bw,
                sample_id=_stream_sample_id if is_last else None,
                parent=chat_parent
            )
            if is_last:
                w.set_structured_ref(panel)
            gui.chat_window.add_message_widget(w)
    elif len(target_groups) == 1:
        target, _ = target_groups[0]
        if target and target.lower() != "player":
            is_self = speaker_name.lower().startswith(target.lower())
            if not is_self:
                msg.set_speaker_name(f"{speaker_name} → {target}")
        msg.set_structured_ref(panel)
    else:
        msg.set_structured_ref(panel)

    wrapped = _wrap_panel_aligned(panel, "assistant",
                                   parent=gui.chat_window.get_layout_parent())
    gui.chat_window.add_message_widget(wrapped)
    gui.chat_window.scroll_to_bottom()


def finish_stream_slot(gui):
    """Finalize the current streaming message."""
    current_role = getattr(gui, "_stream_current_render_role", "assistant")
    if current_role == "think":
        _finalize_streaming_think_block(gui)
    gui._stream_current_render_role = None
    gui._current_stream_message = None


# ─── Compat stubs for old API ────────────────────────────────────────────────
# These existed for QTextBrowser cursor manipulation; no longer needed
# but kept as no-ops so callers don't break.

def insert_message_end(gui, cursor=None, role="assistant"):
    pass

def insert_speaker_name(gui, cursor=None, role="assistant"):
    pass

def _insert_formatted_text(gui, cursor, text, color=None, bold=False, italic=False):
    pass

def append_message(gui, text, color=None, italic=False):
    """Compat: append text to the last message widget."""
    msg = gui.chat_window.get_last_message()
    if msg and hasattr(msg, 'append_text'):
        msg.append_text(text)


def process_image_for_chat(gui, has_image_content, item, processed_content_parts):
    """Process an image item for display in chat — pass through as image_url for ImageWidget."""
    image_url = item.get("image_url", {}).get("url", "")
    if image_url:
        # Pass through the full data URI so insert_message creates an ImageWidget
        processed_content_parts.append({"type": "image_url", "image_url": {"url": image_url}})
        has_image_content = True
    else:
        processed_content_parts.append({"type": "text",
                                         "content": _("<Ошибка загрузки изображения>", "<Image load error>")})
    return has_image_content
