import qtawesome as qta
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QLabel, QHBoxLayout, QVBoxLayout, QSizePolicy

from localization.live import tr_set
from styles.theme import get_theme
from ui.pages.settings.section_registry import get_settings_section_specs


class SettingsSectionHeader(QWidget):
    def __init__(self, section_key, parent=None):
        super().__init__(parent)
        spec = next(
            spec for spec in get_settings_section_specs() if spec.key == section_key
        )
        self.setObjectName("SettingsSectionHeader")
        self.setProperty("sectionKey", section_key)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        self.icon = QLabel()
        self.icon.setObjectName("SettingsSectionIcon")
        self.icon.setFixedSize(48, 48)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setPixmap(
            qta.icon(spec.icon_name, color=get_theme()["accent"]).pixmap(27, 27)
        )
        row.addWidget(self.icon)
        copy = QWidget()
        copy.setObjectName("SettingsSectionCopy")
        copy.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        text = QVBoxLayout(copy)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        self.title = tr_set(QLabel(), *spec.title)
        self.title.setObjectName("SettingsSectionTitle")
        self.description = tr_set(QLabel(), *spec.subtitle)
        self.description.setObjectName("SettingsSectionDescription")
        self.description.setWordWrap(True)
        text.addWidget(self.title)
        text.addWidget(self.description)
        row.addWidget(copy, 1, Qt.AlignmentFlag.AlignVCenter)


def create_settings_header(layout, section_key):
    header = SettingsSectionHeader(section_key)
    layout.addWidget(header)
    return header
