import io
import base64
import re
import time
import uuid
from pathlib import Path
import os
from PyQt6.QtCore import QSize
from styles.main_styles import get_stylesheet
from utils import process_text_to_voice
from utils import getTranslationVariant as _
from localization.live import tr_set
from main_logger import logger
import ui.gui_templates as gui_templates
from managers.settings_manager import CollapsibleSection
from ui.settings.voiceover_settings import LOCAL_VOICE_MODELS
import types
import json
import qtawesome as qta

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint, QPropertyAnimation, QBuffer, QIODevice, QEvent, QEasingCurve, QUrl, QRectF
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPlainTextEdit, QPushButton, QLabel, QScrollArea, QFrame,
    QMessageBox, QDialog, QProgressBar, QStackedWidget,
    QLineEdit, QFileDialog, QGraphicsOpacityEffect, QSizePolicy, QCheckBox,
    QMenu
)
from PyQt6.QtGui import QDesktopServices, QFont, QImage, QIcon, QPalette, QKeyEvent, QPixmap, QPainter, QLinearGradient, QColor

from ui.settings import (
    api_settings, character_settings, game_settings,
    microphone_settings, screen_analysis_settings, voiceover_settings,
    model_interaction_settings, general_settings, updates_settings
)

from ui.widgets import (status_indicators_widget)
from ui.widgets import chat_panel
from ui.widgets.overlay_widget import OverlayWidget
from ui.widgets.image_viewer_widget import ImageViewerWidget
from ui.widgets.image_preview_widget import ImagePreviewBar
from ui.widgets.mita_status_widget import MitaStatusWidget

from ui.window_manager import WindowManager

from controllers.voice_model_controller import VoiceModelController

from core.events import get_event_bus, Events, Event

from ui.dialogs.model_loading_dialog import create_model_loading_dialog
from ui.dialogs.ffmpeg_dialogs import create_ffmpeg_install_popup, show_ffmpeg_error_popup
from ui.dialogs.telegram_auth_dialogs import show_tg_code_dialog, show_tg_password_dialog
from ui.dialogs.voice_model_dialog_manager import handle_voice_model_dialog

from ui.widgets.launcher_dashboard_helpers import (
    DashboardAction,
    DashboardCard,
    DashboardMetric,
    LogItem,
    NewsItem,
    create_shell_page_container,
    create_home_page,
    create_logs_page,
    create_news_page,
)
from ui.widgets.launcher_shell_sidebar import LauncherSidebarWidget
from ui.widgets.settings_panel import create_settings_page
from ui.widgets.chat_panel import setup_chat_panel, hide_image_preview_bar, update_send_button_state
from ui.chat import message_renderer
from ui.chat.chat_delegate import ChatMessageDelegate

from ui.windows.voice_action_windows import VoiceInstallationWindow


