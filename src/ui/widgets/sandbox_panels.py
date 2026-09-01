from __future__ import annotations

# ---------------------------------------------------------------------------
# Sandbox inspector panel visibility
# ---------------------------------------------------------------------------
# Mirrors ui/widgets/settings_panel.py's per-section toggles, but governs the
# right-hand inspector panels in the Sandbox (Session tab) instead of the
# settings tabs. Each panel gets a SettingsManager flag
# (SANDBOX_PANEL_<KEY>_ENABLED). Everything defaults to ON — the user trims the
# list later from settings. Unknown keys stay visible so we never accidentally
# hide a panel added later.

# (key, (ru, en)) in display order.
_PANELS: tuple[tuple[str, tuple[str, str]], ...] = (
    ("active", ("Активная сессия", "Active session")),
    ("status", ("Статус: голос, микрофон, RAG", "Status: voice, mic, RAG")),
    # ("context_budget", ...) hidden for now — placeholder budget, see sandbox_page._build_ui.
    ("last_request", ("Последний запрос", "Last request")),
    ("capture", ("Захват", "Capture")),
    ("actions", ("Быстрые действия", "Quick actions")),
)

# Panels that start hidden. Everything else defaults ON; the user trims/extends
# the list from settings. "last_request" is a diagnostics strip most users don't
# need, so it's off out of the box.
_PANEL_DEFAULT_OFF: frozenset[str] = frozenset({"last_request"})

SANDBOX_PANEL_LABELS: dict[str, tuple[str, str]] = {key: label for key, label in _PANELS}
SANDBOX_PANEL_DEFAULTS: dict[str, bool] = {key: key not in _PANEL_DEFAULT_OFF for key, _ in _PANELS}
TOGGLEABLE_SANDBOX_PANELS: tuple[str, ...] = tuple(key for key, _ in _PANELS)


def _panel_key(key: str) -> str:
    return f"SANDBOX_PANEL_{key.upper()}_ENABLED"


def is_panel_enabled(key: str, settings) -> bool:
    """Whether the sandbox inspector panel should be shown. Unknown keys stay
    visible; everything defaults to ON."""
    if key not in SANDBOX_PANEL_DEFAULTS:
        return True
    default = SANDBOX_PANEL_DEFAULTS[key]
    return bool(settings.get(_panel_key(key), default))


def set_panel_enabled(key: str, enabled: bool, settings) -> None:
    if key not in SANDBOX_PANEL_DEFAULTS:
        return
    settings.set(_panel_key(key), bool(enabled))


def apply_sandbox_panel_visibility(gui) -> None:
    """Re-apply the panel toggles to the live Sandbox page, if it exists."""
    page = getattr(gui, "sandbox_page", None)
    if page is not None and hasattr(page, "apply_panel_visibility"):
        try:
            page.apply_panel_visibility()
        except Exception:
            pass


__all__ = [
    "SANDBOX_PANEL_LABELS",
    "SANDBOX_PANEL_DEFAULTS",
    "TOGGLEABLE_SANDBOX_PANELS",
    "_panel_key",
    "is_panel_enabled",
    "set_panel_enabled",
    "apply_sandbox_panel_visibility",
]
