import io
import base64
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QTextCursor, QColor, QImage, QFont, QPalette, QTextCharFormat
from utils import _
from main_logger import logger
from ui.chat.chat_delegate import ChatMessageDelegate


# ─── Think block constants ───────────────────────────────────────────────────
THINK_DOTS_PHASES = [".  ", ".. ", "..."]
THINK_ARROW_EXPANDED = "▼"
THINK_ARROW_COLLAPSED = "▶"


def _get_delegate(gui) -> ChatMessageDelegate:
    if hasattr(gui, "chat_delegate") and gui.chat_delegate:
        return gui.chat_delegate
    d = ChatMessageDelegate()
    setattr(gui, "chat_delegate", d)
    return d


# ─── Think block helpers ─────────────────────────────────────────────────────

def _get_think_blocks(gui) -> dict:
    if not hasattr(gui, '_think_blocks'):
        gui._think_blocks = {}
        gui._think_block_counter = 0
    return gui._think_blocks


def _make_think_header_fmt(gui, block_id: int) -> QTextCharFormat:
    font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    font = QFont("Arial", font_size)
    font.setBold(True)
    fmt = QTextCharFormat()
    fmt.setForeground(QColor("#aaaaaa"))
    fmt.setFont(font)
    fmt.setAnchor(True)
    fmt.setAnchorHref(f"think://toggle/{block_id}")
    return fmt


def _make_think_content_fmt(gui) -> QTextCharFormat:
    font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    font = QFont("Arial", font_size)
    font.setItalic(True)
    fmt = QTextCharFormat()
    fmt.setForeground(QColor("#b0b0b0"))
    fmt.setFont(font)
    return fmt


def _make_plain_fmt(gui) -> QTextCharFormat:
    font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    font = QFont("Arial", font_size)
    fmt = QTextCharFormat()
    default_color = gui.chat_window.palette().color(QPalette.ColorRole.Text)
    fmt.setForeground(default_color)
    fmt.setFont(font)
    return fmt


def _doc_cursor(gui) -> QTextCursor:
    """Return a fresh cursor on the document (does NOT affect the widget's scroll)."""
    return QTextCursor(gui.chat_window.document())


def _insert_think_header(gui, cursor: QTextCursor, name: str, block_id: int, is_streaming: bool):
    """Insert '▼ {name} думает...' anchor. Returns (header_start, dots_start, header_end)."""
    header_start = cursor.position()
    fmt = _make_think_header_fmt(gui, block_id)
    cursor.insertText(f"{THINK_ARROW_EXPANDED} {name} думает", fmt)
    dots_start = cursor.position()
    initial_dots = THINK_DOTS_PHASES[0] if is_streaming else "..."
    cursor.insertText(initial_dots, fmt)
    header_end = cursor.position()
    return header_start, dots_start, header_end


def start_think_block(gui, name: str, is_streaming: bool = False) -> int:
    """Insert think block header and register it. Returns block_id."""
    blocks = _get_think_blocks(gui)
    block_id = gui._think_block_counter
    gui._think_block_counter += 1

    cursor = _doc_cursor(gui)
    cursor.movePosition(QTextCursor.MoveOperation.End)

    # Blank line before the think header (separates from user message)
    plain_fmt = _make_plain_fmt(gui)
    cursor.insertText("\n", plain_fmt)

    header_start, dots_start, header_end = _insert_think_header(gui, cursor, name, block_id, is_streaming)

    plain_fmt = _make_plain_fmt(gui)
    cursor.insertText("\n", plain_fmt)
    content_start = cursor.position()

    blocks[block_id] = {
        'id': block_id,
        'collapsed': False,
        'name': name,
        'header_start': header_start,
        'dots_start': dots_start,
        'header_end': header_end,
        'content_start': content_start,
        'content_end': content_start,
        'content_text': "",
        'is_streaming': is_streaming,
    }

    if is_streaming:
        gui._current_streaming_think_block_id = block_id
        _start_think_animation(gui)

    gui.chat_window.verticalScrollBar().setValue(
        gui.chat_window.verticalScrollBar().maximum()
    )
    return block_id


