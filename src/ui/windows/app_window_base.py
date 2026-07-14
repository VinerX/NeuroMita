
import base64

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QTimer,
    QUrl,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import ui.gui_templates as gui_templates
from localization.live import tr_set
from main_logger import logger
from ui.chat import message_renderer
from ui.chat.chat_delegate import ChatMessageDelegate
from ui.chat.render_context import ChatRenderContext
from ui.dialogs.ffmpeg_dialogs import create_ffmpeg_install_popup, show_ffmpeg_error_popup
from ui.dialogs.telegram_auth_dialogs import show_tg_code_dialog, show_tg_password_dialog
from ui.widgets.image_viewer_widget import ImageViewerWidget
from ui.widgets.overlay_widget import OverlayWidget
from utils import getTranslationVariant as _


class AppWindowBase(QMainWindow):
    update_chat_signal = pyqtSignal(str, object, bool, str)
    update_status_signal = pyqtSignal()
    update_debug_signal = pyqtSignal()

    prepare_stream_signal = pyqtSignal(object)
    append_stream_chunk_signal = pyqtSignal(object)
    finish_stream_signal = pyqtSignal(object)

    show_thinking_signal = pyqtSignal(object)
    show_error_signal = pyqtSignal(str)
    hide_status_signal = pyqtSignal()
    pulse_error_signal = pyqtSignal()
    show_voicing_signal = pyqtSignal(object)
    hide_voicing_signal = pyqtSignal()
    hide_compression_signal = pyqtSignal()

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
    send_text_message_signal = pyqtSignal(str)
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

    def __init__(
        self,
        settings,
        *,
        telegram_auth_actions,
        chat_message_actions,
        shell_actions,
        window_actions,
    ):
        super().__init__()
        self.settings = settings
        self._telegram_auth_actions = telegram_auth_actions
        self._chat_message_actions = chat_message_actions
        self._shell_actions = shell_actions
        self._window_actions = window_actions
        self.settings_view_model = None
        self.settings_binding = None

        try:
            self.SETTINGS_PANEL_WIDTH = int(self.settings.get("SETTINGS_PANEL_WIDTH", 520) or 520)
        except Exception:
            self.SETTINGS_PANEL_WIDTH = 520
        self.SETTINGS_PANEL_WIDTH = max(280, min(1800, self.SETTINGS_PANEL_WIDTH))

        self._connect_signals()
        self._chat_message_actions.effect_emitted.connect(
            self._handle_chat_message_effect
        )

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
        self._chat_panel_view = None
        self._chat_ui_ready = False
        self._chat_history_load_pending = False
        self._pending_history_payload = None
        self._token_refresh_pending = False
        self._history_load_inflight = False

        tr_set(self, "Чат с NeuroMita", "NeuroMita Chat", "setWindowTitle")
        from ui.app_icon import application_icon
        self.setWindowIcon(application_icon())

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
        self.hide_compression_signal.connect(self._hide_compression_slot)

        self.settings_animation = None
        self.setup_ui()
        self.chat_delegate = ChatMessageDelegate()
        self._chat_render_context = ChatRenderContext(
            settings_getter=self._get_setting,
            character_name_getter=self._get_character_name,
            chat_message_actions=self._chat_message_actions,
            chat_delegate=self.chat_delegate,
        )
        self._ensure_settings_animation()

        self._on_chat_ui_ready()

        self.overlay = OverlayWidget(self)
        self.image_preview_bar = None

        self.prepare_stream_signal.connect(self._on_stream_start)
        self.finish_stream_signal.connect(self._on_stream_finish)

        QTimer.singleShot(0, self.update_status_colors)
        QTimer.singleShot(1000, self._check_eula_and_guide)

        self.last_voice_model_selected = None
        self.current_local_voice_id = None
        self.model_loading_cancelled = False
        self._status_refresh_ticket = 0
        self._debug_refresh_ticket = 0
        self._token_refresh_ticket = 0

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
        self.send_text_message_signal.connect(
            lambda text: self.send_message(
                user_input=text,
                merge_input_from_entry=bool(self._get_setting("MIC_INSTANT_MERGE_CHAT_INPUT", True)),
            ),
            type=Qt.ConnectionType.QueuedConnection,
        )
        self.show_info_message_signal.connect(self._on_show_info_message)
        self.show_error_message_signal.connect(self._on_show_error_message)
        self.update_model_loading_status_signal.connect(self._on_update_model_loading_status)
        self.run_ui_task_signal.connect(
            self._run_ui_task_slot,
            type=Qt.ConnectionType.QueuedConnection,
        )
        self.asr_install_progress_signal.connect(
            self._on_asr_install_progress,
            type=Qt.ConnectionType.QueuedConnection,
        )
        self.asr_install_finished_signal.connect(
            self._on_asr_install_finished,
            type=Qt.ConnectionType.QueuedConnection,
        )
        self.asr_install_failed_signal.connect(
            self._on_asr_install_failed,
            type=Qt.ConnectionType.QueuedConnection,
        )

    def _run_ui_task_slot(self, fn):
        try:
            if callable(fn):
                fn()
        except Exception as exc:
            logger.error(f"_run_ui_task_slot error: {exc}", exc_info=True)

    def attach_settings_binding(self, binding) -> None:
        self.settings_view_model = binding
        self.settings_binding = binding

    @property
    def chat_message_actions(self):
        return self._chat_message_actions

    def _handle_chat_message_effect(self, effect) -> None:
        from ui.chat.message_actions_presentation import (
            ShowChatSampleContext,
            ShowChatSampleContextError,
        )
        from ui.dialogs.context_viewer_dialog import ContextViewerDialog
        from ui.dialogs.styled_message import show_styled_message

        if isinstance(effect, ShowChatSampleContextError):
            if effect.not_found:
                show_styled_message(
                    self,
                    _("Не найдено", "Not found"),
                    _(
                        "Данные не найдены. Убедитесь, что хотя бы одно сообщение было отправлено.",
                        "No data found. Make sure at least one message has been sent.",
                    ),
                    level="warning",
                )
            else:
                show_styled_message(
                    self,
                    _("Ошибка", "Error"),
                    effect.message,
                    level="error",
                )
            return
        if not isinstance(effect, ShowChatSampleContext):
            return
        if effect.used_fallback:
            show_styled_message(
                self,
                _("Данные конкретного сообщения недоступны", "Message-specific data not available"),
                _(
                    "Сбор данных для дообучения был отключён для этого сообщения.\n"
                    "Показан последний сохранённый запрос — он может не совпадать с этим сообщением.",
                    "Finetune collection was disabled for this message.\n"
                    "Showing the last saved request — it may not match this message.",
                ),
                level="info",
            )
        dialog = ContextViewerDialog(
            effect.data,
            parent=self,
            initial_tab=effect.initial_tab,
        )
        dialog.exec()

    def refresh_backend_state(
        self,
        *,
        backend_ready: bool,
        startup_error: str | None = None,
    ) -> None:
        panel = self._chat_panel_view
        if panel is not None:
            panel.refresh_state()
        if not backend_ready and startup_error and hasattr(self, "_set_home_progress"):
            self._set_home_progress(str(startup_error), 0, 1, busy=False)

    def _on_reopen_install_logs(self):
        self._window_actions.reopen_install_logs()

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
        panel = self._chat_panel_view
        if panel is not None:
            QTimer.singleShot(0, panel.reposition_status)

    def eventFilter(self, obj, event):
        return super().eventFilter(obj, event)

    def bind_chat_panel(self, panel) -> None:
        """Expose one composed chat surface to legacy render adapters.

        The panel owns all widgets and local staged-image state. The shell only
        keeps compatibility references for older renderers/controllers that
        have not yet been converted to a dedicated chat-surface port.
        """
        self._chat_panel_view = panel
        self.chat_panel = panel
        self.chat_window = panel.chat_window
        self._chat_render_context.bind_chat_window(panel.chat_window)
        self.token_count_label = panel.token_count_label
        self.user_entry = panel.user_entry
        self.attachment_label = panel.attachment_label
        self.attach_button = panel.attach_button
        self.send_screen_button = panel.send_screen_button
        self.send_button = panel.send_button
        self.composer_bar = panel.composer_bar
        self.composer_warning = panel.composer_warning
        self.composer_warning_label = panel.composer_warning_label
        self.clear_attach_btn = panel.clear_attach_btn
        self.image_preview_bar = panel.image_preview_bar
        self.staged_image_data = panel.staged_images
        self.scroll_to_bottom_btn = panel.scroll_to_bottom_btn
        self.scroll_to_bottom_anim = panel.scroll_to_bottom_anim
        self.mita_status = panel.mita_status
        self._on_chat_ui_ready()

    def bind_sandbox_page(self, page) -> None:
        """Bind the composed Sandbox surface for legacy controller adapters."""
        self.sandbox_page = page
        self.chat_character_combobox = page.chat_character_combobox
        self.chat_prompt_pack_combobox = page.chat_prompt_pack_combobox
        self.chat_model_combobox = page.chat_model_combobox
        self.sandbox_inspector_tabs = page.inspector_stack

    def show_chat_image(self, image_data: bytes) -> None:
        try:
            payload = image_data
            if isinstance(payload, str) and payload.startswith("data:image"):
                payload = base64.b64decode(payload.split(",", 1)[1])
            if not isinstance(payload, (bytes, bytearray)):
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(bytes(payload)):
                return
            viewer = ImageViewerWidget(pixmap)
            viewer.close_requested.connect(self.overlay.hide_animated)
            self.overlay.set_content(viewer)
            self.overlay.show_animated()
        except Exception as exc:
            logger.error("Failed to show chat image: %s", exc, exc_info=True)

    def _on_chat_ui_ready(self):
        """Flush deferred chat work when the lazy Sandbox page materializes."""
        chat_window = getattr(self, "chat_window", None)
        if chat_window is None:
            return False

        self._chat_ui_ready = True

        pending_payload = self._pending_history_payload
        self._pending_history_payload = None
        if pending_payload is not None:
            QTimer.singleShot(0, lambda data=pending_payload: self._on_history_loaded(data))
        elif self._chat_history_load_pending:
            self._chat_history_load_pending = False
            QTimer.singleShot(0, self.load_chat_history)

        if self._token_refresh_pending:
            self._token_refresh_pending = False
            QTimer.singleShot(0, self.update_token_count)
        return True

    def load_chat_history(self):
        chat_window = getattr(self, "chat_window", None)
        if chat_window is None:
            self._chat_history_load_pending = True
            logger.debug("[Load] Chat UI is not ready; history load deferred")
            return False

        self._chat_history_load_pending = False
        self._history_load_inflight = True
        logger.debug("[Load] load_chat_history: начало")
        logger.debug("[Load] Отключаем updates в chat_window")
        chat_window.setUpdatesEnabled(False)
        logger.debug("[Load] Вызываем clear_chat_display()")
        try:
            self.clear_chat_display()
            logger.debug("[Load] Эмитим LOAD_HISTORY")
            self._shell_actions.load_history()
            QTimer.singleShot(15000, self._recover_stalled_history_load)
            logger.debug("[Load] load_chat_history: конец")
            return True
        except Exception:
            self._history_load_inflight = False
            chat_window.setUpdatesEnabled(True)
            chat_window.update()
            raise

    def _recover_stalled_history_load(self):
        if not self._history_load_inflight:
            return
        chat_window = getattr(self, "chat_window", None)
        if chat_window is not None:
            logger.warning("History UI load timed out; restoring chat repaint")
            chat_window.setUpdatesEnabled(True)
            chat_window.update()
        self._history_load_inflight = False

    def _on_history_loaded(self, data: dict):
        chat_window = getattr(self, "chat_window", None)
        if chat_window is None:
            self._pending_history_payload = dict(data or {})
            return

        messages = data.get('messages', [])
        character_id = data.get('character_id', '')
        logger.info(f"[HistoryLoaded] Загружено {len(messages)} сообщений для отображения")
        try:
            for entry in messages:
                role = entry["role"]
                content = entry["content"]
                message_time = entry.get("time", "???")
                structured_data = entry.get("structured_data")
                message_id = entry.get("message_id")
                sample_id = entry.get("sample_id")
                thinking_text = entry.get("thinking")
                show_think_in_gui = bool(self._get_setting("SHOW_THINK_IN_GUI", False))
                if role == "assistant" and thinking_text and show_think_in_gui:
                    speaker = entry.get("speaker", "")
                    message_renderer.insert_message(
                        self._chat_render_context, "think",
                        [{"type": "meta", "speaker": speaker},
                         {"type": "text", "text": thinking_text.strip()}],
                        message_time=message_time,
                        character_id=character_id,
                    )
                message_renderer.insert_message(self._chat_render_context, role, content, message_time=message_time,
                                                structured_data=structured_data,
                                                message_id=message_id, character_id=character_id,
                                                ui_images=entry.get("_ui_images") or [],
                                                sample_id=sample_id)
            self.update_debug_info()
            chat_window.scroll_to_bottom()
        except Exception as exc:
            logger.error(f"Failed to project loaded history: {exc}", exc_info=True)
        finally:
            self._history_load_inflight = False
            chat_window.setUpdatesEnabled(True)
            chat_window.update()

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
        if not (hasattr(self, 'debug_window') and self.debug_window):
            return

        self._debug_refresh_ticket += 1
        ticket = self._debug_refresh_ticket

        def apply(debug_info):
            if ticket != self._debug_refresh_ticket:
                return
            if hasattr(self, 'debug_window') and self.debug_window:
                self.debug_window.clear()
                self.debug_window.insertPlainText(str(debug_info or "Debug info not available"))

        self._shell_actions.request_debug_info(apply)

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
        # Token UI belongs to the lazy Sandbox page. Backend events may arrive
        # before that page is created or while it is being destroyed.
        label = getattr(self, "token_count_label", None)
        if label is None:
            self._token_refresh_pending = True
            return False

        # По умолчанию выключено (#7): строка со статистикой токенов/стоимости
        # включается галкой «Показывать статистику токенов/стоимости».
        show_token_info = self._get_setting("SHOW_TOKEN_INFO", False)
        if show_token_info:
            self._token_refresh_ticket += 1
            ticket = self._token_refresh_ticket

            def apply(stats: dict):
                payload = {
                    "stats": stats or {},
                    "max_model_tokens": int(self._get_setting("MAX_MODEL_TOKENS", 32000) or 32000),
                }
                if ticket != self._token_refresh_ticket:
                    return

                current_label = getattr(self, "token_count_label", None)
                if current_label is None:
                    self._token_refresh_pending = True
                    return

                stats = payload.get("stats") or {}
                fmt = self._fmt_tokens
                current_context_tokens = int(stats.get("estimated_context_tokens") or 0)
                max_model_tokens = int(stats.get("max_context_tokens") or payload.get("max_model_tokens") or 32000)
                est_cost = stats.get("estimated_input_cost")
                est_currency = str(stats.get("estimated_input_cost_currency") or "")
                est_cost_text = "n/a" if est_cost is None else f"{float(est_cost):.4f} {est_currency}".strip()
                ctx_pct = int(round(current_context_tokens / max_model_tokens * 100)) if max_model_tokens else 0
                ctx_str = f"~{ctx_pct}% ({fmt(current_context_tokens)}/{fmt(max_model_tokens)})"

                actual_prompt = stats.get("actual_prompt_tokens")
                actual_completion = stats.get("actual_completion_tokens")
                actual_cost = stats.get("actual_cost")
                actual_currency = str(stats.get("actual_cost_currency") or "")
                if actual_prompt is not None or actual_completion is not None or actual_cost is not None:
                    actual_prompt = int(actual_prompt or 0)
                    actual_completion = int(actual_completion or 0)
                    actual_total = int(stats.get("actual_total_tokens") or (actual_prompt + actual_completion))
                    actual_cost_text = "n/a" if actual_cost is None else f"{float(actual_cost):.4f} {actual_currency}".strip()
                    text = _("Context: {} | Input: {} | Request: {}/{} (total {}) | Actual: {}",
                             "Context: {} | Input: {} | Request: {}/{} (total {}) | Actual: {}").format(
                        ctx_str, est_cost_text, fmt(actual_prompt), fmt(actual_completion), fmt(actual_total), actual_cost_text
                    )
                else:
                    text = _("Context: {} | Input: {}", "Context: {} | Input: {}").format(ctx_str, est_cost_text)

                current_label.setText(text)
                current_label.setVisible(True)
                self.update_debug_info()

            self._shell_actions.request_token_stats(apply)
            return
        else:
            label.setVisible(False)
            label.setText(_("Токены: Токенизатор недоступен", "Tokens: Tokenizer not available"))
        self.update_debug_info()
        return True

    def update_chat_font_size(self, font_size):
        self._chat_font_size = font_size
        self._chat_render_context.set_font_size(font_size)

    def clear_chat_display(self):
        return self._shell_actions.clear_chat()

    def render_chat_cleared(self) -> None:
        chat_window = getattr(self, "chat_window", None)
        if chat_window is None:
            return
        logger.debug("[Clear] chat_window.message_count: %s", chat_window.message_count())
        chat_window.clear_messages()

    def user_input_text(self) -> str:
        entry = getattr(self, "user_entry", None)
        return entry.toPlainText().strip() if entry is not None else ""

    def staged_images_snapshot(self) -> list:
        panel = self._chat_panel_view
        if panel is not None:
            return panel.staged_images_snapshot()
        return list(self.staged_image_data)

    def show_send_error(self, message: str) -> None:
        logger.info(message)
        self.show_error_signal.emit(str(message))

    def render_outgoing_message(
        self,
        *,
        user_input: str,
        image_content: list,
        message_id: str,
        clear_entry: bool,
    ) -> None:
        if user_input:
            message_renderer.insert_message(self._chat_render_context, "user", user_input, message_id=message_id)
        if image_content:
            message_renderer.insert_message(self._chat_render_context, "user", image_content, message_id=message_id)
        if clear_entry and self.user_entry is not None:
            self.user_entry.clear()

    def show_thinking_now(self) -> None:
        self.show_thinking_signal.emit(self._get_character_name())

    def clear_staged_images_view(self) -> None:
        panel = self._chat_panel_view
        if panel is not None:
            panel.clear_staged_images_view()
            return
        self.staged_image_data.clear()

    def send_message(
        self,
        system_input: str = "",
        image_data: list[bytes] | None = None,
        user_input: str | None = None,
        merge_input_from_entry: bool = False,
    ):
        result = self._shell_actions.send_message(
            system_input=system_input,
            image_data=image_data,
            user_input=user_input,
            merge_input_from_entry=merge_input_from_entry,
        )
        if result is False:
            self.show_send_error(_("Backend недоступен.", "Backend is unavailable."))
        return result

    def load_more_history(self):
        if getattr(self, "chat_window", None) is None:
            return False
        self._shell_actions.load_more_history()
        return True

    def _on_more_history_loaded(self, data: dict):
        if getattr(self, "chat_window", None) is None:
            return
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
            message_renderer.insert_message(self._chat_render_context, role, content, insert_at_start=True,
                                            message_time=message_time, structured_data=structured_data,
                                            message_id=message_id, character_id=character_id,
                                            ui_images=entry.get("_ui_images") or [],
                                            sample_id=sample_id)
        QTimer.singleShot(0, lambda: scrollbar.setValue(scrollbar.maximum() - old_max + old_value))
        logger.info(f"Загружено еще {len(messages_to_prepend)} сообщений.")

    def _save_setting(self, key, value):
        binding = getattr(self, "settings_binding", None)
        if binding is not None:
            binding.set(key, value)
            return
        self.settings.set(key, value)

    def _get_setting(self, key, default=None):
        view_model = getattr(self, "settings_view_model", None)
        if view_model is not None:
            return view_model.get(key, default)
        return self.settings.get(key, default)

    def _get_character_name(self):
        combo = getattr(self, "chat_character_combobox", None)
        try:
            text = combo.currentText().strip() if combo is not None else ""
            if text and text != "...":
                return text
        except Exception:
            pass
        return str(self._get_setting("CHARACTER_NAME", "Assistant") or "Assistant")

    def closeEvent(self, event):
        try:
            self._shell_actions.close_application()
        except Exception as exc:
            logger.error(f"Ошибка при закрытии приложения: {exc}", exc_info=True)

        try:
            self._window_actions.close()
        except Exception:
            pass

        logger.info("Закрываемся")
        event.accept()

    def close_app(self):
        logger.info("Завершение программы...")
        self.close()

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
        show_tg_code_dialog(
            self,
            self._telegram_auth_actions,
            str(data.get("request_id") or ""),
            error=data.get("error", ""),
        )

    def _on_show_tg_password_dialog(self, data: dict):
        show_tg_password_dialog(
            self,
            self._telegram_auth_actions,
            str(data.get("request_id") or ""),
            error=data.get("error", ""),
        )

    def _on_chat_anchor_clicked(self, url):
        href = url.toString()
        if href.startswith("think://toggle/"):
            try:
                block_id = int(href.split("/")[-1])
                message_renderer.toggle_think_block(self._chat_render_context, block_id)
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

    def _show_voicing_slot(self, payload=None):
        # Voicing is rendered on the message bubble rather than the global status bar.
        # Подсветить конкретный пузырь, который сейчас озвучивается.
        message_id = payload.get("message_id") if isinstance(payload, dict) else None
        if message_id and getattr(self, "chat_window", None):
            try:
                self.chat_window.set_message_voicing(message_id, True)
            except Exception:
                pass

    def _hide_voicing_slot(self):
        # No global voicing status to clear; only the per-message marker.
        if getattr(self, "chat_window", None):
            try:
                self.chat_window.clear_message_voicing()
            except Exception:
                pass

    def _hide_compression_slot(self):
        if hasattr(self, 'mita_status') and self.mita_status:
            self.mita_status.hide_compression()

    def _on_stream_start(self, _data=None):
        pass

    def _on_stream_finish(self, _data=None):
        self._hide_status_slot()

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
        self._on_display_loading_popup({"message": message})

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
        self._on_hide_loading_popup()

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
        chat_window = getattr(self, "chat_window", None)
        if chat_window is not None:
            chat_window.remove_last_n_widgets(n)

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
        self._shell_actions.insert_debug_message(
            text=text,
            character_id=character_id,
            as_user=self._debug_as_user_cb.isChecked(),
        )
        self._debug_system_input.clear()

    def _on_debug_save_snapshot(self):
        character_id = self._get_current_character_id_for_debug()
        self._shell_actions.save_snapshot(character_id)
        self._on_show_info_message({
            "title": _("Snapshot", "Snapshot"),
            "message": _("Snapshot сохранён в папку Histories/.../Saved/",
                         "Snapshot saved to Histories/.../Saved/"),
        })

    def _on_debug_load_snapshot(self):
        character_id = self._get_current_character_id_for_debug()
        start_dir = self._shell_actions.snapshot_start_directory(character_id)

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
        self._shell_actions.load_snapshot(
            file_path=file_path,
            character_id=character_id,
        )

    def _on_debug_view_last_context(self, initial_tab: str = "request"):
        from ui.chat.message_actions_presentation import ViewChatSampleContext

        self._chat_message_actions.dispatch(
            ViewChatSampleContext("", str(initial_tab or "request"))
        )

    def _on_debug_view_last_response_context(self):
        self._on_debug_view_last_context(initial_tab="response")

    def _get_current_character_id_for_debug(self) -> str:
        return self._shell_actions.current_character_id()

    def current_character_id(self) -> str:
        """Public UI query backed by the injected shell action port."""
        return self._shell_actions.current_character_id()

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
        eula_widget = EULAWidget(self.settings_binding or self.settings)
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

    def _show_guide(self):
        from ui.widgets.guide_widget import GuideWidget
        guide_widget = GuideWidget(self.settings_binding or self.settings)
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

        # ===== Обновление индикаторов статуса =====
    def update_status_colors(self):
        if self._shell_actions.is_closing:
            return
        if QApplication.closingDown():
            return

        self._status_refresh_ticket += 1
        ticket = self._status_refresh_ticket

        def apply(state):
            if ticket != self._status_refresh_ticket:
                return

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

            apply_to("game_status_checkbox", checked=bool(state.get("game_connected")))

            if registry.get("silero_status_checkbox") or hasattr(self, "silero_status_checkbox"):
                method = str(state.get("method") or "Local")
                use_voice = bool(state.get("use_voice"))
                if method == "Local":
                    voice_label = _('Озвучка (Лок.)', 'Voice (Local)')
                    voice_active = bool(state.get("voice_initialized"))
                else:
                    voice_label = _('Озвучка (ТГ)', 'Voice (TG)')
                    voice_active = bool(use_voice and state.get("silero_connected"))
                apply_to("silero_status_checkbox", checked=voice_active, text=voice_label)

            apply_to("rag_status_checkbox", checked=bool(state.get("rag_enabled")))
            apply_to("mic_status_checkbox", checked=bool(state.get("mic_active")))
            apply_to("screen_capture_status_checkbox", checked=bool(state.get("screen_capture_active")))
            apply_to("camera_capture_status_checkbox", checked=bool(state.get("camera_capture_active")))

        self._shell_actions.request_status(apply)

    # ===== Рендер сообщений и streaming-слоты =====
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
        message_renderer.insert_message(self._chat_render_context, role, content, insert_at_start, message_time,
                                        structured_data=structured_data, message_id=message_id)

    def _insert_message_slot(self, role, content, insert_at_start, message_time):
        return message_renderer.insert_message(
            self._chat_render_context,
            role,
            content,
            insert_at_start,
            message_time,
        )

    def _on_prepare_stream_signal(self, data=None):
        from ui.chat import message_renderer
        payload = data if isinstance(data, dict) else {}
        return message_renderer.prepare_stream_slot(
            self._chat_render_context,
            role=payload.get("role", "assistant"),
            stream_id=str(payload.get("stream_id") or "default"),
            speaker_name=str(payload.get("speaker_name") or payload.get("character_name") or ""),
        )

    def _append_stream_chunk_slot(self, data):
        from ui.chat import message_renderer
        payload = data if isinstance(data, dict) else {"chunk": data}
        return message_renderer.append_stream_chunk_slot(
            self._chat_render_context,
            payload.get("chunk"),
            role=payload.get("role", "assistant"),
            stream_id=str(payload.get("stream_id") or "default"),
        )

    def _finish_stream_slot(self, data=None):
        from ui.chat import message_renderer
        payload = data if isinstance(data, dict) else {}
        stream_id = str(payload.get("stream_id") or "default")
        structured = payload.get("structured_data")
        if structured:
            message_renderer.attach_structured_to_stream(
                self._chat_render_context,
                structured,
                stream_id=stream_id,
            )
        message_renderer.finish_stream_slot(self._chat_render_context, stream_id=stream_id)

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

        is_installed, is_initialized = self._shell_actions.voice_model_state(model_id)
        if not is_installed:
            self.set_settings_icon_indicator(
                "voice",
                "red",
                f"Local voice model not installed: {model_id}"
            )
            return

        if not is_initialized:
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

