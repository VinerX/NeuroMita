import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from styles.compose import get_main_window_stylesheet
from ui.pages.settings.section_registry import get_settings_section_specs
from ui.widgets.settings_section_header import SettingsSectionHeader

_APP = None


def test_all_section_headers_have_copy_and_share_icon_height():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    app = _APP
    app.setStyleSheet(get_main_window_stylesheet())
    for spec in get_settings_section_specs():
        header = SettingsSectionHeader(spec.key)
        header.resize(1100, 48)
        header.show()
        app.processEvents()
        assert header.title.text().strip(), spec.key
        assert header.description.text().strip(), spec.key
        assert not header.icon.pixmap().isNull(), spec.key
        copy = header.title.parentWidget()
        assert copy.height() <= header.icon.height() + 2, spec.key
        assert (
            abs(copy.geometry().center().y() - header.icon.geometry().center().y()) <= 1
        )
        header.close()
