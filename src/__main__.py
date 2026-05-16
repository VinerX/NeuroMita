### main.py
import faulthandler
faulthandler.enable()

import pydantic.fields
import uvicorn
import os
import sys
import re

os.environ["QT_API"] = "pyqt6" 

from main_logger import logger
from _version import __version__
def create_startup_banner(title: str, version: str) -> str:
    version_info = f"Version {version}"
    
    padding = 6
    
    content_width = max(len(title), len(version_info)) + padding
    
    if content_width % 2 != 0:
        content_width += 1
        
    top_border = f"╔{'═' * content_width}╗"
    bottom_border = f"╚{'═' * content_width}╝"
    
    empty_line = f"║{' ' * content_width}║"
    title_line = f"║{title.center(content_width)}║"
    version_line = f"║{version_info.center(content_width)}║"
    
    # Собираем и возвращаем финальный баннер
    return (
        f"{top_border}\n"
        f"{empty_line}\n"
        f"{title_line}\n"
        f"{version_line}\n"
        f"{empty_line}\n"
        f"{bottom_border}"
    )


banner = create_startup_banner("NeuroMita", __version__)
logger.success(f"\n\n{banner}\n\n")


from dotenv import load_dotenv
ENV_FILENAME = "features.env" 
loaded = load_dotenv(dotenv_path=ENV_FILENAME)
os.environ["WHISPER_ONNX_DEBUG"]="1"
if loaded:
    logger.notify(f"Переменные окружения успешно загружены из файла: {ENV_FILENAME}")
else:
    logger.notify(f"Файл окружения '{ENV_FILENAME}' не найден по пути: {ENV_FILENAME}. Используются системные переменные или значения по умолчанию.")

# region Для исправления проблем с импортом динамично подгружаемых пакетов:
import timeit
import pickletools
import logging.config
import fileinput
from win32 import win32file
import pyworld
import cProfile
import filecmp
import soxr

try:
    import google.api_core
    import google.auth
    from google.cloud import storage
    from google.protobuf import empty_pb2
    import google.protobuf.wrappers_pb2
except Exception as e:
    logger.warning(f"{e}")
import xml.dom


import modulefinder
import sunau
import xml.etree
import xml.etree.ElementTree
import os

# os.environ["TEST_AS_AMD"] = "TRUE"

if os.environ.get("VERBOSE_TRITON_LOGS", "0") == "1":
    os.environ["TORCH_LOGS"] = "+dynamo"
    os.environ["TORCHDYNAMO_VERBOSE"] = "1"
    
os.environ["UV_LINK_MODE"] = "copy"

#region Переменные для путей
current_file = os.path.abspath(__file__)
# When running from a .pyz archive, __file__ is the pyz itself (one level),
# not src/__main__.py (two levels). Detect and handle both cases.
if current_file.lower().endswith(".pyz"):
    base_dir = os.path.dirname(current_file)
else:
    base_dir = os.path.dirname(os.path.dirname(current_file))

os.environ["NEUROMITA_BASE_DIR"] = base_dir
if not os.environ.get("NEUROMITA_LIB_DIR"):
    os.environ["NEUROMITA_LIB_DIR"] = os.path.join(base_dir, "Lib")
if not os.environ.get("NEUROMITA_PROMPTS_DIR"):
    os.environ["NEUROMITA_PROMPTS_DIR"] = os.path.join(base_dir, "Prompts")
if not os.environ.get("NEUROMITA_HISTORIES_DIR"):
    os.environ["NEUROMITA_HISTORIES_DIR"] = os.path.join(base_dir, "Histories")
if not os.environ.get("NEUROMITA_MODELS_DIR"):
    os.environ["NEUROMITA_MODELS_DIR"] = os.path.join(base_dir, "Models")
if not os.environ.get("NEUROMITA_CHECKPOINTS_DIR"):
    os.environ["NEUROMITA_CHECKPOINTS_DIR"] = os.path.join(base_dir, "checkpoints")

libs_dir = os.environ["NEUROMITA_LIB_DIR"]
if not os.path.exists(libs_dir):
    os.makedirs(libs_dir)

