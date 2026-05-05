# src/ui/widgets/guide_widget.py
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame, QRadioButton, QButtonGroup
from PyQt6.QtGui import QPixmap
import qtawesome as qta
from abc import ABC, abstractmethod
from core.events import get_event_bus, Events
import os
from styles.theme import get_theme
from utils import render_qss

class IGuidePage(ABC):
    min_mode: str = "basic"

    def __init__(self):
        pass
        
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
    def get_image_filename(self) -> str:
        pass

class GuideWidget(QWidget):
    closed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.event_bus = get_event_bus()
        self.pages = []
        self.current_page_index = 0
        self.current_language = "ru"
        self._guide_level = "basic"
        self._filtered_pages = []
        try:
            from managers.settings_manager import SettingsManager
            from ui.widgets.settings_panel import normalize_mode
            saved = SettingsManager.get("GUIDE_LEVEL")
            if saved in ("basic", "advanced", "full"):
                self._guide_level = saved
            else:
                iface = SettingsManager.get("INTERFACE_MODE")
                self._guide_level = normalize_mode(iface)
        except Exception:
            pass
        self.setObjectName("GuideWidget")
        self.setup_ui()
        self._init_pages()
    
    def setup_ui(self):
        self.setStyleSheet(render_qss("""
            #GuideWidget {
                background-color: transparent;
            }
            #GuideContainer {
                background-color: rgba({settings_panel_rgb}, 0.95);
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
            #SkipButton {
                background-color: {chip_bg};
                color: {text};
                border: 1px solid {outline};
                padding: 8px 16px;
                font-weight: 600;
                border-radius: 10px;
            }
            #SkipButton:hover {
                background-color: {chip_hover};
            }
            #SkipButton:pressed {
                background-color: {chip_pressed};
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
        """, get_theme()))
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        container = QFrame()
        container.setObjectName("GuideContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(15)
        
        self.setMinimumSize(600, 500)
        self.setMaximumSize(800, 700)
        
        # --- Level selector ---
        level_row = QWidget()
        level_row_layout = QHBoxLayout(level_row)
        level_row_layout.setContentsMargins(0, 0, 0, 4)
        level_row_layout.setSpacing(8)
        level_row_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._level_group = QButtonGroup(level_row)
        self._level_group.setExclusive(True)

        for label, key in [("Базовый", "basic"), ("Продвинутый", "advanced"), ("Полный", "full")]:
            rb = QRadioButton(label)
            rb.setObjectName("GuideLevelButton")
            rb.setProperty("level_key", key)
            if key == self._guide_level:
                rb.setChecked(True)
            level_row_layout.addWidget(rb)
            self._level_group.addButton(rb)

        self._level_group.buttonClicked.connect(self._on_level_changed)
        container_layout.addWidget(level_row)

        header_layout = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setObjectName("GuideTitle")
        header_layout.addWidget(self.title_label)
        
        header_layout.addStretch()
        
        lang_layout = QHBoxLayout()
        lang_layout.setSpacing(10)
        
        self.lang_group = QButtonGroup()
        self.ru_radio = QRadioButton("RU")
        self.ru_radio.setChecked(True)
        self.en_radio = QRadioButton("EN")
        
        self.lang_group.addButton(self.ru_radio, 0)
        self.lang_group.addButton(self.en_radio, 1)
        self.lang_group.buttonClicked.connect(self._on_language_changed)
        
        lang_layout.addWidget(self.ru_radio)
        lang_layout.addWidget(self.en_radio)
        header_layout.addLayout(lang_layout)
        
        self.skip_button = QPushButton("Пропустить")
        self.skip_button.setObjectName("SkipButton")
        self.skip_button.clicked.connect(self._on_skip)
        header_layout.addWidget(self.skip_button)
        
        container_layout.addLayout(header_layout)
        
        self.image_frame = QFrame()
        self.image_frame.setObjectName("ImageFrame")
        self.image_frame.setMinimumHeight(120)
        self.image_frame.setMaximumHeight(350)
        image_layout = QVBoxLayout(self.image_frame)
        image_layout.setContentsMargins(10, 10, 10, 10)
        
        self.image_label = QLabel()
        self.image_label.setObjectName("ImageLabel")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(200, 100)
        image_layout.addWidget(self.image_label)
        
        container_layout.addWidget(self.image_frame)
        
        self.description_label = QLabel("")
        self.description_label.setObjectName("GuideDescription")
        self.description_label.setWordWrap(True)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.description_label.setTextFormat(Qt.TextFormat.RichText)
        container_layout.addWidget(self.description_label, 1)
        
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
        
        self.close_button = QPushButton("Завершить")
        self.close_button.setObjectName("NavigationButton")
        self.close_button.clicked.connect(self._on_close)
        self.close_button.hide()
        nav_layout.addWidget(self.close_button)
        
        container_layout.addLayout(nav_layout)
        
        main_layout.addWidget(container)  

    def _on_language_changed(self):
        self.current_language = "ru" if self.ru_radio.isChecked() else "en"
        self._update_skip_button_text()
        self._update_close_button_text()
        self.show_page(self.current_page_index)
        
    def _update_skip_button_text(self):
        if self.current_language == "ru":
            self.skip_button.setText("Пропустить")
        else:
            self.skip_button.setText("Skip")
            
    def _update_close_button_text(self):
        if self.current_language == "ru":
            self.close_button.setText("Завершить")
        else:
            self.close_button.setText("Finish")
        
    def _on_level_changed(self, btn):
        level = btn.property("level_key")
        if not level:
            return
        self._guide_level = level
        self._update_filtered_pages()
        self.current_page_index = 0
        self.show_page(0)
        try:
            from managers.settings_manager import SettingsManager
            SettingsManager.set("GUIDE_LEVEL", level)
        except Exception:
            pass
        try:
            self.event_bus.emit(Events.Settings.GUIDE_LEVEL_CHANGED, level)
        except Exception:
            pass

    def _update_filtered_pages(self):
        cur_rank = _LEVEL_RANK.get(self._guide_level, 0)
        self._filtered_pages = [
            p for p in self.pages
            if _LEVEL_RANK.get(getattr(p, 'min_mode', 'basic'), 0) <= cur_rank
        ]

    def _init_pages(self):
        self.pages = [
            WelcomeGuidePage(),
            APIGuidePage(),
            CharactersGuidePage(),
            VoiceoverGuidePage(),
            MicrophoneGuidePage(),
            ScreenAnalysisGuidePage(),
            ModelsGuidePage(),
            ChatGuidePage(),
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

    def show_page(self, index: int):
        if 0 <= index < len(self._filtered_pages):
            self.current_page_index = index
            page = self._filtered_pages[index]

            if self.current_language == "ru":
                self.title_label.setText(page.get_title_ru())
                self.description_label.setText(page.get_description_ru())
            else:
                self.title_label.setText(page.get_title_en())
                self.description_label.setText(page.get_description_en())

            image_filename = page.get_image_filename()
            pixmap = self._load_image(image_filename)

            if pixmap:
                available_width = self.width() - 80
                available_height = 320

                scaled_pixmap = pixmap.scaled(
                    available_width,
                    available_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )

                self.image_label.setPixmap(scaled_pixmap)

                needed_height = scaled_pixmap.height() + 20
                final_height = max(120, min(needed_height, 350))
                self.image_frame.setFixedHeight(final_height)

            self.page_indicator.setText(f"{index + 1} / {len(self._filtered_pages)}")

            self.prev_button.setEnabled(index > 0)
            self.next_button.setVisible(index < len(self._filtered_pages) - 1)
            self.close_button.setVisible(index == len(self._filtered_pages) - 1)

    def start(self):
        self.show_page(0)
        
    def _prev_page(self):
        if self.current_page_index > 0:
            self.show_page(self.current_page_index - 1)

    def _next_page(self):
        if self.current_page_index < len(self._filtered_pages) - 1:
            self.show_page(self.current_page_index + 1)
            
    def _on_skip(self):
        self._on_close()
        
    def _on_close(self):
        self.closed.emit()

# ----------------- СТРАНИЦЫ РУКОВОДСТВА -----------------

_LEVEL_RANK = {"basic": 0, "advanced": 1, "full": 2}


class WelcomeGuidePage(IGuidePage):
    min_mode = "basic"

    def get_title_ru(self):
        return "Добро пожаловать в NeuroMita!"
        
    def get_title_en(self):
        return "Welcome to NeuroMita!"
        
    def get_description_ru(self):
        return """Привет! Это краткое руководство поможет вам быстро разобраться в основах. 
NeuroMita — это ваш умный AI-ассистент, которого можно настроить под любые задачи.

В этом гайде мы пройдемся по самым важным настройкам, чтобы вы могли сразу начать общение. 
Нажмите 'Далее', чтобы начать, или 'Пропустить', если хотите разобраться сами."""
        
    def get_description_en(self):
        return """Hello! This quick guide will help you understand the basics.
NeuroMita is your smart AI assistant that can be configured for any task.

In this guide, we'll walk through the most important settings so you can start chatting right away.
Click 'Next' to begin, or 'Skip' if you want to figure it out on your own."""
        
    def get_image_filename(self):
        return "guide_welcome.jpg"

class APIGuidePage(IGuidePage):
    min_mode = "basic"

    def get_title_ru(self):
        return "Шаг 1: Подключение к 'мозгу' AI"
        
    def get_title_en(self):
        return "Step 1: Connecting to the AI 'Brain'"
        
    def get_description_ru(self):
        return """Чтобы ассистент заработал, ему нужен доступ к большой языковой модели (LLM) — это и есть его "мозг". Этот доступ осуществляется через API.

В настройках API (иконка <b>вилки</b>) вы можете выбрать <b>Провайдера</b>:
• <b>g4f (бесплатно)</b>: Отличный вариант для начала! Использует различные бесплатные сервисы. Просто выберите его, и можно начинать.
• <b>OpenAI, Claude и др. (платно)</b>: Более стабильные и мощные модели. Для них нужен <b>API-ключ</b> (ваш личный "пароль"), который можно получить на сайте провайдера.

<b>Проще говоря:</b> выберите 'g4f' в списке, чтобы сразу начать, или вставьте свой ключ от платного сервиса для максимального качества."""
        
    def get_description_en(self):
        return """For the assistant to work, it needs access to a large language model (LLM) — its "brain." This access is provided via an API.

In the API settings (<b>plug</b> icon), you can select a <b>Provider</b>:
• <b>g4f (free)</b>: A great option to start! It uses various free services. Just select it, and you're ready to go.
• <b>OpenAI, Claude, etc. (paid)</b>: More stable and powerful models. They require an <b>API key</b> (your personal "password"), which you can get from the provider's website.

<b>Simply put:</b> choose 'g4f' from the list to start immediately, or insert your key from a paid service for maximum quality."""
        
    def get_image_filename(self):
        return "guide_api.jpg"

class CharactersGuidePage(IGuidePage):
    min_mode = "basic"

    def get_title_ru(self):
        return "Шаг 2: Выбор Персонажа"
        
    def get_title_en(self):
        return "Step 2: Choosing a Character"
        
    def get_description_ru(self):
        return """Персонаж — это личность вашего ассистента. Он определяет, как AI будет с вами общаться, его характер и знания.

В настройках Персонажей (иконка <b>человека</b>) вы можете:
• <b>Выбрать готового персонажа</b> из списка.
• <b>Настроить промпты</b>: это инструкции, которые формируют поведение персонажа. Можно выбрать готовый набор промптов из "Каталога" или создать свой.
• <b>Управлять историей</b>: очищать память персонажа или открывать папку с диалогами.

<b>Проще говоря:</b> выберите персонажа, который вам нравится. Для начала отлично подойдет "Crazy"."""
        
    def get_description_en(self):
        return """A character is your assistant's personality. It defines how the AI will communicate with you, its nature, and its knowledge.

In the Character settings (<b>user</b> icon), you can:
• <b>Select a pre-made character</b> from the list.
• <b>Configure prompts</b>: these are instructions that shape the character's behavior. You can choose a pre-made prompt set from the "Catalogue" or create your own.
• <b>Manage history</b>: clear the character's memory or open the folder with dialogues.

<b>Simply put:</b> choose a character you like. "Crazy" is a great one to start with."""
        
    def get_image_filename(self):
        return "guide_characters.jpg"

class VoiceoverGuidePage(IGuidePage):
    min_mode = "advanced"

    def get_title_ru(self):
        return "Шаг 3: Настройка голоса (Озвучка)"
        
    def get_title_en(self):
        return "Step 3: Setting up the Voice (Voiceover)"
        
    def get_description_ru(self):
        return """Хотите, чтобы ассистент отвечал вам голосом? Это просто!

В настройках Озвучки (иконка <b>динамика</b>) сначала поставьте галочку <b>"Использовать озвучку"</b>. Затем выберите метод:
• <b>TG (через Telegram)</b>: Самый простой способ. Не требует настроек, работает через ботов в Telegram.
• <b>Local (локально)</b>: Качественный голос, который генерируется на вашем ПК. Требует мощной видеокарты и предварительной установки моделей.

<b>Проще говоря:</b> для начала выберите метод "TG". Если у вас мощный компьютер, можете попробовать "Local" для лучшего качества."""
        
    def get_description_en(self):
        return """Want your assistant to reply with a voice? It's easy!

In the Voiceover settings (<b>speaker</b> icon), first check <b>"Use speech"</b>. Then choose a method:
• <b>TG (via Telegram)</b>: The easiest way. Requires no setup, works through Telegram bots.
• <b>Local</b>: High-quality voice generated on your PC. Requires a powerful graphics card and pre-installation of models.

<b>Simply put:</b> select the "TG" method to start. If you have a powerful computer, you can try "Local" for better quality."""
        
    def get_image_filename(self):
        return "guide_voice.jpg"

class MicrophoneGuidePage(IGuidePage):
    min_mode = "advanced"

    def get_title_ru(self):
        return "Шаг 4: Общение голосом (Микрофон)"
        
    def get_title_en(self):
        return "Step 4: Voice Communication (Microphone)"
        
    def get_description_ru(self):
        return """Вы можете не только слушать, но и говорить с ассистентом.

В настройках Микрофона (иконка <b>микрофона</b>):
• Поставьте галочку <b>"Распознавание"</b>, чтобы включить его.
• Выберите ваш <b>микрофон</b> из списка.
• <b>Тип распознавания</b>: "google" — простой и не требует настроек; "gigaam" — локальный, работает без интернета, но требует установки.

<b>Проще говоря:</b> включите распознавание и выберите свой микрофон, чтобы управлять ассистентом голосом."""
        
    def get_description_en(self):
        return """You can not only listen but also talk to the assistant.

In the Microphone settings (<b>microphone</b> icon):
• Check <b>"Recognition"</b> to enable it.
• Select your <b>microphone</b> from the list.
• <b>Recognition Type</b>: "google" is simple and requires no setup; "gigaam" is local, works offline, but requires installation.

<b>Simply put:</b> enable recognition and select your microphone to control the assistant with your voice."""
        
    def get_image_filename(self):
        return "guide_microphone.jpg"

class ScreenAnalysisGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Доп. фича: Анализ экрана"
        
    def get_title_en(self):
        return "Bonus Feature: Screen Analysis"
        
    def get_description_ru(self):
        return """NeuroMita может "видеть" то, что происходит на вашем экране или что показывает ваша веб-камера. Это полезно, чтобы задавать вопросы о происходящем в игре или приложении.

В настройках Экрана (иконка <b>монитора</b>):
• Включите <b>"Разрешить обработку изображений"</b> — мастер-переключатель.
• Затем включите <b>"Включить захват экрана"</b> или <b>"Захват с камеры"</b>.
• Чтобы кадры прикреплялись автоматически при каждом сообщении — включите <b>"Прикладывать кадры к сообщениям"</b>.
• Кнопка <b>📷</b> в чате делает скриншот вручную (работает, если включена обработка изображений).

<b>Важно:</b> Эта функция работает только с моделями, которые поддерживают анализ изображений (например, GPT-4o, Claude 3, Gemini)."""
        
    def get_description_en(self):
        return """NeuroMita can "see" what's on your screen or what your webcam is showing. This is useful for asking questions about what's happening in a game or application.

In the Screen settings (<b>desktop</b> icon):
• Enable <b>"Enable Image Analysis"</b> — the master toggle.
• Then enable <b>"Enable Screen Capture"</b> or <b>"Camera Capture"</b>.
• To auto-attach frames to every message — enable <b>"Auto-attach frames"</b>.
• The <b>📷</b> button in chat takes a manual screenshot (works when image analysis is enabled).

<b>Important:</b> This feature only works with models that support image analysis (e.g., GPT-4o, Claude 3, Gemini)."""
        
    def get_image_filename(self):
        return "guide_screen.jpg"

class ModelsGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Тонкая настройка: Параметры модели"
        
    def get_title_en(self):
        return "Fine-Tuning: Model Parameters"
        
    def get_description_ru(self):
        return """Если хотите повлиять на то, как именно AI отвечает, загляните в настройки Моделей (иконка <b>робота</b>).

Ключевые параметры:
• <b>Температура</b>: Управляет креативностью. <b>0.1</b> — строгие и точные ответы, <b>1.0</b> — очень творческие и непредсказуемые. Для начала оставьте <b>0.5</b>.
• <b>Лимит сообщений</b>: Сколько последних сообщений AI будет "помнить" при генерации ответа.
• <b>Макс. токенов в ответе</b>: Ограничивает длину ответа ассистента.

<b>Проще говоря:</b> на этой вкладке можно сделать AI более или менее креативным. Для начала можно ничего не менять."""
        
    def get_description_en(self):
        return """If you want to influence how the AI responds, check out the Model settings (<b>robot</b> icon).

Key parameters:
• <b>Temperature</b>: Controls creativity. <b>0.1</b> for strict and precise answers, <b>1.0</b> for very creative and unpredictable ones. Start with <b>0.5</b>.
• <b>Message limit</b>: How many recent messages the AI will "remember" when generating a response.
• <b>Max response tokens</b>: Limits the length of the assistant's answer.

<b>Simply put:</b> on this tab, you can make the AI more or less creative. You can leave the defaults for now."""
        
    def get_image_filename(self):
        return "guide_models.jpg"

class ChatGuidePage(IGuidePage):
    min_mode = "full"

    def get_title_ru(self):
        return "Интерфейс: Настройки чата"
        
    def get_title_en(self):
        return "Interface: Chat Settings"
        
    def get_description_ru(self):
        return """Здесь вы можете настроить внешний вид самого чата.

В настройках Чата (иконка <b>облачка диалога</b>) можно изменить:
• <b>Размер шрифта</b> в окне диалога.
• <b>Показывать метки времени</b> рядом с сообщениями.
• <b>Скрывать теги</b>: убирает технические теги (вроде &lt;e&gt;, &lt;c&gt;) из сообщений AI для более чистого вида.

<b>Проще говоря:</b> настройте чат так, как вам удобно читать."""
        
    def get_description_en(self):
        return """Here you can customize the appearance of the chat itself.

In the Chat settings (<b>dialog bubble</b> icon), you can change:
• <b>Chat Font Size</b> in the dialogue window.
• <b>Show Timestamps</b> next to messages.
• <b>Hide Tags</b>: removes technical tags (like &lt;e&gt;, &lt;c&gt;) from AI messages for a cleaner look.

<b>Simply put:</b> configure the chat to be comfortable for you to read."""
        
    def get_image_filename(self):
        return "guide_chat.jpg"

class FinalGuidePage(IGuidePage):
    min_mode = "basic"

    def get_title_ru(self):
        return "Вы готовы!"
        
    def get_title_en(self):
        return "You're All Set!"
        
    def get_description_ru(self):
        return """На этом всё! Вы прошли основные настройки и готовы к работе.

<b>Краткая памятка:</b>
1.  <b>API (вилка)</b>: Выберите провайдера (g4f для старта).
2.  <b>Персонажи (человек)</b>: Выберите личность AI.
3.  <b>Озвучка (динамик)</b> и <b>Микрофон</b>: Включите, если хотите общаться голосом.
4.  Начинайте общаться в главном окне!

Не бойтесь экспериментировать с другими настройками. Если что-то пойдет не так, всегда можно вернуться к стандартным значениям. Приятного общения!"""
        
    def get_description_en(self):
        return """That's it! You've gone through the basic settings and are ready to go.

<b>Quick reminder:</b>
1.  <b>API (plug)</b>: Select a provider (g4f to start).
2.  <b>Characters (user)</b>: Choose the AI's personality.
3.  <b>Voiceover (speaker)</b> and <b>Microphone</b>: Enable them if you want to use voice chat.
4.  Start chatting in the main window!

Don't be afraid to experiment with other settings. If something goes wrong, you can always revert to the default values. Enjoy your chat!"""
        
    def get_image_filename(self):
        return "guide_final.jpg"
