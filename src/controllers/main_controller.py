import os
import time
from pathlib import Path
from PyQt6.QtCore import QTimer

from controllers.gui_controller import GuiController
from controllers.audio_controller import AudioController
from controllers.telegram_controller import TelegramController
from controllers.capture_controller import CaptureController
from controllers.model_controller import ModelController
from controllers.character_controller import CharacterController
from controllers.speech_controller import SpeechController
from controllers.settings_controller import SettingsController
from controllers.chat_controller import ChatController
from controllers.loop_controller import LoopController
from controllers.task_controller import TaskController
from controllers.api_presets_controller import ApiPresetsController
from controllers.local_voice_controller import LocalVoiceController
from controllers.prompt_controller import PromptController
from controllers.history_controller import HistoryController
from controllers.voice_model_controller import VoiceModelController
from controllers.install_controller import InstallController
from controllers.protocols_controller import ProtocolsController

from main_logger import logger
from utils.ffmpeg_installer import install_ffmpeg
from utils.pip_installer import PipInstaller
from core.events import get_event_bus, Events, Event, shutdown_event_bus


from controllers.server_controller import ServerController
from controllers.server_controller_old import ServerControllerOld


class MainController:
    def __init__(self, view):
        self.view = view
        self.event_bus = get_event_bus()

        self.dialog_active = False


        self.loop_controller = LoopController()
        logger.notify("LoopController успешно инициализирован.")

        self.gui_controller = None

        self.telegram_controller = TelegramController()
        logger.notify("TelegramController успешно инициализирован.")
        

        try:
            target_folder = "Settings"
            os.makedirs(target_folder, exist_ok=True)
            self.config_path = os.path.join(target_folder, "settings.json")

            self.settings_controller = SettingsController(self.config_path)
            self.settings = self.settings_controller.settings
        except Exception as e:
            logger.info("Не удалось удачно получить из системных переменных все данные", e)
            self.settings = SettingsController("Settings/settings.json").settings

        try:
            self.pip_installer = PipInstaller(
                script_path=r"libs\python\python.exe",
                libs_path="Lib",
                update_log=logger.info
            )
            logger.notify("PipInstaller успешно инициализирован.")
        except Exception as e:
            logger.error(f"Не удалось инициализировать PipInstaller: {e}", exc_info=True)
            self.pip_installer = None

        self._check_and_perform_pending_update()

        self.install_controller = InstallController(script_path=r"libs\python\python.exe", libs_path="Lib")
        logger.notify("InstallController успешно инициализирован.")
        
        self.local_voice_controller = LocalVoiceController(self)
        logger.notify("LocalVoiceController успешно инициализирован.")
        
        self.task_controller = TaskController()
        logger.notify("TaskController успешно инициализирован.")

        self.history_controller = HistoryController()
        logger.notify("HistoryController успешно инициализирован.")

        self.prompt_controller = PromptController()
        logger.notify("PromptController успешно инициализирован.")
        
        self.protocols_controller = ProtocolsController()
        logger.notify("ProtocolsController успешно инициализирован.")

        self.api_presets_controller = ApiPresetsController()
        logger.notify("ApiPresetsController успешно инициализирован.")

        self.audio_controller = AudioController(self)
        logger.notify("AudioController успешно инициализирован.")

        self.voice_model_controller = VoiceModelController(config_dir="Settings")
        logger.notify("VoiceModelController (backend) успешно инициализирован.")

        self.character_controller = CharacterController(self.settings)
        logger.notify("CharacterController успешно инициализирован.")
        
        self.model_controller = ModelController(self.settings)
        logger.notify("ModelController успешно инициализирован.")

        self.capture_controller = CaptureController(self.settings)
        logger.notify("CaptureController успешно инициализирован.")

        self.speech_controller = SpeechController()
        logger.notify("SpeechController успешно инициализирован.")

        self._init_server_controller()
        
        self.chat_controller = ChatController(self.settings)
        logger.notify("ChatController успешно инициализирован.")

        

        self.audio_controller.delete_all_sound_files()

        
        self._subscribe_to_events()
        logger.notify("MainController подписался на события")

    def _init_server_controller(self):
        """Инициализация правильного ServerController на основе настроек"""
        use_new_api = self.settings.get('USE_NEW_API', False)
        
        # Проверяем, нужно ли переключение
        if hasattr(self, 'server_controller') and self.server_controller:
            # Определяем текущий тип контроллера
            
            current_is_new = isinstance(self.server_controller, ServerController)
            
            # Если тип соответствует настройке, ничего не делаем
            if (use_new_api and current_is_new) or (not use_new_api and not current_is_new):
                return
                
            # Иначе уничтожаем старый контроллер
            self.server_controller.destroy()
            self.server_controller = None
            
        # Создаем новый контроллер
        if use_new_api:
            self.server_controller = ServerController()
            logger.notify("ServerController (новый API) успешно инициализирован.")
        else:
            self.server_controller = ServerControllerOld()
            logger.notify("ServerController (старый API) успешно инициализирован.")
        

    def update_view(self, view):
        if not self.gui_controller:
            self.view = view
            self.gui_controller = GuiController(self, view)
            logger.notify("GuiController успешно инициализирован.")
            self.settings_controller.load_api_settings(False)
            
            # в этой логике надо добавить автоподключение.
            if self.settings.get('VOICEOVER_METHOD') == 'TG' and self.settings.get('USE_VOICEOVER', False):
                self.telegram_controller.start_silero_async()
    
    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Model.SCHEDULE_G4F_UPDATE, self._on_schedule_g4f_update, weak=False)
        
        self.event_bus.subscribe(Events.Telegram.REQUEST_TG_CODE, self._on_request_tg_code, weak=False)
        self.event_bus.subscribe(Events.Telegram.REQUEST_TG_PASSWORD, self._on_request_tg_password, weak=False)
        
        self.event_bus.subscribe(Events.GUI.SHOW_LOADING_POPUP, self._on_show_loading_popup, weak=False)
        self.event_bus.subscribe(Events.GUI.CLOSE_LOADING_POPUP, self._on_close_loading_popup, weak=False)

        self.event_bus.subscribe(Events.Server.SET_DIALOG_ACTIVE, self._on_set_dialog_active, weak=False)
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)

    def _on_setting_changed(self, event: Event):
        key = event.data.get('key')
        
        if key == 'USE_NEW_API':
            logger.info("Обнаружено изменение настройки API, переинициализация ServerController...")
            self._init_server_controller()

    def close_app(self):
        logger.info("Начинаем закрытие приложения...")

        # 1) Остановить ASR и дождаться
        self.event_bus.emit(Events.Speech.STOP_SPEECH_RECOGNITION)
        start = time.time()
        try:
            while True:
                mic_status = self.event_bus.emit_and_wait(Events.Speech.GET_MIC_STATUS, timeout=0.5)
                active = bool(mic_status and mic_status[0])
                if not active:
                    break
                if time.time() - start > 1.5:  # до ~1.5 сек
                    break
                time.sleep(0.1)
        except Exception:
            pass

        # 2) Остановить сервер
        try:
            self.event_bus.emit(Events.Server.STOP_SERVER)
        except Exception as e:
            logger.error(f"Ошибка при остановке сервера: {e}", exc_info=True)

        # 3) Остановить захваты
        self.capture_controller.stop_screen_capture_thread()
        self.capture_controller.stop_camera_capture_thread()

        # 4) Удалить аудиофайлы
        self.audio_controller.delete_all_sound_files()

        # 5) Остановить общий event loop
        self.loop_controller.stop_loop()

        # 6) Остановить EventBus (ThreadPoolExecutor и обработчик очереди)
        try:
            shutdown_event_bus()
        except Exception as e:
            logger.error(f"Ошибка при остановке EventBus: {e}", exc_info=True)

        logger.info("Закрываемся")

        logger.info("Закрываемся")

    def _check_and_perform_pending_update(self):
        if not self.pip_installer:
            logger.warning("PipInstaller не инициализирован, проверка отложенного обновления пропущена.")
            return

        update_pending = self.settings.get("G4F_UPDATE_PENDING", False)
        target_version = self.settings.get("G4F_TARGET_VERSION", None)

        if update_pending and target_version:
            logger.info(f"Обнаружено запланированное обновление g4f до версии: {target_version}")
            package_spec = f"g4f=={target_version}" if target_version != "latest" else "g4f"
            description = f"Запланированное обновление g4f до {target_version}..."

            success = False
            try:
                success = self.pip_installer.install_package(
                    package_spec,
                    description=description,
                    extra_args=["--force-reinstall", "--upgrade"]
                )
                if success:
                    logger.success(f"Запланированное обновление g4f до {target_version} успешно завершено.")
                    try:
                        import importlib
                        importlib.invalidate_caches()
                        logger.info("Кэш импорта очищен после запланированного обновления.")
                    except Exception as e_invalidate:
                        logger.error(f"Ошибка при очистке кэша импорта после обновления: {e_invalidate}")
                else:
                    logger.error(f"Запланированное обновление g4f до {target_version} не удалось (ошибка pip).")
            except Exception as e_install:
                logger.error(f"Исключение во время запланированного обновления g4f: {e_install}", exc_info=True)
                success = False

            finally:
                logger.info("Сброс флагов запланированного обновления g4f.")
                self.settings.set("G4F_UPDATE_PENDING", False)
                self.settings.set("G4F_TARGET_VERSION", None)
                self.settings.save_settings()
        else:
            logger.info("Нет запланированных обновлений g4f.")
    
    
    
    def _on_schedule_g4f_update(self, event: Event):
        version = event.data.get('version', 'latest')
        
        try:
            self.settings.set("G4F_TARGET_VERSION", version)
            self.settings.set("G4F_UPDATE_PENDING", True)
            self.settings.set("G4F_VERSION", version)
            self.settings.save_settings()
            logger.info(f"Обновление g4f до версии '{version}' запланировано на следующий запуск.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при сохранении настроек для запланированного обновления: {e}", exc_info=True)
            return False
    
    def _on_request_tg_code(self, event: Event):
        code_future = event.data.get('future')
        if code_future:
            self.event_bus.emit("show_tg_code_dialog", {'future': code_future})
    
    def _on_request_tg_password(self, event: Event):
        password_future = event.data.get('future')
        if password_future:
            self.event_bus.emit("show_tg_password_dialog", {'future': password_future})
    
    def _on_show_loading_popup(self, event: Event):
        message = event.data.get('message', 'Loading...')
        self.event_bus.emit("display_loading_popup", {"message": message})
    
    def _on_close_loading_popup(self, event: Event):
        self.event_bus.emit("hide_loading_popup")

    def _on_set_dialog_active(self, event: Event):
        self.dialog_active = event.data.get('active', False)
    