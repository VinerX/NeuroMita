import mss
import mss.tools
import numpy as np
import time
import threading
from Logger import logger
import win32gui
import win32con

class ScreenCapture:
    def __init__(self):
        self._running = False
        self._thread = None
        self._latest_frame = None # Оставляем для совместимости, но будем использовать _frame_history
        self._frame_history = [] # Список для хранения последних кадров
        self._max_history_frames = 1 # Максимальное количество кадров в истории
        self._max_transfer_frames = 3 # Максимальное количество кадров для передачи за запрос
        self._quality = 25  # По умолчанию 25%
        self._fps = 1  # По умолчанию 1 кадр в секунду
        self._interval_seconds = 1.0  # По умолчанию 1 кадр в секунду
        self._sct = None  # Инициализируем здесь как None, чтобы создавать в потоке
        self._pil_checked = False # Флаг, чтобы не проверять установку PIL каждый раз
        self._lock = threading.Lock() # Мьютекс для потокобезопасного доступа к данным
        self._error_count = 0 # Счетчик ошибок
        self._max_errors = 5 # Максимальное количество ошибок перед остановкой
        self.hwnd_to_exclude = None # HWND окна, которое нужно исключить из захвата
        self.window_title_to_exclude = None # Заголовок окна, которое нужно исключить
        self.exclude_gui_window = False # Флаг для исключения окна GUI
    def _ensure_pil_installed(self):
        """Проверяет наличие Pillow и устанавливает при необходимости."""
        if self._pil_checked:
            return
        
        try:
            # Пробуем импортировать, чтобы проверить наличие
            __import__('PIL.Image')
            logger.debug("Библиотека Pillow (PIL) уже установлена.")
        except ImportError:
            logger.warning("Библиотека Pillow (PIL) не найдена. Попытка автоматической установки...")
            import subprocess
            import sys
            try:
                # Выполняем установку через pip, используя текущий интерпретатор Python
                subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
                logger.info("Библиотека Pillow успешно установлена.")
                # После установки нужно обновить пути импорта
                import importlib
                importlib.invalidate_caches()
            except (subprocess.CalledProcessError, ImportError) as e:
                logger.error(f"Не удалось установить или импортировать Pillow: {e}")
                logger.error("Пожалуйста, установите библиотеку вручную: pip install Pillow")
                raise RuntimeError("Необходимая библиотека Pillow не может быть установлена.") from e
        
        self._pil_checked = True


    def start_capture(self, interval_seconds: float = 1.0, quality: int = 25, fps: int = 1, max_history_frames: int = 1, max_transfer_frames: int = 1, capture_width: int = 1024, capture_height: int = 768):
        # --- НАЧАЛО ИЗМЕНЕНИЙ: ДИНАМИЧЕСКАЯ ПОДГРУЗКА ПАКЕТА ---
        try:
            self._ensure_pil_installed()
        except RuntimeError as e:
            logger.error(f"Невозможно запустить захват экрана: {e}")
            return
        # --- КОНЕЦ ИЗМЕНЕНИЙ ---

        if self._running:
            logger.warning("Захват экрана уже запущен.")
            return

        self._quality = max(1, min(quality, 100))  # Ограничение качества от 1 до 100
        self._fps = max(1, fps)  # Минимальный FPS = 1
        #self._interval_seconds = 1.0 / self._fps
        self._interval_seconds = max(0.5, interval_seconds)  # Минимальный интервал 0.1 секунды
        self._max_history_frames = max(1, max_history_frames) # Минимум 1 кадр в истории
        self._max_transfer_frames = max(1, max_transfer_frames) # Минимум 1 кадр для передачи
        self._capture_width = max(1, capture_width) # Минимальная ширина 1
        self._capture_height = max(1, capture_height) # Минимальная высота 1

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info(f"Захват экрана запущен с качеством {self._quality}, {self._fps} FPS (интервал {self._interval_seconds} секунд), разрешением {self._capture_width}x{self._capture_height}.")

    def stop_capture(self):
        if not self._running:
            logger.warning("Захват экрана не запущен.")
            return

        self._running = False
        if self._thread:
            self._thread.join()  # Ждем завершения потока
        logger.info("Захват экрана остановлен.")

    def _capture_loop(self):
        from PIL import Image  # Импортируем Image здесь
        from io import BytesIO  # Импортируем BytesIO здесь

        # Инициализируем mss.mss() внутри потока
        with mss.mss() as sct:
            while self._running:
                try:
                    with self._lock:  # Блокировка для сброса счетчика ошибок
                        self._error_count = 0

                    # --- Определение монитора для захвата ---
                    if not sct.monitors:
                        logger.error("mss: Мониторы не найдены. Пропуск захвата.")
                        time.sleep(self._interval_seconds * 2)  # Ожидание
                        continue

                    # sct.monitors[0] - это bounding box всех мониторов.
                    # sct.monitors[1] - это основной (primary) монитор.
                    # Если нужен именно основной монитор:
                    if len(sct.monitors) > 1:
                        monitor_to_capture = sct.monitors[1]
                    else:
                        # Если sct.monitors содержит только один элемент, это sct.monitors[0] (все экраны).
                        # Используем его, если основного нет (например, система с одним монитором, где mss не создает отдельный sct.monitors[1])
                        # или если такова была исходная задумка (захватить всё, если основной не выделен).
                        monitor_to_capture = sct.monitors[0]
                        logger.debug(
                            f"mss: Захватывается sct.monitors[0], т.к. len(sct.monitors) <= 1. Детали: {monitor_to_capture}")
                    # -----------------------------------------

                    #logger.info("before grab")
                    sct_img = sct.grab(monitor_to_capture)
                    #logger.info("After grab")

                    img = Image.frombytes("RGB", (sct_img.width, sct_img.height),
                                          sct_img.rgb)  # Используем sct_img.width, sct_img.height

                    # Если включено исключение окна GUI
                    if self.exclude_gui_window and self.hwnd_to_exclude:
                        try:

                            #TODO не делатьчерный экран если нет на экране
                            #win32gui.IsWindowVisible(self.hwnd_to_exclude) and win32gui.GetForegroundWindow() == self.hwnd_to_exclude:

                            # Получаем координаты окна по его HWND
                            left, top, right, bottom = win32gui.GetWindowRect(self.hwnd_to_exclude)
                            # Определяем размеры окна
                            width = right - left
                            height = bottom - top

                            # Создаем черное изображение размером с окно
                            # Используем 'RGB' режим для совместимости с основным изображением
                            black_patch = Image.new('RGB', (width, height), (0, 0, 0))

                            # Вставляем черное изображение на захваченный кадр
                            # Координаты вставки должны быть относительно верхнего левого угла захваченного монитора
                            # monitor_to_capture['left'] и monitor_to_capture['top'] - это смещение монитора
                            # относительно виртуального экрана (всех мониторов).
                            # Поэтому нужно вычесть их из абсолютных координат окна.
                            paste_x = left - monitor_to_capture['left']
                            paste_y = top - monitor_to_capture['top']

                            # Убедимся, что координаты вставки находятся в пределах изображения
                            if 0 <= paste_x < img.width and 0 <= paste_y < img.height:
                                img.paste(black_patch, (paste_x, paste_y))
                                logger.debug(f"Окно GUI (HWND: {self.hwnd_to_exclude}) исключено из захвата.")
                            else:
                                logger.warning(f"Координаты окна GUI ({left},{top},{right},{bottom}) вне захваченной области монитора ({monitor_to_capture}). Исключение не применено.")
                        except Exception as e:
                            logger.error(f"Ошибка при исключении окна GUI из захвата: {e}", exc_info=True)
                    elif self.exclude_gui_window and not self.hwnd_to_exclude:
                        logger.warning("exclude_gui_window включен, но HWND окна GUI не установлен.")


                    max_size = (self._capture_width, self._capture_height)
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)

                    byte_arr = BytesIO()
                    img.save(byte_arr, format='JPEG', quality=self._quality)
                    current_frame_bytes = byte_arr.getvalue()

                    with self._lock:  # Блокировка для обновления истории кадров
                        self._frame_history.append(current_frame_bytes)
                        if len(self._frame_history) > self._max_history_frames:
                            self._frame_history.pop(0)
                        self._latest_frame = current_frame_bytes

                except Exception as e:
                    with self._lock:  # Блокировка для обновления счетчика ошибок
                        self._error_count += 1
                        logger.error(f"Ошибка при захвате экрана (попытка {self._error_count}/{self._max_errors}): {e}",
                                     exc_info=True)
                        if self._error_count >= self._max_errors:
                            logger.critical(
                                f"Достигнуто максимальное количество ошибок ({self._max_errors}). Остановка захвата экрана.")
                            self._running = False

                time.sleep(self._interval_seconds)

    def get_latest_frame(self) -> bytes | None:
        """Возвращает последний захваченный кадр в формате JPEG байтов (для совместимости)."""
        with self._lock:
            if self._frame_history:
                return self._frame_history[-1]
            return None

    def get_recent_frames(self, limit: int) -> list[bytes]:
        """Возвращает список последних захваченных кадров в формате JPEG байтов."""
        with self._lock:
            # Ограничиваем запрошенный лимит максимальным лимитом передачи
            actual_limit = min(limit, self._max_transfer_frames)
            # Возвращаем не более actual_limit кадров из истории, начиная с самого старого из запрошенных
            return self._frame_history[max(0, len(self._frame_history) - actual_limit):]

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def set_exclusion_parameters(self, hwnd: int | None, title: str | None, exclude: bool):
        """
        Устанавливает параметры для исключения окна из захвата.
        :param hwnd: HWND окна, которое нужно исключить. None, если исключение по заголовку.
        :param title: Заголовок окна, которое нужно исключить. None, если исключение по HWND.
        :param exclude: Флаг, указывающий, нужно ли исключать окно.
        """
        with self._lock:
            self.hwnd_to_exclude = hwnd
            self.window_title_to_exclude = title
            self.exclude_gui_window = exclude
            logger.info(f"Параметры исключения окна обновлены: HWND={hwnd}, Title='{title}', Exclude={exclude}")
