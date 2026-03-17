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

# ─── Structured block constants ──────────────────────────────────────────────
STRUCTURED_HEADER_COLOR  = "#7a9cc4"   # muted blue — header / arrow
STRUCTURED_CONTENT_COLOR = "#9ab5cc"   # lighter blue — default content text
STRUCTURED_KEY_PARAM_COLOR  = "#c8a84b"  # amber — att / bore / stress keys
STRUCTURED_KEY_MEMORY_COLOR = "#7ab870"  # green  — memory keys
STRUCTURED_SEG_HDR_COLOR    = "#8fb0cc"  # blue-grey — "Seg N:" line
STRUCTURED_TEXT_COLOR       = "#d4d4d4"  # near-white — segment text value

STRUCTURED_SEP_LINE = "  " + "─" * 40 + "\n"  # visual container border
STRUCTURED_INDENT   = "    "                    # 4-space indent for content

# Display mode values (must match combobox options in general_settings.py)
STRUCTURED_MODE_OFF   = "Выкл"
STRUCTURED_MODE_BRIEF = "Кратко"
STRUCTURED_MODE_JSON  = "JSON"
# English aliases
_STRUCTURED_MODE_OFF_EN   = "Off"
_STRUCTURED_MODE_BRIEF_EN = "Brief"


def _fmt_val(v: float) -> str:
    """Format a numeric parameter change value with sign and arrow."""
    if v == 0:
        return "±0"
    s = f"+{v:.2g}" if v > 0 else f"{v:.2g}"
    arrow = "↑" if v > 0 else "↓"
    return f"{s}{arrow}"


# ─── Parts type: list of (text, color_or_None) tuples ────────────────────────
# None color means "use the default content color"

def _format_structured_brief(data: dict) -> list:
    """
    Return a list of (text, color | None) pairs for "brief" mode.

    Keys att/bore/stress are highlighted in amber; memory keys in green.
    No emoji. Each segment: text first, then commands.
    """
    parts = []  # (text, color | None)
    C = STRUCTURED_CONTENT_COLOR
    CP = STRUCTURED_KEY_PARAM_COLOR
    CM = STRUCTURED_KEY_MEMORY_COLOR
    CS = STRUCTURED_SEG_HDR_COLOR
    CT = STRUCTURED_TEXT_COLOR

    def p(text, color=None):
        parts.append((text, color))

    att    = data.get("attitude_change", 0) or 0
    bore   = data.get("boredom_change",  0) or 0
    stress = data.get("stress_change",   0) or 0

    I = STRUCTURED_INDENT      # 4 spaces — first-level indent
    I2 = I + "  "              # 6 spaces — second-level indent

    # — Parameter line —
    p(I + "att", CP); p(f" {_fmt_val(att)}   ", C)
    p("bore", CP); p(f" {_fmt_val(bore)}   ", C)
    p("stress", CP); p(f" {_fmt_val(stress)}\n", C)

    # — Segments —
    segments = data.get("segments") or []
    for i, seg in enumerate(segments, 1):
        p(f"\n{I}Seg {i}:\n", CS)
        text = (seg.get("text") or "").strip()
        if text:
            p(f'{I2}"{text}"\n', CT)

        # Collect key: value lines
        field_map = [
            ("emotions",      "emotions"),
            ("animations",    "animations"),
            ("commands",      "commands"),
            ("movement_modes","movement"),
            ("visual_effects","effects"),
            ("clothes",       "clothes"),
            ("music",         "music"),
            ("interactions",  "interactions"),
            ("face_params",   "face"),
        ]
        for field, label in field_map:
            vals = seg.get(field) or []
            if vals:
                p(f"{I2}{label}: ", C)
                p(", ".join(str(v) for v in vals) + "\n", CT)

        for fname, label in [("start_game", "start_game"),
                              ("end_game",   "end_game"),
                              ("target",     "target"),
                              ("hint",       "hint")]:
            val = seg.get(fname)
            if val:
                p(f"{I2}{label}: ", C); p(f"{val}\n", CT)
        if seg.get("allow_sleep") is not None:
            p(f"{I2}allow_sleep: ", C); p(f"{seg['allow_sleep']}\n", CT)

    # — Memory —
    mem_add    = data.get("memory_add") or []
    mem_update = data.get("memory_update") or []
    mem_delete = data.get("memory_delete") or []
    if mem_add or mem_update or mem_delete:
        p(f"\n{I}memory:\n", CM)
        for entry in mem_add:
            if "|" in str(entry):
                priority, content = str(entry).split("|", 1)
                p(f"{I2}+ [{priority.strip()}] {content.strip()}\n", C)
            else:
                p(f"{I2}+ {entry}\n", C)
        for entry in mem_update:
            p(f"{I2}~ {entry}\n", C)
        for entry in mem_delete:
            p(f"{I2}- #{entry}\n", C)

    return parts


