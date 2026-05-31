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
