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


def _wrap_panel_aligned(panel, role="assistant", parent=None):
    """Wrap a structured panel in a container with left margin to align under message bubble."""
    wrapper = QWidget(parent)  # parent set immediately to avoid HWND flash on Windows
    wrapper.setStyleSheet("background: transparent; border: none;")
    lay = QHBoxLayout(wrapper)
    lay.setContentsMargins(AVATAR_SIZE + 4, 0, 0, 0)  # offset past avatar
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


# ─── Public message renderer API ─────────────────────────────────────────────

def insert_message(gui, role, content, insert_at_start=False, message_time="", structured_data=None):
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

        block = ThinkBlockWidget(speaker_name, think_text, is_streaming=False,
                                  font_size=font_size, parent=chat_parent)
        blocks = _get_think_blocks(gui)
        block_id = gui._think_block_counter
        gui._think_block_counter += 1
        blocks[block_id] = block

        gui.chat_window.add_message_widget(block, at_start=insert_at_start)
        return

    # ── Other roles (user, assistant, system) ───────────────────────────────
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
    msg_widget = MessageWidget(
        role=role,
        speaker_name=speaker_name,
        content_text=full_text,
        show_avatar=(role in ("user", "assistant")),
        font_size=font_size,
        message_time=message_time,
        show_timestamp=show_ts,
        max_bubble_width=max_bw,
        parent=chat_parent
    )

    # Attach structured output panel if available
    mode = _struct_mode(gui)
    if role == "assistant" and structured_data and not _is_struct_off(mode):
        display_mode = "json" if mode in (STRUCTURED_MODE_JSON, "JSON") else "brief"
        start_expanded = bool(gui._get_setting("STRUCTURED_EXPANDED_DEFAULT", False))
        panel = StructuredOutputPanel(
            structured_data, font_size, start_expanded=start_expanded, mode=display_mode,
            attached_to_message=True, parent=chat_parent
        )

        # Register for toggle compat
        blocks = _get_think_blocks(gui)
        block_id = gui._think_block_counter
        gui._think_block_counter += 1
        blocks[block_id] = panel

        msg_widget.set_structured_ref(panel)
        _pending_struct_panel = panel
    else:
        _pending_struct_panel = None

    gui.chat_window.add_message_widget(msg_widget, at_start=insert_at_start)

    # Add structured panel as separate widget right after the message, aligned under bubble
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

        block = ThinkBlockWidget(name, "", is_streaming=True, font_size=font_size, parent=chat_parent)
        blocks = _get_think_blocks(gui)
        block_id = gui._think_block_counter
        gui._think_block_counter += 1
        blocks[block_id] = block
        gui._current_streaming_think_block = block

        gui.chat_window.add_message_widget(block)
    else:
        speaker_name = str(getattr(gui, "_stream_speaker_name", "") or "")
        if not speaker_name and role == "assistant" and hasattr(gui, "_get_character_name"):
            speaker_name = gui._get_character_name()
        elif not speaker_name and role == "user":
            speaker_name = _("Вы", "You")

        show_ts = bool(gui._get_setting("SHOW_CHAT_TIMESTAMPS", True))
        max_bw = int(gui._get_setting("CHAT_MAX_BUBBLE_WIDTH", 600))
        msg = MessageWidget(
            role=role,
            speaker_name=speaker_name,
            content_text="",
            show_avatar=(role in ("user", "assistant")),
            font_size=font_size,
            show_timestamp=show_ts,
            max_bubble_width=max_bw,
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
    """Retroactively attach structured output panel to the just-finished stream message."""
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

    panel = StructuredOutputPanel(
        structured_data, font_size, start_expanded=start_expanded, mode=display_mode,
        attached_to_message=True, parent=chat_parent
    )

    blocks = _get_think_blocks(gui)
    block_id = gui._think_block_counter
    gui._think_block_counter += 1
    blocks[block_id] = panel

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