def _format_structured_json(data: dict) -> str:
    """Return pretty-printed JSON of the raw structured data."""
    import json
    return json.dumps(data, ensure_ascii=False, indent=2)


def _format_structured_block_text(data: dict) -> str:
    """Legacy plain-text formatter (kept for back-compat, not used in new code)."""
    parts = _format_structured_brief(data)
    return "".join(text for text, _ in parts)


def _build_structured_summary(structured_data: dict) -> str:
    """Build a compact summary string for the structured block header."""
    segs = structured_data.get("segments") or []
    n_segs = len(segs)
    att = structured_data.get("attitude_change", 0) or 0
    bore = structured_data.get("boredom_change", 0) or 0
    stress = structured_data.get("stress_change", 0) or 0
    mem_count = (len(structured_data.get("memory_add") or [])
                 + len(structured_data.get("memory_update") or [])
                 + len(structured_data.get("memory_delete") or []))

    def _arrow(v): return "↑" if v > 0 else ("↓" if v < 0 else "·")
    parts = [f"{n_segs} seg"]
    if att: parts.append(f"att {'+' if att>0 else ''}{att:.2g}{_arrow(att)}")
    if bore: parts.append(f"bore {'+' if bore>0 else ''}{bore:.2g}{_arrow(bore)}")
    if stress: parts.append(f"stress {'+' if stress>0 else ''}{stress:.2g}{_arrow(stress)}")
    if mem_count: parts.append(f"mem ×{mem_count}")
    return "  ·  ".join(parts)


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


def _insert_static_structured_block(gui, text: str, summary: str, insert_at_start: bool = False):
    """Insert a collapsible structured-output block (reuses think block infrastructure)."""
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
        cursor.insertText("\n", plain_fmt)

    # Header: "▼ structured  <summary>"
    font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    from PyQt6.QtGui import QFont
    font = QFont("Arial", font_size)
    font.setBold(True)
    header_fmt = QTextCharFormat()
    header_fmt.setForeground(QColor(STRUCTURED_HEADER_COLOR))
    header_fmt.setFont(font)
    header_fmt.setAnchor(True)
    header_fmt.setAnchorHref(f"think://toggle/{block_id}")

    header_start = cursor.position()
    cursor.insertText(f"{THINK_ARROW_EXPANDED} structured", header_fmt)
    dots_start = cursor.position()
    cursor.insertText("   ", header_fmt)  # 3 spaces (same width as dots in think)
    if summary:
        cursor.insertText(f"  {summary}", header_fmt)
    header_end = cursor.position()

    cursor.insertText("\n", plain_fmt)
    content_start = cursor.position()

    content_fmt = QTextCharFormat()
    content_fmt.setForeground(QColor(STRUCTURED_CONTENT_COLOR))
    font2 = QFont("Courier New", font_size - 1)
    content_fmt.setFont(font2)
    cursor.insertText(text, content_fmt)
    content_end = cursor.position()

    blocks[block_id] = {
        'id': block_id,
        'collapsed': False,
        'name': "structured",
        'header_start': header_start,
        'dots_start': dots_start,
        'header_end': header_end,
        'content_start': content_start,
        'content_end': content_end,
        'content_text': text,
        'is_streaming': False,
    }

    cursor.insertText("\n\n", plain_fmt)

    if not insert_at_start:
        gui.chat_window.verticalScrollBar().setValue(
            gui.chat_window.verticalScrollBar().maximum()
        )


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

    cursor = _doc_cursor(gui)
    fmt = _make_think_header_fmt(gui, block_id)
    dots_start = block['dots_start']

    # "думает" → "думала"  (оба 6 символов → позиции не сдвигаются)
    verb_start = dots_start - 6
    cursor.setPosition(verb_start)
    cursor.setPosition(dots_start, QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText("думала", fmt)

    # Set final '...'
    cursor.setPosition(dots_start)
    cursor.setPosition(dots_start + 3, QTextCursor.MoveMode.KeepAnchor)
    cursor.insertText("...", fmt)

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


def _make_structured_content_fmt(gui) -> QTextCharFormat:
    font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    font = QFont("Courier New", font_size - 1)
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(STRUCTURED_CONTENT_COLOR))
    fmt.setFont(font)
    return fmt