local_python = os.path.join(base_dir, "libs", "python", "python.exe")
if os.path.exists(local_python):
    os.environ["NEUROMITA_PYTHON"] = local_python
else:
    os.environ["NEUROMITA_PYTHON"] = sys.executable
#endregion


logger.info(f"Базовая директория: {os.environ['NEUROMITA_BASE_DIR']}")
logger.info(f"Prompts: {os.environ['NEUROMITA_PROMPTS_DIR']}")
logger.info(f"Histories: {os.environ['NEUROMITA_HISTORIES_DIR']}")
logger.info(f"Checkpoints: {os.environ['NEUROMITA_CHECKPOINTS_DIR']}")
logger.info(f"Python: {os.environ['NEUROMITA_PYTHON']}")
logger.info(libs_dir)

# Check for updates (before heavy imports)
try:
    from updater import check_for_updates as _check_for_updates, check_for_unity_updates as _check_for_unity_updates
    import json as _json
    _upd_settings: dict = {}
    try:
        _settings_path = os.path.join(base_dir, "Settings", "settings.json")
        with open(_settings_path, encoding="utf-8") as _f:
            _upd_settings = _json.load(_f)
    except Exception:
        pass
    _py_startup_update = bool(
        _upd_settings.get("AUTO_UPDATE", _upd_settings.get("AUTO_UPDATE_CHECK", False))
    )
    _unity_startup_update = bool(_upd_settings.get("AUTO_UPDATE_UNITY", False))

    if _py_startup_update:
        _check_for_updates(
            base_dir=base_dir,
            logger=logger,
            channel=_upd_settings.get("UPDATE_CHANNEL", "stable"),
            tester_code=_upd_settings.get("TESTER_CODE") or None,
            auto_update=True,
        )

    if _unity_startup_update:
        _check_for_unity_updates(
            base_dir=base_dir,
            logger=logger,
            unity_dir=_upd_settings.get("UNITY_INSTALL_DIR") or None,
            channel=_upd_settings.get("UPDATE_CHANNEL", "stable"),
            tester_code=_upd_settings.get("TESTER_CODE") or None,
            auto_update=True,
        )
except Exception as _upd_err:
    logger.warning(f"Update check failed: {_upd_err}")

_libs_dir_norm = os.path.normcase(os.path.abspath(libs_dir))
sys.path = [
    p for p in sys.path
    if os.path.normcase(os.path.abspath(p or "")) != _libs_dir_norm
]
sys.path.insert(0, libs_dir)
import importlib.util, ctypes, pathlib, os

# ── Torch CUDA bootstrap ──────────────────────────────────────────────
# Должен выполняться ДО любого import torch в процессе.
# Если стоит CPU-вариант, а GPU — NVIDIA, переустанавливаем на CUDA.
try:
    from utils.torch_install_utils import decide_torch_install, TORCH_PACKAGES
    from utils.gpu_utils import check_gpu_provider
    _gpu = check_gpu_provider() or "CPU"
    # Передаём libs_dir как target_dir — проверяем dist-info прямо в папке
    # установки, а не через importlib.metadata (который может найти torch из
    # другого Python-окружения).
    _plan = decide_torch_install(_gpu, target_dir=libs_dir)
    # Только реактивный апгрейд: если torch уже установлен в неправильном варианте.
    # Первичную установку делает lazy bootstrap (embedding_handler / cross_encoder).
    from utils.torch_install_utils import get_installed_torch_variant as _get_torch_variant
    if _plan["action"] == "reinstall" and _get_torch_variant(target_dir=libs_dir) is not None:
        logger.info(f"Torch bootstrap (early): gpu={_gpu}, action=reinstall (CPU→CUDA)")
        from utils.pip_installer import PipInstaller
        _pip = PipInstaller(update_log=logger.info)
        logger.info("Удаление CPU-варианта PyTorch перед установкой CUDA...")
        _pip.uninstall_packages(
            ["torch", "torchaudio"],
            description="Удаление CPU-варианта PyTorch",
        )
        _pip.install_package(
            list(TORCH_PACKAGES),
            description=_plan["description"],
            extra_args=_plan.get("extra_args"),
        )
    elif _plan["action"] != "skip":
        logger.info(f"Torch bootstrap (early): gpu={_gpu}, action={_plan['action']} — отложено до первого использования")
    else:
        logger.info(f"Torch bootstrap (early): gpu={_gpu}, action=skip — {_plan.get('reason', '')}")
