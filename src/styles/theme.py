from __future__ import annotations

THEME = {
    "bg_root": "#0d0713",
    "bg_window": "#09050f",
    "text": "#f4e7f1",
    "muted": "#b095ad",
    "panel_bg": "rgba(27,12,31,0.94)",
    "card_bg": "rgba(34,14,39,0.96)",
    "card_border": "rgba(255,120,181,0.18)",
    "border_soft": "rgba(255,255,255,0.10)",
    "outline": "rgba(255,255,255,0.06)",
    "accent": "#ff5c9e",
    "accent_hover": "#ff73ad",
    "accent_pressed": "#ef4b8f",
    "accent_border": "rgba(255,92,158,0.48)",
    "chip_bg": "rgba(255,255,255,0.05)",
    "chip_hover": "rgba(255,92,158,0.14)",
    "chip_pressed": "rgba(255,92,158,0.20)",
    "scroll_handle": "rgba(255,156,210,0.22)",
    "warn_bg": "rgba(255,120,120,0.08)",
    "warn_border": "rgba(255,120,120,0.25)",
    "warn_text": "#ffb4b4",
    "success": "#7fe38c",
    "success_hover": "#91eba0",
    "success_pressed": "#69d97a",
    "danger": "#d64545",
    "danger_hover": "#e25757",
    "danger_pressed": "#bf3838",
    "link": "#7bc6ff",
    "btn_disabled_bg": "#3a2236",
    "btn_disabled_fg": "#7e6178",
}


def get_theme() -> dict[str, str]:
    return THEME.copy()
