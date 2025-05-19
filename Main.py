### main.py

import pydantic.fields
import uvicorn
from gui import ChatGUI
import os
import sys
import re
from Logger import logger
import tkinter as tk # Пример импорта для вашего GUI

from dotenv import load_dotenv
ENV_FILENAME = "features.env" 
loaded = load_dotenv(dotenv_path=ENV_FILENAME)

if loaded:
    logger.info(f"Переменные окружения успешно загружены из файла: {ENV_FILENAME}")
else:
    logger.info(f"Файл окружения '{ENV_FILENAME}' не найден по пути: {ENV_FILENAME}. Используются системные переменные или значения по умолчанию.")

# region Для исправления проблем с импортом динамично подгружаемых пакетов:
import timeit
import pickletools
import logging.config
import fileinput
# import pywintypes
# import win32file
import pyworld
import cProfile
import filecmp
if os.environ.get("ENABLE_COMMAND_REPLACER_BY_DEFAULT", "0") != "1":
    import transformers.models.auto.modeling_auto
import modulefinder
import sunau
import xml.etree
import xml.etree.ElementTree

import os

# os.environ["TEST_AS_AMD"] = "TRUE"

libs_dir = os.path.join(os.path.dirname(sys.executable), "Lib")
if not os.path.exists(libs_dir):
    os.makedirs(libs_dir)

logger.info(libs_dir)
sys.path.insert(0, libs_dir)


config_path = os.path.join(libs_dir, "fairseq", "dataclass", "configs.py")
if os.path.exists(config_path):
    

    with open(config_path, "r", encoding="utf-8") as f:
        source = f.read()

    patched_source = re.sub(r"metadata=\{(.*?)help:", r'metadata={\1"help":', source)

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(patched_source)

    logger.info("Патч успешно применён к configs.py")

audio_path = os.path.join(libs_dir, "tts_with_rvc", "lib", "audio.py")
if os.path.exists(audio_path):

    with open(audio_path, "r", encoding="utf-8") as f:
        source = f.read()

    patched_source = re.sub(
        r"\bimport ffmpeg\b", 
        'import importlib\nffmpeg = importlib.import_module("ffmpeg")', 
        source
    )

    with open(audio_path, "w", encoding="utf-8") as f:
        f.write(patched_source)

    logger.info("Патч успешно применён к audio.py")

# Патч для triton windows_utils.py
windows_utils_path = os.path.join(libs_dir, "triton", "windows_utils.py")
if os.path.exists(windows_utils_path):
    with open(windows_utils_path, "r", encoding="utf-8") as f:
        source = f.read()
    
    patched_source = source.replace(
        "output = subprocess.check_output(command, text=True).strip()",
        "output = subprocess.check_output(\n            command, text=True, close_fds=True, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE\n        ).strip()"
    )
    
    with open(windows_utils_path, "w", encoding="utf-8") as f:
        f.write(patched_source)
        
    logger.info("Патч успешно применён к windows_utils.py")
else:
    logger.info(f"Файл {windows_utils_path} не найден")


# Патч для compiler.py
compiler_path = os.path.join(libs_dir, "triton", "backends", "nvidia", "compiler.py")
if os.path.exists(compiler_path):
    with open(compiler_path, "r", encoding="utf-8") as f:
        source = f.read()
    
    old_code = '@functools.lru_cache()\ndef get_ptxas_version():\n    version = subprocess.check_output([_path_to_binary("ptxas")[0], "--version"]).decode("utf-8")\n    return version'
    new_code = '@functools.lru_cache()\ndef get_ptxas_version():\n    version = subprocess.check_output([_path_to_binary("ptxas")[0], "--version"], stderr=subprocess.PIPE, close_fds=True, stdin=subprocess.DEVNULL).decode("utf-8")\n    return version'
    
    patched_source = source.replace(old_code, new_code)
    
    with open(compiler_path, "w", encoding="utf-8") as f:
        f.write(patched_source)
        
    logger.info("Патч успешно применён к compiler.py")
