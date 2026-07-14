import threading
from core.task_supervisor import task_supervisor
import time
from main_logger import logger

# Функция для перевода
def getTranslationVariant(ru_str, en_str=""):
    from managers.settings_manager import SettingsManager
    lang = SettingsManager.get("LANGUAGE", "RU")
    if en_str and lang == "EN":
        return en_str
    return ru_str

_ = getTranslationVariant

class CameraCapture:
    def __init__(self):
        self._running = False
        self._thread = None
        self._latest_frame = None
        self._frame_history = []
        self._max_history_frames = 3
        self._max_transfer_frames = 1
        self._quality = 25  # Default quality
        self._fps = 1  # Default FPS
        self._camera_index = 0  # Default camera index
        self._capture_width = 640  # Default width
        self._capture_height = 480  # Default height
        self._lock = threading.Lock()
        self._error_count = 0
        self._max_errors = 5
        self._video_capture = None
        self._cv2_checked = False  # Флаг для проверки установки cv2
        

    def _ensure_cv2_installed(self):
        """Require the managed OpenCV component without mutating Lib/core."""
        if self._cv2_checked:
            return
        try:
            __import__("cv2")
        except ImportError as exc:
            raise RuntimeError(
                _(
                    "OpenCV не установлен. Установите его в AI Hub → Зависимости → OpenCV.",
                    "OpenCV is not installed. Install it from AI Hub → Dependencies → OpenCV.",
                )
            ) from exc
        self._cv2_checked = True

    def start_capture(self, camera_index: int = 0, quality: int = 25, fps: int = 1, max_history_frames: int = 1, max_transfer_frames: int = 3, capture_width: int = 640, capture_height: int = 480):
        # Проверка и установка cv2 перед запуском захвата
        try:
            self._ensure_cv2_installed()
        except RuntimeError as e:
            logger.error(f"Невозможно запустить захват с камеры: {e}")
            return
            
        if self._running:
            logger.warning("Camera capture already running.")
            return

        self._camera_index = camera_index
        self._quality = max(1, min(quality, 100))
        self._fps = max(1, fps)
        self._max_history_frames = max(1, max_history_frames)
        self._max_transfer_frames = max(1, max_transfer_frames)
        self._capture_width = max(1, capture_width)
        self._capture_height = max(1, capture_height)

        self._running = True
        self._thread = task_supervisor().start_thread(
            self, "camera-capture", self._capture_loop, replace=True
        )
        logger.info(f"Camera capture started with camera {self._camera_index}, quality {self._quality}, {self._fps} FPS, resolution {self._capture_width}x{self._capture_height}.")

    def stop_capture(self):
        if not self._running:
            logger.warning("Camera capture not running.")
            return

        self._running = False
        if self._thread:
            self._thread.join()
        if self._video_capture and self._video_capture.isOpened():
            self._video_capture.release()
        logger.info("Camera capture stopped.")

    def _capture_loop(self):
        # Импортируем cv2 локально в потоке
        import cv2
        
        logger.info("Start capture _capture_loop.")
        try:
            self._video_capture = cv2.VideoCapture(self._camera_index)
            if not self._video_capture.isOpened():
                logger.error(f"Error: Could not open camera {self._camera_index}")
                self._running = False
                return
           #self._video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._capture_width)
           #self._video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._capture_height)
           #self._video_capture.set(cv2.CAP_PROP_FPS, self._fps)
           # self._video_capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            ret, _ = self._video_capture.read()
            if not ret:
                logger.error(f"Error: Could not read first frame from camera {self._camera_index}")
                self._running = False
                return

            while self._running:
                try:
                    with self._lock:
                        self._error_count = 0
                        #logger.info("loop before read")
                        ret, frame = self._video_capture.read()
                        if not ret:
                            logger.error("Error: Could not read frame")
                            self._error_count += 1
                            if self._error_count >= self._max_errors:
                                logger.critical("Maximum error count reached. Stopping camera capture.")
                                self._running = False
                            continue

                        # Convert the frame to JPEG
                        ret, jpeg_frame = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self._quality])
                        if not ret:
                            logger.error("Error: Could not encode frame to JPEG")
                            self._error_count += 1
                            if self._error_count >= self._max_errors:
                                logger.critical("Maximum error count reached. Stopping camera capture.")
                                self._running = False
                            continue

                        current_frame_bytes = jpeg_frame.tobytes()

                        self._frame_history.append(current_frame_bytes)
                        if len(self._frame_history) > self._max_history_frames:
                            self._frame_history.pop(0)
                        self._latest_frame = current_frame_bytes

                except Exception as e:
                    with self._lock:
                        self._error_count += 1
                        logger.error(f"Error during camera capture (attempt {self._error_count}/{self._max_errors}): {e}", exc_info=True)
                        if self._error_count >= self._max_errors:
                            logger.critical("Maximum error count reached. Stopping camera capture.")
                            self._running = False

                time.sleep(1 / self._fps)

        finally:
            with self._lock:
                if self._video_capture and self._video_capture.isOpened():
                    self._video_capture.release()
                    logger.info("Camera capture released.")

    def get_latest_frame(self) -> bytes | None:
        with self._lock:
            if self._frame_history:
                return self._frame_history[-1]
            return None

    def get_recent_frames(self, limit: int) -> list[bytes]:
        with self._lock:
            actual_limit = min(limit, self._max_transfer_frames)
            return self._frame_history[max(0, len(self._frame_history) - actual_limit):]

    def is_running(self) -> bool:
        with self._lock:
            return self._running