class AppWindowBase(QMainWindow):
    update_chat_signal = pyqtSignal(str, object, bool, str)
    update_status_signal = pyqtSignal()
    update_debug_signal = pyqtSignal()

    prepare_stream_signal = pyqtSignal(object)
    append_stream_chunk_signal = pyqtSignal(object)
    finish_stream_signal = pyqtSignal()

    show_thinking_signal = pyqtSignal(object)
    show_error_signal = pyqtSignal(str)
    hide_status_signal = pyqtSignal()
    pulse_error_signal = pyqtSignal()
    show_voicing_signal = pyqtSignal()
    hide_voicing_signal = pyqtSignal()

    history_loaded_signal = pyqtSignal(dict)          
    more_history_loaded_signal = pyqtSignal(dict)     
    model_initialized_signal = pyqtSignal(dict)       
    model_init_cancelled_signal = pyqtSignal(dict)    
    model_init_failed_signal = pyqtSignal(dict)       
    show_tg_code_dialog_signal = pyqtSignal(dict)     
    show_tg_password_dialog_signal = pyqtSignal(dict) 
    reload_prompts_success_signal = pyqtSignal()      
    reload_prompts_failed_signal = pyqtSignal(dict)   
    display_loading_popup_signal = pyqtSignal(dict)   
    hide_loading_popup_signal = pyqtSignal()          

    clear_user_input_signal = pyqtSignal()
    insert_user_input_signal = pyqtSignal(str) 
    update_chat_font_size_signal = pyqtSignal(int)
    switch_voiceover_settings_signal = pyqtSignal()
    load_chat_history_signal = pyqtSignal()
    remove_last_chat_widgets_signal = pyqtSignal(int)
    check_triton_dependencies_signal = pyqtSignal()
    show_info_message_signal = pyqtSignal(dict)
    show_error_message_signal = pyqtSignal(dict)
    update_model_loading_status_signal = pyqtSignal(str)
    finish_model_loading_signal = pyqtSignal(dict)
    cancel_model_loading_signal = pyqtSignal()

    create_dialog_signal = pyqtSignal(dict)
    create_installation_window_signal = pyqtSignal(str, str, object)  # title, initial_status, holder(dict)
    close_installation_window_signal = pyqtSignal(object)
    finalize_installation_window_signal = pyqtSignal(object, bool)  # win, close_now
    
    asr_install_progress_signal = pyqtSignal(dict)
    asr_install_finished_signal = pyqtSignal(dict)
    asr_install_failed_signal = pyqtSignal(dict)

    run_ui_task_signal = pyqtSignal(object)

    # api_settings.py
    test_result_received = pyqtSignal(dict)
    test_result_failed = pyqtSignal(dict)

    # microphone_settings.py
    asr_set_pill = pyqtSignal(dict)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        
        try:
            self.SETTINGS_PANEL_WIDTH = int(self.settings.get("SETTINGS_PANEL_WIDTH", 520) or 520)
        except Exception:
            self.SETTINGS_PANEL_WIDTH = 520
        self.SETTINGS_PANEL_WIDTH = max(280, min(1800, self.SETTINGS_PANEL_WIDTH))
        
        self.event_bus = get_event_bus()
        self._connect_signals()
        self._init_window_manager()
        
        self.voice_language_var = None
        self.local_voice_combobox = None
        self.debug_window = None
        self.mic_combobox = None
        self.chat_window = None
        self.token_count_label = None
        self.user_entry = None
        self.attachment_label = None
        self.attach_button = None
        self.send_screen_button = None

        tr_set(self, "Чат с NeuroMita", "NeuroMita Chat", "setWindowTitle")
        self.setWindowIcon(QIcon('Icon.png'))

        self.staged_image_data = []

        self.ffmpeg_install_popup = None

        self.current_settings_category = None
        self.settings_containers = {}

        self._voice_model_dialog = None
        self._voice_model_controller_callback = None
        self._voice_model_init_in_progress_model_id = None

        self.update_chat_signal.connect(self._on_update_chat_signal)
        self.update_status_signal.connect(self.update_status_colors)
        self.update_debug_signal.connect(self.update_debug_info)

        self.prepare_stream_signal.connect(self._on_prepare_stream_signal)
        self.append_stream_chunk_signal.connect(self._append_stream_chunk_slot)
        self.finish_stream_signal.connect(self._finish_stream_slot)

        self.show_thinking_signal.connect(self._show_thinking_slot)
        self.show_error_signal.connect(self._show_error_slot)
        self.hide_status_signal.connect(self._hide_status_slot)
        self.pulse_error_signal.connect(self._pulse_error_slot)
        self.show_voicing_signal.connect(self._show_voicing_slot)
        self.hide_voicing_signal.connect(self._hide_voicing_slot)

        self.settings_animation = None
        self.setup_ui()
        self.chat_delegate = ChatMessageDelegate()
        self._ensure_settings_animation()

        self.chat_window.installEventFilter(self)

        self.overlay = OverlayWidget(self)
        self.image_preview_bar = None

        from ui.widgets.chat_panel import init_image_preview
        init_image_preview(self)

        try:
            microphone_settings.load_mic_settings(self)
        except Exception as e:
            logger.info(f"Не удалось удачно получить настройки микрофона: {e}")


        self.prepare_stream_signal.connect(self._on_stream_start)
        self.finish_stream_signal.connect(self._on_stream_finish)

        QTimer.singleShot(0, self.update_status_colors)
        QTimer.singleShot(1000, self._check_eula_and_guide)

        self.last_voice_model_selected = None
        self.current_local_voice_id = None
        self.model_loading_cancelled = False

    def _ensure_settings_animation(self):
        target = getattr(self, "settings_overlay", None) or self.centralWidget()
        if target is None:
            return None

        if self.settings_animation is None:
            self.settings_animation = QPropertyAnimation(target, b"maximumWidth")
            self.settings_animation.setDuration(250)
            self.settings_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
            return self.settings_animation

        if self.settings_animation.targetObject() is not target:
            self.settings_animation.stop()
            self.settings_animation.setTargetObject(target)
        return self.settings_animation

    def _window_specs(self) -> dict:
        return {
            "ai_hub": {
                "factory": self._factory_ai_hub_dialog,
                "singleton": True,
                "hide_on_close": True,
                "modal": False,
                "on_ready": self._on_ai_hub_dialog_ready,
            },
            "voice_models": {
                "factory": self._factory_voice_models_dialog,
                "singleton": True,
                "hide_on_close": True,
                "modal": False
            },
            "asr_glossary": {
                "factory": self._factory_asr_glossary_dialog,
                "singleton": True,
                "hide_on_close": True,
                "modal": False,
            },

            # Blocking dialogs (used by VoiceModelGuiController via show_dialog_blocking)
            "vc_redist_dialog": {
                "factory": self._factory_vc_redist_dialog,
                "singleton": False,
                "hide_on_close": False,
                "modal": True,
            },
            "triton_deps_dialog": {
                "factory": self._factory_triton_deps_dialog,
                "singleton": False,
                "hide_on_close": False,
                "modal": True,
            },
        }

    def _connect_signals(self):
        self.history_loaded_signal.connect(self._on_history_loaded)
        self.more_history_loaded_signal.connect(self._on_more_history_loaded)
        self.show_tg_code_dialog_signal.connect(self._on_show_tg_code_dialog)
        self.show_tg_password_dialog_signal.connect(self._on_show_tg_password_dialog)
        self.reload_prompts_success_signal.connect(self._on_reload_prompts_success)
        self.reload_prompts_failed_signal.connect(self._on_reload_prompts_failed)
        self.display_loading_popup_signal.connect(self._on_display_loading_popup)
        self.hide_loading_popup_signal.connect(self._on_hide_loading_popup)
        self.update_chat_font_size_signal.connect(self.update_chat_font_size)
        self.load_chat_history_signal.connect(self.load_chat_history)
        self.remove_last_chat_widgets_signal.connect(self._on_remove_last_chat_widgets)
        self.clear_user_input_signal.connect(self._on_clear_user_input)
        self.insert_user_input_signal.connect(self._on_insert_user_input)
        self.show_info_message_signal.connect(self._on_show_info_message)
        self.show_error_message_signal.connect(self._on_show_error_message)
        self.update_model_loading_status_signal.connect(self._on_update_model_loading_status)

        self.create_dialog_signal.connect(self._create_dialog_for_voice_model)

        self.run_ui_task_signal.connect(
            self._run_ui_task_slot,
            type=Qt.ConnectionType.QueuedConnection
        )

        # Окно установки.
        self.create_installation_window_signal.connect(
            self._on_create_installation_window,
            type=Qt.ConnectionType.QueuedConnection
        )

        self.close_installation_window_signal.connect(
            self._on_close_installation_window,
            type=Qt.ConnectionType.QueuedConnection
        )

        self.finalize_installation_window_signal.connect(
            self._on_finalize_installation_window,
            type=Qt.ConnectionType.QueuedConnection
        )

        # Текущее окно установки (живёт, пока задача не завершена; может быть
        # свёрнуто пользователем и открыто снова через сайдбар).
        self._active_install_window = None

        self.asr_install_progress_signal.connect(
            self._on_asr_install_progress,
            type=Qt.ConnectionType.QueuedConnection
        )
        self.asr_install_finished_signal.connect(
            self._on_asr_install_finished,
            type=Qt.ConnectionType.QueuedConnection
        )
        self.asr_install_failed_signal.connect(
            self._on_asr_install_failed,
            type=Qt.ConnectionType.QueuedConnection
        )

    def _run_ui_task_slot(self, fn):
        try:
            if callable(fn):
                fn()
        except Exception as e:
            logger.error(f"_run_ui_task_slot error: {e}", exc_info=True)

    def _init_window_manager(self):
        self.window_manager = WindowManager(parent=self)

        for window_id, spec in self._window_specs().items():
            self.window_manager.register_dialog(
                window_id,
                factory=spec["factory"],
                singleton=spec.get("singleton", True),
                hide_on_close=spec.get("hide_on_close", True),
                modal=spec.get("modal", False),
                on_ready=spec.get("on_ready", None),
            )

    def _factory_voice_models_dialog(self, parent, payload: dict):
        dialog = QDialog(parent)
        dialog.setWindowTitle(_("Управление локальными моделями", "Manage Local Models"))
        dialog.setModal(False)
        dialog.resize(875, 800)

        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(0, 0, 0, 0)
        dialog_layout.setSpacing(0)

        return dialog

    def _factory_ai_hub_dialog(self, parent, payload: dict):
        from ui.windows.ai_hub_window import AIHubDialog

        return AIHubDialog(parent)

    def _on_ai_hub_dialog_ready(self, dialog, payload: dict):
        if hasattr(dialog, "apply_payload"):
            dialog.apply_payload(payload if isinstance(payload, dict) else {})

    def _factory_asr_glossary_dialog(self, parent, payload: dict):
        dialog = QDialog(parent)
        dialog.setWindowTitle(_("ASR модели", "ASR Models"))
        dialog.setModal(False)
        dialog.resize(900, 650)
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        return dialog
    
    def _factory_vc_redist_dialog(self, parent, payload: dict):
        from ui.windows.voice_action_windows import VCRedistWarningDialog
        return VCRedistWarningDialog(parent=parent)

    def _factory_triton_deps_dialog(self, parent, payload: dict):
        from ui.windows.voice_action_windows import TritonDependenciesDialog
        deps = payload.get("dependencies_status") or payload.get("deps") or {}
        return TritonDependenciesDialog(parent=parent, dependencies_status=deps)

    def _create_dialog_for_voice_model(self, data):
        if not hasattr(self, "window_manager") or self.window_manager is None:
            return
        payload = data if isinstance(data, dict) else {}
        payload = dict(payload)
        payload.setdefault("category", "tts")
        self.window_manager.show_dialog("ai_hub", payload)

    def _on_create_installation_window(self, title: str, initial_status: str, holder: dict):
        win = VoiceInstallationWindow(self, title, initial_status)
        self._active_install_window = win

        try:
            win.minimized.connect(lambda: self._set_install_logs_button_visible(True))
            win.window_closed.connect(lambda w=win: self._on_install_window_closed(w))
        except Exception:
            pass

        # Кнопка «Логи установки» в сайдбаре — чтобы вернуться к окну,
        # если пользователь его закрыл (свернул).
        self._set_install_logs_button_visible(True)

        win.show()

        holder["window"] = win
        if hasattr(win, "get_threadsafe_callbacks"):
            holder["callbacks"] = win.get_threadsafe_callbacks()
        else:
            holder["callbacks"] = (win.update_progress, win.update_status, win.update_log)

        ev = holder.get("ready_event")
        if ev is not None and hasattr(ev, "set"):
            try:
                ev.set()
            except Exception:
                pass

    def _on_close_installation_window(self, win_obj: object):
        try:
            if win_obj is None:
                return
            if hasattr(win_obj, "finalize"):
                win_obj.finalize()
            win_obj.close()
        except Exception:
            pass

    def _on_finalize_installation_window(self, win_obj: object, close_now: bool):
        try:
            if win_obj is None:
                return
            if hasattr(win_obj, "finalize"):
                win_obj.finalize()
            if close_now:
                win_obj.close()
        except Exception:
            pass

    def _on_install_window_closed(self, win_obj: object):
        # Окно действительно закрыто (задача завершена) — убираем ссылку и
        # прячем кнопку повторного открытия.
        if win_obj is self._active_install_window:
            self._active_install_window = None
            self._set_install_logs_button_visible(False)

    def _on_reopen_install_logs(self):
        win = getattr(self, "_active_install_window", None)
        if win is None:
            self._set_install_logs_button_visible(False)
            return
        try:
            win.show()
            win.raise_()
            win.activateWindow()
        except Exception:
            pass

    def _set_install_logs_button_visible(self, visible: bool):
        sidebar = getattr(self, "shell_sidebar", None)
        if sidebar is not None and hasattr(sidebar, "set_install_logs_visible"):
            try:
                sidebar.set_install_logs_visible(bool(visible))
            except Exception:
                pass

    def setup_ui(self):
        raise NotImplementedError("AppWindowBase.setup_ui() must be implemented by a concrete window class.")

    def _on_shell_utility_requested(self, action):
        if isinstance(action, str) and action.startswith("language:"):
            code = action.split(":", 1)[1].upper()
            # Живая смена языка: запись настройки + обновление зарегистрированных
            # виджетов + сигнал language_changed (без перезапуска приложения).
            try:
                from localization.live import set_language
                set_language(code)
            except Exception:
                try:
                    self.settings.set("LANGUAGE", code)
                except Exception:
                    try:
                        self.settings["LANGUAGE"] = code
                    except Exception:
                        pass
            self.shell_sidebar.set_active_language(code.lower())
            return
        if action == "language":
            self.show_settings_category("language")
            return

        self.switch_main_page("home")

    def _on_shell_social_requested(self, platform):
        urls = {
            "discord": "https://discord.gg/Tu5MPFxM4P",
            "github": "https://github.com/VinerX/NeuroMita",
            "youtube": "https://www.youtube.com/@NeuroMita",
            "boosty": "https://boosty.to/vinerx",
        }
        url = urls.get(platform)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.resize(self.size())
        for child in self.children():
            if child.__class__.__name__ == 'GuideOverlay':
                child.resize(self.size())
        from ui.widgets.chat_panel import position_mita_status
        QTimer.singleShot(0, lambda: position_mita_status(self))

    def eventFilter(self, obj, event):

        # кнопка "вниз" — на скролле чата
        if obj == self.chat_window.viewport() and event.type() in (QEvent.Type.Resize, QEvent.Type.Paint):
            if hasattr(self, 'scroll_to_bottom_btn'):
                chat_panel.reposition_scroll_button(self)

        # позиционирование статуса при ресайзе чата
        if obj == self.chat_window and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, lambda: chat_panel.position_mita_status(self))

        # хоткеи в поле ввода
        if obj == self.user_entry and event.type() == QEvent.Type.KeyPress:
            if not isinstance(event, QKeyEvent) or not hasattr(event, "key"):
                return super().eventFilter(obj, event)

            key = event.key()
            mods = event.modifiers()

            # Ctrl+V (или Meta+V на mac) — попытка вставить картинку из буфера
            if (key == Qt.Key.Key_V and (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier))) \
            or (key == Qt.Key.Key_Insert and (mods & Qt.KeyboardModifier.ShiftModifier)):  # Shift+Insert
                if chat_panel.clipboard_image_to_controller(self):
                    return True  # съели событие, чтобы не вставлялся текст/эмодзи

            # Enter без Shift — отправить сообщение
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (mods & Qt.KeyboardModifier.ShiftModifier):
                self.send_message()
                return True  # не даём вставлять перенос строки

        return super().eventFilter(obj, event)

    def load_chat_history(self):
        logger.debug("[Load] load_chat_history: начало")
        logger.debug("[Load] Отключаем updates в chat_window")
        self.chat_window.setUpdatesEnabled(False)
        logger.debug("[Load] Вызываем clear_chat_display()")
        self.clear_chat_display()
        logger.debug("[Load] Эмитим LOAD_HISTORY")
        self.event_bus.emit(Events.Model.LOAD_HISTORY)
        logger.debug("[Load] load_chat_history: конец")

    def _on_history_loaded(self, data: dict):
        messages = data.get('messages', [])
        character_id = data.get('character_id', '')
        logger.info(f"[HistoryLoaded] Загружено {len(messages)} сообщений для отображения")
        for i, entry in enumerate(messages):
            msg_role = entry.get("role", "?")
            msg_content = entry.get("content", "")
            content_preview = msg_content[:50] if isinstance(msg_content, str) else f"list({len(msg_content)})"
            logger.info(f"[HistoryLoaded] msg[{i}] role='{msg_role}', preview='{content_preview}'")
            role = entry["role"]
            content = entry["content"]
            message_time = entry.get("time", "???")
            structured_data = entry.get("structured_data")
            message_id = entry.get("message_id")
            sample_id = entry.get("sample_id")
            thinking_text = entry.get("thinking")
            try:
                show_think_in_gui = bool(self._get_setting("SHOW_THINK_IN_GUI", False))
                if role == "assistant" and thinking_text and show_think_in_gui:
                    speaker = entry.get("speaker", "")
                    message_renderer.insert_message(
                        self, "think",
                        [{"type": "meta", "speaker": speaker},
                         {"type": "text", "text": thinking_text.strip()}],
                        message_time=message_time,
                        character_id=character_id,
                    )
                message_renderer.insert_message(self, role, content, message_time=message_time,
                                                structured_data=structured_data,
                                                message_id=message_id, character_id=character_id,
                                                ui_images=entry.get("_ui_images") or [],
                                                sample_id=sample_id)
            except Exception as ex:
                logger.error(f"_on_history_loaded: НУ Я ПОНЯЛ: {str(ex)}")
        self.update_debug_info()
        self.chat_window.scroll_to_bottom()
        self.chat_window.setUpdatesEnabled(True)
        self.chat_window.update()

    def validate_number_0_60(self, new_value):
        if not new_value.isdigit():
            return False
        return 0 <= int(new_value) <= 60

    def validate_float_0_1(self, new_value):
        try:
            val = float(new_value)
            return 0.0 <= val <= 1.0
        except ValueError:
            return False

    def validate_float_positive(self, new_value):
        try:
            val = float(new_value)
            return val > 0.0
        except ValueError:
            return False

    def validate_float_positive_or_zero(self, new_value):
        if new_value == "": return True
        try:
            value = float(new_value)
            return value >= 0.0
        except ValueError:
            return False

    def validate_positive_integer(self, new_value):
        if new_value == "": return True
        try:
            value = int(new_value)
            return value > 0
        except ValueError:
            return False

    def validate_non_negative_integer(self, new_value):
        if new_value == "": return True
        try:
            value = int(new_value)
            return value >= 0
        except ValueError:
            return False

    def validate_positive_integer_or_zero(self, new_value):
        if new_value == "": return True
        try:
            value = int(new_value)
            return value >= 0
        except ValueError:
            return False

    def validate_float_0_to_1(self, new_value):
        if new_value == "": return True
        try:
            value = float(new_value)
            return 0.0 <= value <= 1.0
        except ValueError:
            return False

    def validate_float_0_to_2(self, new_value):
        if new_value == "": return True
        try:
            value = float(new_value)
            return 0.0 <= value <= 2.0
        except ValueError:
            return False

    def validate_float_minus2_to_2(self, new_value):
        if new_value == "": return True
        try:
            value = float(new_value)
            return -2.0 <= value <= 2.0
        except ValueError:
            return False

    def update_debug_info(self):
        debug_info_result = self.event_bus.emit_and_wait(Events.Model.GET_DEBUG_INFO, timeout=0.5)
        debug_info = debug_info_result[0] if debug_info_result else "Debug info not available"

        if hasattr(self, 'debug_window') and self.debug_window:
            self.debug_window.clear()
            self.debug_window.insertPlainText(debug_info)

        # logs_window больше не дублирует debug_info — в нём показывается tail файла логов,
        # а не "Debug info not available". См. _refresh_logs_view().

    @staticmethod
    def _fmt_tokens(n) -> str:
        """Компактные счётчики токенов: тысячи как «21.3к» / «21.3k» от 10 000.
        Хвостовой .0 убираем (20041 → «20к», а не «20.0к»)."""
        try:
            n = int(n)
        except (TypeError, ValueError):
            return str(n)
        if n >= 10000:
            s = f"{n / 1000:.1f}".rstrip("0").rstrip(".")
            return f"{s}{_('к', 'k')}"
        return str(n)

    def update_token_count(self, event=None):
        show_token_info = self._get_setting("SHOW_TOKEN_INFO", True)
        if show_token_info:
            stats_res = self.event_bus.emit_and_wait(Events.Model.GET_TOKEN_STATS, timeout=0.5)
            stats = stats_res[0] if stats_res and isinstance(stats_res[0], dict) else {}
            current_context_tokens = int(stats.get("estimated_context_tokens") or 0)
            max_model_tokens = int(stats.get("max_context_tokens") or self._get_setting("MAX_MODEL_TOKENS", 32000))
            est_cost = stats.get("estimated_input_cost")
            est_currency = str(stats.get("estimated_input_cost_currency") or "")
            est_cost_text = "n/a" if est_cost is None else f"{float(est_cost):.4f} {est_currency}".strip()
            actual_prompt = stats.get("actual_prompt_tokens")
            actual_completion = stats.get("actual_completion_tokens")
            actual_cached = stats.get("actual_cached_prompt_tokens")
            actual_cost = stats.get("actual_cost")
            actual_currency = str(stats.get("actual_cost_currency") or "")
            fmt = self._fmt_tokens
            cost = float(est_cost or 0.0) if est_cost is not None else 0.0
            self.token_count_label.setText(
                _("Токены: {}/{} (Макс. токены: {}) | Ориент. стоимость: {:.4f} ₽",
                  "Tokens: {}/{} (Max tokens: {}) | Approx. cost: {:.4f} ₽").format(
                    fmt(current_context_tokens), fmt(max_model_tokens), fmt(max_model_tokens), cost
                )
            )
            ctx_pct = int(round(current_context_tokens / max_model_tokens * 100)) if max_model_tokens else 0
            ctx_str = f"~{ctx_pct}% ({fmt(current_context_tokens)}/{fmt(max_model_tokens)})"
            if actual_prompt is not None or actual_completion is not None or actual_cost is not None:
                actual_prompt = int(actual_prompt or 0)
                actual_completion = int(actual_completion or 0)
                actual_cached = int(actual_cached or 0)
                actual_total = int(stats.get("actual_total_tokens") or (actual_prompt + actual_completion))
                actual_cost_text = "n/a" if actual_cost is None else f"{float(actual_cost):.4f} {actual_currency}".strip()
                if actual_cached > 0:
                    # Кеш контекста — как процент от промпта (доля попадания в кеш).
                    cache_pct = int(round(actual_cached / actual_prompt * 100)) if actual_prompt else 0
                    self.token_count_label.setText(
                        _("Контекст: {} | Вход: {} | Запрос: {}/{} (всего {}, кеш {}%) | Факт: {}",
                          "Context: {} | Input: {} | Request: {}/{} (total {}, cache {}%) | Actual: {}").format(
                            ctx_str, est_cost_text,
                            fmt(actual_prompt), fmt(actual_completion), fmt(actual_total), cache_pct, actual_cost_text
                        )
                    )
                else:
                    self.token_count_label.setText(
                        _("Контекст: {} | Вход: {} | Запрос: {}/{} (всего {}) | Факт: {}",
                          "Context: {} | Input: {} | Request: {}/{} (total {}) | Actual: {}").format(
                            ctx_str, est_cost_text,
                            fmt(actual_prompt), fmt(actual_completion), fmt(actual_total), actual_cost_text
                        )
                    )
            else:
                self.token_count_label.setText(
                    _("Контекст: {} | Вход: {}",
                      "Context: {} | Input: {}").format(ctx_str, est_cost_text)
                )
            self.token_count_label.setVisible(True)
        else:
            self.token_count_label.setVisible(False)
            self.token_count_label.setText(_("Токены: Токенизатор недоступен", "Tokens: Tokenizer not available"))
        self.update_debug_info()

    def update_chat_font_size(self, font_size):
        self._chat_font_size = font_size

    def clear_chat_display(self):
        logger.debug("[Clear] clear_chat_display: начало")
        logger.debug(f"[Clear] chat_window.message_count: {self.chat_window.message_count()}")
        self.chat_window.clear_messages()
        logger.debug("[Clear] Сообщения очищены")
        self.event_bus.emit(Events.Chat.CLEAR_CHAT)
        logger.debug("[Clear] clear_chat_display: конец")

    @staticmethod
    def _dedupe_images(image_list):
        """Убрать дубли изображений по содержимому, сохранив порядок (#14).

        Одно и то же изображение могло прийти из нескольких источников
        (прикреплённое вручную + авто-кадр экрана/камеры) и попадало в чат
        дважды. Сравниваем по байтам (bytes хешируемы), не-байтовые элементы
        пропускаем как есть.
        """
        seen = set()
        result = []
        for img in image_list or []:
            if isinstance(img, (bytes, bytearray)):
                key = bytes(img)
                if key in seen:
                    continue
                seen.add(key)
            result.append(img)
        return result

    def send_message(self, system_input: str = "", image_data: list[bytes] = None):
        user_input = self.user_entry.toPlainText().strip()
        current_image_data = []
        staged_image_data = self.staged_image_data.copy()

        character_id = ""
        try:
            prof_res = self.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=0.5)
            prof = prof_res[0] if prof_res else {}
            if isinstance(prof, dict):
                character_id = str(prof.get("character_id") or "")
        except Exception:
            character_id = ""

        if self._get_setting("AUTO_ATTACH_IMAGES", False):
            history_limit = int(self._get_setting("SCREEN_CAPTURE_HISTORY_LIMIT", 1))
            frames = self.event_bus.emit_and_wait(Events.Capture.CAPTURE_SCREEN, {'limit': history_limit}, timeout=0.5)
            if frames and frames[0]:
                current_image_data.extend(frames[0])
            else:
                logger.info("Авто-прикрепление кадров включено, но кадры не готовы или история пуста.")

        all_image_data = (image_data or []) + current_image_data + staged_image_data

        if self._get_setting("ENABLE_CAMERA_CAPTURE", False):
            history_limit = int(self._get_setting("CAMERA_CAPTURE_HISTORY_LIMIT", 1))
            camera_frames = self.event_bus.emit_and_wait(Events.Capture.GET_CAMERA_FRAMES, {'limit': history_limit}, timeout=0.5)
            if camera_frames and camera_frames[0]:
                all_image_data.extend(camera_frames[0])
                logger.info(f"Добавлено {len(camera_frames[0])} кадров с камеры для отправки.")
            else:
                logger.info("Захват с камеры включен, но кадры не готовы или история пуста.")

        if not self._get_setting("ENABLE_IMAGE_ANALYSIS", True):
            all_image_data = []
            logger.info("ENABLE_IMAGE_ANALYSIS отключен — изображения не отправляются.")

        # #14: одно изображение могло попасть в список дважды (напр. и как
        # прикреплённое вручную, и как авто-кадр экрана) и рисовалось в чате
        # два раза, хотя в истории сохранялась одна копия. Дедупим по
        # содержимому, сохраняя порядок — одна копия и в UI, и в отправке.
        all_image_data = self._dedupe_images(all_image_data)

        if not user_input and not system_input and not all_image_data:
            return

        # Generate req_id now so we can pre-compute the user message_id for the widget
        req_id = uuid.uuid4().hex
        user_message_id = f"in:{req_id}"

        if user_input:
            message_renderer.insert_message(self, "user", user_input, message_id=user_message_id)
            self.user_entry.clear()

        if all_image_data:
            image_content_for_display = [{"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{base64.b64encode(img).decode('utf-8')}"}} for img in all_image_data]

            if not user_input:
                label = _("<Изображения>", "<Images>")
                if staged_image_data and not current_image_data and not (image_data or []):
                    label = _("<Прикрепленные изображения>", "<Attached Images>")
                elif (current_image_data or (image_data or [])) and not staged_image_data:
                    label = _("<Изображение экрана>", "<Screen Image>")

                image_content_for_display.insert(0, {"type": "text", "content": label + "\n"})

            message_renderer.insert_message(self, "user", image_content_for_display,
                                            message_id=user_message_id)

        self.event_bus.emit(Events.Chat.SEND_MESSAGE, {
            "user_input": user_input,
            "system_input": system_input,
            "image_data": all_image_data,
            "character_id": character_id,
            "sender": "Player",
            "req_id": req_id,
        })

        # #10: показываем «думает» сразу при отправке, не дожидаясь конца
        # подготовки контекста (RAG/промпт), из-за которой ON_STARTED прилетает
        # с заметной задержкой — казалось, что запрос не ушёл. Повторный
        # ON_STARTED с тем же именем безопасен (show_thinking его гасит).
        try:
            self.show_thinking_signal.emit(self._get_character_name())
        except Exception:
            pass

        if staged_image_data:
            self.event_bus.emit(Events.Chat.CLEAR_STAGED_IMAGES)
            self.staged_image_data.clear()
            if self.image_preview_bar:
                self.image_preview_bar.clear()
                hide_image_preview_bar(self)

    def load_more_history(self):
        self.event_bus.emit(Events.Model.LOAD_MORE_HISTORY)

    def _on_more_history_loaded(self, data: dict):
        messages_to_prepend = data.get('messages', [])
        if not messages_to_prepend:
            return
        character_id = data.get('character_id', '')
        scrollbar = self.chat_window.verticalScrollBar()
        old_value = scrollbar.value()
        old_max = scrollbar.maximum()
        for entry in reversed(messages_to_prepend):
            role = entry["role"]
            content = entry["content"]
            message_time = entry.get("time", "???")
            structured_data = entry.get("structured_data")
            message_id = entry.get("message_id")
            sample_id = entry.get("sample_id")
            message_renderer.insert_message(self, role, content, insert_at_start=True,
                                            message_time=message_time, structured_data=structured_data,
                                            message_id=message_id, character_id=character_id,
                                            ui_images=entry.get("_ui_images") or [],
                                            sample_id=sample_id)
        QTimer.singleShot(0, lambda: scrollbar.setValue(scrollbar.maximum() - old_max + old_value))
        logger.info(f"Загружено еще {len(messages_to_prepend)} сообщений.")

    def _save_setting(self, key, value):
        self.event_bus.emit(Events.Settings.SAVE_SETTING, {'key': key, 'value': value})

    def _get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def _get_character_name(self):
        result = self.event_bus.emit_and_wait(Events.Character.GET_CURRENT_NAME, timeout=0.5)
        return result[0] if result else "Assistant"

    def closeEvent(self, event):
        try:
            main_controller = getattr(self, "main_controller", None)
            if main_controller is not None:
                main_controller.close_app()
            else:
                self.event_bus.emit(Events.Capture.STOP_SCREEN_CAPTURE)
                self.event_bus.emit(Events.Capture.STOP_CAMERA_CAPTURE)
                self.event_bus.emit(Events.Audio.DELETE_SOUND_FILES)
                self.event_bus.emit(Events.Server.STOP_SERVER)
        except Exception as exc:
            logger.error(f"Ошибка при закрытии приложения: {exc}", exc_info=True)

        try:
            if hasattr(self, "window_manager") and self.window_manager:
                self.window_manager.close_all(destroy=True)
        except Exception:
            pass

        logger.info("Закрываемся")
        event.accept()

    def close_app(self):
        logger.info("Завершение программы...")
        self.close()

    def _open_logs_folder(self):
        log_path = Path("NeuroMitaLogs.log")
        target = log_path.resolve().parent if log_path.exists() else Path.cwd()
        try:
            os.startfile(str(target))  # noqa: S606 - Windows-only launcher
        except Exception as exc:
            logger.info(f"Не удалось открыть папку логов: {exc}")

 
    def _show_ffmpeg_installing_popup(self):
        if hasattr(self, 'ffmpeg_install_popup') and self.ffmpeg_install_popup:
            return
        self.ffmpeg_install_popup = create_ffmpeg_install_popup(self)
        self.ffmpeg_install_popup.show()

    def _close_ffmpeg_installing_popup(self):
        if hasattr(self, 'ffmpeg_install_popup') and self.ffmpeg_install_popup:
            self.ffmpeg_install_popup.close()
            self.ffmpeg_install_popup = None

    def _show_ffmpeg_error_popup(self):
        show_ffmpeg_error_popup(self)

    def paste_from_clipboard(self, event=None):
        try:
            clipboard_content = QApplication.clipboard().text()
            self.user_entry.insertPlainText(clipboard_content)
        except Exception:
            pass

    def copy_to_clipboard(self, event=None):
        try:
            if self.user_entry.textCursor().hasSelection():
                selected_text = self.user_entry.textCursor().selectedText()
                QApplication.clipboard().setText(selected_text)
        except Exception:
            pass

    def _on_show_tg_code_dialog(self, data: dict):
        code_future = data.get('future')
        show_tg_code_dialog(self, code_future, self.event_bus)

    def _on_show_tg_password_dialog(self, data: dict):
        password_future = data.get('future')
        show_tg_password_dialog(self, password_future, self.event_bus)

    def _on_chat_anchor_clicked(self, url):
        href = url.toString()
        if href.startswith("think://toggle/"):
            try:
                block_id = int(href.split("/")[-1])
                message_renderer.toggle_think_block(self, block_id)
            except Exception as e:
                logger.error(f"Error toggling think block {block_id}: {e}")

    def _show_thinking_slot(self, character_name):
        if hasattr(self, 'mita_status') and self.mita_status:
            logger.info('Показываем статус "Думает" для персонажа: %s', character_name)
            self.mita_status.show_thinking(character_name)

    def _show_error_slot(self, error_message: str):
        if hasattr(self, 'mita_status') and self.mita_status:
            logger.info('Показываем статус ошибки: %s', error_message)
            self.mita_status.show_error(error_message)

    def _hide_status_slot(self):
        if hasattr(self, 'mita_status') and self.mita_status:
            logger.info('Скрываем статус')
            self.mita_status.hide_animated()
    
    def _pulse_error_slot(self):
        if hasattr(self, 'mita_status') and self.mita_status:
            self.mita_status.pulse_error_animation()

    def _show_voicing_slot(self):
        if hasattr(self, 'mita_status') and self.mita_status:
            self.mita_status.show_voicing()

    def _hide_voicing_slot(self):
        if hasattr(self, 'mita_status') and self.mita_status:
            self.mita_status.hide_voicing()

    def _on_stream_start(self):
        pass

    def _on_stream_finish(self):
        print("[DEBUG] Стрим завершен, скрываем статус")
        self.event_bus.emit(Events.GUI.HIDE_MITA_STATUS)

    def _on_reload_prompts_success(self):
        QMessageBox.information(self, _("Успешно", "Success"), 
            _("Промпты успешно скачаны и перезагружены.", "Prompts successfully downloaded and reloaded."))
    
    def _on_reload_prompts_failed(self, data: dict):
        error = data.get('error', 'Unknown error')
        if error == "Event loop not running":
            QMessageBox.critical(self, _("Ошибка", "Error"), 
                _("Не удалось запустить асинхронную загрузку промптов.", "Failed to start asynchronous prompt download."))
        else:
            QMessageBox.critical(self, _("Ошибка", "Error"), 
                _("Не удалось скачать промпты с GitHub. Проверьте подключение к интернету.", 
                  "Failed to download prompts from GitHub. Check your internet connection."))
    
    def _show_loading_popup(self, message):
        self.event_bus.emit(Events.GUI.SHOW_LOADING_POPUP, {"message": message})
    
    def _on_display_loading_popup(self, data: dict):
        message = data.get('message', 'Loading...')
        if not hasattr(self, 'loading_popup'):
            from PyQt6.QtWidgets import QProgressDialog
            self.loading_popup = QProgressDialog(message, None, 0, 0, self)
            self.loading_popup.setWindowTitle(_("Загрузка", "Loading"))
            self.loading_popup.setModal(True)
            self.loading_popup.setCancelButton(None)
            self.loading_popup.setMinimumDuration(0)
        else:
            self.loading_popup.setLabelText(message)
        self.loading_popup.show()
    
    def _close_loading_popup(self):
        self.event_bus.emit(Events.GUI.CLOSE_LOADING_POPUP)
    
    def _on_hide_loading_popup(self):
        if hasattr(self, 'loading_popup') and self.loading_popup:
            self.loading_popup.close()

    def _on_clear_user_input(self):
        if self.user_entry:
            self.user_entry.clear()
    
    def _on_insert_user_input(self, text: str):
        if self.user_entry:
            self.user_entry.insertPlainText(text + " ")
            self.user_entry.ensureCursorVisible()

    def _on_show_info_message(self, data: dict):
        title = data.get('title', 'Информация')
        message = data.get('message', '')
        QMessageBox.information(self, title, message)

    def _on_show_error_message(self, data: dict):
        title = data.get('title', 'Ошибка')
        message = data.get('message', '')
        QMessageBox.critical(self, title, message)

    def _on_remove_last_chat_widgets(self, n: int):
        self.chat_window.remove_last_n_widgets(n)

    def _on_update_model_loading_status(self, status: str):
        if hasattr(self, 'loading_status_label'):
            self.loading_status_label.setText(status)

    def _debug_wrapper(self, parent_layout):
        self.setup_debug_controls(parent_layout)
        from ui.settings.debug_settings import setup_debug_panel_controls
        setup_debug_panel_controls(self, parent_layout)

    def _on_debug_insert_system_message(self):
        text = self._debug_system_input.toPlainText().strip()
        if not text:
            return
        character_id = self._get_current_character_id_for_debug()
        self.event_bus.emit(Events.Chat.INSERT_SYSTEM_MESSAGE, {
            "text": text,
            "character_id": character_id,
            "as_user": self._debug_as_user_cb.isChecked(),
        })
        self._debug_system_input.clear()

    def _on_debug_save_snapshot(self):
        character_id = self._get_current_character_id_for_debug()
        self.event_bus.emit(Events.Chat.SAVE_SNAPSHOT, {"character_id": character_id})
        self.event_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
            "title": _("Snapshot", "Snapshot"),
            "message": _("Snapshot сохранён в папку Histories/.../Saved/",
                         "Snapshot saved to Histories/.../Saved/"),
        })

    def _on_debug_load_snapshot(self):
        import os
        character_id = self._get_current_character_id_for_debug()

        histories_root = os.environ.get("NEUROMITA_HISTORIES_DIR", os.path.join(os.getcwd(), "Histories"))
        start_dir = histories_root
        if character_id:
            candidate = os.path.join(histories_root, character_id, "Saved")
            if os.path.isdir(candidate):
                start_dir = candidate
        if not os.path.isdir(start_dir):
            start_dir = "."

        # QFileDialog must run in the main thread — do it here in the View
        file_path, __ = QFileDialog.getOpenFileName(
            self,
            _("Загрузить snapshot", "Load snapshot"),
            start_dir,
            "JSON files (*.json)",
        )
        if not file_path:
            return

        logger.info(f"[Debug] Отправляем Event LOAD_SNAPSHOT для {file_path}")
        # ChatController reads the JSON and saves history, then emits RELOAD_CHAT_HISTORY.
        # SettingsController catches that and calls load_chat_history_signal.emit(),
        # which safely returns execution to the main thread — no 0xC0000409 crashes.
        self.event_bus.emit(Events.Chat.LOAD_SNAPSHOT, {
            "file_path": file_path,
            "character_id": character_id,
        })

    def _on_debug_view_last_context(self, initial_tab: str = "request"):
        import json
        import os
        from ui.dialogs.styled_message import show_styled_message
        base = os.environ.get("NEUROMITA_BASE_DIR", "")
        path = (
            os.path.join(base, "SavedMessages", "last_request_context.json")
            if base
            else os.path.join("SavedMessages", "last_request_context.json")
        )
        if not os.path.isfile(path):
            show_styled_message(
                self,
                _("Нет данных", "No data"),
                _("Файл контекста не найден. Сначала отправьте сообщение.",
                  "Context file not found. Send a message first."),
                level="warning",
            )
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            show_styled_message(self, _("Ошибка", "Error"), str(e), level="error")
            return
        try:
            from ui.dialogs.context_viewer_dialog import ContextViewerDialog
            ContextViewerDialog(data, parent=self, initial_tab=initial_tab).exec()
        except Exception as e:
            import traceback
            show_styled_message(
                self, _("Ошибка открытия диалога", "Dialog error"),
                f"{e}\n\n{traceback.format_exc()}",
                level="error",
            )

    def _on_debug_view_last_response_context(self):
        self._on_debug_view_last_context(initial_tab="response")

    def _get_current_character_id_for_debug(self) -> str:
        try:
            res = self.event_bus.emit_and_wait(Events.Character.GET_CURRENT_PROFILE, timeout=0.5)
            profile = res[0] if res else {}
            if isinstance(profile, dict):
                return str(profile.get("character_id") or "")
        except Exception:
            pass
        return ""

    def _news_wrapper(self, parent_layout):
        self.setup_news_control(parent_layout)

    def setup_news_control(self, parent_layout):
        news_label = QLabel(self.get_news_content())
        news_label.setWordWrap(True)
        news_label.setObjectName("SeparatorLabel")
        parent_layout.addWidget(news_label)

    def setup_debug_controls(self, parent_layout):
        debug_label = QLabel(_("Отладочная информация", "Debug Information"))
        debug_label.setObjectName("SeparatorLabel")
        parent_layout.addWidget(debug_label)

        self.debug_window = QTextEdit()
        self.debug_window.setReadOnly(True)
        self.debug_window.setObjectName("DebugWindow")
        self.debug_window.setMinimumHeight(200)
        parent_layout.addWidget(self.debug_window)
        self.update_debug_info()

    def create_settings_section(self, parent_layout, title, settings_config, icon_name=None):
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 10)
        header_layout.setSpacing(5)
        
        title_label = QLabel(title)
        title_label.setObjectName('SectionTitle')
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet('''
            QLabel#SectionTitle { font-size: 14px; font-weight: bold; color: #ffffff; padding: 5px 0; }
        ''')
        header_layout.addWidget(title_label)
        
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet('''
            QFrame { background-color: #4a4a4a; max-height: 2px; margin: 0 10px; }
        ''')
        header_layout.addWidget(separator)
        parent_layout.addWidget(header_widget)
        gui_templates.create_settings_direct(self, parent_layout, settings_config)

    def create_settings_flat(self, parent_layout, title, settings_config, icon_name=None):
        gui_templates.create_settings_direct(self, parent_layout, settings_config)

    def _check_eula_and_guide(self):
        if not self._get_setting("EULA_ACCEPTED", False):
            self._show_eula_dialog()
    
    def _show_eula_dialog(self):
        from ui.widgets.eula_widget import EULAWidget
        eula_widget = EULAWidget()
        eula_widget.accepted.connect(lambda: self._on_eula_accepted(eula_widget))
        eula_widget.rejected.connect(lambda: self._on_eula_rejected(eula_widget))
        self.overlay.set_content(eula_widget, locked=True)
        self.overlay.show_animated()
        
    def _on_eula_accepted(self, eula_widget):
        self.overlay.hide_animated()
        # Если на стартовом экране выбрали другой язык — интерфейс уже построен
        # на старом, поэтому предлагаем перезапуск. При отказе продолжаем как есть.
        try:
            if eula_widget.language_changed_on_start():
                from ui.language_restart import prompt_language_restart
                if prompt_language_restart(self):
                    return
        except Exception:
            pass
        QTimer.singleShot(500, self._show_guide)
        
    def _on_eula_rejected(self, eula_widget):
        QMessageBox.critical(self, "Отказ от соглашения / Agreement Rejected", 
            "Вы не можете использовать программу без принятия лицензионного соглашения.\n"
            "You cannot use the software without accepting the license agreement.")
        self.close()
        import sys
        sys.exit(0)
        
    def _show_guide(self):
        from ui.widgets.guide_widget import GuideWidget
        guide_widget = GuideWidget()
        guide_widget.closed.connect(lambda: self._on_guide_closed(guide_widget))
        self.overlay.set_content(guide_widget)
        self.overlay.show_animated()
        guide_widget.start()
        
    def _on_guide_closed(self, guide_widget):
        self.overlay.hide_animated()
        
    def _setup_guide_highlights(self, guide_widget):
        if len(guide_widget.pages) > 1:
            guide_widget.pages[1].set_highlight_target(
                lambda: self.settings_buttons.get("language") if hasattr(self, 'settings_buttons') else None
            )
        if len(guide_widget.pages) > 2:
            guide_widget.pages[2].set_highlight_target(
                lambda: self.settings_buttons.get("api") if hasattr(self, 'settings_buttons') else None
            )
        if len(guide_widget.pages) > 3:
            guide_widget.pages[3].set_highlight_target(
                lambda: self.settings_buttons.get("models") if hasattr(self, 'settings_buttons') else None
            )
        if len(guide_widget.pages) > 4:
            guide_widget.pages[4].set_highlight_target(
                lambda: self.settings_buttons.get("voice") if hasattr(self, 'settings_buttons') else None
            )
        if len(guide_widget.pages) > 5:
            guide_widget.pages[5].set_highlight_target(
                lambda: self.settings_buttons.get("microphone") if hasattr(self, 'settings_buttons') else None
            )
        if len(guide_widget.pages) > 6:
            guide_widget.pages[6].set_highlight_target(
                lambda: self.settings_buttons.get("characters") if hasattr(self, 'settings_buttons') else None
            )
        if len(guide_widget.pages) > 7:
            guide_widget.pages[7].set_highlight_target(
                lambda: self.chat_window if hasattr(self, 'chat_window') else None
            )
        if len(guide_widget.pages) > 8:
            guide_widget.pages[8].set_highlight_target(
                lambda: self.token_count_label if hasattr(self, 'token_count_label') else None
            )
        if len(guide_widget.pages) > 9:
            guide_widget.pages[9].set_highlight_target(
                lambda: self.settings_buttons.get("debug") if hasattr(self, 'settings_buttons') else None
            )
    
        # ===== Совместимость: обновление индикаторов статуса =====
    def update_status_colors(self):
        from managers.settings_manager import SettingsManager
        game_connected = self.event_bus.emit_and_wait(Events.Server.GET_GAME_CONNECTION, timeout=0.5)
        silero_connected = self.event_bus.emit_and_wait(Events.Telegram.GET_SILERO_STATUS, timeout=0.5)
        mic_active = self.event_bus.emit_and_wait(Events.Speech.GET_MIC_STATUS, timeout=0.5)
        screen_capture_active = self.event_bus.emit_and_wait(Events.Capture.GET_SCREEN_CAPTURE_STATUS, timeout=0.5)
        camera_capture_active = self.event_bus.emit_and_wait(Events.Capture.GET_CAMERA_CAPTURE_STATUS, timeout=0.5)
        rag_enabled = SettingsManager.get("RAG_ENABLED", False)

        use_voice = bool(SettingsManager.get("USE_VOICEOVER", False))
        method = str(SettingsManager.get("VOICEOVER_METHOD", "Local") or "Local")

        registry = getattr(self, "_status_indicator_registry", {})

        def apply_to(attr_name, checked=None, text=None):
            widgets = list(registry.get(attr_name, []))
            fallback = getattr(self, attr_name, None)
            if fallback is not None and fallback not in widgets:
                widgets.append(fallback)

            for widget in widgets:
                if text is not None and hasattr(widget, "setText"):
                    widget.setText(text)
                if checked is not None and hasattr(widget, "setChecked"):
                    widget.setChecked(bool(checked))

        apply_to("game_status_checkbox", checked=bool(game_connected and game_connected[0]))

        if registry.get("silero_status_checkbox") or hasattr(self, "silero_status_checkbox"):
            if method == "Local":
                voice_label = _('Озвучка (Лок.)', 'Voice (Local)')
                if use_voice:
                    model_id = str(SettingsManager.get("NM_CURRENT_VOICEOVER", "") or "")
                    is_init = self.event_bus.emit_and_wait(
                        Events.Audio.CHECK_MODEL_INITIALIZED, {'model_id': model_id}, timeout=0.5
                    ) if model_id else None
                    voice_active = bool(is_init and is_init[0])
                else:
                    voice_active = False
            else:
                voice_label = _('Озвучка (ТГ)', 'Voice (TG)')
                voice_active = bool(use_voice and silero_connected and silero_connected[0])
            apply_to("silero_status_checkbox", checked=voice_active, text=voice_label)

        apply_to("rag_status_checkbox", checked=bool(rag_enabled))
        apply_to("mic_status_checkbox", checked=bool(mic_active and mic_active[0]))
        apply_to("screen_capture_status_checkbox", checked=bool(screen_capture_active and screen_capture_active[0]))
        apply_to("camera_capture_status_checkbox", checked=bool(camera_capture_active and camera_capture_active[0]))

    # ===== Совместимость: диалоги g4f =====
    def trigger_g4f_reinstall_schedule(self):
        logger.info("Запрос на планирование обновления g4f...")
        target_version = None
        if hasattr(self, 'g4f_version_entry') and self.g4f_version_entry:
            target_version = self.g4f_version_entry.text().strip()
            if not target_version:
                QMessageBox.critical(self, _("Ошибка", "Error"),
                    _("Пожалуйста, введите версию g4f или 'latest'.", "Please enter a g4f version or 'latest'."))
                return
        else:
            logger.error("Виджет entry для версии g4f не найден.")
            QMessageBox.critical(self, _("Ошибка", "Error"),
                _("Не найден элемент интерфейса для ввода версии.", "UI element for version input not found."))
            return

        success = self.event_bus.emit_and_wait(Events.Model.SCHEDULE_G4F_UPDATE, {'version': target_version}, timeout=1.0)
        if success and success[0]:
            QMessageBox.information(self, _("Запланировано", "Scheduled"),
                _("Версия g4f '{version}' будет установлена/обновлена при следующем запуске программы.",
                  "g4f version '{version}' will be installed/updated the next time the program starts.").format(
                    version=target_version))
        else:
            QMessageBox.critical(self, _("Ошибка сохранения", "Save Error"),
                _("Не удалось сохранить настройки для обновления. Пожалуйста, проверьте логи.",
                  "Failed to save settings for the update. Please check the logs."))

    # ===== Совместимость: рендер сообщений (обёртки к message_renderer) =====
    def _on_update_chat_signal(self, role, content, insert_at_start, message_time):
        """Slot for update_chat_signal — picks up pending structured_data and message_id if available."""
        # Only assistant messages consume _pending_structured_data / _pending_message_id.
        # Think/system messages must not steal it from the following assistant message.
        structured_data = None
        message_id = None
        if role == "assistant":
            structured_data = getattr(self, '_pending_structured_data', None)
            self._pending_structured_data = None
            message_id = getattr(self, '_pending_message_id', None) or None
            self._pending_message_id = None
        from ui.chat import message_renderer
        message_renderer.insert_message(self, role, content, insert_at_start, message_time,
                                        structured_data=structured_data, message_id=message_id)

    def _insert_message_slot(self, role, content, insert_at_start, message_time):
        return self.insert_message(role, content, insert_at_start, message_time)

    def insert_message(self, role, content, insert_at_start=False, message_time="", structured_data=None):
        from ui.chat import message_renderer
        return message_renderer.insert_message(self, role, content, insert_at_start, message_time,
                                               structured_data=structured_data)

    def insert_message_end(self, cursor=None, role="assistant"):
        from ui.chat import message_renderer
        return message_renderer.insert_message_end(self, cursor, role)

    def insert_speaker_name(self, cursor=None, role="assistant"):
        from ui.chat import message_renderer
        return message_renderer.insert_speaker_name(self, cursor, role)

    def _insert_formatted_text(self, cursor, text, color=None, bold=False, italic=False):
        from ui.chat import message_renderer
        return message_renderer._insert_formatted_text(self, cursor, text, color, bold, italic)

    def _on_prepare_stream_signal(self, data=None):
        from ui.chat import message_renderer
        role = data.get("role", "assistant") if isinstance(data, dict) else "assistant"
        
        # Сохраняем имя спикера, если оно пришло
        if isinstance(data, dict) and "speaker_name" in data:
            self._stream_speaker_name = data["speaker_name"]
            
        return message_renderer.prepare_stream_slot(self, role=role)

    def _append_stream_chunk_slot(self, data):
        from ui.chat import message_renderer
        chunk = data.get("chunk") if isinstance(data, dict) else data
        role = data.get("role", "assistant") if isinstance(data, dict) else "assistant"
        return message_renderer.append_stream_chunk_slot(self, chunk, role=role)

    def _finish_stream_slot(self):
        from ui.chat import message_renderer
        # Сбрасываем имя спикера после завершения стрима
        self._stream_speaker_name = ""
        # Attach structured panel BEFORE finish (finish clears _current_stream_message)
        pending = getattr(self, '_pending_structured_data', None)
        if pending:
            self._pending_structured_data = None
            message_renderer.attach_structured_to_stream(self, pending)
        message_renderer.finish_stream_slot(self)

    def process_image_for_chat(self, has_image_content, item, processed_content_parts):
        from ui.chat import message_renderer
        return message_renderer.process_image_for_chat(self, has_image_content, item, processed_content_parts)

    # ===== Совместимость: методы панели чата (обёртки к chat_panel) =====
    def _create_scroll_to_bottom_button(self):
        return chat_panel.create_scroll_to_bottom_button(self)

    def _handle_chat_scroll(self):
        return chat_panel.handle_chat_scroll(self)

    def _fade_in_scroll_button(self):
        return chat_panel.fade_in_scroll_button(self)

    def _fade_out_scroll_button(self):
        return chat_panel.fade_out_scroll_button(self)

    def _reposition_scroll_button(self):
        return chat_panel.reposition_scroll_button(self)

    def _adjust_input_height(self):
        return chat_panel.adjust_input_height(self)

    def _update_send_button_state(self):
        return chat_panel.update_send_button_state(self)

    def _init_image_preview(self):
        return chat_panel.init_image_preview(self)

    def _show_image_preview_bar(self):
        return chat_panel.show_image_preview_bar(self)

    def _remove_staged_image(self, index):
        return chat_panel.remove_staged_image(self, index)

    def _hide_image_preview_bar(self):
        return chat_panel.hide_image_preview_bar(self)

    def _show_full_image(self, image_data):
        return chat_panel.show_full_image(self, image_data)

    def _clipboard_image_to_controller(self):
        return chat_panel.clipboard_image_to_controller(self)

    def attach_images(self):
        return chat_panel.attach_images(self)

    def send_screen_capture(self):
        return chat_panel.send_screen_capture(self)

    def _clear_staged_images(self):
        return chat_panel.clear_staged_images(self)

    def _position_mita_status(self):
        return chat_panel.position_mita_status(self)

    # ===== Слоты прогресса установки ASR (если вдруг отсутствуют) =====
    def _on_asr_install_progress(self, data: dict):
        if hasattr(self, 'install_model_button'):
            status   = data.get("status", "")
            progress = data.get("progress", 0)
            self.install_model_button.setText(f"{status} ({progress}%)")

    def _on_asr_install_finished(self, data: dict):
        if hasattr(self, 'install_model_button'):
            self.install_model_button.setText(_("Установлено!", "Installed!"))
            self.install_model_button.setEnabled(True)

    def _on_asr_install_failed(self, data: dict):
        if hasattr(self, 'install_model_button'):
            self.install_model_button.setText(_("Ошибка установки", "Installation failed"))
            self.install_model_button.setEnabled(True)

    # ===== Совместимость: упрощённая вставка диалога =====
    def insert_dialog(self, input_text="", response="", system_text=""):
        MitaName = self._get_character_name()
        if input_text:
            self.insert_message("user", input_text)
        if system_text:
            self.insert_message("system", system_text)
        if response:
            self.insert_message("assistant", response)

    def set_settings_icon_indicator(self, category: str, state: str | None, tooltip: str | None = None) -> None:
        btn = getattr(self, "settings_buttons", {}).get(category)
        if not btn:
            return
        if hasattr(btn, "set_indicator_state"):
            btn.set_indicator_state(state, tooltip_text=tooltip)


    def _set_voice_icon_loading(self, model_id: str | None) -> None:
        mid = str(model_id) if model_id else None
        self._voice_model_init_in_progress_model_id = mid


    def _update_voice_settings_icon_indicator(self) -> None:
        use_voice = bool(self._get_setting("USE_VOICEOVER", False))
        method = self._get_setting("VOICEOVER_METHOD", "Local")

        if not use_voice or method != "Local":
            self.set_settings_icon_indicator("voice", None, None)
            return

        model_id = self._get_setting("NM_CURRENT_VOICEOVER", None)
        model_id = str(model_id) if model_id else ""

        if not model_id:
            self.set_settings_icon_indicator(
                "voice",
                "red",
                "Local voiceover enabled: model not selected"
            )
            return

        if self._voice_model_init_in_progress_model_id == model_id:
            self.set_settings_icon_indicator(
                "voice",
                "loading",
                f"Initializing local voice model: {model_id}"
            )
            return

        is_installed = self.event_bus.emit_and_wait(
            Events.Audio.CHECK_MODEL_INSTALLED,
            {'model_id': model_id},
            timeout=0.5
        )
        if not (is_installed and is_installed[0]):
            self.set_settings_icon_indicator(
                "voice",
                "red",
                f"Local voice model not installed: {model_id}"
            )
            return

        is_initialized = self.event_bus.emit_and_wait(
            Events.Audio.CHECK_MODEL_INITIALIZED,
            {'model_id': model_id},
            timeout=0.5
        )
        if not (is_initialized and is_initialized[0]):
            self.set_settings_icon_indicator(
                "voice",
                "red",
                f"Local voice model requires initialization: {model_id}"
            )
            return

        self.set_settings_icon_indicator(
            "voice",
            "green",
            f"Local voice model ready: {model_id}"
        )


