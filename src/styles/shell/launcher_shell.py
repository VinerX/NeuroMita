from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LauncherShellPalette:
    # Фоновые ступени эталона (#0A0A18 → #0D0E1C → #101221), сине-серые, без фиолета.
    root_bg: str = "#0a0a18"
    panel_bg: str = "rgba(14, 16, 31, 0.995)"
    panel_soft: str = "rgba(14, 16, 31, 0.98)"
    card_bg: str = "rgba(14, 16, 31, 0.92)"
    card_alt_bg: str = "rgba(14, 16, 31, 0.94)"
    # Нейтрально-серые обводки эталона (#1B1928 / #252236) вместо розовых.
    border: str = "rgba(27, 25, 40, 0.92)"
    border_strong: str = "rgba(37, 34, 54, 0.95)"
    text: str = "#f3edf6"
    muted: str = "#bca9bb"
    accent: str = "#b74b7d"
    accent_soft: str = "rgba(183, 75, 125, 0.14)"
    accent_hover: str = "#c04c80"
    accent_pressed: str = "#a0436c"
    success: str = "#89f7b2"
    warning: str = "#ffcf7d"
    danger: str = "#ff7a98"
    link: str = "#89dbff"


PALETTE = LauncherShellPalette()


def resolve_launcher_asset(name: str) -> str | None:
    asset_path = Path("assets") / "launcher_ui" / name
    return str(asset_path) if asset_path.exists() else None