def _insert_static_think_block(gui, text: str, name: str, insert_at_start: bool = False):
    """Insert a complete static (non-streaming) collapsible think block."""
    if not hasattr(gui, '_images_in_chat'):
        gui._images_in_chat = []

    blocks = _get_think_blocks(gui)
    block_id = gui._think_block_counter
    gui._think_block_counter += 1

    cursor = _doc_cursor(gui)
    plain_fmt = _make_plain_fmt(gui)
    if insert_at_start:
        cursor.movePosition(QTextCursor.MoveOperation.Start)
    else:
        cursor.movePosition(QTextCursor.MoveOperation.End)
        # Blank line before the think header (separates from user message)
        cursor.insertText("\n", plain_fmt)

    header_start, dots_start, header_end = _insert_think_header(
        gui, cursor, name, block_id, is_streaming=False
    )

    cursor.insertText("\n", plain_fmt)
    content_start = cursor.position()

    content_fmt = _make_think_content_fmt(gui)
    cursor.insertText(text, content_fmt)
    content_end = cursor.position()

    blocks[block_id] = {
        'id': block_id,
        'collapsed': False,
        'name': name,
        'header_start': header_start,
        'dots_start': dots_start,
        'header_end': header_end,
        'content_start': content_start,
        'content_end': content_end,
        'content_text': text,
        'is_streaming': False,
    }

    # footer newlines
    cursor.insertText("\n\n", plain_fmt)

    if not insert_at_start:
        gui.chat_window.verticalScrollBar().setValue(
            gui.chat_window.verticalScrollBar().maximum()
        )


# ─── Animation ───────────────────────────────────────────────────────────────

def _start_think_animation(gui):
    if not hasattr(gui, '_think_anim_timer') or gui._think_anim_timer is None:
        timer = QTimer(gui)
        timer.timeout.connect(lambda: _tick_think_animation(gui))
        gui._think_anim_timer = timer
    gui._think_anim_phase = 0
    if not gui._think_anim_timer.isActive():
        gui._think_anim_timer.start(400)


def _stop_think_animation(gui):
    if hasattr(gui, '_think_anim_timer') and gui._think_anim_timer:
        gui._think_anim_timer.stop()