def _insert_structured_content(gui, cursor, content_text, content_parts) -> int:
    """
    Insert structured block content at cursor position (with decorators).
    Adds separator lines above/below and returns the new cursor end position.
    """
    font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    mono_font = QFont("Courier New", font_size - 1)

    sep_fmt = QTextCharFormat()
    sep_fmt.setFont(mono_font)
    sep_fmt.setForeground(QColor(STRUCTURED_HEADER_COLOR))
    cursor.insertText(STRUCTURED_SEP_LINE, sep_fmt)

    if content_parts:
        for text, color in content_parts:
            fmt = QTextCharFormat()
            fmt.setFont(mono_font)
            fmt.setForeground(QColor(color if color else STRUCTURED_CONTENT_COLOR))
            cursor.insertText(text, fmt)
    else:
        # JSON mode — indent every line by STRUCTURED_INDENT
        raw = content_text or ""
        indented = STRUCTURED_INDENT + raw.replace("\n", "\n" + STRUCTURED_INDENT)
        # Remove trailing indent after the final newline
        if raw.endswith("\n"):
            indented = indented[: -len(STRUCTURED_INDENT)]
        fmt = QTextCharFormat()
        fmt.setFont(mono_font)
        fmt.setForeground(QColor(STRUCTURED_CONTENT_COLOR))
        cursor.insertText(indented, fmt)

    cursor.insertText(STRUCTURED_SEP_LINE, sep_fmt)
    return cursor.position()


def _expand_think_block(gui, block: dict):
    content_start = block['content_start']
    _update_think_arrow(gui, block, THINK_ARROW_EXPANDED)

    cursor = _doc_cursor(gui)
    cursor.setPosition(content_start)

    if block.get('name') == "structured":
        new_end = _insert_structured_content(
            gui, cursor,
            block.get('content_text'),
            block.get('content_parts'),
        )
    else:
        text = block['content_text']
        cursor.insertText(text, _make_think_content_fmt(gui))
        new_end = content_start + len(text)

    delta = new_end - content_start
    block['content_end'] = new_end
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

def insert_message(gui, role, content, insert_at_start=False, message_time="", structured_data=None):
    if not hasattr(gui, '_images_in_chat'):
        gui._images_in_chat = []

    # ── Legacy structured role: convert to assistant + structured_data ────────
    if role == "structured":
        # Old code path — extract data and render as standalone block for back-compat
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
            block_text = _format_structured_block_text(sd)
            summary = _build_structured_summary(sd)
            _insert_static_structured_block(gui, block_text, summary, insert_at_start)
        return

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

    struct_mode = gui._get_setting("SHOW_STRUCTURED_IN_GUI", STRUCTURED_MODE_OFF)
    has_structured_display = (
        role == "assistant"
        and bool(structured_data)
        and struct_mode not in (STRUCTURED_MODE_OFF, _STRUCTURED_MODE_OFF_EN, "", False, None)
    )

    struct_block_id = None
    struct_header_start = None
    struct_dots_start = None
    struct_header_end = None
    start_expanded = False

    # ── Timestamp (before diamond) ────────────────────────────────────────────
    if show_timestamps and timestamp_str:
        _insert_formatted_text(gui, cursor, timestamp_str, QColor("#888888"), italic=True)

    # ── Diamond anchor — after timestamp, before label ────────────────────────
    if has_structured_display:
        _get_think_blocks(gui)  # ensures _think_block_counter is initialized
        struct_block_id = gui._think_block_counter
        gui._think_block_counter += 1
        start_expanded = bool(gui._get_setting("STRUCTURED_EXPANDED_DEFAULT", False))

        font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
        diamond_font = QFont("Arial", font_size)
        diamond_font.setBold(True)
        diamond_fmt = QTextCharFormat()
        diamond_fmt.setForeground(QColor(STRUCTURED_HEADER_COLOR))
        diamond_fmt.setFont(diamond_font)
        diamond_fmt.setAnchor(True)
        diamond_fmt.setAnchorHref(f"think://toggle/{struct_block_id}")

        initial_arrow = THINK_ARROW_EXPANDED if start_expanded else THINK_ARROW_COLLAPSED
        struct_header_start = cursor.position()
        cursor.insertText(initial_arrow + " ", diamond_fmt)
        struct_dots_start = struct_header_start + 1  # after the arrow char
        struct_header_end = cursor.position()        # after "▶ " / "▼ "

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

    # ── End of message text ───────────────────────────────────────────────────
    if has_structured_display and role == "assistant":
        # Single \n — content block provides visual separation; trailing \n added after
        cursor.insertText("\n", _make_plain_fmt(gui))
    else:
        insert_message_end(gui, cursor, role)

    # ── Register structured content panel (after message end) ────────────────
    if has_structured_display and struct_block_id is not None:
        content_start = cursor.position()
        content_end = content_start

        if struct_mode in (STRUCTURED_MODE_JSON, "JSON"):
            s_content_text = _format_structured_json(structured_data)
            s_content_parts = None
        else:
            s_content_text = None
            s_content_parts = _format_structured_brief(structured_data)

        if start_expanded:
            content_end = _insert_structured_content(gui, cursor, s_content_text, s_content_parts)

        blocks = _get_think_blocks(gui)
        blocks[struct_block_id] = {
            'id': struct_block_id,
            'collapsed': not start_expanded,
            'name': "structured",
            'header_start': struct_header_start,
            'dots_start': struct_dots_start,
            'header_end': struct_header_end,
            'content_start': content_start,
            'content_end': content_end,
            'content_text': s_content_text or "",
            'content_parts': s_content_parts,
            'is_streaming': False,
        }

        # Always-visible trailing \n: provides gap with next message when collapsed
        cursor.insertText("\n", _make_plain_fmt(gui))

    if not insert_at_start:
        gui.chat_window.verticalScrollBar().setValue(gui.chat_window.verticalScrollBar().maximum())