def get_launcher_shell_stylesheet() -> str:
    p = PALETTE
    bg_rule = """
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #0d0e1c,
            stop: 0.42 #0a0a18,
            stop: 1 #080814
        );
    """
    return f"""
    QWidget#LauncherShellRoot {{
        background: transparent;
        color: {p.text};
        font-family: "Segoe UI", "Arial", sans-serif;
    }}
    QWidget#LauncherShellPage {{
        background: transparent;
    }}
    QFrame#LauncherShellBackdrop {{
        {bg_rule}
        border: none;
    }}
    QScrollArea#LauncherShellScrollArea,
    QScrollArea#LauncherShellScrollArea > QWidget,
    QScrollArea#LauncherShellScrollArea > QWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QFrame#LauncherShellPage,
    QFrame#LauncherShellSectionCard,
    QFrame#LauncherShellPromoCard,
    QFrame#LauncherShellStatusCard,
    QFrame#LauncherShellSocialCard,
    QFrame#LauncherShellMetricCard,
    QFrame#LauncherShellNewsCard,
    QFrame#LauncherShellLogCard {{
        background-color: {p.card_bg};
        border: 1px solid {p.border};
        border-radius: 22px;
    }}
    /* Шапка страницы выделена отдельным уровнем, чтобы не сливаться 1-в-1 с
       карточками релизов: чуть приподнятый градиент + акцентная левая грань. */
    QFrame#LauncherShellHeroCard {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 rgba(23, 25, 40, 0.96),
            stop: 1 rgba(14, 16, 31, 0.96)
        );
        border: 1px solid {p.border_strong};
        border-left: 3px solid rgba(183, 75, 125, 0.85);
        border-radius: 22px;
    }}
    /* Заголовок секции (PRE-RELEASES / RELEASES). */
    QLabel#LauncherShellSectionHeader {{
        color: {p.muted};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 1px;
        padding: 2px 2px;
    }}
    /* Фильтр-табы (Все / Релизы / Пререлизы). */
    QPushButton#LauncherShellFilterTab {{
        background-color: rgba(255, 255, 255, 0.03);
        color: {p.muted};
        border: 1px solid {p.border};
        border-radius: 12px;
        padding: 7px 16px;
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 12px;
        font-weight: 700;
    }}
    QPushButton#LauncherShellFilterTab:hover {{
        color: {p.text};
        border: 1px solid {p.border_strong};
    }}
    QPushButton#LauncherShellFilterTab[active="true"] {{
        background-color: rgba(144, 65, 106, 0.85);
        color: {p.text};
        border: 1px solid rgba(130, 56, 88, 0.55);
    }}
    /* Цветные бейджи статуса релиза (эталонные оттенки). */
    QLabel#LauncherShellBadge {{
        color: #f3dfe9;
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 1px;
        border-radius: 7px;
        padding: 3px 9px;
        background-color: #792e56;
    }}
    QLabel#LauncherShellBadge[kind="pre"] {{
        background-color: #422258;
        color: #ddccea;
    }}
    QLabel#LauncherShellBadge[kind="offline"] {{
        background-color: rgba(255, 255, 255, 0.06);
        color: {p.muted};
    }}
    /* Тонкий разделитель между шапкой карточки (бейдж+название) и описанием. */
    QFrame#LauncherShellCardDivider {{
        min-height: 1px;
        max-height: 1px;
        background-color: rgba(255, 255, 255, 0.06);
        border: none;
    }}
    /* Прокручиваемый контейнер развёрнутого changelog: ограничивает высоту,
       чтобы длинные заметки не растягивали страницу на километры. */
    QScrollArea#LauncherShellDetailsScroll {{
        background: rgba(0, 0, 0, 0.18);
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    QScrollArea#LauncherShellDetailsScroll > QWidget > QWidget {{
        background: transparent;
    }}
    QFrame#LauncherShellSidebar {{
        /* Плоская заливка вместо вертикального градиента: на высокой узкой
           панели qlineargradient давал видимые «полосы-тайлы» (фидбэк Артёма). */
        background-color: #0e101f;
        border: none;
        border-right: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 0px;
    }}
    QFrame#LauncherShellNavHost,
    QFrame#LauncherShellBrandRow,
    QFrame#LauncherShellDivider {{
        background: transparent;
        border: none;
        border-radius: 0px;
    }}
    QFrame#LauncherShellDivider {{
        min-height: 1px;
        max-height: 1px;
        background-color: rgba(255, 255, 255, 0.12);
    }}
    QLabel#LauncherShellEyebrow {{
        color: {p.accent_hover};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellTitle {{
        color: {p.text};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 26px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellSubtitle,
    QLabel#LauncherShellMeta,
    QLabel#LauncherShellHint,
    QLabel#LauncherShellBody {{
        color: {p.muted};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 13px;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellSectionTitle {{
        color: {p.text};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellSectionValue {{
        color: {p.text};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 17px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellStatusDot {{
        min-width: 10px;
        max-width: 10px;
        min-height: 10px;
        max-height: 10px;
        border-radius: 5px;
        background-color: {p.success};
    }}
    QPushButton#LauncherShellNavButton {{
        background-color: transparent;
        color: {p.muted};
        border: 1px solid transparent;
        border-radius: 16px;
        padding: 13px 14px;
        font-family: "Segoe UI", "Arial", sans-serif;
        text-align: left;
        font-size: 14px;
        font-weight: 600;
        letter-spacing: 0px;
    }}
    QPushButton#LauncherShellNavButton:hover {{
        background-color: rgba(255, 255, 255, 0.03);
        border: 1px solid transparent;
        color: {p.text};
    }}
    QPushButton#LauncherShellNavButton[active="true"] {{
        background-color: rgba(144, 65, 106, 0.85);
        border: 1px solid rgba(130, 56, 88, 0.55);
        color: {p.text};
    }}
    QPushButton#LauncherShellActionButton,
    QPushButton#LauncherShellPromoButton {{
        background-color: {p.accent};
        color: white;
        border: 1px solid rgba(130, 56, 88, 0.60);
        border-radius: 14px;
        padding: 10px 14px;
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QPushButton#LauncherShellActionButton:hover,
    QPushButton#LauncherShellPromoButton:hover {{
        background-color: {p.accent_hover};
    }}
    QPushButton#LauncherShellActionButton:pressed,
    QPushButton#LauncherShellPromoButton:pressed {{
        background-color: {p.accent_pressed};
    }}
    QPushButton#LauncherShellGhostButton,
    QPushButton#LauncherShellChipButton {{
        background-color: rgba(255, 255, 255, 0.04);
        color: {p.text};
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 14px;
        padding: 9px 12px;
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0px;
    }}
    QPushButton#LauncherShellGhostButton:hover,
    QPushButton#LauncherShellChipButton:hover {{
        background-color: {p.accent_soft};
        border: 1px solid {p.border};
    }}
    QPushButton#LauncherShellSocialButton {{
        background: transparent;
        border: none;
        border-radius: 10px;
        padding: 4px;
    }}
    QPushButton#LauncherShellSocialButton:hover {{
        background-color: {p.accent_soft};
    }}
    QWidget#LauncherShellSocialBlock,
    QWidget#LauncherShellFooterBlock,
    QWidget#LauncherShellLangPillsHost {{
        background: transparent;
    }}
    QFrame#LauncherShellSocialIconCard {{
        background-color: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 16px;
        padding: 6px;
    }}
    QFrame#LauncherShellBrandRow {{
        background: transparent;
        border: none;
    }}
    QLabel#LauncherShellBrandTitle {{
        color: {p.text};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 16px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QLabel#LauncherShellBrandSubtitle {{
        color: {p.muted};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 13px;
        font-weight: 500;
        letter-spacing: 0px;
    }}
    QPushButton#LauncherShellLangPill {{
        background: transparent;
        color: {p.muted};
        border: none;
        border-radius: 12px;
        padding: 0;
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0px;
    }}
    QPushButton#LauncherShellLangPill:hover {{
        background: transparent;
        color: {p.text};
    }}
    QPushButton#LauncherShellLangPill[active="true"] {{
        background-color: {p.accent};
        color: white;
        border: none;
    }}
    QPushButton#LauncherShellLangGlobe {{
        background: transparent;
        border: none;
        border-radius: 8px;
        padding: 0;
    }}
    QPushButton#LauncherShellLangGlobe:hover {{
        background-color: {p.accent_soft};
    }}
    QLabel#LauncherShellVersionLabel {{
        color: {p.muted};
        font-family: "Segoe UI", "Arial", sans-serif;
        font-size: 11px;
        letter-spacing: 0px;
    }}
    QScrollArea#LauncherShellScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollBar:vertical {{
        width: 10px;
        background: transparent;
        margin: 4px 0;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(183, 75, 125, 0.22);
        border-radius: 5px;
        min-height: 28px;
    }}
    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical,
    QScrollBar::sub-page:vertical {{
        background: transparent;
        height: 0px;
    }}
    """
