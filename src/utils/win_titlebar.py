"""Best-effort native title-bar theming on Windows.

`apply_dark_titlebar()` asks DWM to paint the window's native caption (the top
bar with the title and the min/max/close buttons) in dark mode instead of the
default white. It is deliberately *maximally optional*:

* no-op on anything that is not win32;
* no-op (and silent) on Windows builds that don't support the attribute
  (DwmSetWindowAttribute simply returns a non-zero HRESULT, which we ignore);
* never raises — any failure is swallowed and reported via the return value.

Note: an arbitrary caption *color* (e.g. an accent colour) needs
DWMWA_CAPTION_COLOR, which only exists on Windows 11 (build 22000+). Dark mode
below works on Windows 10 1809+ as well, so it's the portable option.
"""

from __future__ import annotations

import sys

from main_logger import logger

# DWM window attributes (see dwmapi.h).
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
# Older 1809/1903 builds used attribute 19 before it was finalised as 20.
_DWMWA_USE_IMMERSIVE_DARK_MODE_PRE_20H1 = 19

_TITLEBAR_FILTER_PROP = "_neuromita_dark_titlebar_filter"


def apply_dark_titlebar(widget, enabled: bool = True) -> bool:
    """Make the given top-level widget's native title bar dark.

    Returns True only if the DWM call reported success; False on non-Windows,
    unsupported builds, or any error. Safe to call before or after show().
    """
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        # winId() forces creation of the native HWND if it doesn't exist yet.
        hwnd = int(widget.winId())
        if not hwnd:
            return False

        value = ctypes.c_int(1 if enabled else 0)
        set_attr = ctypes.windll.dwmapi.DwmSetWindowAttribute

        for attr in (_DWMWA_USE_IMMERSIVE_DARK_MODE, _DWMWA_USE_IMMERSIVE_DARK_MODE_PRE_20H1):
            hresult = set_attr(
                wintypes.HWND(hwnd),
                ctypes.c_int(attr),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if hresult == 0:  # S_OK
                return True
        return False
    except Exception as exc:  # pragma: no cover - platform dependent
        logger.debug(f"apply_dark_titlebar skipped: {exc}")
        return False


def install_dark_titlebar_sync(app, enabled: bool = True):
    """Apply dark native title bars to every shown top-level widget.

    The main window already uses a dark in-app theme; this keeps auxiliary
    dialogs/windows visually consistent without sprinkling per-dialog logic
    across the codebase.
    """
    if sys.platform != "win32" or app is None:
        return None

    existing = app.property(_TITLEBAR_FILTER_PROP)
    if existing is not None:
        return existing

    try:
        from PyQt6.QtCore import QObject, QEvent
        from PyQt6.QtWidgets import QWidget

        class _DarkTitlebarFilter(QObject):
            def eventFilter(self, obj, event):
                if isinstance(obj, QWidget) and obj.isWindow():
                    if event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange):
                        apply_dark_titlebar(obj, enabled)
                return False

        filt = _DarkTitlebarFilter(app)
        app.installEventFilter(filt)
        app.setProperty(_TITLEBAR_FILTER_PROP, filt)

        for widget in app.topLevelWidgets():
            try:
                if widget.isWindow():
                    apply_dark_titlebar(widget, enabled)
            except Exception:
                pass
        return filt
    except Exception as exc:  # pragma: no cover - GUI dependent
        logger.debug(f"install_dark_titlebar_sync skipped: {exc}")
        return None
