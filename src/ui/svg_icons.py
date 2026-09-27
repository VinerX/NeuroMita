from functools import lru_cache
from importlib.resources import files

from PyQt6.QtCore import QByteArray, Qt, QTemporaryFile, QDir
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer


@lru_cache(maxsize=32)
def _stylesheet_svg(name: str, color: str):
    data = files("ui").joinpath("icons", name + ".svg").read_text(encoding="utf-8")
    data = data.replace("currentColor", color).encode("utf-8")
    resource = QTemporaryFile(QDir.tempPath() + "/neuromita-icon-XXXXXX.svg")
    if not resource.open():
        raise OSError(resource.errorString())
    if resource.write(data) != len(data):
        raise OSError(resource.errorString())
    resource.close()
    return resource


def svg_stylesheet_url(name: str, color: str) -> str:
    """Keep a Qt-readable SVG file alive for stylesheets, including in zipapps."""
    return _stylesheet_svg(name, color).fileName().replace("\\", "/")


@lru_cache(maxsize=32)
def svg_icon(name: str, color: str | None = None) -> QIcon:
    """Load an SVG resource from source or a zipapp without extracting it."""
    data = files("ui").joinpath("icons", name + ".svg").read_bytes()
    from styles.theme import THEME
    data = data.replace(b"currentColor", (color or THEME["text"]).encode("utf-8"))
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        raise ValueError(f"Invalid SVG icon: {name}")
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 96, 128):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
