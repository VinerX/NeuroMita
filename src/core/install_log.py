from __future__ import annotations

from typing import Literal

InstallLogLevel = Literal["error", "warning"]

_STRUCTURAL_PREFIXES = (
    "__STATS__",
    "__SNAPSHOT_START__",
    "__SNAPSHOT_END__",
)


def classify_install_log(message: object, explicit_level: object = "") -> InstallLogLevel | None:
    """Classify only human-facing installer diagnostics.

    Progress protocol frames deliberately contain fields named ``errors`` and
    ``warnings``. Treating those JSON keys as text diagnostics polluted the
    application log with ERROR records while installation was healthy.
    """
    text = "" if message is None else str(message)
    if text.startswith(_STRUCTURAL_PREFIXES):
        return None

    level = str(explicit_level or "").strip().lower()
    lowered = text.lower()
    if level in {"error", "exception", "critical"} or any(
        marker in lowered for marker in ("error", "ошибка", "failed", "traceback")
    ):
        return "error"
    if level in {"warn", "warning"} or any(
        marker in lowered for marker in ("warning", "предупреж")
    ):
        return "warning"
    return None
