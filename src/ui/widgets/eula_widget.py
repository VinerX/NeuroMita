from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QFrame, QButtonGroup, QRadioButton
from PyQt6.QtGui import QFont
from localization import available_languages, language_display_name, translate_for_language
from styles.theme import get_theme
from utils import render_qss
from ui.widgets.flow_layout import FlowLayout
from ui.settings.settings_access import get_setting, set_setting

class EULAWidget(QWidget):
    accepted = pyqtSignal()
    rejected = pyqtSignal()
    
    def __init__(self, settings_view_model, parent=None):
        super().__init__(parent)
        self.settings_view_model = settings_view_model
        self.setObjectName("EULAWidget")
        self.current_language = "ru"
        self._lang_buttons: dict[str, QRadioButton] = {}
        self.current_language = str(
            get_setting(self, "LANGUAGE", "RU") or "RU"
        ).strip().lower()
        # Язык, с которым уже построен интерфейс под оверлеем: если на старте
        # пользователь выберет другой — после принятия предложим перезапуск.
        self._initial_language = self.current_language
        self.setup_ui()
        
    def setup_ui(self):
        self.setStyleSheet(render_qss("""
            #EULAWidget {
                background-color: transparent;
            }
            #EULAContainer {
                background-color: rgba({settings_panel_rgb}, 0.95);
                border: 1px solid {border_soft};
                border-radius: 16px;
            }
            #EULATitle {
                font-size: 18px;
                font-weight: 700;
                color: {text};
                padding: 6px 8px;
                border-radius: 8px;
                background-color: {chip_bg};
            }
            #EULAText {
                background-color: rgba({sandbox_bg_rgb}, 0.92);
                color: {text};
                border: 1px solid {outline};
                border-radius: 12px;
                padding: 12px;
                font-size: 12px;
                line-height: 1.55;
                selection-background-color: {accent};
                selection-color: #ffffff;
            }
            QPushButton {
                min-width: 120px;
                min-height: 36px;
                font-size: 14px;
                font-weight: 600;
                border-radius: 10px;
                border: 1px solid {outline};
                background-color: {chip_bg};
                color: {text};
            }
            QPushButton:hover {
                background-color: {chip_hover};
            }
            QPushButton:pressed {
                background-color: {chip_pressed};
            }
            #AcceptButton {
                background-color: {success};
                color: #ffffff;
                border: 1px solid rgba(61,166,110,0.35);
            }
            #AcceptButton:hover {
                background-color: {success_hover};
            }
            #AcceptButton:pressed {
                background-color: {success_pressed};
            }
            #RejectButton {
                background-color: {danger};
                color: #ffffff;
                border: 1px solid rgba(214,69,69,0.35);
            }
            #RejectButton:hover {
                background-color: {danger_hover};
            }
            #RejectButton:pressed {
                background-color: {danger_pressed};
            }
            #EULALangBar {
                background: transparent;
            }
            QRadioButton {
                color: {muted};
                font-size: 13px;
                background: transparent;
                border: none;
                padding: 4px 6px;
                spacing: 7px;
            }
            QRadioButton:hover {
                color: {text};
            }
            QRadioButton:checked {
                color: {text};
                font-weight: 600;
            }
            QRadioButton::indicator {
                width: 15px;
                height: 15px;
                border-radius: 8px;
                border: 1.5px solid rgba(255,255,255,0.28);
                background: transparent;
            }
            QRadioButton::indicator:hover {
                border: 1.5px solid {accent};
            }
            QRadioButton::indicator:checked {
                background-color: {accent};
                border: 1.5px solid {accent_alt};
            }
            QFrame#Separator {
                background-color: {border_soft};
                max-height: 1px;
                border-radius: 1px;
            }
        """, get_theme()))
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        container = QFrame()
        container.setObjectName("EULAContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(15)
        
        self.setMinimumSize(700, 600)
        self.setMaximumSize(900, 700)
        
        header_layout = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("EULATitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.title_label)
        
        container_layout.addLayout(header_layout)
        
        separator = QFrame()
        separator.setObjectName("Separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        container_layout.addWidget(separator)
        
        # Языки выкладываем во flow-раскладку: при росте числа языков строка
        # сама переносится на следующую (раньше один QHBoxLayout сжимал и
        # обрезал названия — «Deutsch» → «Deutsc»).
        lang_container = QWidget()
        lang_container.setObjectName("EULALangBar")
        lang_flow = FlowLayout(lang_container, margin=2, hspacing=10, vspacing=8, center=True)

        self.lang_group = QButtonGroup()
        for idx, code in enumerate(available_languages()):
            button = QRadioButton(language_display_name(code))
            button.setProperty("lang_code", code.lower())
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if code.lower() == self.current_language:
                button.setChecked(True)
            self.lang_group.addButton(button, idx)
            self._lang_buttons[code.lower()] = button
            lang_flow.addWidget(button)
        self.lang_group.buttonClicked.connect(self._on_language_changed)

        if self.current_language not in self._lang_buttons:
            self.current_language = "ru"
            if "ru" in self._lang_buttons:
                self._lang_buttons["ru"].setChecked(True)
        container_layout.addWidget(lang_container)
        
        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("EULAText")
        self.text_edit.setReadOnly(True)
        container_layout.addWidget(self.text_edit, 1)
        
        button_layout = QHBoxLayout()
        button_layout.setSpacing(20)
        
        self.reject_button = QPushButton()
        self.reject_button.setObjectName("RejectButton")
        self.reject_button.clicked.connect(self._on_reject)
        button_layout.addWidget(self.reject_button)
        
        button_layout.addStretch()
        
        self.accept_button = QPushButton()
        self.accept_button.setObjectName("AcceptButton")
        self.accept_button.clicked.connect(self._on_accept)
        button_layout.addWidget(self.accept_button)
        
        container_layout.addLayout(button_layout)
        
        main_layout.addWidget(container)
        
        self._update_texts()
        
    def _on_language_changed(self):
        button = self.lang_group.checkedButton()
        code = button.property("lang_code") if button is not None else None
        self.current_language = str(code or "ru")
        self._update_texts()
        
    def _update_texts(self):
        self.title_label.setText(
            translate_for_language(
                self.current_language,
                "Лицензионное соглашение пользователя",
                "End User License Agreement",
            )
        )
        self.reject_button.setText(
            translate_for_language(self.current_language, "Отклонить", "Reject")
        )
        self.accept_button.setText(
            translate_for_language(self.current_language, "Принять", "Accept")
        )
        # Текст соглашения берём из языкового модуля EULA (#3): раньше для всех
        # языков, кроме RU/EN, показывался английский (translate_for_language падал
        # в en-фолбэк, т.к. полный текст не лежит в построчном каталоге).
        from localization.eula_texts import get_eula_text
        self.text_edit.setPlainText(get_eula_text(self.current_language))
        
    def _on_accept(self):
        # Сохраняем выбранный на стартовом экране язык интерфейса.
        set_setting(self, "LANGUAGE", str(self.current_language or "ru").upper())
        set_setting(self, "EULA_ACCEPTED", True)
        self.accepted.emit()

    def language_changed_on_start(self) -> bool:
        """True, если язык, выбранный на стартовом экране, отличается от того,
        с которым уже построен интерфейс (значит нужен перезапуск)."""
        return str(self.current_language or "ru") != str(self._initial_language or "ru")
        
    def _on_reject(self):
        self.rejected.emit()
