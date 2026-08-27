from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def main() -> int:
    app = _app()

    from ui.pages.sandbox_page import _SandboxStatusRow

    row = _SandboxStatusRow(
        "Микрофон",
        on_settings=lambda: None,
        settings_tooltip="Open microphone settings",
        initial_on=True,
    )
    row.resize(320, 36)
    row.show()
    app.processEvents()

    row.set_value("gigaam-large-v2")
    row.set_enabled_state(True)
    app.processEvents()

    on_switch_x = row._switch.geometry().x()
    assert row._value_slot.width() >= 60, row._value_slot.width()

    row.set_enabled_state(False)
    app.processEvents()

    assert not row._value.isVisible()
    assert row._switch.geometry().x() == on_switch_x, (
        on_switch_x,
        row._switch.geometry().x(),
    )

    print("sandbox status row: ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
