# src/ui/widgets/guide_widget.py
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame, QRadioButton, QButtonGroup, QComboBox, QScrollArea, QSizePolicy
from PyQt6.QtGui import QPixmap
import qtawesome as qta
from abc import ABC, abstractmethod
from localization import available_languages, language_display_name, translate_for_language
from main_logger import logger
import os
import re
from styles.theme import get_theme
from utils import render_qss
from ui.settings.settings_access import get_setting, set_setting

class IGuidePage(ABC):
    min_mode: str = "basic"

    def __init__(self):
        self._highlight_target = None

    def set_highlight_target(self, target):
        """Store an optional UI target for callers that decorate guide steps."""
        self._highlight_target = target

    @abstractmethod
    def get_title_ru(self) -> str:
        pass

    @abstractmethod
    def get_title_en(self) -> str:
        pass

    @abstractmethod
    def get_description_ru(self) -> str:
        pass

    @abstractmethod
    def get_description_en(self) -> str:
        pass

    @abstractmethod
    def get_image_filename(self, language: str) -> str:
        pass


class GuideWidget(QWidget):
    closed = pyqtSignal()

    def __init__(self, settings_view_model, parent=None):
        super().__init__(parent)
        self.settings_view_model = settings_view_model
        self.pages = []
        self.current_page_index = 0
        self.current_language = "ru"
        self._guide_level = "basic"
        self._filtered_pages = []
        self._lang_buttons: dict[str, QRadioButton] = {}
        self._level_group = None
        from ui.widgets.settings_panel import normalize_mode
        saved = get_setting(self, "GUIDE_LEVEL")
        if saved in ("basic", "advanced", "full"):
            self._guide_level = saved
        else:
            iface = get_setting(self, "INTERFACE_MODE")
            self._guide_level = normalize_mode(iface)
            if self._guide_level not in ("basic", "advanced", "full"):
                self._guide_level = "basic"
        self.current_language = str(
            get_setting(self, "LANGUAGE", "RU") or "RU"
        ).strip().lower()
        self.setObjectName("GuideWidget")
        self.setup_ui()
        self._init_pages()

    def setup_ui(self):
        self.setStyleSheet(render_qss("""
            #GuideWidget {
                background-color: transparent;
            }
            #GuideContainer {
                background-color: rgba({settings_panel_rgb}, 1.0);
                border: 1px solid {border_soft};
                border-radius: 16px;
            }
            #GuideTitle {
                font-size: 18px;
                font-weight: 700;
                color: {text};
                padding: 6px 8px;
                border-radius: 8px;
                background-color: {chip_bg};
            }
            #GuideDescription {
                font-size: 13px;
                color: {text};
                padding: 10px;
                line-height: 1.55;
                border-radius: 8px;
                background-color: rgba({sidebar_panel_rgb}, 0.52);
            }
            #NavigationButton {
                background-color: {accent};
                color: #ffffff;
                border: 1px solid {accent_border};
                padding: 8px 16px;
                font-weight: 600;
                border-radius: 10px;
                min-width: 80px;
            }
            #NavigationButton:hover {
                background-color: {accent_alt};
            }
            #NavigationButton:pressed {
                background-color: {accent_pressed};
            }
            #NavigationButton:disabled {
                background-color: {btn_disabled_bg};
                color: {btn_disabled_fg};
                border: 1px solid {outline};
            }
            #PageIndicator {
                color: {muted};
                font-size: 11px;
                padding: 4px 8px;
                border-radius: 6px;
                background-color: {chip_bg};
            }
            #ImageFrame {
                background-color: rgba({sandbox_bg_rgb}, 0.92);
                border: 1px solid {outline};
                border-radius: 12px;
            }
            #ImageLabel {
                color: {muted};
                background-color: transparent;
            }
            QRadioButton {
                background-color: {chip_bg};
                color: {text};
                border: 1px solid {outline};
                border-radius: 14px;
                padding: 5px 8px;
                font-size: 12px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.18);
                background-color: rgba({sidebar_panel_rgb}, 1.0);
                margin-right: 6px;
            }
            QRadioButton::indicator:checked {
                background-color: {accent};
                border: 1px solid {accent_alt};
            }
            QComboBox {
                min-width: 180px;
                padding: 6px 10px;
                border-radius: 10px;
                border: 1px solid {outline};
                background-color: {chip_bg};
                color: {text};
            }
            QComboBox::drop-down {
                border: none;
                width: 26px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid {outline};
                background-color: {sidebar_panel};
                color: {text};
                selection-background-color: {accent};
                selection-color: #ffffff;
            }
            #GuideMetaLabel {
                color: {muted};
                font-size: 12px;
                font-weight: 600;
                padding: 6px 12px;
                border-radius: 8px;
                background-color: {chip_bg};
            }
            /* Раньше строка выбора уровня, подсказка и метка «Язык» не имели
               своей поверхности и читались как чёрный фон поверх тёмного
               контейнера (фидбэк Артёма). Даём им ту же лёгкую подложку, что и
               у заголовка. */
            #GuideLevelRow {
                background-color: {chip_bg};
                border-radius: 16px;
            }
            #GuideLevelHint {
                color: {muted};
                font-size: 12px;
                padding: 6px 12px;
                border-radius: 8px;
                background-color: {chip_bg};
            }
            #CloseButton {
                background-color: {chip_bg};
                color: {text};
                border: 1px solid {outline};
                padding: 8px 16px;
                font-weight: 600;
                border-radius: 10px;
            }
            #CloseButton:hover {
                background-color: {chip_hover};
            }
            #CloseButton:pressed {
                background-color: {chip_pressed};
            }
        """, get_theme()))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("GuideContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(15)

        self.setMinimumSize(720, 520)
        self.setMaximumSize(920, 760)

        self._level_hint = None

        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        self.title_label = QLabel("")
        self.title_label.setObjectName("GuideTitle")
        title_row.addWidget(self.title_label, 1)
        title_row.addStretch()

        self.close_button = QPushButton("Завершить")
        self.close_button.setObjectName("CloseButton")
        self.close_button.clicked.connect(self._on_close)
        title_row.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        header_layout.addLayout(title_row)

        container_layout.addLayout(header_layout)

        # Прокручиваемая область для картинки
        self.image_scroll = QScrollArea()
        self.image_scroll.setObjectName("ImageFrame")          # чтобы стили работали
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setMinimumHeight(120)
        self.image_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.image_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.image_scroll.setStyleSheet("QScrollArea { border: none; }")
        self.image_scroll.setSizePolicy(
            self.image_scroll.sizePolicy().horizontalPolicy(),
            QSizePolicy.Expanding
        )

        self.image_label = QLabel()
        self.image_label.setObjectName("ImageLabel")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        # self.image_label.setMinimumWidth(200)
        self.image_scroll.setWidget(self.image_label)

        container_layout.addWidget(self.image_scroll, 1)

        self.description_label = QLabel("")
        self.description_label.setObjectName("GuideDescription")
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.description_label.setTextFormat(Qt.TextFormat.RichText)
        container_layout.addWidget(self.description_label)

        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(15)

        self.prev_button = QPushButton(qta.icon('fa5s.angle-left', color='white'), '')
        self.prev_button.setObjectName("NavigationButton")
        self.prev_button.setFixedSize(40, 35)
        self.prev_button.clicked.connect(self._prev_page)
        nav_layout.addWidget(self.prev_button)

        self.page_indicator = QLabel("1 / 1")
        self.page_indicator.setObjectName("PageIndicator")
        self.page_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(self.page_indicator)

        self.next_button = QPushButton(qta.icon('fa5s.angle-right', color='white'), '')
        self.next_button.setObjectName("NavigationButton")
        self.next_button.setFixedSize(40, 35)
        self.next_button.clicked.connect(self._next_page)
        nav_layout.addWidget(self.next_button)

        nav_layout.addStretch()

        # Переключатель уровня «Базовый / Полный» (внизу по центру)
        self._level_group = QButtonGroup(self)
        self._level_group.setExclusive(True)
        self._level_buttons: dict[str, QRadioButton] = {}
        for key in ("basic", "advanced", "full"):
            rb = QRadioButton("")
            rb.setObjectName("GuideLevelButton")
            rb.setProperty("level_key", key)
            rb.setMinimumHeight(36)
            if key == self._guide_level:
                rb.setChecked(True)
            nav_layout.addWidget(rb)
            self._level_group.addButton(rb)
            self._level_buttons[key] = rb
        self._level_group.buttonClicked.connect(self._on_level_changed)
        self._update_level_texts()            # чтобы текст появился сразу
        nav_layout.addSpacing(20)

        # Перенесённый переключатель языка (справа внизу)
        lang_layout = QHBoxLayout()
        lang_layout.setContentsMargins(0, 0, 0, 0)
        lang_layout.setSpacing(10)

        self.lang_label = QLabel("")
        self.lang_label.setObjectName("GuideMetaLabel")
        lang_layout.addWidget(self.lang_label)

        self.lang_selector = QComboBox()
        self.lang_selector.blockSignals(True)
        for code in available_languages():
            lowered = code.lower()
            self.lang_selector.addItem(language_display_name(code), lowered)
            self._lang_buttons[lowered] = None

        if self.current_language not in self._lang_buttons:
            self.current_language = "ru"
        current_index = self.lang_selector.findData(self.current_language)
        if current_index >= 0:
            self.lang_selector.setCurrentIndex(current_index)
        self.lang_selector.blockSignals(False)
        self.lang_selector.currentIndexChanged.connect(self._on_language_changed)
        lang_layout.addWidget(self.lang_selector, 0)

        nav_layout.addLayout(lang_layout)

        container_layout.addLayout(nav_layout)

        self._update_language_label_text()
        self._update_close_button_text()

        main_layout.addWidget(container)

    def _on_language_changed(self):
        code = self.lang_selector.currentData() if hasattr(self, "lang_selector") else None
        self.current_language = str(code or "ru")
        self._update_language_label_text()
        self._update_close_button_text()
        self._update_level_texts()
        self.show_page(self.current_page_index)

    # Подписи и пояснения уровней (локализуются под выбранный язык).
    _LEVEL_LABELS = {
        "basic": ("Базовый", "Basic"),
        "advanced": ("Продвинутый", "Advanced"),
        "full": ("Полный", "Full"),
    }
    _LEVEL_HINTS = {
        "basic": ("Только самое необходимое для старта: подключение и готово!",
                  "Just the essentials to get started: connection and you're ready!"),
        "advanced": ("Базовый гайд + озвучка и микрофон.",
                     "Basic guide + voiceover and microphone."),
        "full": ("Все разделы: + память, экран, модели и песочница.",
                 "All sections: + memory, screen, models, and sandbox."),
    }

    def _update_level_texts(self):
        for key, rb in getattr(self, "_level_buttons", {}).items():
            ru, en = self._LEVEL_LABELS.get(key, (key, key))
            rb.setText(translate_for_language(self.current_language, ru, en))
            hru, hen = self._LEVEL_HINTS.get(key, ("", ""))
            rb.setToolTip(translate_for_language(self.current_language, hru, hen))
        hint = getattr(self, "_level_hint", None)
        if hint is not None:
            hru, hen = self._LEVEL_HINTS.get(self._guide_level, ("", ""))
            hint.setText(translate_for_language(self.current_language, hru, hen))

    def _update_language_label_text(self):
        self.lang_label.setText(
            translate_for_language(self.current_language, "Язык", "Language")
        )

    def _update_close_button_text(self):
        self.close_button.setText(
            translate_for_language(self.current_language, "Завершить", "Finish")
        )

    def _on_level_changed(self, btn):
        level = btn.property("level_key")
        if not level:
            return
        self._guide_level = level
        self._update_filtered_pages()
        self._update_level_texts()
        self.current_page_index = 0
        self.show_page(0)
        # Раньше здесь были: SettingsManager.set() без сохранения на диск и emit
        # несуществующего Events.Settings.GUIDE_LEVEL_CHANGED — оба под try/except,
        # то есть уровень гайда молча не сохранялся и никто о смене не узнавал.
        # SettingsService.update() сразу обновляет реестр и планирует запись на диск.
        try:
            set_setting(self, "GUIDE_LEVEL", level)
        except Exception as e:
            logger.warning(f"[GuideWidget] Не удалось сохранить GUIDE_LEVEL: {e}")

    def _update_filtered_pages(self):
        cur_rank = _LEVEL_RANK.get(self._guide_level, 0)
        self._filtered_pages = [
            p for p in self.pages
            if _LEVEL_RANK.get(getattr(p, 'min_mode', 'basic'), 0) <= cur_rank
        ]

    def _init_pages(self):
        self.pages = [
            WelcomeGuidePage(),
            PresetGuidePage(),
            VoiceoverGuidePage(),
            MicrophoneGuidePage(),
            MemoryGuidePage(),
            ScreenAnalysisGuidePage(),
            ModelsGuidePage(),
            SandboxGuidePage(),
            FinalGuidePage(),
        ]
        self._update_filtered_pages()

    def _load_image(self, filename):
        if not filename:
            no_image_text = "Изображение не загружено" if self.current_language == "ru" else "Image not loaded"
            self.image_label.setText(no_image_text)
            self.image_frame.setFixedHeight(120)
            return None

        image_path = os.path.join("assets", filename)
        if os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                return pixmap

        no_image_text = f"Изображение не загружено:\n{filename}" if self.current_language == "ru" else f"Image not loaded:\n{filename}"
        self.image_label.setText(no_image_text)
        self.image_frame.setFixedHeight(120)
        return None

    @staticmethod
    def _format_description(text: str) -> str:
        """Convert plain-text paragraphs and bullet lines to compact rich text."""
        blocks = []
        list_items = []

        def flush_list():
            if list_items:
                blocks.append(
                    "<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>"
                )
                list_items.clear()

        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                flush_list()
                continue

            bullet = re.match(r"^(?:[\u2022-]|\u2014)\s+(.*)$", line)
            if bullet:
                list_items.append(bullet.group(1))
                continue

            # Some archived pages omit the bullet before a numbered step.
            # Keep such lines in the current list instead of making a paragraph.
            numbered_step = re.search(r"<b>\s*\d+\s*[-+]", line)
            if numbered_step:
                list_items.append(line)
                continue

            flush_list()
            blocks.append(f"<p>{line}</p>")

        flush_list()
        return "".join(blocks)

    def show_page(self, index: int):
        if 0 <= index < len(self._filtered_pages):
            self.current_page_index = index
            page = self._filtered_pages[index]

            self.title_label.setText(
                translate_for_language(self.current_language, page.get_title_ru(), page.get_title_en())
            )
            description = translate_for_language(
                self.current_language,
                page.get_description_ru(),
                page.get_description_en(),
            )
            self.description_label.setText(self._format_description(description))

            image_filename = page.get_image_filename(self.current_language)
            pixmap = self._load_image(image_filename)

            if pixmap:
                viewport_width = self.image_scroll.viewport().width() - 10
                if viewport_width < 100:
                    viewport_width = self.width() - 80

                # Если картинка и так влезает — показываем 1:1
                if pixmap.width() <= viewport_width:
                    scaled_pixmap = pixmap
                else:
                    # Уменьшаем до ширины viewport'а с высоким качеством
                    scaled_pixmap = pixmap.scaled(
                        viewport_width,
                        pixmap.height(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    # пересчитать пиксели с лучшим сглаживанием
                    scaled_pixmap = scaled_pixmap.scaled(
                        scaled_pixmap.size(),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )

                self.image_label.setPixmap(scaled_pixmap)
                self.image_label.setFixedSize(scaled_pixmap.size())
            else:
                self.image_label.clear()
                no_image_text = "Изображение не загружено" if self.current_language == "ru" else "Image not loaded"
                self.image_label.setText(no_image_text)
                self.image_label.setMinimumSize(200, 100)

            self.page_indicator.setText(f"{index + 1} / {len(self._filtered_pages)}")

            self.prev_button.setEnabled(index > 0)
            self.next_button.setVisible(index < len(self._filtered_pages) - 1)

    def start(self):
        self.show_page(0)

    def _prev_page(self):
        if self.current_page_index > 0:
            self.show_page(self.current_page_index - 1)

    def _next_page(self):
        if self.current_page_index < len(self._filtered_pages) - 1:
            self.show_page(self.current_page_index + 1)

    def _on_close(self):
        self.closed.emit()

# ----------------- СТРАНИЦЫ РУКОВОДСТВА (обновлённые) -----------------

_LEVEL_RANK = {"basic": 0, "advanced": 1, "full": 2}


class WelcomeGuidePage(IGuidePage):
    min_mode = "basic"

    def get_title_ru(self):
        return "Добро пожаловать в NeuroMita!"

    def get_title_en(self):
        return "Welcome to NeuroMita!"

    def get_description_ru(self):
        return """Привет! Это краткое руководство поможет вам быстро освоиться в NeuroMita.

В этом гайде мы пройдёмся по самым важным настройкам, чтобы вы могли сразу начать общение.
Нажмите 'Далее', чтобы начать, или 'Завершить', если хотите разобраться сами."""

    def get_description_en(self):
        return """Hello! This quick guide will help you get comfortable with NeuroMita.

In this guide, we’ll walk through the most important settings so you can start chatting right away.
Click 'Next' to begin, or 'Finish' if you want to figure it out on your own."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_welcome.png" if language == "ru" else "guide/guide_welcome1.png"


class PresetGuidePage(IGuidePage):
    min_mode = "basic"

    def get_title_ru(self):
        return "Создание своего пресета"

    def get_title_en(self):
        return "Creating Your Own Preset"

    def get_description_ru(self):
        return """Чтобы НейроМита ожила и могла с вами общаться, ей нужен доступ к языковой модели — её «мозгу». Для этого мы создадим ваш первый пресет API. Это просто!

• Откройте настройки и перейдите во вкладку <b>API</b>. Нажмите <b>1 +</b>, чтобы добавить новый пресет.
• Выберите <b>2 - Шаблон</b> провайдера — например, OpenRouter, Gemini, или KodikRouter и нажмите <b>OK</b>. Если вашего провайдера нет в списке, используйте вариант «Без шаблона».
Затем вам понадобится <b>3 - API-ключ</b>. Перейдите по ссылке <b>4 - Получить ключ</b>, зарегистрируйтесь у провайдера и вставьте ключ в соответствующее поле.
Чтобы проверить, всё ли работает, нажмите <b>5 - Тест подключения</b> и выберите модель из списка. Или оставьте ту, что предложена по умолчанию.
В конце нажмите <b>6 - Сохранить</b> — и пресет готов! Теперь Мита будет думать именно с помощью этой модели."""

    def get_description_en(self):
        return """For NeuroMita to come alive and chat with you, she needs access to a language model — her “brain”. Let’s create your first API preset. It’s easy!

Open the settings and go to the <b>API</b> tab. Click <b>1 +</b> to add a new preset.
Choose a <b>2 - Template</b> — for example, OpenRouter, Gemini, or KodikRouter — and click <b>OK</b>. If your provider isn't listed, select “No template”.
Next, you’ll need an <b>3 - API key</b>. Follow the <b>4 - Get key</b> link, sign up with the provider, and paste the key into the field.
To make sure everything works, click <b>5 - Test Connection</b> and pick a model from the list. Or keep the default one.
Finally, click <b>6 - Save</b> — and your preset is ready! Now Mita will think using this model."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_preset.png" if language == "ru" else "guide/guide_preset1.png"


class VoiceoverGuidePage(IGuidePage):
    min_mode = "advanced"

    def get_title_ru(self):
        return "Озвучка - голосовые ответы"

    def get_title_en(self):
        return "Voiceover — Voice Responses"

    def get_description_ru(self):
        return """Хотите, чтобы Мита общалась голосом?
• В настройках Озвучки (иконка динамика) включите <b>1 - Использовать озвучку</b>.

После включения станут доступны два метода:
• <b>TG (Telegram)</b> — простой способ, потребуется связать аккаунт Telegram.
• <b>Local</b> — качественная локальная генерация голоса с помощью скачиваемой модели (нужна мощная видеокарта).

Выберите подходящий вариант.

Если вы предпочитаете Local, потребуется скачать модель синтеза речи:
• Включите <b>1 - Использовать озвучку</b>, если ещё не включили, и выберите <b>2 - Local</b> в списке методов.
• Выберите <b>3 - язык озвучки</b>.
• Нажмите кнопку <b>4 - Установить</b> — откроется <b>AI Hub</b>, где можно выбрать модель, подходящую для вашей видеокарты.
• После завершения установки Мита сможет говорить локальным голосом."""

    def get_description_en(self):
        return """Want Mita to talk?
• In the Voiceover settings (speaker icon), enable <b>1 - Use speech</b>.

Once enabled, two methods become available:
• <b>TG (Telegram)</b> — a simple option, requires linking a Telegram account.
• <b>Local</b> — high-quality local voice generation using a downloadable model (requires a powerful GPU).

Choose the one that suits you.

If you prefer Local, you'll need to download a speech synthesis model:
• Enable <b>1 - Use speech</b> if you haven't already, and select <b>2 - Local</b> from the list of methods.
• Choose <b>3 - the voice language</b>.
• Click <b>4 - Install</b> — the <b>AI Hub</b> will open, where you can pick a model suitable for your graphics card.
• After installation, Mita will be able to speak with a local voice."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_voice.png" if language == "ru" else "guide/guide_voice1.png"


class MicrophoneGuidePage(IGuidePage):
    min_mode = "advanced"

    def get_title_ru(self):
        return "Голосовой ввод (Микрофон)"

    def get_title_en(self):
        return "Voice Input (Microphone)"

    def get_description_ru(self):
        return """Вы можете не только слышать Миту, но и говорить с ней, используя ввод голосом.

Чтобы включить микрофон:
• Перейдите в настройки.
• Выберите вкладку <b>ASR</b> со значком микрофона.
• Выберите ваш микрофон из <b>1 - списка устройств</b>.
• Нажмите кнопку <b>2 - Перейти к настройкам AI Engine</b>.
• Откроется <b>AI Hub</b> — перейдите на вкладку <b>3 - Распознавание (ASR)</b>.
• Выберите подходящую модель распознавания речи и дождитесь установки.
• Установите галочку <b>4 - Микрофон активен</b>

Теперь можно общаться с Митой голосом."""

    def get_description_en(self):
        return """You can not only hear Mita, but also talk to her using voice input.

To set up the microphone:
• Go to Settings.
• Select the <b>ASR</b> tab with the microphone icon.
• Choose your microphone from <b>1 - the device list</b>.
• Click the <b>2 - Open AI Engine settings</b> button.
• The <b>AI Hub</b> will open — go to the <b>3 - ASR</b> tab.
• Select a suitable speech recognition model and wait for it to install.
• Check the box <b>4 - Microphone active</b>.

Now you can talk to Mita with your voice."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_microphone.png" if language == "ru" else "guide/guide_microphone1.png"


class MemoryGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Память и граф знаний (RAG)"

    def get_title_en(self):
        return "Memory & Knowledge Graph (RAG)"

    def get_description_ru(self):
        return """В NeuroMita появилась продвинутая память! Перейдите в настройки и откройте раздел <b>Модели</b>.
Здесь вы можете:
- Включить улучшенный (RAG) поиск в памяти.
- Настроить векторный поиск в истории.
- Активировать граф знаний — Мита будет понимать связи между объектами.
- И ещё сделать множество улучшений памяти Миты.

<b>Включаем пайплайн:</b>
• Разверните вкладку <b>1 - Пресет пайплайна</b>.
• Выберите один из <b>2 - предустановленных пресетов</b>.
• Нажмите <b>3 - Применить</b>.

<b>Включаем RAG:</b>
• Разверните вкладку <b>4 - RAG и память</b>.
• Включите переключатели <b>5 - Включить RAG</b>, <b>6 - Искать в памяти</b> и <b>7 - Искать в истории</b>.

<b>Включаем векторный поиск:</b>
• Разверните вкладку <b>8 - Векторный поиск и эмбеддинги</b>.
• Активируйте переключатель <b>9 - Векторный поиск</b>.
• <b>10 - Выберите пресет</b> (для начала рекомендуется выбрать пресет с не локальной моделью, например OpenRouter Embeddings или Google Gemini Embeddings).
• Введите <b>11 - API ключ</b> (можно использовать тот же ключ, что и для языковой модели).
• Нажмите <b>12 - Тест</b> — если показало <b>OK</b>, значит модель работает.
• Нажмите <b>13 - Сохранить</b>.
• Нажмите <b>14 - Обновить статус</b>.
• Если появилось сообщение о неиндексированных записях, нажмите <b>15 - Индекс нового</b> и дождитесь окончания процесса индексации.

<b>Активируем граф:</b>
• Разверните вкладку <b>16 - Граф знаний (экстракция сущностей)</b>.
• Активируйте переключатель <b>17 - Включить экстракцию сущностей</b>.
• Рекомендуется также включить <b>18 - Inline-режим</b>.

Всё это делает общение намного глубже: Мита не забывает контекст и может эффективнее рассуждать о различных деталях и ваших приключениях с ней."""

    def get_description_en(self):
        return """NeuroMita now features advanced memory! Go to Settings and open the <b>Models</b> section.
Here you can:
- Enable improved (RAG) memory search.
- Set up vector search in history.
- Activate the knowledge graph — Mita will understand relationships between objects.
- And much more to enhance Mita's memory.

<b>Enabling the pipeline:</b>
• Expand the <b>1 - Pipeline Preset</b> tab.
• Select one of <b>2 - the preset pipelines</b>.
• Click <b>3 - Apply</b>.

<b>Enabling RAG:</b>
• Expand the <b>4 - RAG & Memory</b> tab.
• Turn on the toggles: <b>5 - Enable RAG</b>, <b>6 - Search in Memory</b>, and <b>7 - Search in History</b>.

<b>Enabling vector search:</b>
• Expand the <b>8 - Vector Search and Embeddings</b> tab.
• Activate the switch <b>9 - Vector Search</b>.
• <b>10 - Choose a preset</b> (for starters, it's recommended to pick a non-local model, e.g. OpenRouter Embeddings or Google Gemini Embeddings).
• Enter your <b>11 - API key</b> (you can use the same key as for the language model).
• Click <b>12 - Test</b> — if it shows <b>OK</b>, the model is working.
• Click <b>13 - Save</b>.
• Click <b>14 - Update Status</b>.
• If a message about unindexed records appears, click <b>15 - Index New</b> and wait for the indexing process to finish.

<b>Activating the graph:</b>
• Expand the <b>16 - Knowledge Graph (Entity Extraction)</b> tab.
• Turn on the <b>17 - Enable Entity Extraction</b> toggle.
• It's also recommended to enable <b>18 - Inline Mode</b>.

All this makes conversations much deeper: Mita doesn't forget context and can reason more effectively about various details and your adventures with her."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_memory.png" if language == "ru" else "guide/guide_memory1.png"


class ScreenAnalysisGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Анализ экрана и камеры"

    def get_title_en(self):
        return "Screen & Camera Analysis"

    def get_description_ru(self):
        return """Мита может видеть происходящее на экране, скриншоты или вас через веб-камеру.

<b>Для изображений и скриншотов:</b>
• Перейдите в настройки и откройте раздел <b>Изображения</b>.
• Откройте вкладку <b>1 - Настройки анализа экрана</b>.
• Включите <b>2 - Разрешить обработку изображений</b>.
• Вы можете показывать Мите свой экран каждым сообщением или включить непрерывную отправку (например, для просмотра видео вместе с Митой).
• Можно прикреплять изображение или скриншот экрана и отправлять их Мите с помощью соответствующих кнопок в поле чата песочницы.

<b>Для захвата с камеры:</b>
• Перейдите в настройки и откройте раздел <b>Изображения</b>.
• Откройте вкладку <b>3 - Настройки захвата с камеры</b>.
• Активируйте переключатель <b>4 - Включить захват с камеры</b> (у вас должна быть подключена веб-камера).
• Если OpenCV не установлен, сначала сделайте видимым раздел <b>5 - AI Engine</b> в общих настройках.
• Откройте вкладку <b>6 - AI Engine</b> и нажмите в этой вкладке кнопку <b>AI Hub</b>.
• В AI Hub перейдите на вкладку <b>7 - Зависимости</b>.
• Установите <b>8 - OpenCV</b>.
• Вернитесь в <b>3 - Настройки захвата с камеры</b> и <b>9 - выберите камеру</b>.
Теперь Мита сможет увидеть вас через веб-камеру.

• Мита сможет анализировать изображения, только если выбранная языковая модель поддерживает обработку изображений (например: Gemini, Mistral)."""

    def get_description_en(self):
        return """Mita can see what's happening on your screen, screenshots, or you through your webcam.

<b>For images and screenshots:</b>
• Go to Settings and open the <b>Images</b> section.
• Open the <b>1 - Screen Analysis Settings</b> tab.
• Turn on <b>2 - Enable Image Analysis</b>.
• You can show Mita your screen with every message, or enable continuous capture (for example, to watch videos together with Mita).
• You can attach an image or a screenshot and send it to Mita using the corresponding buttons in the Sandbox chat field.

<b>For camera capture:</b>
• Go to Settings and open the <b>Images</b> section.
• Open the <b>3 - Camera Capture Settings</b> tab.
• Turn on <b>4 - Enable Camera Capture</b> (make sure your webcam is connected).
• If OpenCV is not installed, first make the <b>5 - AI Engine</b> section visible in the general settings.
• Open the <b>6 - AI Engine</b> tab and click the <b>AI Hub</b> button inside it.
• In AI Hub, go to the <b>7 - Dependencies</b> tab.
• Install <b>8 - OpenCV</b>.
• Return to <b>3 - Camera Capture Settings</b> and <b>9 - select your camera</b>.
Now Mita will be able to see you via the webcam.

• Mita can analyze images only if the selected language model supports image processing (e.g., Gemini, Mistral)."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_screen.png" if language == "ru" else "guide/guide_screen1.png"


class ModelsGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Параметры генерации"

    def get_title_en(self):
        return "Generation Parameters"

    def get_description_ru(self):
        return """Вы можете тонко настроить, как именно Мита формулирует ответы.
Для большинства случаев стандартные настройки уже хороши, но если хочется больше креативности или, наоборот, строгости — эти параметры для вас.

<b>Где находятся:</b>
• Откройте настройки и перейдите во вкладку <b>Модели</b>.
• Разверните вкладку <b>1 - Настройки генерации текста</b>.

<b>Основные параметры:</b>
• <b>2 - Макс. токенов в ответе</b> — максимальная длина ответа Миты. Если ответы обрываются — увеличьте значение.
• <b>3 - Температура</b> — управляет креативностью. 0.0 — очень строгие, предсказуемые ответы; 2.0 — очень творческие и неожиданные.
• <b>4 - Top-K</b> — ограничивает выбор только K самых вероятных следующих слов. Чем ниже K (например, 10), тем суше ответ. Чем выше (например, 80), тем разнообразнее лексика.
• <b>5 - Top-P</b> — ядерная выборка: модель перебирает слова, пока их суммарная вероятность не достигнет P. Например, P=0.9 означает, что модель выберет из самого узкого набора слов, дающих 90% уверенности. Низкое P — более сфокусированный ответ, высокое P — больше экспериментов.
• <b>6 - Штраф присутствия</b> — насколько модель избегает повторения уже использованных слов. Положительное значение 0.1–2.0 заставит Миту чаще говорить о новых вещах, а не топтаться на одном.
• <b>7 - Штраф частоты</b> — снижает вероятность повторения одних и тех же слов пропорционально их частоте в ответе. Полезно, если Мита начинает «зацикливаться». Обычно хватает небольшого значения 0.1–0.5, чтобы ответы стали разнообразнее.

Не бойтесь экспериментировать: если результат не нравится, всегда можно вернуться к стандартным."""

    def get_description_en(self):
        return """You can fine-tune how Mita formulates her responses.
The default settings work well for most cases, but if you want more creativity or stricter answers — these parameters are for you.

<b>Where to find them:</b>
• Open Settings and go to the <b>Models</b> tab.
• Expand the <b>1 - Text Generation Settings</b> section.

<b>Key parameters:</b>
• <b>2 - Max tokens in response</b> — the maximum length of Mita's answer. If responses get cut off, increase this value.
• <b>3 - Temperature</b> — controls creativity. 0.0 gives very strict, predictable answers; 2.0 gives very creative, unexpected ones.
• <b>4 - Top-K</b> — limits the selection to only the K most likely next words. A low K (e.g., 10) makes answers more focused and dry; a higher K (e.g., 80) adds lexical variety.
• <b>5 - Top-P</b> — nucleus sampling: the model considers words until their total probability reaches P. For example, P=0.9 means the model picks from the smallest set of words that together have at least 90% confidence. Lower P gives more focused answers, higher P encourages more variety.
• <b>6 - Presence penalty</b> — how much the model avoids repeating words already used. A positive value of 0.1–2.0 encourages Mita to bring up new topics rather than circling around the same ones.
• <b>7 - Frequency penalty</b> — reduces the chance of repeating the same words based on how often they've appeared. Useful if Mita starts sounding repetitive. A small value of 0.1–0.5 usually makes responses more diverse.

Feel free to experiment: if you don't like the results, you can always go back to the defaults."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_models.png" if language == "ru" else "guide/guide_models1.png"


class SandboxGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Песочница: отладка и тестирование"

    def get_title_en(self):
        return "Sandbox: Debugging & Testing"

    def get_description_ru(self):
        return """Если что-то работает не так, как ожидалось, отладка поможет понять, в чём дело.
Перейдите в Песочницу и откройте вкладку <b>1 - Отладка</b> — это мощный инструмент для просмотра состояния Миты и тестирования.

<b>Основные возможности диагностики:</b>
• <b>2 - Открыть DB персонажа</b> — просмотр сохранённых воспоминаний Миты, истории и графических связей.
• <b>3 - Открыть страницу логов</b> — если какую-то ошибку не удаётся исправить, сохраните логи, они помогут разработчикам понять проблему.
• <b>4 - Structured output (дебаг)</b> — выберите <b>5 - JSON</b>, чтобы видеть структуру ответа Миты прямо в чате.
• <b>6 - Вставить system-сообщение в историю</b> — вы можете добавить своё сообщение как системное.
• <b>7 - Просмотр контекста запроса</b>:
  — <b>8 - Посмотреть последний запрос</b> — полный запрос, отправляемый нейросети.
  — <b>9 - Посмотреть последний ответ</b> — полный ответ нейросети."""

    def get_description_en(self):
        return """If something isn't working as expected, the Debug tab will help you figure out what's going on.
Go to the Sandbox and open the <b>1 - Debug</b> tab — a powerful tool for inspecting Mita's state and testing.

<b>Main diagnostic features:</b>
• <b>2 - Open Character DB</b> — view Mita's saved memories, history, and graphical connections.
• <b>3 - Open logs page</b> — if you can't fix an error, save the logs, they will help developers understand the problem.
• <b>4 - Structured output (debug)</b> — select <b>5 - JSON</b> to see the structure of Mita's response directly in the chat.
• <b>6 - Insert system message into history</b> — you can add your own message as a system message.
• <b>7 - Request context viewer</b>:
  — <b>8 - View last request</b> — the full request sent to the neural network.
  — <b>9 - View last response</b> — the full response from the neural network."""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_sandbox.png" if language == "ru" else "guide/guide_sandbox1.png"


class FinalGuidePage(IGuidePage):
    min_mode = "basic"

    def get_title_ru(self):
        return "Готово!"

    def get_title_en(self):
        return "All Set!"

    def get_description_ru(self):
        return """В NeuroMita вы можете общаться с разными Митами, каждая со своим характером и историей.
Миты уже готовы вас принять.

<b>🎮 Игра:</b>
Скачайте игру NeuroMita (Unity-версия) и погрузитесь в мир Мит. Поставьте <b>1 - галочку</b> для скачивания Unity. Кнопка «Скачать Unity» загрузит последнюю версию игры.
Если игра уже установлена, просто нажмите «Играть» и начинайте приключение.

<b>⏳ Песочница:</b>
Если нужно общение только в чате, откройте Песочницу.
Здесь также можно:
• Выбрать понравившуюся Миту — <b>2 - Крейзи, Добрая, Сонная и другие</b>.
• Выбрать или настроить <b>3 - Набор промптов</b>, который определит характер и поведение Миты.
• Выбрать <b>4 - Пресет</b> для Миты.
• Можно сразу начать чат — Мита ответит, используя созданный вами пресет.

<b>Помните: это лишь основные настройки. Не бойтесь исследовать и другие разделы — NeuroMita умеет гораздо больше!</b>"""

    def get_description_en(self):
        return """In NeuroMita you can chat with different Mitas, each with their own personality and story.
The Mitas are ready to welcome you.

<b>🎮 Game:</b>
Download the NeuroMita game (Unity version) and dive into the world of Mitas. Check <b>1 - the checkbox</b> to download Unity. The “Download Unity” button will fetch the latest game version.
If the game is already installed, just click “Play” and begin your adventure.

<b>⏳ Sandbox:</b>
If you only need text chat, open the Sandbox.
Here you can also:
• Choose your favorite Mita — <b>2 - Crazy, Kind, Sleepy and others</b>.
• Select or customize <b>3 - a prompt set</b> that defines Mita's character and behavior.
• Choose <b>4 - a preset</b> for Mita.
• Start chatting right away — Mita will respond using the preset you created.

<b>Remember: these are just the main settings. Don't be afraid to explore other sections — NeuroMita can do a whole lot more!</b>"""

    def get_image_filename(self, language: str) -> str:
        return "guide/guide_next.png" if language == "ru" else "guide/guide_next1.png"