def _insert_inline_structured_block(
    gui,
    summary: str,
    insert_at_start: bool = False,
    *,
    content_text: str | None = None,
    content_parts: list | None = None,
    start_expanded: bool = False,
):
    """
    Insert a structured-output block right after an assistant message.

    content_text  — plain string (used for JSON mode)
    content_parts — list of (text, color|None) for brief mode
    start_expanded — if True, render expanded immediately
    """
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

    font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    font = QFont("Arial", font_size - 1)
    font.setBold(True)
    header_fmt = QTextCharFormat()
    header_fmt.setForeground(QColor(STRUCTURED_HEADER_COLOR))
    header_fmt.setFont(font)
    header_fmt.setAnchor(True)
    header_fmt.setAnchorHref(f"think://toggle/{block_id}")

    initial_arrow = THINK_ARROW_EXPANDED if start_expanded else THINK_ARROW_COLLAPSED

    header_start = cursor.position()
    cursor.insertText(initial_arrow, header_fmt)
    dots_start = cursor.position()
    cursor.insertText("   ", header_fmt)
    if summary:
        cursor.insertText(f"  {summary}", header_fmt)
    header_end = cursor.position()

    cursor.insertText("\n", plain_fmt)
    content_start = cursor.position()
    content_end = content_start

    if start_expanded:
        content_end = _insert_structured_content(gui, cursor, content_text, content_parts)

    blocks[block_id] = {
        'id': block_id,
        'collapsed': not start_expanded,
        'name': "structured",
        'header_start': header_start,
        'dots_start': dots_start,
        'header_end': header_end,
        'content_start': content_start,
        'content_end': content_end,
        'content_text': content_text or "",
        'content_parts': content_parts,
        'is_streaming': False,
    }


def insert_message_end(gui, cursor=None, role="assistant"):
    if not cursor:
        cursor = gui.chat_window.textCursor()
    if role == "user":
        cursor.insertText("\n")
    elif role in {"think", "structured"}:
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
        # Save label start position for retroactive diamond insertion
        c_pre = _doc_cursor(gui)
        c_pre.movePosition(QTextCursor.MoveOperation.End)
        gui._stream_label_start = c_pre.position()

        insert_speaker_name(gui, role=role)
        # Remember where content starts so we can reapply tag colours after streaming
        c = _doc_cursor(gui)
        c.movePosition(QTextCursor.MoveOperation.End)
        gui._stream_content_start = c.position()


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


