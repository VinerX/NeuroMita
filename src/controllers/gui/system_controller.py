from pathlib import Path
from PyQt6.QtCore import QTimer
from main_logger import logger
from core.events import Events, Event
from core.task_supervisor import task_supervisor
from .base_controller import BaseController

class SystemController(BaseController):
    def __init__(self, main_controller, view):
        super().__init__(main_controller, view)
        self.ffmpeg_install_popup = None
        
    def subscribe_to_events(self):
        self.event_bus.subscribe(Events.GUI.UPDATE_DEBUG_INFO, self._on_update_debug_info, weak=False)
        self.event_bus.subscribe(Events.GUI.CHECK_AND_INSTALL_FFMPEG, self._on_check_and_install_ffmpeg, weak=False)
        
    def update_debug(self):
        logger.debug("SystemController: update_debug")
        if self.view:
            self.view.update_debug_signal.emit()
        else:
            logger.error("SystemController: view не найден!")
            
    def check_and_install_ffmpeg(self):
        logger.info("SystemController: check_and_install_ffmpeg")
        QTimer.singleShot(100, self._check_and_install_ffmpeg_impl)
        
    def _check_and_install_ffmpeg_impl(self):
        ffmpeg_path = Path(".") / "ffmpeg.exe"
        logger.info(f"Checking for FFmpeg at: {ffmpeg_path}")

        if not ffmpeg_path.exists():
            logger.info("FFmpeg not found. Starting installation process in a separate thread.")
            task_supervisor().start_thread(
                self,
                "ffmpeg-install",
                self._ffmpeg_install_thread_target,
                replace=True,
            )
        else:
            logger.info("FFmpeg found. No installation needed.")
            
    def _ffmpeg_install_thread_target(self):
        # Окно «Идёт установка FFmpeg» временно отключено по просьбе —
        # установка идёт тихо в фоне. Возврат окна: раскомментировать показ/закрытие.
        # if self.view:
        #     QTimer.singleShot(0, self.view._show_ffmpeg_installing_popup)

        logger.info("Starting FFmpeg installation attempt...")
        from utils.ffmpeg_installer import install_ffmpeg

        success = install_ffmpeg()
        logger.info(f"FFmpeg installation attempt finished. Success: {success}")

        # if self.view:
        #     QTimer.singleShot(0, self.view._close_ffmpeg_installing_popup)

        if not success and self.view:
            self._ui(self.view._show_ffmpeg_error_popup)
            
    def _on_update_debug_info(self, event: Event):
        logger.debug("SystemController: получено событие UPDATE_DEBUG_INFO")
        self.update_debug()
        
    def _on_check_and_install_ffmpeg(self, event: Event):
        logger.debug("SystemController: получено событие CHECK_AND_INSTALL_FFMPEG")
        self.check_and_install_ffmpeg()
        
    def _on_get_gui_window_id(self, event: Event):
        if self.view and hasattr(self.view, 'winId'):
            return int(self.view.winId())
        return None