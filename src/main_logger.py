import atexit
import logging
import os
import queue
import sys
from logging.handlers import QueueHandler, QueueListener
from typing import Any, Optional

from core.app_paths import runtime_log_path

try:
    import colorlog
except Exception:
    colorlog = None

# -----------------------------------------------------------------------------
# Кастомные уровни логирования
# -----------------------------------------------------------------------------
PROGRESS_LEVEL = 45  # между DEBUG (10) и INFO (20)
NOTIFY_LEVEL = 25  # между INFO (20) и WARNING (30)
SUCCESS_LEVEL = 35  # между WARNING (30) и ERROR (40)

logging.addLevelName(NOTIFY_LEVEL, "NOTIFY")
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")
logging.addLevelName(PROGRESS_LEVEL, "PROGRESS")

# -----------------------------------------------------------------------------
# Фильтры
# -----------------------------------------------------------------------------
class ProjectFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.project_path = os.path.dirname(os.path.abspath(__file__))

    def filter(self, record):
        if hasattr(sys, '_MEIPASS'):  # запущено из exe
            return True
        return record.pathname.startswith(self.project_path)

class LocationFilter(logging.Filter):
    def filter(self, record):
        record.location = f"[{record.filename}:{record.lineno}]"
        return True

# -----------------------------------------------------------------------------
# Кастомный класс логгера
# -----------------------------------------------------------------------------
class CustomLogger(logging.Logger):
    """
    Кастомный логгер с дополнительными методами notify и success.
    Наследует все функции стандартного logging.Logger.
    """
    
    def __init__(self, name: str, level: int = logging.NOTSET):
        super().__init__(name, level)
        self._setup_handlers()
    
    def notify(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        Логирование уведомлений с уровнем NOTIFY (25).
        Подойдёт для уведомления пользователя о компоненте системы..
        Args:
            message: Сообщение для логирования
            *args: Позиционные аргументы для форматирования сообщения
            **kwargs: Именованные аргументы для Logger._log
        """
        if self.isEnabledFor(NOTIFY_LEVEL):
            self._log(NOTIFY_LEVEL, message, args, **kwargs)
    
    def progress(self, message: str, *args: Any, **kwargs: Any) -> None:
        if self.isEnabledFor(PROGRESS_LEVEL):
            self._log(PROGRESS_LEVEL, message, args, **kwargs)

    def success(self, message: str, *args: Any, **kwargs: Any) -> None:
        """
        Логирование успешных операций с уровнем SUCCESS (35).
        Подойдёт для уведомления пользователя об удачном выполнении команды.

        Args:
            message: Сообщение для логирования
            *args: Позиционные аргументы для форматирования сообщения
            **kwargs: Именованные аргументы для Logger._log
        """
        if self.isEnabledFor(SUCCESS_LEVEL):
            self._log(SUCCESS_LEVEL, message, args, **kwargs)
    
    def _setup_handlers(self) -> None:
        """Настройка обработчиков для логгера."""
        for stream_name in ("stdout", "stderr"):
            stream = getattr(sys, stream_name, None)
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                try:
                    reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass

        # Консольный обработчик
        if colorlog is not None:
            console_handler = colorlog.StreamHandler()
            console_handler.setFormatter(
                colorlog.ColoredFormatter(
                    '%(log_color)s%(levelname)-8s %(location)-30s | %(message)s',
                    log_colors={
                        'DEBUG':    'white',
                        'PROGRESS': 'light_blue',
                        'INFO':     'white',
                        'NOTIFY':   'light_purple',
                        'WARNING':  'yellow',
                        'SUCCESS':  'light_green',
                        'ERROR':    'red',
                        'CRITICAL': 'red,bg_white',
                    },
                )
            )
        else:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter('%(levelname)-8s %(location)-30s | %(message)s'))
        console_handler.addFilter(ProjectFilter())
        console_handler.addFilter(LocationFilter())

        # Файловый обработчик
        log_path = runtime_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setFormatter(
            logging.Formatter(
                '%(asctime)s - %(levelname)-8s '
                '[%(filename)s:%(lineno)d - %(funcName)s] '
                '%(message)s'
            )
        )
        file_handler.addFilter(ProjectFilter())

        # Асинхронное логирование: сам logger.* только кладёт запись в очередь
        # (микросекунды), а фактическую запись в консоль/файл (диск!) делает
        # отдельный поток QueueListener. Это убирает блокировку вызывающего
        # потока на дисковом I/O — на старте лог/варнинг-флуд больше не тормозит
        # обработку событий и не даёт «GUI FREEZE» из-за медленного диска.
        try:
            log_queue: "queue.Queue[Any]" = queue.Queue(-1)
            queue_handler = QueueHandler(log_queue)
            listener = QueueListener(
                log_queue, console_handler, file_handler,
                respect_handler_level=True,
            )
            listener.start()
            # Останавливаем слушателя на выходе — дописать хвост очереди на диск.
            atexit.register(listener.stop)
            self.addHandler(queue_handler)
        except Exception:
            # Фолбэк на синхронные обработчики, если очередь по какой-то причине
            # недоступна — логирование важнее его асинхронности.
            self.addHandler(console_handler)
            self.addHandler(file_handler)
        self.propagate = False

# -----------------------------------------------------------------------------
# Создаем экземпляр логгера
# -----------------------------------------------------------------------------
# Регистрируем наш кастомный класс в системе логирования
logging.setLoggerClass(CustomLogger)

# Создаем логгер
logger: CustomLogger = logging.getLogger(__name__)  # type: ignore
logger.setLevel(logging.INFO)

# Восстанавливаем стандартный класс логгера для других модулей
logging.setLoggerClass(logging.Logger)

# -----------------------------------------------------------------------------
# Пример использования (можно удалить)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Запуск программы")
    logger.notify("Важное уведомление для пользователя")
    logger.warning("Предупреждение о потенциальной проблеме")
    logger.success("Операция завершена успешно!")
    logger.error("Произошла ошибка")