else:
    logger.info(f"Файл {compiler_path} не найден")


build_py_path = os.path.join(libs_dir, "triton", "runtime", "build.py")
if os.path.exists(compiler_path):
    with open(build_py_path, "r", encoding="utf-8") as f:
        source = f.read()
                        
    # Заменяем путь к tcc.exe
    patched_source = source.replace(
        'cc = os.path.join(sysconfig.get_paths()["platlib"], "triton", "runtime", "tcc", "tcc.exe")',
        'cc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tcc", "tcc.exe")'
    )

    with open(build_py_path, "w", encoding="utf-8") as f:
        f.write(patched_source)
                        
cache_py_path = os.path.join(libs_dir, "triton", "runtime", "cache.py")
if os.path.exists(cache_py_path):
    with open(cache_py_path, "r", encoding="utf-8") as f:
        source = f.read()

    old_line = 'temp_dir = os.path.join(self.cache_dir, f"tmp.pid_{pid}_{rnd_id}")'
    new_line = 'temp_dir = os.path.join(self.cache_dir, f"tmp.pid_{str(pid)[:5]}_{str(rnd_id)[:5]}")'

    # Выполняем замену
    patched_source = source.replace(old_line, new_line)

    # Записываем измененный файл
    with open(cache_py_path, "w", encoding="utf-8") as f:
        f.write(patched_source)

# ВРЕМЕННО ПОКА НЕ ВЫЙДЕТ ПАТЧ
build_py_path = os.path.join(libs_dir, "triton", "runtime", "build.py")
if os.path.exists(build_py_path):
    with open(build_py_path, "r", encoding="utf-8") as f:
        source = f.read()
    old_line = 'cc_cmd = [cc, src, "-O3", "-shared", "-fPIC", "-Wno-psabi", "-o", out]'
    new_line = 'cc_cmd = [cc, src, "-O3", "-shared", "-Wno-psabi", "-o", out]'

    patched_source = source.replace(old_line, new_line)

    with open(build_py_path, "w", encoding="utf-8") as f:
        f.write(patched_source)


def ensure_project_root():
    project_root_file = os.path.join(os.path.dirname(sys.executable), '.project-root')
    
    if not os.path.exists(project_root_file):
        open(project_root_file, 'w').close() # Создать пустой файл
        logger.info(f"Файл '{project_root_file}' создан.")

ensure_project_root()



# Установка

# Теперь делаю файлом с папкой, так как антивирусы ругаются)
#pyinstaller --name NeuroMita --noconfirm --console --add-data "Prompts/*;Prompts" --add-data "Prompts/**/*;Prompts" Main.py

# Скакать между версиями g4f
#pip install --upgrade g4f==0.4.7.7
#pip install --upgrade g4f==0.4.8.3
#pip install --upgrade g4f

#"""
#Тестово, потом надо будет вот это вернуть
#pyinstaller --name NeuroMita --noconfirm --add-data "Prompts/*;Prompts" --add-data "%USERPROFILE%\AppData\Local\Programs\Python\Python313\Lib\site-packages\emoji\unicode_codes\emoji.json;emoji\unicode_codes  --add-data "Prompts/**/*;Prompts" Main.py
#"""



# Старый вариант
#pyinstaller --onefile --name NeuroMita --add-data "Prompts/*;Prompts" --add-data "Prompts/**/*;Prompts" Main.py

# Не забудь рядом папку промптов и ffmpeg

import threading


def main():
    
    server_thread = threading.Thread(
        target=lambda: uvicorn.run("web.server:app", host="0.0.0.0", port=8000),
        daemon=True
    )
    server_thread.start()
    
    # Запуск GUI в основном потоке
    gui = ChatGUI()
    gui.run()


if __name__ == "__main__":
    main()
