from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QWidgetItem


class FlowLayout(QLayout):
    """Left-to-right layout that wraps items onto new rows when they run out
    of horizontal space (instead of overflowing or clipping).

    When `justify` is set, the items on every row are stretched to fill the
    full available width (extra space is shared equally between them) instead
    of hugging the left edge.

    When `center` is set (and `justify` is off), items keep their natural
    (fixed) width and each row is centered as a group within the available
    width instead of hugging the left edge.
    """

    def __init__(self, parent=None, margin=0, hspacing=6, vspacing=6, justify=False, center=False):
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._hspace = hspacing
        self._vspace = vspacing
        self._justify = justify
        self._center = center
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, widget):  # type: ignore[override]
        self.addChildWidget(widget)
        self.addItem(QWidgetItem(widget))

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _item_hint(self, item: QWidgetItem) -> QSize:
        widget = item.widget()
        hint = item.sizeHint()
        if widget is not None:
            hint = QSize(
                max(hint.width(), widget.minimumWidth()),
                max(hint.height(), widget.minimumHeight()),
            )
        return hint

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        x0 = rect.x() + margins.left()
        right = rect.right() - margins.right()
        avail = max(0, right - x0)
        y = rect.y() + margins.top()

        # Skip only items that were explicitly toggled off. Using isHidden()
        # (not isVisible()) keeps sizing correct before the window is shown,
        # when descendants are not "visible" yet.
        visible = [
            item
            for item in self._items
            if not (item.widget() is not None and item.widget().isHidden())
        ]

        # Group visible items into rows the same way in both passes so the
        # measured height (test_only) matches the placed geometry.
        rows: list[list[QWidgetItem]] = []
        current: list[QWidgetItem] = []
        current_w = 0
        for item in visible:
            w = self._item_hint(item).width()
            add = w if not current else w + self._hspace
            if current and current_w + add > avail:
                rows.append(current)
                current = []
                current_w = 0
                add = w
            current.append(item)
            current_w += add
        if current:
            rows.append(current)

        bottom = y
        for row in rows:
            natural = sum(self._item_hint(it).width() for it in row)
            natural += self._hspace * (len(row) - 1)
            extra = max(0, avail - natural) if self._justify else 0
            per = extra // len(row) if row else 0
            remainder = extra - per * len(row)

            # Center the (natural-width) row as a group when requested.
            x = x0
            if self._center and not self._justify:
                x = x0 + max(0, avail - natural) // 2
            line_height = 0
            for i, item in enumerate(row):
                hint = self._item_hint(item)
                w = hint.width() + per + (1 if i < remainder else 0)
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), QSize(w, hint.height())))
                x += w + self._hspace
                line_height = max(line_height, hint.height())
            y += line_height + self._vspace
            bottom = y - self._vspace

        return bottom - rect.y() + margins.bottom()