except Exception as _torch_boot_err:
    logger.warning(f"Torch early bootstrap failed: {_torch_boot_err}")
# ──────────────────────────────────────────────────────────────────────

# ort_spec = importlib.util.find_spec("onnxruntime")
# capi_dir = pathlib.Path(ort_spec.origin).parent / "capi"
# ctypes.WinDLL(str(capi_dir / "libiomp5md.dll"))

import onnxruntime

from PyQt6.QtWidgets import QApplication



config_path = os.path.join(libs_dir, "fairseq", "dataclass", "configs.py")
if os.path.exists(config_path):
    

    with open(config_path, "r", encoding="utf-8") as f:
        source = f.read()

    patched_source = re.sub(r"metadata=\{(.*?)help:", r'metadata={\1"help":', source)

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(patched_source)

    logger.success("Патч успешно применён к configs.py")

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

    logger.success("Патч успешно применён к audio.py")

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
        
    logger.success("Патч успешно применён к windows_utils.py")
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
        
    logger.success("Патч успешно применён к compiler.py")
else:
    logger.info(f"Файл {compiler_path} не найден")


build_py_path = os.path.join(libs_dir, "triton", "runtime", "build.py")

os.environ["CC"] = os.path.join(os.path.abspath(libs_dir), "triton", "runtime", "tcc", "tcc.exe")

if os.path.exists(compiler_path):
    with open(build_py_path, "r", encoding="utf-8") as f:
        source = f.read()
                        
    # Заменяем путь к tcc.exe
    patched_source = source.replace(
        'cc = os.path.join(sysconfig.get_paths()["platlib"], "triton", "runtime", "tcc", "tcc.exe")',
        f'cc = os.path.join("{libs_dir}", "triton", "runtime", "tcc", "tcc.exe")'
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
    project_root_file = os.path.join(os.environ["NEUROMITA_BASE_DIR"], '.project-root')
    
    if not os.path.exists(project_root_file):
        open(project_root_file, 'w').close()
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

from ui.windows.main_window import MainWindow
from controllers.main_controller import MainController
from core.events import get_event_bus
from main_logger import logger
from PyQt6.QtWidgets import QApplication
import sys

if __name__ == "__main__":
    logger.success("Функция main() запущена")
    try:
        app = QApplication(sys.argv)
        logger.info("QApplication создан")

        if sys.platform == 'win32':
            import ctypes
            myappid = 'mycompany.myproduct.subproduct.version' 
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

        # Создаем пустой объект для контроллера
        logger.info("Создаю MainController...")
        controller = MainController(None)
        logger.info("MainController создан")

        # Инициализация сборщика данных для дообучения
        try:
            from managers.finetune_collector import FineTuneCollector
            FineTuneCollector.instance = FineTuneCollector()
            logger.info("FineTuneCollector инициализирован")
        except Exception as _ft_init_err:
            logger.warning(f"FineTuneCollector не инициализирован: {_ft_init_err}")
    
        logger.info("Создаю MainWindow...")
        main_win = MainWindow(controller.settings)
        logger.info("MainWindow создан")
        
        # Обновляем ссылку на реальный view в контроллере
        controller.update_view(main_win)

        main_win.load_chat_history()
        
        
        logger.info("Показываю главное окно...")
        main_win.show()
        logger.info("Запускаю app.exec()...")

        
        # При завершении приложения останавливаем систему событий
        app.aboutToQuit.connect(lambda: get_event_bus().shutdown())
        
        sys.exit(app.exec())
    except Exception as e:
        logger.error(f"Ошибка в main(): {e}", exc_info=True)
        raise