def _reformat_streamed_content(gui):
    """Re-apply tag colouring to the content that was just streamed (assistant/system)."""
    content_start = getattr(gui, '_stream_content_start', None)
    if content_start is None:
        return

    delegate = _get_delegate(gui)
    hide_tags = gui._get_setting("HIDE_CHAT_TAGS", False)

    cursor = _doc_cursor(gui)
    cursor.movePosition(QTextCursor.MoveOperation.End)
    content_end = cursor.position()

    if content_start >= content_end:
        return

    cursor.setPosition(content_start)
    cursor.setPosition(content_end, QTextCursor.MoveMode.KeepAnchor)
    # selectedText() uses U+2029 as paragraph separator — convert to \n
    text = cursor.selectedText().replace('\u2029', '\n')

    parts = delegate.split_text_with_tags(text, hide_tags)

    # Skip reformat if there are no coloured parts
    if not any(p.get("tag") == "tag_green" for p in parts):
        return

    cursor.removeSelectedText()
    for part in parts:
        color = delegate.tag_color if part.get("tag") == "tag_green" else None
        _insert_formatted_text(gui, cursor, part["content"], color)

    gui.chat_window.verticalScrollBar().setValue(
        gui.chat_window.verticalScrollBar().maximum()
    )


def attach_structured_to_stream(gui, structured_data: dict):
    """
    Retroactively attach a clickable diamond and structured panel to the
    message that was just streamed.

    Must be called right after finish_stream_slot completes.
    Reads gui._stream_label_start (set in prepare_stream_slot) to know
    where to insert the arrow character.
    """
    mode = gui._get_setting("SHOW_STRUCTURED_IN_GUI", STRUCTURED_MODE_OFF)
    if mode in (STRUCTURED_MODE_OFF, _STRUCTURED_MODE_OFF_EN, "", False, None):
        return

    label_start = getattr(gui, '_stream_label_start', None)
    if label_start is None:
        return
    gui._stream_label_start = None

    _get_think_blocks(gui)
    block_id = gui._think_block_counter
    gui._think_block_counter += 1
    start_expanded = bool(gui._get_setting("STRUCTURED_EXPANDED_DEFAULT", False))

    font_size = int(gui._get_setting("CHAT_FONT_SIZE", 12))
    diamond_font = QFont("Arial", font_size)
    diamond_font.setBold(True)
    diamond_fmt = QTextCharFormat()
    diamond_fmt.setForeground(QColor(STRUCTURED_HEADER_COLOR))
    diamond_fmt.setFont(diamond_font)
    diamond_fmt.setAnchor(True)
    diamond_fmt.setAnchorHref(f"think://toggle/{block_id}")

    initial_arrow = THINK_ARROW_EXPANDED if start_expanded else THINK_ARROW_COLLAPSED

    # Insert diamond at label_start (retroactively)
    cursor = _doc_cursor(gui)
    cursor.setPosition(label_start)
    struct_header_start = label_start
    cursor.insertText(initial_arrow + " ", diamond_fmt)
    struct_dots_start = struct_header_start + 1
    struct_header_end = cursor.position()

    # Shift all existing blocks whose positions are >= label_start
    _adjust_block_positions(gui, label_start, 2, exclude_id=block_id)

    # insert_message_end added \n\n; remove one \n so content is flush with message
    cursor.movePosition(QTextCursor.MoveOperation.End)
    end_pos = cursor.position()
    cursor.setPosition(end_pos - 1)
    cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
    if cursor.selectedText() in ("\n", "\u2029"):
        cursor.removeSelectedText()
        # Also shift all block positions that were after the removed char
        _adjust_block_positions(gui, end_pos - 1, -1, exclude_id=block_id)

    cursor.movePosition(QTextCursor.MoveOperation.End)
    content_start = cursor.position()
    content_end = content_start

    if mode in (STRUCTURED_MODE_JSON, "JSON"):
        s_content_text = _format_structured_json(structured_data)
        s_content_parts = None
    else:
        s_content_text = None
        s_content_parts = _format_structured_brief(structured_data)

    if start_expanded:
        content_end = _insert_structured_content(gui, cursor, s_content_text, s_content_parts)

    blocks = _get_think_blocks(gui)
    blocks[block_id] = {
        'id': block_id,
        'collapsed': not start_expanded,
        'name': "structured",
        'header_start': struct_header_start,
        'dots_start': struct_dots_start,
        'header_end': struct_header_end,
        'content_start': content_start,
        'content_end': content_end,
        'content_text': s_content_text or "",
        'content_parts': s_content_parts,
        'is_streaming': False,
    }

    # Always-visible trailing \n: provides gap with next message when collapsed
    cursor.insertText("\n", _make_plain_fmt(gui))

    gui.chat_window.verticalScrollBar().setValue(gui.chat_window.verticalScrollBar().maximum())


def finish_stream_slot(gui):
    current_role = getattr(gui, "_stream_current_render_role", "assistant")
    if current_role == "think":
        _finalize_streaming_think_block(gui)
    else:
        _reformat_streamed_content(gui)
    gui._stream_content_start = None
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
