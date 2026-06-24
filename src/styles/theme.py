from __future__ import annotations

THEME = {
    # Фоновые ступени по эталонной палитре (#0A0A18 → #0D0E1C → #0F1120 → #101221):
    # уводим прежний фиолетовый оттенок в спокойный сине-серый (#18).
    "bg_root": "#0a0a18",
    "bg_window": "#0a0a18",
    "app_bg": "#0a0a18",
    "app_bg_rgb": "10, 10, 24",
    "sidebar_bg": "#0d0e1c",
    "sidebar_bg_rgb": "13, 14, 28",
    "sidebar_panel": "#0f1120",
    "sidebar_panel_rgb": "15, 17, 32",
    "sandbox_bg": "#0a0a18",
    "sandbox_bg_rgb": "10, 10, 24",
    "settings_panel_bg": "#101221",
    "settings_panel_rgb": "16, 18, 33",
    "text": "#f3edf6",
    "muted": "#bca9bb",
    "panel_bg": "rgba(16, 18, 33, 0.96)",
    "card_bg": "rgba(16, 18, 33, 0.96)",
    "card_alt_bg": "rgba(20, 22, 40, 0.92)",
    # Обводки уведены в нейтрально-серую гамму эталона (#1B1928 / #1C1C2C / #252236):
    # розовый бордюр оставлен только на акцентных action-кнопках (accent_border, ~#823858).
    "card_border": "rgba(40, 38, 54, 0.85)",
    # Нейтрально-серая обводка панелей (эталон #252236) — заменяет розовые
    # rgba(accent)-бордюры на статичных карточках/полях (фидбэк Артёма: «розовая
    # обводка ещё много где осталась, я просил на серый заменить»).
    "panel_border": "rgba(37, 34, 54, 0.9)",
    "panel_border_rgb": "37, 34, 54",
    "border_soft": "rgba(255,255,255,0.07)",
    "outline": "rgba(255,255,255,0.05)",
    "accent": "#b74b7d",
    "accent_alt": "#c04c80",
    "accent_rgb": "183, 75, 125",
    "accent_rgb_alt": "192, 76, 128",
    "accent_hover": "#c04c80",
    "accent_pressed": "#a0436c",
    "accent_border": "rgba(130, 56, 88, 0.55)",
    "slider_progress": "#c0476f",
    "slider_progress_rgb": "192, 71, 111",
    "chip_bg": "rgba(255,255,255,0.04)",
    "chip_hover": "rgba(183, 75, 125, 0.12)",
    "chip_pressed": "rgba(183, 75, 125, 0.18)",
    "scroll_handle": "rgba(183, 75, 125, 0.24)",
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
    "btn_disabled_bg": "#2b2230",
    "btn_disabled_fg": "#7c687a",
}


def get_theme() -> dict[str, str]:
    return THEME.copy()