def _tick_think_animation(gui):
    blocks = _get_think_blocks(gui)
    block_id = getattr(gui, '_current_streaming_think_block_id', None)
    if block_id is None or block_id not in blocks:
        _stop_think_animation(gui)
        return

    block = blocks[block_id]
    if not block.get('is_streaming'):
        _stop_think_animation(gui)
        return

    gui._think_anim_phase = (getattr(gui, '_think_anim_phase', 0) + 1) % 3
    dots = THINK_DOTS_PHASES[gui._think_anim_phase]

    cursor = _doc_cursor(gui)
    dots_start = block['dots_start']
    cursor.setPosition(dots_start)
    cursor.setPosition(dots_start + 3, QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText(dots, _make_think_header_fmt(gui, block_id))
    # Dots replacement is always same length → no position shifts


def _finalize_streaming_think_block(gui):
    """Finalize current streaming think block: lock dots to '...' and stop timer."""
    block_id = getattr(gui, '_current_streaming_think_block_id', None)
    if block_id is None:
        return
    blocks = _get_think_blocks(gui)
    if block_id not in blocks:
        return

    block = blocks[block_id]
    block['is_streaming'] = False

    # Set final '...'
    cursor = _doc_cursor(gui)
    dots_start = block['dots_start']
    cursor.setPosition(dots_start)
    cursor.setPosition(dots_start + 3, QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText("...", _make_think_header_fmt(gui, block_id))

    _stop_think_animation(gui)
    gui._current_streaming_think_block_id = None


# ─── Toggle collapse / expand ─────────────────────────────────────────────────

def toggle_think_block(gui, block_id: int):
    blocks = _get_think_blocks(gui)
    if block_id not in blocks:
        return
    block = blocks[block_id]
    if block.get('is_streaming'):
        return  # don't toggle while streaming
    if block['collapsed']:
        _expand_think_block(gui, block)
    else:
        _collapse_think_block(gui, block)


def _collapse_think_block(gui, block: dict):
    content_start = block['content_start']
    content_end = block['content_end']
    if content_start >= content_end:
        return

    _update_think_arrow(gui, block, THINK_ARROW_COLLAPSED)

    cursor = _doc_cursor(gui)
    cursor.setPosition(content_start)
    cursor.setPosition(content_end, QTextCursor.MoveMode.KeepAnchor)
    cursor.removeSelectedText()

    delta = -(content_end - content_start)
    block['content_end'] = content_start
    block['collapsed'] = True
    _adjust_block_positions(gui, content_end, delta, exclude_id=block['id'])


def _expand_think_block(gui, block: dict):
    content_start = block['content_start']
    _update_think_arrow(gui, block, THINK_ARROW_EXPANDED)

    cursor = _doc_cursor(gui)
    cursor.setPosition(content_start)
    text = block['content_text']
    cursor.insertText(text, _make_think_content_fmt(gui))

    delta = len(text)
    block['content_end'] = content_start + delta
    block['collapsed'] = False
    _adjust_block_positions(gui, content_start, delta, exclude_id=block['id'])

    gui.chat_window.verticalScrollBar().setValue(
        gui.chat_window.verticalScrollBar().maximum()
    )


def _update_think_arrow(gui, block: dict, arrow: str):
    """Replace the ▼/▶ arrow in-place (1 char → 1 char, no position shift)."""
    cursor = _doc_cursor(gui)
    h = block['header_start']
    cursor.setPosition(h)
    cursor.setPosition(h + 1, QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText(arrow, _make_think_header_fmt(gui, block['id']))


def _adjust_block_positions(gui, threshold_pos: int, delta: int, exclude_id: int = -1):
    """Shift all block positions that start at or after threshold_pos by delta."""
    blocks = _get_think_blocks(gui)
    for block in blocks.values():
        if block['id'] == exclude_id:
            continue
        if block['header_start'] >= threshold_pos:
            block['header_start'] += delta
            block['dots_start'] += delta
            block['header_end'] += delta
            block['content_start'] += delta
            block['content_end'] += delta


# ─── Public message renderer API ──────────────────────────────────────────────

def insert_message(gui, role, content, insert_at_start=False, message_time=""):
    if not hasattr(gui, '_images_in_chat'):
        gui._images_in_chat = []

    # ── Think role: collapsible block ────────────────────────────────────────
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

        _insert_static_think_block(gui, think_text, speaker_name, insert_at_start)
        return

    # ── Other roles ──────────────────────────────────────────────────────────
    processed_content_parts = []
    has_image_content = False
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
                continue

            if item.get("type") == "text":
                txt = item.get("text")
                if txt is None:
                    txt = item.get("content", "")
                processed_content_parts.append({"type": "text", "content": txt, "tag": "default"})
            elif item.get("type") == "image_url":
                has_image_content = process_image_for_chat(gui, has_image_content, item, processed_content_parts)

        if has_image_content and not any(
            part["type"] == "text" and part["content"].strip() for part in processed_content_parts
        ):
            processed_content_parts.insert(0, {
                "type": "text",
                "content": _("<Изображение экрана>", "<Screen Image>") + "\n",
                "tag": "default"
            })

    elif isinstance(content, str):
        processed_content_parts.append({"type": "text", "content": content, "tag": "default"})
    else:
        return

    delegate = _get_delegate(gui)
    hide_tags = gui._get_setting("HIDE_CHAT_TAGS", False)

    normalized_parts = []
    for part in processed_content_parts:
        if part["type"] == "text":
            normalized_parts.extend(delegate.split_text_with_tags(part["content"], hide_tags))
        else:
            normalized_parts.append(part)

    cursor = gui.chat_window.textCursor()
    show_timestamps = gui._get_setting("SHOW_CHAT_TIMESTAMPS", False)
    timestamp_str = delegate.get_timestamp(show_timestamps, message_time)

    if insert_at_start:
        cursor.movePosition(QTextCursor.MoveOperation.Start)
    else:
        cursor.movePosition(QTextCursor.MoveOperation.End)

    if show_timestamps and timestamp_str:
        _insert_formatted_text(gui, cursor, timestamp_str, QColor("#888888"), italic=True)

    label_text, label_color, label_bold = delegate.get_label(gui, role, speaker_name=speaker_name)
    _insert_formatted_text(gui, cursor, label_text, label_color, bold=label_bold)

    content_color = delegate.get_content_color(role)

    for part in normalized_parts:
        if part["type"] == "text":
            if part.get("tag") == "tag_green":
                color = delegate.tag_color
            else:
                color = content_color
            _insert_formatted_text(gui, cursor, part["content"], color, italic=False)
        elif part["type"] == "image":
            cursor.insertImage(part["content"])
            cursor.insertText("\n")

    insert_message_end(gui, cursor, role)

    if not insert_at_start:
        gui.chat_window.verticalScrollBar().setValue(gui.chat_window.verticalScrollBar().maximum())


def insert_message_end(gui, cursor=None, role="assistant"):
    if not cursor:
        cursor = gui.chat_window.textCursor()
    if role == "user":
        cursor.insertText("\n")
    elif role == "think":
        cursor.insertText("\n")
    elif role in {"assistant", "system"}:
        cursor.insertText("\n\n")


def insert_speaker_name(gui, cursor=None, role="assistant"):
    delegate = _get_delegate(gui)
    if not cursor:
        cursor = gui.chat_window.textCursor()

    speaker_name = str(getattr(gui, "_stream_speaker_name", "") or "")

    label_text, label_color, label_bold = delegate.get_label(gui, role, speaker_name=speaker_name)
    _insert_formatted_text(gui, cursor, label_text, label_color, bold=label_bold)


def _insert_formatted_text(gui, cursor, text, color=None, bold=False, italic=False):
    char_format = cursor.charFormat()

    new_format = QTextCharFormat()

    if color:
        new_format.setForeground(color)
    else:
        default_text_color = gui.chat_window.palette().color(QPalette.ColorRole.Text)
        new_format.setForeground(default_text_color)

    font = QFont("Arial", int(gui._get_setting("CHAT_FONT_SIZE", 12)))
    font.setBold(bold)
    font.setItalic(italic)
    new_format.setFont(font)

    cursor.insertText(text, new_format)


def append_message(gui, text, color=None, italic=False):
    cursor = gui.chat_window.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    _insert_formatted_text(gui, cursor, text, color=color, italic=italic)
    gui.chat_window.verticalScrollBar().setValue(gui.chat_window.verticalScrollBar().maximum())


def prepare_stream_slot(gui, role="assistant"):
    """Подготавливает UI к стримингу для указанной роли."""
    prev_role = getattr(gui, "_stream_current_render_role", None)

    if prev_role is not None and prev_role != role:
        if prev_role == "think":
            _finalize_streaming_think_block(gui)
        insert_message_end(gui, role=prev_role)

    gui._stream_current_render_role = role
    gui._stream_is_first_chunk = True

    if role == "think":
        name = str(getattr(gui, "_stream_speaker_name", "") or "")
        if not name and hasattr(gui, "_get_character_name"):
            name = gui._get_character_name()
        start_think_block(gui, name, is_streaming=True)
    else:
        insert_speaker_name(gui, role=role)


def append_stream_chunk_slot(gui, chunk, role="assistant"):
    # Strip leading newlines from the very first chunk of each streaming block
    if getattr(gui, '_stream_is_first_chunk', False):
        gui._stream_is_first_chunk = False
        chunk = chunk.lstrip('\n')
        if not chunk:
            return

    delegate = _get_delegate(gui)
    color = delegate.get_content_color(role)
    italic = (role == "think")
    append_message(gui, chunk, color=color, italic=italic)

    if role == "think":
        block_id = getattr(gui, '_current_streaming_think_block_id', None)
        if block_id is not None:
            blocks = _get_think_blocks(gui)
            if block_id in blocks:
                blocks[block_id]['content_text'] += chunk
                blocks[block_id]['content_end'] += len(chunk)


def finish_stream_slot(gui):
    current_role = getattr(gui, "_stream_current_render_role", "assistant")
    if current_role == "think":
        _finalize_streaming_think_block(gui)
    insert_message_end(gui, role=current_role)
    gui._stream_current_render_role = None


def process_image_for_chat(gui, has_image_content, item, processed_content_parts):
    image_data_base64 = item.get("image_url", {}).get("url", "")
    if image_data_base64.startswith("data:image/jpeg;base64,"):
        image_data_base64 = image_data_base64.replace("data:image/jpeg;base64,", "")
    elif image_data_base64.startswith("data:image/png;base64,"):
        image_data_base64 = image_data_base64.replace("data:image/png;base64,", "")
    try:
        from PIL import Image
        image_bytes = base64.b64decode(image_data_base64)
        image = Image.open(io.BytesIO(image_bytes))
        max_width = 400
        max_height = 300
        original_width, original_height = image.size
        if original_width > max_width or original_height > max_height:
            ratio = min(max_width / original_width, max_height / original_height)
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        image_bytes = io.BytesIO()
        image.save(image_bytes, format='PNG')
        image_bytes.seek(0)
        qimage = QImage()
        qimage.loadFromData(image_bytes.getvalue())
        processed_content_parts.append({"type": "image", "content": qimage})
        has_image_content = True
    except Exception as e:
        logger.error(f"Ошибка при декодировании или обработке изображения: {e}")
        processed_content_parts.append({"type": "text", "content": _("<Ошибка загрузки изображения>", "<Image load error>")})
    return has_image_content
