import time
import threading
from win32 import win32gui
from handlers.screen_handler import ScreenCapture
from main_logger import logger
from core.events import get_event_bus, Events, Event


class CaptureController:
    def __init__(self, settings):
        logger.info("CaptureController инициализируется")
        self.settings = settings

        self.event_bus = get_event_bus()
        self.screen_capture_instance = ScreenCapture()
        self.screen_capture_thread = None
        self.screen_capture_running = False
        self.screen_capture_active = False
        self.camera_capture_active = False
        self.last_captured_frame = None
        self.camera_capture = None
        
        self.image_request_thread = None
        self.image_request_running = False
        self.last_image_request_time = time.time()
        self.image_request_timer_running = False
        
        self._subscribe_to_events()
        
        self._start_periodic_check()
        
    def _subscribe_to_events(self):
        self.event_bus.subscribe("capture_settings_loaded", self._on_capture_settings_loaded, weak=False)
        self.event_bus.subscribe("start_screen_capture", self._on_start_screen_capture, weak=False)
        self.event_bus.subscribe("stop_screen_capture", self._on_stop_screen_capture, weak=False)
        self.event_bus.subscribe("start_camera_capture", self._on_start_camera_capture, weak=False)
        self.event_bus.subscribe("stop_camera_capture", self._on_stop_camera_capture, weak=False)
        self.event_bus.subscribe("start_image_request_timer", self._on_start_image_request_timer, weak=False)
        self.event_bus.subscribe("stop_image_request_timer", self._on_stop_image_request_timer, weak=False)
        self.event_bus.subscribe("update_screen_capture_exclusion", self._on_update_screen_capture_exclusion, weak=False)
        self.event_bus.subscribe("check_image_request_timer_running", self._on_check_image_request_timer_running, weak=False)
        self.event_bus.subscribe("trigger_send_interval_image", self._on_trigger_send_interval_image, weak=False)
        self.event_bus.subscribe(Events.Capture.GET_SCREEN_CAPTURE_STATUS, self._on_get_screen_capture_status, weak=False)
        self.event_bus.subscribe(Events.Capture.GET_CAMERA_CAPTURE_STATUS, self._on_get_camera_capture_status, weak=False)
        self.event_bus.subscribe(Events.Capture.UPDATE_LAST_IMAGE_REQUEST_TIME, self._on_update_last_image_request_time, weak=False)
        self.event_bus.subscribe(Events.Capture.CAPTURE_SCREEN, self._on_capture_screen, weak=False)
        self.event_bus.subscribe(Events.Capture.GET_CAMERA_FRAMES, self._on_get_camera_frames, weak=False)
        self.event_bus.subscribe(Events.Capture.STOP_SCREEN_CAPTURE, self._on_stop_screen_capture, weak=False)
        self.event_bus.subscribe(Events.Capture.STOP_CAMERA_CAPTURE, self._on_stop_camera_capture, weak=False)
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)

    def _on_capture_settings_loaded(self, event: Event):
        if self.settings:
            if self.settings.get("ENABLE_IMAGE_ANALYSIS", False):
                if self.settings.get("ENABLE_SCREEN_ANALYSIS", False):
                    logger.info("Настройка 'ENABLE_SCREEN_ANALYSIS' включена. Автоматический запуск захвата экрана.")
                    self.start_screen_capture_thread()

                if self.settings.get("ENABLE_CAMERA_CAPTURE", False):
                    logger.info("Настройка 'ENABLE_CAMERA_CAPTURE' включена. Автоматический запуск захвата с камеры.")
                    self.start_camera_capture_thread()
                
    def _on_start_screen_capture(self, event: Event):
        logger.info("Получено событие start_screen_capture")
        self.start_screen_capture_thread()
        
    def _on_stop_screen_capture(self, event: Event):
        logger.info("Получено событие stop_screen_capture")
        self.stop_screen_capture_thread()
        
    def _on_start_camera_capture(self, event: Event):
        self.start_camera_capture_thread()
        
    def _on_stop_camera_capture(self, event: Event):
        self.stop_camera_capture_thread()
        
    def _on_start_image_request_timer(self, event: Event):
        self.start_image_request_timer()
        
    def _on_stop_image_request_timer(self, event: Event):
        self.stop_image_request_timer()
        
    def _on_update_screen_capture_exclusion(self, event: Event):
        hwnd_to_pass = event.data.get('hwnd')
        exclude_title = event.data.get('exclude_title', '')
        exclude_enabled = event.data.get('exclude_enabled', False)
        
        if self.screen_capture_instance:
            self.screen_capture_instance.set_exclusion_parameters(hwnd_to_pass, exclude_title, exclude_enabled)
            
            if self.screen_capture_instance.is_running():
                self.stop_screen_capture_thread()
                self.start_screen_capture_thread()
                
    def _on_check_image_request_timer_running(self, event: Event):
        return self.image_request_timer_running

    def _on_trigger_send_interval_image(self, event: Event):
        self.send_interval_image()

    def _on_update_last_image_request_time(self, event: Event):
        self.last_image_request_time = time.time()
        logger.debug(f"Обновлено время последнего запроса изображения: {self.last_image_request_time}")

    def _on_get_screen_capture_status(self, event: Event):
        return self.screen_capture_active
    
    def _on_get_camera_capture_status(self, event: Event):
        return self.camera_capture_active
    
    def _on_capture_screen(self, event: Event):
        history_limit = event.data.get('limit', 1) if event.data else 1
        
        if self.screen_capture_instance:
            frames = self.screen_capture_instance.get_recent_frames(history_limit)
            if frames:
                return frames

        if not self.settings.get("ENABLE_IMAGE_ANALYSIS", False):
            return []

        quality = int(self.settings.get("SCREEN_CAPTURE_QUALITY", 25))
        width = int(self.settings.get("SCREEN_CAPTURE_WIDTH", 1024))
        height = int(self.settings.get("SCREEN_CAPTURE_HEIGHT", 768))
        frame = self.screen_capture_instance.capture_one_shot(quality, width, height)
        return [frame] if frame else []
    
    def _on_get_camera_frames(self, event: Event):
        history_limit = event.data.get('limit', 1) if event.data else 1
        
        if (self.camera_capture is not None and 
            self.camera_capture.is_running()):
            frames = self.camera_capture.get_recent_frames(history_limit)
            return frames
        return []
            
    def _on_setting_changed(self, event: Event):
        key = event.data.get('key')
        value = event.data.get('value')
        
        if key == "ENABLE_IMAGE_ANALYSIS":
            if bool(value):
                pass
            else:
                self.stop_screen_capture_thread()
                self.stop_camera_capture_thread()
                self.stop_image_request_timer()
        elif key == "ENABLE_SCREEN_ANALYSIS":
            if bool(value):
                self.start_screen_capture_thread()
            else:
                self.stop_screen_capture_thread()
        elif key in ["SCREEN_CAPTURE_INTERVAL", "SCREEN_CAPTURE_QUALITY", "SCREEN_CAPTURE_FPS",
                    "SCREEN_CAPTURE_HISTORY_LIMIT", "SCREEN_CAPTURE_TRANSFER_LIMIT", 
                    "SCREEN_CAPTURE_WIDTH", "SCREEN_CAPTURE_HEIGHT"]:
            logger.info(f"Настройка захвата экрана '{key}' изменена на '{value}'. Перезапускаю поток захвата.")
            self.stop_screen_capture_thread()
            self.start_screen_capture_thread()
        elif key == "ENABLE_CAMERA_CAPTURE":
            if bool(value):
                self.start_camera_capture_thread()
            else:
                self.stop_camera_capture_thread()
        elif key in ["EXCLUDE_GUI_WINDOW", "EXCLUDE_WINDOW_TITLE"]:
            exclude_gui = self.settings.get("EXCLUDE_GUI_WINDOW", False)
            exclude_title = self.settings.get("EXCLUDE_WINDOW_TITLE", "")

            hwnd_to_pass = None
            if exclude_gui:
                hwnd_to_pass = self.event_bus.emit_and_wait(Events.GUI.GET_GUI_WINDOW_ID, timeout=0.5)
                hwnd_to_pass = hwnd_to_pass[0] if hwnd_to_pass else None
                logger.info(f"Получен HWND окна GUI для исключения: {hwnd_to_pass}")
            elif exclude_title:
                try:
                    from win32 import win32gui
                    hwnd_to_pass = win32gui.FindWindow(None, exclude_title)
                    if hwnd_to_pass:
                        logger.info(f"Найден HWND для заголовка '{exclude_title}': {hwnd_to_pass}")
                    else:
                        logger.warning(f"Окно с заголовком '{exclude_title}' не найдено.")
                except Exception as e:
                    logger.error(f"Ошибка при поиске окна по заголовку '{exclude_title}': {e}")

            self.event_bus.emit("update_screen_capture_exclusion", {
                'hwnd': hwnd_to_pass,
                'exclude_title': exclude_title,
                'exclude_enabled': exclude_gui or bool(exclude_title)
            })
        elif key == "SEND_IMAGE_REQUESTS":
            if bool(value):
                self.start_image_request_timer()
            else:
                self.stop_image_request_timer()
        elif key == "IMAGE_REQUEST_INTERVAL":
            self.stop_image_request_timer()
            self.start_image_request_timer()

        if key in ["MIC_ACTIVE", "ENABLE_IMAGE_ANALYSIS", "ENABLE_SCREEN_ANALYSIS", "AUTO_ATTACH_IMAGES", "ENABLE_CAMERA_CAPTURE"]:
            self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
    
    def start_screen_capture_thread(self):
        if not self.settings:
            logger.error("Settings не доступны в CaptureController")
            return

        if not self.settings.get("ENABLE_IMAGE_ANALYSIS", False):
            logger.info("ENABLE_IMAGE_ANALYSIS отключен — захват экрана не запускается.")
            return

        if not self.screen_capture_running:
                
            interval = float(self.settings.get("SCREEN_CAPTURE_INTERVAL", 5.0))
            quality = int(self.settings.get("SCREEN_CAPTURE_QUALITY", 25))
            fps = int(self.settings.get("SCREEN_CAPTURE_FPS", 1))
            max_history_frames = int(self.settings.get("SCREEN_CAPTURE_HISTORY_LIMIT", 3))
            max_frames_per_request = int(self.settings.get("SCREEN_CAPTURE_TRANSFER_LIMIT", 1))
            capture_width = int(self.settings.get("SCREEN_CAPTURE_WIDTH", 1024))
            capture_height = int(self.settings.get("SCREEN_CAPTURE_HEIGHT", 768))
            
            logger.info(f"Запуск захвата экрана с параметрами: interval={interval}, quality={quality}, fps={fps}")
            
            self.screen_capture_instance.start_capture(interval, quality, fps, max_history_frames,
                                                       max_frames_per_request, capture_width,
                                                       capture_height)
            self.screen_capture_running = True
            logger.info(f"Поток захвата экрана запущен")
            
            self.screen_capture_active = True
            if self.settings.get("SEND_IMAGE_REQUESTS", 1):
                self.start_image_request_timer()
            self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
            
    def stop_screen_capture_thread(self):
        if self.screen_capture_running:
            self.screen_capture_instance.stop_capture()
            self.screen_capture_running = False
            logger.info("Поток захвата экрана остановлен.")
        self.screen_capture_active = False
        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
        
    def start_camera_capture_thread(self):
        if not self.settings:
            logger.error("Settings не доступны в CaptureController")
            return

        if not self.settings.get("ENABLE_IMAGE_ANALYSIS", False):
            logger.info("ENABLE_IMAGE_ANALYSIS отключен — захват с камеры не запускается.")
            return
            
        if not hasattr(self, 'camera_capture') or self.camera_capture is None:
            from handlers.camera_handler import CameraCapture
            self.camera_capture = CameraCapture()

        if self.camera_capture and not self.camera_capture.is_running():
            camera_index = int(self.settings.get("CAMERA_INDEX", 0))
            interval = float(self.settings.get("CAMERA_CAPTURE_INTERVAL", 5.0))
            quality = int(self.settings.get("CAMERA_CAPTURE_QUALITY", 25))
            fps = int(self.settings.get("CAMERA_CAPTURE_FPS", 1))
            max_history_frames = int(self.settings.get("CAMERA_CAPTURE_HISTORY_LIMIT", 3))
            max_frames_per_request = int(self.settings.get("CAMERA_CAPTURE_TRANSFER_LIMIT", 1))
            capture_width = int(self.settings.get("CAMERA_CAPTURE_WIDTH", 640))
            capture_height = int(self.settings.get("CAMERA_CAPTURE_HEIGHT", 480))
            self.camera_capture.start_capture(camera_index, quality, fps, max_history_frames,
                                              max_frames_per_request, capture_width,
                                              capture_height)
            logger.info(f"Поток захвата с камеры запущен с индексом {camera_index}")
            self.camera_capture_active = True
            self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
            
    def stop_camera_capture_thread(self):
        if hasattr(self, 'camera_capture') and self.camera_capture is not None and self.camera_capture.is_running():
            self.camera_capture.stop_capture()
            logger.info("Поток захвата с камеры остановлен.")
        self.camera_capture_active = False
        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
        
    def start_image_request_timer(self):
        if not self.image_request_timer_running:
            self.image_request_timer_running = True
            self.last_image_request_time = time.time()
            logger.info("Таймер периодической отправки изображений запущен.")

    def stop_image_request_timer(self):
        if self.image_request_timer_running:
            self.image_request_timer_running = False
            logger.info("Таймер периодической отправки изображений остановлен.")
            
    def _start_periodic_check(self):
        def check_loop():
            while True:
                try:
                    if self.image_request_timer_running:
                        self.send_interval_image()
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"Ошибка в периодической проверке отправки изображений: {e}")
                    time.sleep(5)
        
        thread = threading.Thread(target=check_loop, daemon=True)
        thread.start()
        logger.info("Поток периодической проверки отправки изображений запущен")
            
    def send_interval_image(self):
        if not self.settings:
            return
            
        current_time = time.time()
        interval = float(self.settings.get("IMAGE_REQUEST_INTERVAL", 20.0))
        delta = current_time - self.last_image_request_time
        
        if delta >= interval:
            if not self.settings.get("ENABLE_IMAGE_ANALYSIS", True):
                self.last_image_request_time = current_time
                return

            image_data = []
            if self.settings.get("ENABLE_SCREEN_ANALYSIS", False):
                logger.info(f"Отправка периодического запроса с изображением ({current_time - self.last_image_request_time:.2f}/{interval:.2f} сек).")
                history_limit = int(self.settings.get("SCREEN_CAPTURE_HISTORY_LIMIT", 1))
                frames = self.screen_capture_instance.get_recent_frames(history_limit)
                if frames:
                    image_data.extend(frames)
                    logger.info(f"Захвачено {len(frames)} кадров для периодической отправки.")
                else:
                    logger.info("Анализ экрана включен, но кадры не готовы или история пуста для периодической отправки.")

                if image_data:
                    self.event_bus.emit("send_periodic_image_request", {
                        'user_input': "",
                        'system_input': "",
                        'image_data': image_data
                    })
                    self.last_image_request_time = current_time
                else:
                    logger.warning("Нет изображений для периодической отправки.")