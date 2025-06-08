import logging
import colorlog
import os
import sys

class MyFileFilter(logging.Filter):
    def filter(self, record):
        # Упрощенная проверка для работы в PyInstaller
        if hasattr(sys, '_MEIPASS'):
            # Если мы в собранном приложении, пропускаем все логи
            return True
        # Иначе используем оригинальную фильтрацию
        project_path = os.path.dirname(os.path.abspath(__file__))
        return record.pathname.startswith(project_path)

# Создаем логгер
logger = colorlog.getLogger(__name__)
logger.setLevel(logging.INFO)

# Обработчик для консоли
console_handler = colorlog.StreamHandler()
console_handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s - %(levelname)s - %(message)s',
    log_colors={
        'INFO': 'white',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }
))
console_handler.addFilter(MyFileFilter())

# Обработчик для файла (добавляется всегда)
file_handler = logging.FileHandler('NeuroMitaLogs.log', encoding='utf-8')
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s'
))

# Добавляем обработчики
logger.addHandler(console_handler)
logger.addHandler(file_handler)
logger.propagate = False