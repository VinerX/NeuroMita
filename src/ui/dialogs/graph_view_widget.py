"""
Interactive knowledge-graph visualisation widget (PyQt6, no external deps).

Renders entities as circles and relations as directed edges with arrowheads.
Supports pan, zoom (mouse wheel), drag nodes, hover tooltips, Ctrl+F search,
double-click neighbour-only view, and labels drawn above circles.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, QLineF
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QWheelEvent,
    QMouseEvent,
    QPaintEvent,
    QResizeEvent,
    QKeySequence,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtSql import QSqlDatabase, QSqlQuery

from main_logger import logger

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GNode:
    id: int
    name: str
    entity_type: str
    mention_count: int
    relation_count: int = 0
    aliases: List[str] = field(default_factory=list)
    # Layout position (world coords).
    x: float = 0.0
    y: float = 0.0
    # Velocity for force-directed layout.
    vx: float = 0.0
    vy: float = 0.0


@dataclass
class GEdge:
    src_id: int
    dst_id: int
    predicate: str
    confidence: float = 1.0


# ---------------------------------------------------------------------------
# Colour palette by entity type
# ---------------------------------------------------------------------------

_TYPE_COLORS: Dict[str, QColor] = {
    "person":  QColor(100, 160, 255),   # blue
    "place":   QColor(130, 210, 130),   # green
    "thing":   QColor(240, 180, 80),    # amber
    "concept": QColor(200, 140, 220),   # purple
}
_DEFAULT_COLOR = QColor(180, 180, 200)


def _color_for_type(t: str) -> QColor:
    return _TYPE_COLORS.get(t.lower().strip(), _DEFAULT_COLOR)


# ---------------------------------------------------------------------------
# Canvas widget (custom QPainter rendering)
# ---------------------------------------------------------------------------

class _GraphCanvas(QWidget):
    """Low-level drawing surface with pan/zoom and node dragging."""

    # Layout tuning constants.
    REPULSION = 8000.0
    ATTRACTION = 0.005
    DAMPING = 0.85
    MIN_VELOCITY = 0.1
    IDEAL_EDGE_LEN = 160.0
    # Skip repulsion between nodes farther than this (world units squared).
    REPULSION_CUTOFF_SQ = 600.0 * 600.0

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)

        self.nodes: Dict[int, GNode] = {}
        self.edges: List[GEdge] = []

        # View transform.
        self._zoom = 1.0
        self._pan = QPointF(0, 0)

        # Interaction state.
        self._dragged_node: Optional[GNode] = None
        self._last_mouse: Optional[QPointF] = None
        self._panning = False
        self._hovered_node: Optional[GNode] = None

        # Neighbour-only view.
        self._neighbour_mode = False
        self._focal_node_id: Optional[int] = None
        self._visible_ids: Optional[Set[int]] = None  # None = show all

        # Search.
        self._search_matches: Set[int] = set()  # node ids matching search

        # Force-directed layout timer.
        self._layout_timer = QTimer(self)
        self._layout_timer.setInterval(30)
        self._layout_timer.timeout.connect(self._layout_step)
        self._layout_iterations = 0
        self._max_iterations = 300

        # Font.
        self._font = QFont("Segoe UI", 9)
        self._font_bold = QFont("Segoe UI", 9, QFont.Weight.Bold)
        self._font_small = QFont("Segoe UI", 7)

    # ----- data loading -----

    def set_data(self, nodes: Dict[int, GNode], edges: List[GEdge]):
        self.nodes = nodes
        self.edges = edges
        self._neighbour_mode = False
        self._focal_node_id = None
        self._visible_ids = None
        self._search_matches = set()
        self._randomise_positions()
        self._layout_iterations = 0
        n = len(nodes)
        self._max_iterations = min(300, max(30, 9000 // max(n, 1)))
        self._layout_timer.start()
        self.update()

    def _randomise_positions(self):
        w = max(self.width(), 600)
        h = max(self.height(), 400)
        cx, cy = w / 2, h / 2
        radius = min(w, h) * 0.35
        count = max(len(self.nodes), 1)
        for i, node in enumerate(self.nodes.values()):
            angle = 2 * math.pi * i / count
            node.x = cx + radius * math.cos(angle) + random.uniform(-20, 20)
            node.y = cy + radius * math.sin(angle) + random.uniform(-20, 20)
            node.vx = 0
            node.vy = 0

    # ----- neighbour view -----

    def enter_neighbour_mode(self, node: GNode):
        """Show only node + its direct neighbours."""
        neighbour_ids = {node.id}
        for e in self.edges:
            if e.src_id == node.id:
                neighbour_ids.add(e.dst_id)
            elif e.dst_id == node.id:
                neighbour_ids.add(e.src_id)
        self._visible_ids = neighbour_ids
        self._focal_node_id = node.id
        self._neighbour_mode = True
        self.update()
        # Notify parent to show "Show all" button.
        p = self.parent()
        if hasattr(p, "_on_neighbour_mode_changed"):
            p._on_neighbour_mode_changed(True)

    def exit_neighbour_mode(self):
        self._visible_ids = None
        self._focal_node_id = None
        self._neighbour_mode = False
        self.update()
        p = self.parent()
        if hasattr(p, "_on_neighbour_mode_changed"):
            p._on_neighbour_mode_changed(False)

    # ----- search -----

    def apply_search(self, term: str):
        term = term.strip().lower()
        if not term:
            self._search_matches = set()
            self.update()
            return

        matches = {
            nid for nid, n in self.nodes.items()
            if term in n.name.lower() or any(term in a.lower() for a in n.aliases)
        }
        self._search_matches = matches

        # Pan to first match.
        if matches:
            first = next(iter(matches))
            node = self.nodes[first]
            cx = self.width() / 2
            cy = self.height() / 2
            self._pan = QPointF(cx - node.x * self._zoom, cy - node.y * self._zoom)

        self.update()

    # ----- force-directed layout -----

    def _layout_step(self):
        if self._layout_iterations > self._max_iterations:
            self._layout_timer.stop()
            return

        nodes_list = list(self.nodes.values())
        n = len(nodes_list)
        if n == 0:
            self._layout_timer.stop()
            return

        # Repulsion (all pairs, distance-culled).
        for i in range(n):
            a = nodes_list[i]
            for j in range(i + 1, n):
                b = nodes_list[j]
                dx = a.x - b.x
                dy = a.y - b.y
                dist_sq = dx * dx + dy * dy
                if dist_sq > self.REPULSION_CUTOFF_SQ:
                    continue
                dist = max(math.sqrt(dist_sq), 1.0)
                force = self.REPULSION / (dist * dist)
                fx = force * dx / dist
                fy = force * dy / dist
                a.vx += fx
                a.vy += fy
                b.vx -= fx
                b.vy -= fy

        # Attraction (edges).
        for edge in self.edges:
            a = self.nodes.get(edge.src_id)
            b = self.nodes.get(edge.dst_id)
            if not a or not b:
                continue
            dx = b.x - a.x
            dy = b.y - a.y
            dist = max(math.hypot(dx, dy), 1.0)
            force = self.ATTRACTION * (dist - self.IDEAL_EDGE_LEN)
            fx = force * dx / dist
            fy = force * dy / dist
            a.vx += fx
            a.vy += fy
            b.vx -= fx
            b.vy -= fy

        # Centre gravity (gentle pull toward canvas centre).
        cx = self.width() / 2
        cy = self.height() / 2
        for node in nodes_list:
            node.vx += (cx - node.x) * 0.0005
            node.vy += (cy - node.y) * 0.0005

        # Apply velocity.
        total_movement = 0.0
        for node in nodes_list:
            if node is self._dragged_node:
                node.vx = 0
                node.vy = 0
                continue
            node.vx *= self.DAMPING
            node.vy *= self.DAMPING
            node.x += node.vx
            node.y += node.vy
            total_movement += abs(node.vx) + abs(node.vy)

        self._layout_iterations += 1

        # Stop when settled.
        if total_movement < self.MIN_VELOCITY * n and self._layout_iterations > 50:
            self._layout_timer.stop()

        self.update()

    # ----- coordinate transforms -----

    def _world_to_screen(self, wx: float, wy: float) -> QPointF:
        return QPointF(wx * self._zoom + self._pan.x(),
                       wy * self._zoom + self._pan.y())

    def _screen_to_world(self, sx: float, sy: float) -> QPointF:
        return QPointF((sx - self._pan.x()) / self._zoom,
                       (sy - self._pan.y()) / self._zoom)

    # ----- node geometry -----

    def _node_radius(self, node: GNode) -> float:
        base = 22.0
        extra = min(node.mention_count, 30) * 0.8 + min(node.relation_count, 20) * 0.6
        return base + extra

    def _node_at(self, screen_pos: QPointF) -> Optional[GNode]:
        wp = self._screen_to_world(screen_pos.x(), screen_pos.y())
        for node in self._iter_visible():
            r = self._node_radius(node)
            if math.hypot(wp.x() - node.x, wp.y() - node.y) <= r:
                return node
        return None

    def _iter_visible(self):
        """Iterate over currently visible nodes."""
        if self._visible_ids is None:
            yield from self.nodes.values()
        else:
            for nid in self._visible_ids:
                n = self.nodes.get(nid)
                if n:
                    yield n

    # ----- painting -----

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background.
        p.fillRect(self.rect(), QColor(32, 34, 40))

        if not self.nodes:
            p.setPen(QColor(140, 140, 150))
            p.setFont(self._font)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No graph data")
            p.end()
            return

        # Draw edges first.
        self._draw_edges(p)
        # Draw nodes on top.
        self._draw_nodes(p)
        # Draw tooltip for hovered node.
        self._draw_tooltip(p)

        p.end()

    def _draw_edges(self, p: QPainter):
        visible = self._visible_ids
        pen = QPen(QColor(100, 105, 115, 160), 1.5)
        p.setFont(self._font_small)

        for edge in self.edges:
            if visible is not None:
                if edge.src_id not in visible or edge.dst_id not in visible:
                    continue
            src = self.nodes.get(edge.src_id)
            dst = self.nodes.get(edge.dst_id)
            if not src or not dst:
                continue

            sp = self._world_to_screen(src.x, src.y)
            dp = self._world_to_screen(dst.x, dst.y)

            # Shorten line to stop at node borders.
            line = QLineF(sp, dp)
            length = line.length()
            if length < 1:
                continue
            r_src = self._node_radius(src) * self._zoom
            r_dst = self._node_radius(dst) * self._zoom
            if length <= r_src + r_dst:
                continue

            t_start = r_src / length
            t_end = 1.0 - r_dst / length
            start = QPointF(sp.x() + (dp.x() - sp.x()) * t_start,
                            sp.y() + (dp.y() - sp.y()) * t_start)
            end = QPointF(sp.x() + (dp.x() - sp.x()) * t_end,
                          sp.y() + (dp.y() - sp.y()) * t_end)

            p.setPen(pen)
            p.drawLine(start, end)

            # Arrowhead.
            self._draw_arrowhead(p, start, end, 10)

            # Edge label.
            mid = QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)
            label = edge.predicate
            if len(label) > 20:
                label = label[:18] + "…"
            p.setPen(QColor(160, 165, 175))
            fm = QFontMetrics(self._font_small)
            tw = fm.horizontalAdvance(label)
            th = fm.height()
            label_rect = QRectF(mid.x() - tw / 2 - 3, mid.y() - th / 2 - 1, tw + 6, th + 2)
            p.fillRect(label_rect, QColor(32, 34, 40, 200))
            p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_arrowhead(self, p: QPainter, start: QPointF, end: QPointF, size: float):
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        a1 = angle + math.pi * 0.85
        a2 = angle - math.pi * 0.85
        p1 = QPointF(end.x() + size * math.cos(a1), end.y() + size * math.sin(a1))
        p2 = QPointF(end.x() + size * math.cos(a2), end.y() + size * math.sin(a2))
        poly = QPolygonF([end, p1, p2])
        p.setBrush(QBrush(QColor(100, 105, 115, 180)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(poly)

    def _draw_nodes(self, p: QPainter):
        focal = self._focal_node_id
        for node in self._iter_visible():
            sp = self._world_to_screen(node.x, node.y)
            r = self._node_radius(node) * self._zoom

            color = _color_for_type(node.entity_type)
            is_hovered = node is self._hovered_node
            is_focal = node.id == focal

            # Shadow.
            p.setBrush(QBrush(QColor(0, 0, 0, 60)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(sp.x() + 3, sp.y() + 3), r, r)

            # Search match ring (yellow, drawn behind circle).
            if node.id in self._search_matches:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(255, 220, 50), 3.0))
                p.drawEllipse(sp, r + 5, r + 5)

            # Focal node ring (bright white).
            if is_focal:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 200), 2.5))
                p.drawEllipse(sp, r + 3, r + 3)

            # Fill.
            fill = color.lighter(120) if is_hovered else color
            p.setBrush(QBrush(fill))
            border_pen = QPen(color.darker(140), 2.0 if is_hovered else 1.5)
            p.setPen(border_pen)
            p.drawEllipse(sp, r, r)

            # Inner highlight.
            p.setBrush(QBrush(QColor(255, 255, 255, 50)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(sp.x() - r * 0.2, sp.y() - r * 0.25), r * 0.45, r * 0.35)

            # Node label — drawn ABOVE the circle.
            p.setFont(self._font_bold if is_hovered else self._font)
            p.setPen(QColor(240, 240, 245))
            label = node.name
            fm = QFontMetrics(p.font())
            th = fm.height()
            label_y_top = sp.y() - r - 4  # top of label rect, 4px above circle
            text_rect = QRectF(sp.x() - 80, label_y_top - th, 160, th + 2)
            # Semi-transparent backing so text is readable over edges.
            p.fillRect(text_rect.adjusted(-2, -1, 2, 1), QColor(32, 34, 40, 160))
            p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

            # Stats line just below label (still above circle).
            p.setFont(self._font_small)
            p.setPen(QColor(200, 200, 210, 200))
            stats = f"×{node.mention_count}  ↔{node.relation_count}"
            stats_rect = QRectF(sp.x() - 60, label_y_top - th - 14, 120, 13)
            p.drawText(stats_rect, Qt.AlignmentFlag.AlignCenter, stats)

    def _draw_tooltip(self, p: QPainter):
        if not self._hovered_node:
            return
        node = self._hovered_node
        sp = self._world_to_screen(node.x, node.y)
        r = self._node_radius(node) * self._zoom

        lines = [
            node.name,
            f"Type: {node.entity_type}",
            f"Mentions: {node.mention_count}",
            f"Relations: {node.relation_count}",
        ]
        if node.aliases:
            alias_str = ", ".join(node.aliases[:6])
            if len(node.aliases) > 6:
                alias_str += f" (+{len(node.aliases) - 6})"
            lines.append(f"Aliases: {alias_str}")

        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        line_h = fm.height() + 2
        max_w = max(fm.horizontalAdvance(l) for l in lines)
        pad = 8

        tw = max_w + pad * 2
        th = line_h * len(lines) + pad * 2
        tx = sp.x() + r + 10
        ty = sp.y() - th / 2

        # Keep tooltip on screen.
        if tx + tw > self.width():
            tx = sp.x() - r - 10 - tw
        if ty < 0:
            ty = 4
        if ty + th > self.height():
            ty = self.height() - th - 4

        bg = QRectF(tx, ty, tw, th)
        p.setBrush(QBrush(QColor(50, 52, 58, 230)))
        p.setPen(QPen(QColor(100, 105, 115), 1))
        p.drawRoundedRect(bg, 6, 6)

        p.setPen(QColor(220, 220, 230))
        for i, line in enumerate(lines):
            p.setFont(self._font_bold if i == 0 else self._font)
            p.drawText(QPointF(tx + pad, ty + pad + (i + 1) * line_h - 3), line)

    # ----- mouse events -----

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            node = self._node_at(event.position())
            if node:
                self._dragged_node = node
            else:
                self._panning = True
            self._last_mouse = event.position()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            node = self._node_at(event.position())
            if node:
                if self._neighbour_mode and self._focal_node_id == node.id:
                    self.exit_neighbour_mode()
                else:
                    self.enter_neighbour_mode(node)
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position()

        if self._dragged_node and self._last_mouse:
            wp = self._screen_to_world(pos.x(), pos.y())
            self._dragged_node.x = wp.x()
            self._dragged_node.y = wp.y()
            self._dragged_node.vx = 0
            self._dragged_node.vy = 0
            self.update()
        elif self._panning and self._last_mouse:
            dx = pos.x() - self._last_mouse.x()
            dy = pos.y() - self._last_mouse.y()
            self._pan = QPointF(self._pan.x() + dx, self._pan.y() + dy)
            self.update()

        self._last_mouse = pos

        new_hovered = self._node_at(pos)
        if new_hovered is not self._hovered_node:
            self._hovered_node = new_hovered
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if new_hovered
                else Qt.CursorShape.ArrowCursor
            )
            self.update()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragged_node = None
            self._panning = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        old_zoom = self._zoom
        self._zoom = max(0.1, min(5.0, self._zoom * factor))
        real_factor = self._zoom / old_zoom

        cursor = event.position()
        self._pan = QPointF(
            cursor.x() - (cursor.x() - self._pan.x()) * real_factor,
            cursor.y() - (cursor.y() - self._pan.y()) * real_factor,
        )
        self.update()

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        if self._layout_iterations == 0 and self.nodes:
            self._randomise_positions()


# ---------------------------------------------------------------------------
# High-level page widget (toolbar + canvas)
# ---------------------------------------------------------------------------

class GraphViewPage(QWidget):
    """
    Tab page for the DB Viewer: loads graph data from SQLite and
    renders an interactive force-directed graph.
    """

    def __init__(self, parent: QWidget, *, db: QSqlDatabase, character_id: Optional[str] = None):
        super().__init__(parent)
        self.db = db
        self.character_id = character_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Toolbar row 1: type filter + stats + buttons.
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("Filter type:"))
        self.cmb_type = QComboBox(self)
        self.cmb_type.addItems(["All", "person", "place", "thing", "concept"])
        self.cmb_type.currentIndexChanged.connect(self._reload)
        toolbar.addWidget(self.cmb_type)

        toolbar.addStretch(1)

        self.lbl_stats = QLabel("", self)
        toolbar.addWidget(self.lbl_stats)

        self.btn_show_all = QPushButton("Show all", self)
        self.btn_show_all.setVisible(False)
        self.btn_show_all.clicked.connect(self._show_all)
        toolbar.addWidget(self.btn_show_all)

        btn_refresh = QPushButton("Refresh", self)
        btn_refresh.clicked.connect(self._reload)
        toolbar.addWidget(btn_refresh)

        btn_relayout = QPushButton("Re-layout", self)
        btn_relayout.clicked.connect(self._relayout)
        toolbar.addWidget(btn_relayout)

        btn_reset_view = QPushButton("Reset view", self)
        btn_reset_view.clicked.connect(self._reset_view)
        toolbar.addWidget(btn_reset_view)

        layout.addLayout(toolbar)

        # Toolbar row 2: search bar (hidden until Ctrl+F).
        self._search_bar = QWidget(self)
        search_layout = QHBoxLayout(self._search_bar)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit(self._search_bar)
        self._search_edit.setPlaceholderText("Entity name or alias…")
        self._search_edit.textChanged.connect(self._on_search_changed)
        self._search_edit.returnPressed.connect(self._on_search_changed)
        search_layout.addWidget(self._search_edit)
        btn_close_search = QPushButton("✕", self._search_bar)
        btn_close_search.setFixedWidth(26)
        btn_close_search.clicked.connect(self._close_search)
        search_layout.addWidget(btn_close_search)
        self._search_bar.setVisible(False)
        layout.addWidget(self._search_bar)

        # Canvas.
        self.canvas = _GraphCanvas(self)
        layout.addWidget(self.canvas, 1)

        # Legend.
        legend = QHBoxLayout()
        legend.addStretch(1)
        for type_name, color in _TYPE_COLORS.items():
            dot = QLabel(f"● {type_name}", self)
            dot.setStyleSheet(f"color: {color.name()}; font-size: 11px; margin-right: 12px;")
            legend.addWidget(dot)
        lbl_hint = QLabel("  Double-click: neighbour view", self)
        lbl_hint.setStyleSheet("color: #888; font-size: 10px;")
        legend.addWidget(lbl_hint)
        legend.addStretch(1)
        layout.addLayout(legend)

        # Ctrl+F shortcut.
        sc = QShortcut(QKeySequence("Ctrl+F"), self)
        sc.activated.connect(self._open_search)

        # Initial load.
        self._reload()

    # ----- search UI -----

    def _open_search(self):
        self._search_bar.setVisible(True)
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    def _close_search(self):
        self._search_edit.clear()
        self._search_bar.setVisible(False)
        self.canvas.apply_search("")

    def _on_search_changed(self):
        self.canvas.apply_search(self._search_edit.text())

    # ----- neighbour mode callback (called by canvas) -----

    def _on_neighbour_mode_changed(self, active: bool):
        self.btn_show_all.setVisible(active)

    def _show_all(self):
        self.canvas.exit_neighbour_mode()

    # ----- reload / relayout / reset -----

    def _reload(self):
        nodes, edges = self._load_from_db()
        self.canvas.set_data(nodes, edges)
        self.lbl_stats.setText(f"Entities: {len(nodes)}  |  Relations: {len(edges)}")

    def _relayout(self):
        self.canvas._randomise_positions()
        self.canvas._layout_iterations = 0
        n = len(self.canvas.nodes)
        self.canvas._max_iterations = min(300, max(30, 9000 // max(n, 1)))
        self.canvas._layout_timer.start()
        self.canvas.update()

    def _reset_view(self):
        self.canvas._zoom = 1.0
        self.canvas._pan = QPointF(0, 0)
        self.canvas.update()

    def _load_from_db(self) -> Tuple[Dict[int, GNode], List[GEdge]]:
        nodes: Dict[int, GNode] = {}
        edges: List[GEdge] = []

        if not self.db or not self.db.isOpen():
            return nodes, edges

        # Check if tables exist.
        for tbl in ("graph_entities", "graph_relations"):
            q = QSqlQuery(self.db)
            q.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?")
            q.addBindValue(tbl)
            if not (q.exec() and q.next()):
                return nodes, edges

        type_filter = self.cmb_type.currentText()

        # Load entities.
        sql_ent = "SELECT id, name, entity_type, mention_count FROM graph_entities"
        conditions = []
        if self.character_id:
            conditions.append(f"character_id = '{_sql_esc(self.character_id)}'")
        if type_filter != "All":
            conditions.append(f"entity_type = '{_sql_esc(type_filter)}'")
        if conditions:
            sql_ent += " WHERE " + " AND ".join(conditions)

        q = QSqlQuery(self.db)
        if q.exec(sql_ent):
            while q.next():
                nid = q.value(0)
                nodes[nid] = GNode(
                    id=nid,
                    name=str(q.value(1) or ""),
                    entity_type=str(q.value(2) or ""),
                    mention_count=int(q.value(3) or 0),
                )

        if not nodes:
            return nodes, edges

        # Load aliases (if table exists).
        alias_check = QSqlQuery(self.db)
        alias_check.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='graph_entity_aliases'")
        if alias_check.exec() and alias_check.next():
            sql_alias = "SELECT entity_id, surface FROM graph_entity_aliases"
            q_alias = QSqlQuery(self.db)
            if q_alias.exec(sql_alias):
                while q_alias.next():
                    eid = q_alias.value(0)
                    surface = str(q_alias.value(1) or "")
                    if eid in nodes and surface:
                        nodes[eid].aliases.append(surface)

        node_ids = set(nodes.keys())

        # Load relations (only between loaded nodes).
        sql_rel = "SELECT subject_id, object_id, predicate, confidence FROM graph_relations"
        rel_conditions = []
        if self.character_id:
            rel_conditions.append(f"character_id = '{_sql_esc(self.character_id)}'")
        if rel_conditions:
            sql_rel += " WHERE " + " AND ".join(rel_conditions)

        q2 = QSqlQuery(self.db)
        if q2.exec(sql_rel):
            while q2.next():
                src = q2.value(0)
                dst = q2.value(1)
                if src in node_ids and dst in node_ids:
                    edges.append(GEdge(
                        src_id=src,
                        dst_id=dst,
                        predicate=str(q2.value(2) or ""),
                        confidence=float(q2.value(3) or 1.0),
                    ))

        # Count relations per node.
        rel_count: Dict[int, int] = {}
        for e in edges:
            rel_count[e.src_id] = rel_count.get(e.src_id, 0) + 1
            rel_count[e.dst_id] = rel_count.get(e.dst_id, 0) + 1
        for nid, cnt in rel_count.items():
            if nid in nodes:
                nodes[nid].relation_count = cnt

        return nodes, edges

    def cleanup(self):
        self.canvas._layout_timer.stop()


def _sql_esc(s: str) -> str:
    return str(s).replace("'", "''")
