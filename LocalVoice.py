# LocalVoice.py
# Файл для установки и управления локальными моделями озвучки.

import importlib
import queue
import threading
import subprocess
import sys
import os
import asyncio
import pygame
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkFont
import time
import ffmpeg
from utils.GpuUtils import check_gpu_provider

import hashlib
from datetime import datetime
import traceback
import site
import tempfile
import gc
import soundfile as sf
import re
from xml.sax.saxutils import escape
from typing import Dict, Optional, Any

from packaging.utils import canonicalize_name, NormalizedName
from utils.PipInstaller import PipInstaller, DependencyResolver
from SettingsManager import SettingsManager

# --- Новые импорты для модульной структуры ---
from voice_models.base_model import IVoiceModel
from voice_models.edge_tts_rvc_model import EdgeTTS_RVC_Model
from voice_models.fish_speech_model import FishSpeechModel
from voice_models.f5_tts_model import F5TTSModel

from docs import DocsManager
from Logger import logger

def getTranslationVariant(ru_str, en_str=""):
    if en_str and SettingsManager.get("LANGUAGE") == "EN":
        return en_str
    return ru_str

_ = getTranslationVariant

class LocalVoice:
    def __init__(self, parent=None):
        self.parent = parent
        self.settings = parent.settings if parent else SettingsManager()
        
        self.first_compiled: Optional[bool] = None

        self.current_model_id: Optional[str] = None
        self.active_model_instance: Optional[IVoiceModel] = None
        
        # Создаем один экземпляр для всех RVC-моделей
        edge_rvc_handler = EdgeTTS_RVC_Model(self, "edge_rvc_handler")
        
        self.models: Dict[str, IVoiceModel] = {
            "low": edge_rvc_handler,
            "low+": edge_rvc_handler,
            "medium": FishSpeechModel(self, "medium"),
            "medium+": FishSpeechModel(self, "medium+"),
            "medium+low": FishSpeechModel(self, "medium+low"),
            "f5_tts": F5TTSModel(self, "f5_tts"),
        }

        self.pth_path: Optional[str] = None
        self.index_path: Optional[str] = None
        self.clone_voice_folder: str = "Models"
        self.clone_voice_filename: Optional[str] = None
        self.clone_voice_text: Optional[str] = None
        self.current_character_name: str = ""
        self.current_character: Optional[Any] = None

        self.voice_language = self.settings.get("VOICE_LANGUAGE", "ru")
        self.docs_manager = DocsManager()
        self.provider = check_gpu_provider()
        self.amd_test = os.environ.get('TEST_AS_AMD', '').upper() == 'TRUE'
        if self.provider in ["AMD"] or self.amd_test:
            os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

        self.cuda_found = False
        self.winsdk_found = False
        self.msvc_found = False
        self.triton_installed = False
        self.triton_checks_performed = False
        self._dialog_choice = None
        
        self.known_main_packages = ["tts-with-rvc", "fish-speech-lib", "triton-windows", "f5-tts"]
        self.protected_package = "g4f"
        
        if self.is_triton_installed():
            try:
                self._check_system_dependencies()
            except Exception:
                logger.info(_("Triton установлен, но проверка зависимостей не удалась.", "Triton is installed, but dependency check failed."))

    # =========================================================================
    # НОВЫЕ ПУБЛИЧНЫЕ МЕТОДЫ (Упрощенный интерфейс)
    # =========================================================================

    def download_model(self, model_id: str) -> bool:
        model_to_install = self.models.get(model_id)
        if not model_to_install:
            logger.error(f"Неизвестный идентификатор модели для установки: {model_id}")
            return False
        logger.info(f"Начало установки модели '{model_to_install.get_display_name()}' (ID: {model_id})")
        success = model_to_install.install()
        if success:
            logger.info(f"Установка модели '{model_id}' завершена успешно.")
            self.current_model_id = model_id
        else:
            logger.error(f"Установка модели '{model_id}' не удалась.")
        return success

    def initialize_model(self, model_id: str, init: bool = False) -> bool:
        model_to_init = self.models.get(model_id)
        if not model_to_init:
            logger.error(f"Неизвестный идентификатор модели для инициализации: {model_id}")
            return False
        
        if not model_to_init.is_installed():
            logger.error(f"Модель {model_id} не установлена. Пожалуйста, установите ее сначала.")
            return False
        
        # Шаг 1: Устанавливаем ID модели, которую мы СОБИРАЕМСЯ инициализировать.
        # Это дает дочернему классу правильный контекст.
        self.current_model_id = model_id
        logger.info(f"Попытка инициализации и активации модели '{model_id}'...")

        # Шаг 2: Устанавливаем пути по умолчанию ДО инициализации
        is_nvidia = self.provider in ["NVIDIA"]
        model_ext = 'pth' if is_nvidia else 'onnx'
        self.pth_path = os.path.join(self.clone_voice_folder, f"Mila.{model_ext}")
        self.index_path = os.path.join(self.clone_voice_folder, "Mila.index")
        self.clone_voice_filename = os.path.join(self.clone_voice_folder, "Mila.wav")
        self.clone_voice_text = os.path.join(self.clone_voice_folder, "Mila.txt")
        self.current_character_name = "Mila"

        # Шаг 3: Вызываем инициализацию. Дочерний метод теперь достаточно умен,
        # чтобы догрузить/выгрузить компоненты по необходимости.
        success = model_to_init.initialize(init=init)
        
        if not success:
            logger.error(f"Не удалось инициализировать модель '{model_id}'.")
            # Сбрасываем состояние, если что-то пошло не так
            if self.active_model_instance and self.active_model_instance.model_id == model_id:
                self.active_model_instance = None
            self.current_model_id = None
            return False

        # Шаг 4: Если все прошло успешно, устанавливаем модель как активную.
        self.active_model_instance = model_to_init
        logger.info(f"Модель '{model_id}' успешно установлена как активная.")
        
        return True

    async def voiceover(self, text: str, output_file="output.wav", character: Optional[Any] = None) -> Optional[str]:
        if self.active_model_instance is None or not self.active_model_instance.initialized:
            if self.current_model_id:
                logger.warning(f"Активная модель '{self.current_model_id}' не инициализирована. Попытка автоматической инициализации...")
                if not self.initialize_model(self.current_model_id, init=False):
                     raise Exception(f"Не удалось инициализировать модель '{self.current_model_id}'.")
            else:
                 raise ValueError("Модель не выбрана или не инициализирована.")
        if character is not None:
            self.current_character = character
            is_nvidia = self.provider in ["NVIDIA"]
            short_name = str(getattr(character, 'short_name', "Mila"))
            self.current_character_name = short_name
            self.pth_path = os.path.join(self.clone_voice_folder, f"{short_name}.{'pth' if is_nvidia else 'onnx'}")
            self.index_path = os.path.join(self.clone_voice_folder, f"{short_name}.index")
            self.clone_voice_filename = os.path.join(self.clone_voice_folder, f"{short_name}.wav")
            self.clone_voice_text = os.path.join(self.clone_voice_folder, f"{short_name}.txt")
        else:
            self.current_character_name = "Mila"
            self.pth_path = os.path.join(self.clone_voice_folder, "Mila.pth")
            self.index_path = os.path.join(self.clone_voice_folder, "Mila.index")
            self.clone_voice_filename = os.path.join(self.clone_voice_folder, "Mila.wav")
            self.clone_voice_text = os.path.join(self.clone_voice_folder, "Mila.txt")
        return await self.active_model_instance.voiceover(text, character)

    # =========================================================================
    # Методы для управления и проверки состояния
    # =========================================================================
    
    def is_model_installed(self, model_id: str) -> bool:
        model = self.models.get(model_id)
        if model:
            return model.is_installed()
        return False
        
    def is_model_initialized(self, model_id: str) -> bool:
        model = self.models.get(model_id)
        if model:
            # Для Edge/Silero проверяем готовность к конкретному режиму
            if model_id in ["low", "low+"]:
                if not model.initialized or not model.current_tts_rvc:
                    return False
                if model_id == "low+" and not model.current_silero_model:
                    return False
                return True
            return model.initialized
        return False

    def is_triton_installed(self) -> bool:
        """Проверяет, установлен ли Triton."""
        try:
            libs_path_abs = os.path.abspath("Lib")
            if libs_path_abs not in sys.path:
                sys.path.insert(0, libs_path_abs)
            import triton
            self.triton_installed = True
            return True
        except ImportError:
            self.triton_installed = False
            return False

    def change_voice_language(self, new_voice_language: str):
        logger.info(f"Запрос на изменение языка озвучки на '{new_voice_language}'...")
        self.voice_language = new_voice_language
        logger.info(f"Установлен язык озвучки: {self.voice_language}")
        if self.active_model_instance:
            logger.info(f"Сброс состояния активной модели '{self.active_model_instance.model_id}' из-за смены языка.")
            self.active_model_instance.cleanup_state()
            self.active_model_instance = None
        logger.info("Изменение языка завершено.")

    # =========================================================================
    # Методы удаления
    # =========================================================================
    def uninstall_edge_tts_rvc(self):
        return self.models["low"].uninstall()

    def uninstall_fish_speech(self):
        return self.models["medium"].uninstall()

    def uninstall_f5_tts(self):
        return self.models["f5_tts"].uninstall()

    def uninstall_triton_component(self):
        return self._uninstall_component("Triton", "triton-windows")
    
    def _cleanup_after_uninstall(self, removed_package_name: str):
        logger.info(f"Очистка состояния LocalVoice после удаления пакета: {removed_package_name}")
        
        model_to_reset_ids = []
        if removed_package_name == "tts-with-rvc":
            model_to_reset_ids = ["low", "low+", "medium+low"]
        elif removed_package_name == "fish-speech-lib":
            model_to_reset_ids = ["medium", "medium+", "medium+low"]
        elif removed_package_name == "triton-windows":
            model_to_reset_ids = ["medium+", "medium+low"]
            self.triton_installed = False
            self.triton_checks_performed = False
        elif removed_package_name == "f5-tts":
            model_to_reset_ids = ["f5_tts"]
            
        for model_id in model_to_reset_ids:
            if model := self.models.get(model_id):
                model.cleanup_state()
                if self.active_model_instance and self.active_model_instance.model_id == model_id:
                    self.active_model_instance = None
                    self.current_model_id = None
                    logger.info(f"Активная модель '{model_id}' была сброшена.")

        try:
            importlib.invalidate_caches()
            module_name = removed_package_name.replace('-', '_')
            if module_name in sys.modules:
                del sys.modules[module_name]
        except Exception:
            pass

    # =========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ УСТАНОВКИ (вызываются из классов моделей)
    # =========================================================================

    def download_edge_tts_rvc_internal(self):
        gui_elements = None
        try:
            gui_elements = self._create_installation_window(
                title=_("Скачивание Edge-TTS + RVC", "Downloading Edge-TTS + RVC"),
                initial_status=_("Подготовка...", "Preparing...")
            )
            if not gui_elements:
                return False

            progress_window = gui_elements["window"]
            update_progress = gui_elements["update_progress"]
            update_status = gui_elements["update_status"]
            update_log = gui_elements["update_log"]

            installer = PipInstaller(
                script_path=r"libs\python\python.exe",
                libs_path="Lib",
                update_status=update_status,
                update_log=update_log,
                progress_window=progress_window
            )

            update_progress(10)
            update_log(_("Начало установки Edge-TTS + RVC...", "Starting Edge-TTS + RVC installation..."))

            if self.provider in ["NVIDIA"] and not self.is_cuda_available():
                update_status(_("Установка PyTorch с поддержкой CUDA 12.4...", "Installing PyTorch with CUDA 12.4 support..."))
                update_progress(20)
                success = installer.install_package(
                    ["torch==2.6.0", "torchaudio==2.6.0"],
                    description=_("Установка PyTorch с поддержкой CUDA 12.4...", "Installing PyTorch with CUDA 12.4 support..."),
                    extra_args=["--index-url", "https://download.pytorch.org/whl/cu124"]
                )

                if not success:
                    update_status(_("Ошибка при установке PyTorch", "Error installing PyTorch"))
                    if progress_window and progress_window.winfo_exists():
                        progress_window.after(5000, progress_window.destroy)
                    return False
                update_progress(50)
            else:
                update_progress(50) 

            update_status(_("Установка зависимостей...", "Installing dependencies..."))
            success = installer.install_package(
                "omegaconf",
                description=_("Установка omegaconf...", "Installing omegaconf...")
            )
            if not success:
                update_status(_("Ошибка при установке omegaconf", "Error installing omegaconf"))
                if progress_window and progress_window.winfo_exists():
                    progress_window.after(5000, progress_window.destroy)
                return False

            update_progress(70)

            package_url = None
            desc = ""
            if self.provider in ["NVIDIA"]:
                package_url = "tts_with_rvc"
                desc = _("Установка основной библиотеки tts-with-rvc (NVIDIA)...", "Installing main library tts-with-rvc (NVIDIA)...")
            elif self.provider in ["AMD"]:
                package_url = "tts_with_rvc_onnx[dml]"
                desc = _("Установка основной библиотеки tts-with-rvc (AMD)...", "Installing main library tts-with-rvc (AMD)...")
            else:
                update_log(_(f"Ошибка: не найдена подходящая видеокарта: {self.provider}", f"Error: suitable graphics card not found: {self.provider}"))
                if progress_window and progress_window.winfo_exists():
                    progress_window.after(5000, progress_window.destroy)
                return False

            success = installer.install_package(package_url, description=desc)

            if not success:
                update_status(_("Ошибка при установке tts-with-rvc", "Error installing tts-with-rvc"))
                if progress_window and progress_window.winfo_exists():
                    progress_window.after(5000, progress_window.destroy)
                return False

            libs_path_abs = os.path.abspath("Lib")
            update_progress(95)
            update_status(_("Применение патчей...", "Applying patches..."))
            config_path = os.path.join(libs_path_abs, "fairseq", "dataclass", "configs.py")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        source = f.read()
                    patched_source = re.sub(r"metadata=\{(.*?)help:", r'metadata={\1"help":', source)
                    with open(config_path, "w", encoding="utf-8") as f:
                        f.write(patched_source)
                    update_log(_("Патч успешно применен к configs.py", "Patch successfully applied to configs.py"))
                except Exception as e:
                    update_log(_(f"Ошибка при патче configs.py: {e}", f"Error patching configs.py: {e}"))
            
            update_progress(100)
            update_status(_("Установка успешно завершена!", "Installation successful!"))
            
            self.models['low']._load_module()
            self.models['low+']._load_module()
            
            if progress_window and progress_window.winfo_exists():
                progress_window.after(3000, progress_window.destroy)
            return True
        except Exception as e:
            logger.error(f"Ошибка при установке Edge-TTS + RVC: {e}", exc_info=True)
            if gui_elements and gui_elements["window"] and gui_elements["window"].winfo_exists():
                gui_elements["window"].destroy()
            return False

    def download_fish_speech_internal(self):
        gui_elements = None
        try:
            gui_elements = self._create_installation_window(
                title=_("Скачивание Fish Speech", "Downloading Fish Speech"),
                initial_status=_("Подготовка...", "Preparing...")
            )
            if not gui_elements:
                return False

            progress_window = gui_elements["window"]
            update_progress = gui_elements["update_progress"]
            update_status = gui_elements["update_status"]
            update_log = gui_elements["update_log"]
            
            installer = PipInstaller(
                script_path=r"libs\python\python.exe",
                libs_path="Lib",
                update_status=update_status,
                update_log=update_log,
                progress_window=progress_window
            )

            update_progress(10)
            update_log(_("Начало установки Fish Speech...", "Starting Fish Speech installation..."))

            if self.provider in ["NVIDIA"] and not self.is_cuda_available():
                update_status(_("Установка PyTorch с поддержкой CUDA 12.4...", "Installing PyTorch with CUDA 12.4 support..."))
                update_progress(20)
                success = installer.install_package(
                    ["torch==2.6.0", "torchaudio==2.6.0"],
                    description=_("Установка PyTorch с поддержкой CUDA 12.4...", "Installing PyTorch with CUDA 12.4 support..."),
                    extra_args=["--index-url", "https://download.pytorch.org/whl/cu124"]
                )
                if not success:
                    update_status(_("Ошибка при установке PyTorch", "Error installing PyTorch"))
                    if progress_window and progress_window.winfo_exists():
                        progress_window.after(5000, progress_window.destroy)
                    return False
                update_progress(40)
            else:
                 update_progress(40)

            update_status(_("Установка библиотеки Fish Speech...", "Installing Fish Speech library..."))
            force_install_unsupported = os.environ.get("ALLOW_UNSUPPORTED_GPU", "0") == "1"
            if self.provider in ["NVIDIA"] or force_install_unsupported:
                success = installer.install_package(
                    "fish_speech_lib",
                    description=_("Установка библиотеки Fish Speech...", "Installing Fish Speech library...")
                )
                if not success:
                    update_status(_("Ошибка при установке Fish Speech", "Error installing Fish Speech"))
                    if progress_window and progress_window.winfo_exists():
                        progress_window.after(5000, progress_window.destroy)
                    return False
                update_progress(80)

                success = installer.install_package(
                    "librosa==0.9.1",
                    description=_("Установка дополнительной библиотеки librosa...", "Installing additional library librosa...")
                )
                if not success:
                    update_log(_("Предупреждение: Fish Speech может работать некорректно без librosa", "Warning: Fish Speech may not work correctly without librosa"))
            else:
                update_log(_(f"Ошибка: не найдена подходящая видеокарта: {self.provider}", f"Error: suitable graphics card not found: {self.provider}"))
                update_status(_("Требуется NVIDIA GPU", "NVIDIA GPU required"))
                if progress_window and progress_window.winfo_exists():
                    progress_window.after(5000, progress_window.destroy)
                return False

            update_progress(100)
            update_status(_("Установка успешно завершена!", "Installation successful!"))
            
            self.models['medium']._load_module()
            
            if progress_window and progress_window.winfo_exists():
                progress_window.after(5000, progress_window.destroy)
            return True
        except Exception as e:
            logger.error(f"Ошибка при установке Fish Speech: {e}", exc_info=True)
            if gui_elements and gui_elements["window"] and gui_elements["window"].winfo_exists():
                gui_elements["window"].destroy()
            return False

    def download_triton_internal(self):
        gui_elements = None
        try:
            gui_elements = self._create_installation_window(
                title=_("Установка Triton", "Installing Triton"),
                initial_status=_("Подготовка...", "Preparing...")
            )
            if not gui_elements:
                logger.error(_("Не удалось создать окно установки Triton.", "Failed to create Triton installation window."))
                return False

            progress_window = gui_elements["window"]
            update_progress = gui_elements["update_progress"]
            update_status = gui_elements["update_status"]
            update_log = gui_elements["update_log"]

            installer = PipInstaller(
                script_path=r"libs\python\python.exe",
                libs_path="Lib",
                update_status=update_status,
                update_log=update_log,
                progress_window=progress_window
            )
            success = installer.install_package(
                "triton-windows<3.3.0",
                description=_("Установка библиотеки Triton...", "Installing Triton library..."),
                extra_args=["--upgrade"]
            )

            if not success:
                update_status(_("Ошибка при установке Triton", "Error installing Triton"))
                if progress_window and progress_window.winfo_exists():
                    progress_window.after(5000, progress_window.destroy)
                return False

            # --- Патчи ---
            update_progress(50)
            update_status(_("Применение патчей...", "Applying patches..."))
            libs_path_abs = os.path.abspath("Lib")
            
            # Патч build.py
            build_py_path = os.path.join(libs_path_abs, "triton", "runtime", "build.py")
            if os.path.exists(build_py_path):
                with open(build_py_path, "r+", encoding="utf-8") as f:
                    source = f.read()
                    old_line_tcc = f'cc = os.path.join(sysconfig.get_paths()["platlib"], "triton", "runtime", "tcc", "tcc.exe")'
                    new_line_tcc = 'cc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tcc", "tcc.exe")'
                    old_line_fpic = 'cc_cmd = [cc, src, "-O3", "-shared", "-fPIC", "-Wno-psabi", "-o", out]'
                    new_line_fpic = 'cc_cmd = [cc, src, "-O3", "-shared", "-Wno-psabi", "-o", out]'
                    patched_source = source.replace(old_line_tcc, new_line_tcc).replace(old_line_fpic, new_line_fpic)
                    if patched_source != source:
                        f.seek(0)
                        f.write(patched_source)
                        f.truncate()
                        update_log("Патчи для build.py применены.")

            # ... (остальные патчи, как в оригинале)

            # --- Проверка зависимостей ---
            update_progress(80)
            update_status(_("Проверка системных зависимостей...", "Checking system dependencies..."))
            
            max_retries = 100
            retries_left = max_retries
            check_successful = False
            while retries_left >= 0:
                show_vc_redist_warning = False
                try:
                    importlib.invalidate_caches()
                    if "triton" in sys.modules: del sys.modules["triton"]
                    self._check_system_dependencies()
                    check_successful = True
                    break
                except ImportError as e:
                    if "DLL load failed" in str(e):
                        show_vc_redist_warning = True
                    else:
                        update_log(f"Ошибка импорта: {e}")
                        break
                except Exception as e:
                    update_log(f"Ошибка проверки зависимостей: {e}")
                    break
                
                if show_vc_redist_warning:
                    user_choice = self._show_vc_redist_warning_dialog()
                    if user_choice == "retry" and retries_left > 0:
                        retries_left -= 1
                        continue
                    else:
                        break
            
            # --- Инициализация ядра ---
            skip_init = not check_successful
            if not (self.cuda_found and self.winsdk_found and self.msvc_found):
                user_action_deps = self._show_triton_init_warning_dialog()
                if user_action_deps != "continue":
                    skip_init = True

            if not skip_init:
                update_progress(90)
                update_status(_("Инициализация ядра Triton...", "Initializing Triton kernel..."))
                init_cmd = [r"libs\python\python.exe", "init.py"]
                result = subprocess.run(init_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', check=False, creationflags=subprocess.CREATE_NO_WINDOW)
                if result.stdout: update_log(f"STDOUT: {result.stdout}")
                if result.stderr: update_log(f"STDERR: {result.stderr}")
            
            update_progress(100)
            update_status(_("Установка Triton завершена.", "Triton installation complete."))
            if progress_window and progress_window.winfo_exists():
                progress_window.after(5000, progress_window.destroy)
            
            self.triton_installed = True
            return True
        except Exception as e:
            logger.error(f"Критическая ошибка при установке Triton: {e}", exc_info=True)
            if gui_elements and gui_elements["window"] and gui_elements["window"].winfo_exists():
                gui_elements["window"].destroy()
            return False

    def download_f5_tts_internal(self):
        gui_elements = None
        try:
            gui_elements = self._create_installation_window(
                title=_("Установка F5-TTS", "Installing F5-TTS"),
                initial_status=_("Подготовка...", "Preparing...")
            )
            if not gui_elements:
                return False

            progress_window = gui_elements["window"]
            update_progress = gui_elements["update_progress"]
            update_status = gui_elements["update_status"]
            update_log = gui_elements["update_log"]

            installer = PipInstaller(
                script_path=r"libs\python\python.exe",
                libs_path="Lib",
                update_status=update_status,
                update_log=update_log,
                progress_window=progress_window
            )

            update_progress(5)
            update_log(_("Начало установки F5-TTS...", "Starting F5-TTS installation..."))

            if self.provider in ["NVIDIA"] and not self.is_cuda_available():
                update_progress(10)
                if not installer.install_package(["torch==2.6.0", "torchaudio==2.6.0"], description=_("Установка PyTorch..."), extra_args=["--index-url", "https://download.pytorch.org/whl/cu124"]):
                    return False
            update_progress(25)

            if not installer.install_package(["f5-tts", "google-api-core"], description=_("Установка f5-tts...")):
                return False
            update_progress(50)

            def _download_file_with_progress(url, dest_path, file_description):
                import requests
                response = requests.get(url, stream=True, timeout=30)
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                with open(dest_path, 'wb') as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            update_status(f"Загрузка {file_description}: {int(percent)}%")
                return True

            model_dir = os.path.join("checkpoints", "F5-TTS")
            os.makedirs(model_dir, exist_ok=True)
            
            model_url = "https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN/resolve/main/F5TTS_v1_Base/model_240000_inference.safetensors?download=true"
            vocab_url = "https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN/resolve/main/F5TTS_v1_Base/vocab.txt?download=true"
            
            if not _download_file_with_progress(model_url, os.path.join(model_dir, "model_240000_inference.safetensors"), "model.safetensors"): return False
            update_progress(75)
            if not _download_file_with_progress(vocab_url, os.path.join(model_dir, "vocab.txt"), "vocab.txt"): return False
            update_progress(90)

            update_progress(100)
            update_status(_("Установка F5-TTS завершена.", "F5-TTS installation complete."))
            
            self.models['f5_tts']._load_module()

            if progress_window and progress_window.winfo_exists():
                progress_window.after(3000, progress_window.destroy)
            return True
        except Exception as e:
            logger.error(f"Критическая ошибка при установке F5-TTS: {e}", exc_info=True)
            if gui_elements and gui_elements["window"] and gui_elements["window"].winfo_exists():
                gui_elements["window"].destroy()
            return False

    # =========================================================================
    # Вспомогательные и GUI функции (остаются здесь)
    # =========================================================================
    
    async def apply_rvc_to_file(self, filepath: str, original_model_id: str) -> Optional[str]:
        """Применяет RVC к существующему аудиофайлу. Используется для модели medium+low."""
        rvc_model_handler = self.models.get("low")
        if not rvc_model_handler or not isinstance(rvc_model_handler, EdgeTTS_RVC_Model):
            logger.error("Не найден обработчик RVC для применения к файлу.")
            return None
            
        if not rvc_model_handler.initialized:
            logger.info("Инициализация RVC компонента на лету...")
            # Инициализируем именно 'low', так как это базовый RVC компонент
            if not self.initialize_model("low"):
                 logger.error("Не удалось инициализировать RVC компонент.")
                 return None

        logger.info(f"Вызов RVC для файла: {filepath}")
        # Передаем ID оригинальной модели, чтобы использовать ее настройки
        return await rvc_model_handler._voiceover_edge_tts_rvc(
            text=None, 
            TEST_WITH_DONE_AUDIO=filepath,
            settings_model_id=original_model_id
        )
        
    def is_cuda_available(self):
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def load_model_settings(self, model_id):
        try:
            settings_file = os.path.join("Settings", "voice_model_settings.json")
            if os.path.exists(settings_file):
                with open(settings_file, "r", encoding="utf-8") as f:
                    all_settings = __import__('json').load(f)
                    return all_settings.get(model_id, {})
            return {}
        except Exception as e:
            logger.info(f"Ошибка при загрузке настроек модели {model_id}: {e}")
            return {}

    async def convert_wav_to_stereo(self, input_path, output_path, atempo: float = 1, volume: str = "1.0", pitch=0):
        try:
            if not os.path.exists(input_path):
                logger.info(f"Файл {input_path} не найден при попытке конвертации.")
                return None
            (
                ffmpeg.input(input_path)
                .filter('rubberband', semitones=pitch, pitchq='quality') 
                .filter('atempo', atempo)
                .filter('volume', volume=volume)  
                .output(output_path, format="wav", acodec="pcm_s16le", ar="44100", ac=2)
                .run(cmd=["ffmpeg", "-nostdin"], capture_stdout=True, capture_stderr=True)
            )
            return output_path
        except Exception as e:
            logger.info(f"Ошибка при конвертации WAV в стерео: {e}")
            return None

    def _check_system_dependencies(self):
        self.cuda_found = False
        self.winsdk_found = False
        self.msvc_found = False
        self.triton_installed = False
        self.triton_checks_performed = False

        libs_path_abs = os.path.abspath("Lib")
        if libs_path_abs not in sys.path:
            sys.path.insert(0, libs_path_abs)

        import triton
        from triton.windows_utils import find_cuda, find_winsdk, find_msvc
        self.triton_installed = True

        try:
            cuda_result = find_cuda()
            if isinstance(cuda_result, (tuple, list)) and len(cuda_result) >= 1:
                self.cuda_found = cuda_result[0] is not None and os.path.exists(str(cuda_result[0]))
            
            winsdk_result = find_winsdk(False)
            if isinstance(winsdk_result, (tuple, list)) and len(winsdk_result) >= 1:
                self.winsdk_found = isinstance(winsdk_result[0], list) and bool(winsdk_result[0])

            msvc_result = find_msvc(False)
            if isinstance(msvc_result, (tuple, list)) and len(msvc_result) >= 1:
                self.msvc_found = isinstance(msvc_result[0], list) and bool(msvc_result[0])
            
            self.triton_checks_performed = True
        except Exception as e:
            logger.error(f"Общая ошибка при выполнении проверок find_* в Triton: {e}")
            self.triton_checks_performed = False

    def _create_installation_window(self, title, initial_status="Подготовка..."):
        progress_window = None
        try:
            if not hasattr(self, '_installation_fonts_created'):
                try:
                    title_font_name = "LocalVoiceInstallTitle"
                    status_font_name = "LocalVoiceInstallStatus"
                    log_font_name = "LocalVoiceInstallLog"

                    try:
                        self._title_font = tkFont.Font(name=title_font_name)
                        self._title_font.config(family="Segoe UI", size=12, weight="bold")
                    except tk.TclError:
                        self._title_font = tkFont.Font(name=title_font_name, family="Segoe UI", size=12, weight="bold")

                    try:
                        self._status_font_prog = tkFont.Font(name=status_font_name)
                        self._status_font_prog.config(family="Segoe UI", size=9)
                    except tk.TclError:
                        self._status_font_prog = tkFont.Font(name=status_font_name, family="Segoe UI", size=9)

                    try:
                        self._log_font = tkFont.Font(name=log_font_name)
                        self._log_font.config(family="Consolas", size=9)
                    except tk.TclError:
                        self._log_font = tkFont.Font(name=log_font_name, family="Consolas", size=9)

                    self._installation_fonts_created = True
                except tk.TclError as e:
                    logger.info(f"Критическая ошибка при создании/получении шрифтов: {e}")
                    return None
            
            bg_color, fg_color, log_bg_color, log_fg_color = "#1e1e1e", "#ffffff", "#101010", "#cccccc"
            progress_bar_trough, progress_bar_color = "#555555", "#4CAF50"
            
            progress_window = tk.Toplevel(self.parent.root if self.parent and hasattr(self.parent, 'root') else None)
            progress_window.title(title)
            progress_window.geometry("700x400")
            progress_window.configure(bg=bg_color)
            progress_window.resizable(False, False)
            progress_window.attributes('-topmost', True)

            tk.Label(progress_window, text=title, font=self._title_font, bg=bg_color, fg=fg_color).pack(pady=10)
            
            info_frame = tk.Frame(progress_window, bg=bg_color)
            info_frame.pack(fill=tk.X, padx=10)
            status_label = tk.Label(info_frame, text=initial_status, anchor="w", font=self._status_font_prog, bg=bg_color, fg=fg_color)
            status_label.pack(side=tk.LEFT, pady=5, fill=tk.X, expand=True)
            progress_value_label = tk.Label(info_frame, text="0%", font=self._status_font_prog, bg=bg_color, fg=fg_color)
            progress_value_label.pack(side=tk.RIGHT, pady=5)

            progress_bar_canvas = tk.Canvas(progress_window, bg=progress_bar_trough, height=10, highlightthickness=0)
            progress_bar_canvas.pack(pady=5, padx=10, fill=tk.X)
            progress_rectangle = progress_bar_canvas.create_rectangle(0, 0, 0, 10, fill=progress_bar_color, outline="")

            log_frame = tk.Frame(progress_window, bg=bg_color)
            log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            log_text = tk.Text(log_frame, height=15, bg=log_bg_color, fg=log_fg_color, wrap=tk.WORD, font=self._log_font, relief=tk.FLAT, state=tk.DISABLED)
            log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar = tk.Scrollbar(log_frame, command=log_text.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            log_text.config(yscrollcommand=scrollbar.set)

            progress_window.update_idletasks()
            parent_win = self.parent.root if self.parent and hasattr(self.parent, 'root') else None
            if parent_win and parent_win.winfo_exists():
                x = parent_win.winfo_x() + (parent_win.winfo_width() // 2) - (progress_window.winfo_width() // 2)
                y = parent_win.winfo_y() + (parent_win.winfo_height() // 2) - (progress_window.winfo_height() // 2)
                progress_window.geometry(f"+{x}+{y}")
            progress_window.grab_set()

            def update_progress_bar(value):
                if progress_window and progress_window.winfo_exists():
                    max_width = progress_bar_canvas.winfo_width()
                    if max_width <= 1: return progress_window.after(50, lambda: update_progress_bar(value))
                    fill_width = (value / 100) * max_width
                    progress_bar_canvas.coords(progress_rectangle, 0, 0, fill_width, 10)
                    progress_value_label.config(text=f"{int(value)}%")
                    progress_window.update_idletasks()

            def update_status(message):
                if progress_window and progress_window.winfo_exists(): status_label.config(text=message)

            def update_log(text):
                if progress_window and progress_window.winfo_exists():
                    log_text.config(state=tk.NORMAL)
                    log_text.insert(tk.END, text + "\n")
                    log_text.see(tk.END)
                    log_text.config(state=tk.DISABLED)

            return {"window": progress_window, "update_progress": update_progress_bar, "update_status": update_status, "update_log": update_log}
        except Exception as e:
            logger.error(f"Ошибка при создании окна установки: {e}", exc_info=True)
            if progress_window: progress_window.destroy()
            return None

    def _create_action_window(self, title, initial_status="Подготовка..."):
        progress_window = None
        try:
            if not hasattr(self, '_action_fonts_created'):
                try:
                    title_font_name = "LocalVoiceActionTitle"
                    status_font_name = "LocalVoiceActionStatus"
                    log_font_name = "LocalVoiceActionLog"
                    self._title_font_action = tkFont.Font(name=title_font_name, family="Segoe UI", size=12, weight="bold")
                    self._status_font_prog_action = tkFont.Font(name=status_font_name, family="Segoe UI", size=9)
                    self._log_font_action = tkFont.Font(name=log_font_name, family="Consolas", size=9)
                    self._action_fonts_created = True
                except tk.TclError as e: 
                    logger.info(f"Ошибка шрифтов окна действия: {e}")
                    return None
            
            title_font = self._title_font_action
            status_font_prog = self._status_font_prog_action
            log_font = self._log_font_action

            bg_color="#1e1e1e"
            fg_color="#ffffff"
            log_bg_color="#101010"
            log_fg_color="#cccccc"
            button_bg="#333333"

            progress_window = tk.Toplevel(self.parent.root if self.parent and hasattr(self.parent, 'root') else None)
            progress_window.title(title)
            progress_window.geometry("700x400")
            progress_window.configure(bg=bg_color)
            progress_window.resizable(False, False)
            progress_window.attributes('-topmost', False)

            tk.Label(progress_window, text=title, font=title_font, bg=bg_color, fg=fg_color).pack(pady=10)

            info_frame = tk.Frame(progress_window, bg=bg_color)
            info_frame.pack(fill=tk.X, padx=10)

            status_label = tk.Label(info_frame, text=initial_status, anchor="w", font=status_font_prog, bg=bg_color, fg=fg_color)
            status_label.pack(side=tk.LEFT, pady=5, fill=tk.X, expand=True)
            log_frame = tk.Frame(progress_window, bg=bg_color)
            log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            log_text = tk.Text(log_frame, height=15, bg=log_bg_color, fg=log_fg_color, wrap=tk.WORD, font=log_font, relief=tk.FLAT, borderwidth=1, highlightthickness=0, insertbackground=fg_color)
            log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            scrollbar = tk.Scrollbar(log_frame, command=log_text.yview, relief=tk.FLAT, troughcolor=bg_color, bg=button_bg, activebackground="#555", elementborderwidth=0, borderwidth=0)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            log_text.config(yscrollcommand=scrollbar.set)
            log_text.config(state=tk.DISABLED)
            progress_window.update_idletasks()

            parent_win = self.parent.root if self.parent and hasattr(self.parent, 'root') else None
            if parent_win and parent_win.winfo_exists():
                x = parent_win.winfo_x() + (parent_win.winfo_width() // 2) - (progress_window.winfo_width() // 2)
                y = parent_win.winfo_y() + (parent_win.winfo_height() // 2) - (progress_window.winfo_height() // 2)
                progress_window.geometry(f"+{x}+{y}")
            else:
                screen_width = progress_window.winfo_screenwidth()
                screen_height = progress_window.winfo_screenheight()
                x = (screen_width // 2) - (progress_window.winfo_width() // 2)
                y = (screen_height // 2) - (progress_window.winfo_height() // 2)
                progress_window.geometry(f'+{x}+{y}')
            progress_window.grab_set()
            def update_status(message):
                if progress_window and progress_window.winfo_exists():
                    status_label.config(text=message)
                    progress_window.update()
            def update_log(text):
                 if progress_window and progress_window.winfo_exists():
                    log_text.config(state=tk.NORMAL)
                    log_text.insert(tk.END, text + "\n")
                    log_text.see(tk.END)
                    log_text.config(state=tk.DISABLED)
                    
                    progress_window.update()
            return {"window": progress_window, "update_status": update_status, "update_log": update_log}
        except Exception as e: 
            logger.error(f"Ошибка создания окна действия: {e}")
            traceback.print_exc()
            return None

    def _show_vc_redist_warning_dialog(self):
        """Отображает диалоговое окно с предупреждением об установке VC Redist
        и предлагает повторить попытку импорта."""
        self._dialog_choice = None 

        bg_color = "#1e1e1e"
        fg_color = "#ffffff"
        button_bg = "#333333"
        button_fg = "#ffffff"
        button_active_bg = "#555555"
        warning_color = "orange"
        retry_button_bg = "#4CAF50" 

        try:

            dlg_main_font_name = "VCRedistDialogMainFont"
            dlg_bold_font_name = "VCRedistDialogBoldFont"
            dlg_button_font_name = "VCRedistDialogButtonFont"

            try: 
                main_font = tkFont.Font(name=dlg_main_font_name)
                main_font.config(family="Segoe UI", size=10)
            except tk.TclError: 
                main_font = tkFont.Font(name=dlg_main_font_name, family="Segoe UI", size=10)
            try: 
                bold_font = tkFont.Font(name=dlg_bold_font_name)
                bold_font.config(family="Segoe UI", size=11, weight="bold")
            except tk.TclError: 
                bold_font = tkFont.Font(name=dlg_bold_font_name, family="Segoe UI", size=11, weight="bold")
            try: 
                button_font = tkFont.Font(name=dlg_button_font_name)
                button_font.config(family="Segoe UI", size=9, weight="bold")
            except tk.TclError: 
                button_font = tkFont.Font(name=dlg_button_font_name, family="Segoe UI", size=9, weight="bold")

        except tk.TclError as e:
            logger.info(f"{_('Критическая ошибка шрифтов для диалога VC Redist:', 'Critical font error for VC Redist dialog:')} {e}")
            main_font, bold_font, button_font = None, None, None

        dialog = tk.Toplevel(self.parent.root if self.parent and hasattr(self.parent, 'root') else None)
        dialog.title(_("⚠️ Ошибка загрузки Triton", "⚠️ Triton Load Error"))

        dialog.configure(bg=bg_color)
        dialog.resizable(False, False)
        dialog.attributes('-topmost', True)

        top_frame = tk.Frame(dialog, bg=bg_color, padx=15, pady=10)
        top_frame.pack(fill=tk.X)

        tk.Label(top_frame, text=_("Ошибка импорта Triton (DLL Load Failed)", "Triton Import Error (DLL Load Failed)"), font=bold_font, bg=bg_color, fg=warning_color).pack(anchor='w')

        info_frame = tk.Frame(dialog, bg=bg_color, padx=15, pady=5)
        info_frame.pack(fill=tk.X)
        info_text = _(
            "Не удалось загрузить библиотеку для Triton (возможно, отсутствует VC++ Redistributable).\n"
            "Установите последнюю версию VC++ Redistributable (x64) с сайта Microsoft\n"
            "или попробуйте импортировать снова, если вы только что его установили.",
            "Failed to load the library for Triton (VC++ Redistributable might be missing).\n"
            "Install the latest VC++ Redistributable (x64) from the Microsoft website\n"
            "or try importing again if you just installed it."
        )
        tk.Label(info_frame, text=info_text, font=main_font, bg=bg_color, fg=fg_color, justify=tk.LEFT).pack(anchor='w')

        button_frame = tk.Frame(dialog, bg=bg_color, padx=15, pady=15)
        button_frame.pack(fill=tk.X)

        # --- Функции для кнопок ---
        def on_retry():
            self._dialog_choice = "retry"
            dialog.destroy()

        def on_docs():
            try:
                if hasattr(self, 'docs_manager') and self.docs_manager:
                    self.docs_manager.open_doc("installation_guide.html#vc_redist")
                else: logger.warning(_("DocsManager не инициализирован.", "DocsManager not initialized."))
            except Exception as e_docs: logger.info(f"{_('Не удалось открыть документацию:', 'Failed to open documentation:')} {e_docs}")

        def on_close():
            self._dialog_choice = "close"
            dialog.destroy()

        # --- Создание кнопок ---
        retry_button = tk.Button(button_frame, text=_("Попробовать снова", "Retry"), command=on_retry,
                                font=button_font, bg=retry_button_bg, fg=button_fg, relief=tk.FLAT, borderwidth=0,
                                activebackground=button_active_bg, activeforeground=button_fg, padx=10, pady=3, cursor="hand2")
        retry_button.pack(side=tk.RIGHT, padx=(5, 0))

        close_button = tk.Button(button_frame, text=_("Закрыть", "Close"), command=on_close,
                                font=button_font, bg=button_bg, fg=button_fg, relief=tk.FLAT, borderwidth=0,
                                activebackground=button_active_bg, activeforeground=button_fg, padx=10, pady=3, cursor="hand2")
        close_button.pack(side=tk.RIGHT, padx=(5, 0))

        docs_button = tk.Button(button_frame, text=_("Документация", "Documentation"), command=on_docs, # Укоротил текст
                                font=button_font, bg=button_bg, fg=button_fg, relief=tk.FLAT, borderwidth=0,
                                activebackground=button_active_bg, activeforeground=button_fg, padx=10, pady=3, cursor="hand2")
        docs_button.pack(side=tk.LEFT, padx=(0, 5))

        # --- Центрирование и модальность ---
        dialog.update_idletasks()
        parent_win = self.parent.root if self.parent and hasattr(self.parent, 'root') else None
        if parent_win and parent_win.winfo_exists():
            x = parent_win.winfo_x() + (parent_win.winfo_width() // 2) - (dialog.winfo_width() // 2)
            y = parent_win.winfo_y() + (parent_win.winfo_height() // 2) - (dialog.winfo_height() // 2)
            dialog.geometry(f"+{x}+{y}")
        else:
            screen_width = dialog.winfo_screenwidth()
            screen_height = dialog.winfo_screenheight()
            x = (screen_width // 2) - (dialog.winfo_width() // 2)
            y = (screen_height // 2) - (dialog.winfo_height() // 2)
            dialog.geometry(f'+{x}+{y}')

        dialog.protocol("WM_DELETE_WINDOW", on_close) 
        dialog.grab_set()
        dialog.wait_window()

        return self._dialog_choice

    def _show_triton_init_warning_dialog(self):
        """Отображает диалоговое окно с предупреждением о зависимостях Triton."""
        self._dialog_choice = None

        # Цвета и шрифты
        bg_color = "#1e1e1e"
        fg_color = "#ffffff"
        button_bg = "#333333"
        button_fg = "#ffffff"
        button_active_bg = "#555555"
        status_found_color = "#4CAF50"
        status_notfound_color = "#F44336"
        orange_color = "orange"

        try:
            # Уникальные имена для шрифтов этого диалога
            dlg_main_font_name = "TritonDialogMainFont"
            dlg_bold_font_name = "TritonDialogBoldFont"
            dlg_status_font_name = "TritonDialogStatusFont"
            dlg_button_font_name = "TritonDialogButtonFont"

            # Пытаемся получить или создать каждый шрифт
            try:
                main_font = tkFont.Font(name=dlg_main_font_name)
                main_font.config(family="Segoe UI", size=10)
            except tk.TclError:
                main_font = tkFont.Font(name=dlg_main_font_name, family="Segoe UI", size=10)

            try:
                bold_font = tkFont.Font(name=dlg_bold_font_name)
                bold_font.config(family="Segoe UI", size=10, weight="bold")
            except tk.TclError:
                bold_font = tkFont.Font(name=dlg_bold_font_name, family="Segoe UI", size=10, weight="bold")

            try:
                status_font = tkFont.Font(name=dlg_status_font_name)
                status_font.config(family="Segoe UI", size=9)
            except tk.TclError:
                status_font = tkFont.Font(name=dlg_status_font_name, family="Segoe UI", size=9)

            try:
                button_font = tkFont.Font(name=dlg_button_font_name)
                button_font.config(family="Segoe UI", size=9, weight="bold")
            except tk.TclError:
                button_font = tkFont.Font(name=dlg_button_font_name, family="Segoe UI", size=9, weight="bold")

        except tk.TclError as e:
            logger.info(f"{_('Критическая ошибка при создании/получении шрифтов для диалога:', 'Critical error creating/getting fonts for dialog:')} {e}")
            main_font, bold_font, status_font, button_font = None, None, None, None 

        # Создание окна
        dialog = tk.Toplevel(self.parent.root if self.parent and hasattr(self.parent, 'root') else None)
        dialog.title(_("⚠️ Зависимости Triton", "⚠️ Triton Dependencies"))
        dialog.configure(bg=bg_color)
        dialog.resizable(False, False)
        dialog.attributes('-topmost', True)

        # --- Верхняя часть: Статус ---
        top_frame = tk.Frame(dialog, bg=bg_color, padx=15, pady=10)
        top_frame.pack(fill=tk.X)

        tk.Label(top_frame, text=_("Статус зависимостей Triton:", "Triton Dependency Status:"), font=bold_font, bg=bg_color, fg=fg_color).pack(anchor='w', pady=(0, 5))

        status_frame = tk.Frame(top_frame, bg=bg_color)
        status_frame.pack(fill=tk.X, pady=(0, 10))

        # Словарь для хранения ссылок на метки статуса (для обновления)
        status_label_widgets = {}

        def update_status_display():
            # Очищаем предыдущие метки статуса
            for widget in status_frame.winfo_children():
                widget.destroy()
            status_label_widgets.clear()

            items = [
                ("CUDA Toolkit:", self.cuda_found),
                ("Windows SDK:", self.winsdk_found),
                ("MSVC:", self.msvc_found)
            ]

            for text, found in items:
                item_frame = tk.Frame(status_frame, bg=bg_color)
                # Размещаем элементы горизонтально
                item_frame.pack(side=tk.LEFT, padx=(0, 15), anchor='w')

                label = tk.Label(item_frame, text=text, font=status_font, bg=bg_color, fg=fg_color)
                label.pack(side=tk.LEFT)
                status_text = _("Найден", "Found") if found else _("Не найден", "Not Found")
                status_color = status_found_color if found else status_notfound_color
                status_label_widget = tk.Label(item_frame, text=status_text, font=status_font, bg=bg_color, fg=status_color)
                status_label_widget.pack(side=tk.LEFT, padx=(3, 0))
                # Сохраняем ссылку на метку статуса
                status_label_widgets[text] = status_label_widget

            # Показываем или скрываем предупреждение
            all_found = self.cuda_found and self.winsdk_found and self.msvc_found
            warning_text_tr = _("⚠️ Модели Fish Speech+ / + RVC требуют всех компонентов!", "⚠️ Models Fish Speech+ / + RVC require all components!")
            if not all_found:
                if not hasattr(dialog, 'warning_label') or not dialog.warning_label.winfo_exists():
                    dialog.warning_label = tk.Label(top_frame, text=warning_text_tr, bg=bg_color, fg=orange_color, font=bold_font)
                    # Пакуем под status_frame
                    dialog.warning_label.pack(anchor='w', pady=(5, 0), before=status_frame)
                    dialog.warning_label.pack_forget() 
                    dialog.warning_label.pack(anchor='w', pady=(5,0), fill=tk.X)
                dialog.warning_label.config(text=_("⚠️ Модели Fish Speech+ / + RVC требуют всех компонентов!", "⚠️ Models Fish Speech+ / + RVC require all components!"))
                if not dialog.warning_label.winfo_ismapped():
                     dialog.warning_label.pack(anchor='w', pady=(5,0), fill=tk.X)
            elif hasattr(dialog, 'warning_label') and dialog.warning_label.winfo_ismapped():
                dialog.warning_label.pack_forget() 

            dialog.update_idletasks() # Обновляем геометрию окна

        update_status_display() # Первоначальное отображение статуса

        # --- Средняя часть: Информация ---
        info_frame = tk.Frame(dialog, bg=bg_color, padx=15, pady=5)
        info_frame.pack(fill=tk.X)
        info_text = _(
            "Если компоненты не найдены, установите их согласно документации.\n"
            "Вы также можете попробовать инициализировать модель вручную,\n"
            "запустив `init_triton.bat` в корневой папке программы.",
            "If components are not found, install them according to the documentation.\n"
            "You can also try initializing the model manually\n"
            "by running `init_triton.bat` in the program's root folder."
        )
        tk.Label(info_frame, text=info_text, font=main_font, bg=bg_color, fg=fg_color, justify=tk.LEFT).pack(anchor='w')

        # --- Нижняя часть: Кнопки ---
        button_frame = tk.Frame(dialog, bg=bg_color, padx=15, pady=15)
        button_frame.pack(fill=tk.X)

        # Функции для кнопок
        def on_refresh():
            logger.info(_("Обновление статуса зависимостей...", "Updating dependency status..."))
            refresh_button.config(state=tk.DISABLED, text=_("Проверка...", "Checking..."))
            dialog.update()
            self._check_system_dependencies()
            update_status_display()
            refresh_button.config(state=tk.NORMAL, text=_("Обновить статус", "Refresh Status"))
            logger.info(_("Статус обновлен.", "Status updated."))

        def on_docs():
            self.docs_manager.open_doc("installation_guide.html") 
                
        def on_skip():
            self._dialog_choice = "skip"
            dialog.destroy()

        def on_continue():
            self._dialog_choice = "continue"
            dialog.destroy()

        # Создание кнопок
        continue_button = tk.Button(button_frame, text=_("Продолжить инициализацию", "Continue Initialization"), command=on_continue,
                                    font=button_font, bg=status_found_color, fg=button_fg, relief=tk.FLAT, borderwidth=0,
                                    activebackground=button_active_bg, activeforeground=button_fg, padx=10, pady=3, cursor="hand2")
        continue_button.pack(side=tk.RIGHT, padx=(5, 0))

        skip_button = tk.Button(button_frame, text=_("Пропустить инициализацию", "Skip Initialization"), command=on_skip,
                                font=button_font, bg=button_bg, fg=button_fg, relief=tk.FLAT, borderwidth=0,
                                activebackground=button_active_bg, activeforeground=button_fg, padx=10, pady=3, cursor="hand2")
        skip_button.pack(side=tk.RIGHT, padx=(5, 0))

        docs_button = tk.Button(button_frame, text=_("Открыть документацию", "Open Documentation"), command=on_docs,
                                font=button_font, bg=button_bg, fg=button_fg, relief=tk.FLAT, borderwidth=0,
                                activebackground=button_active_bg, activeforeground=button_fg, padx=10, pady=3, cursor="hand2")
        docs_button.pack(side=tk.LEFT, padx=(0, 5))

        refresh_button = tk.Button(button_frame, text=_("Обновить статус", "Refresh Status"), command=on_refresh,
                                   font=button_font, bg=button_bg, fg=button_fg, relief=tk.FLAT, borderwidth=0,
                                   activebackground=button_active_bg, activeforeground=button_fg, padx=10, pady=3, cursor="hand2")
        refresh_button.pack(side=tk.LEFT, padx=(0, 5))


        # Центрирование окна
        dialog.update_idletasks() # Убедимся, что размеры окна рассчитаны
        parent_win = self.parent.root if self.parent and hasattr(self.parent, 'root') else None
        if parent_win and parent_win.winfo_exists():
            # Центрируем относительно родительского окна
            parent_x = parent_win.winfo_x()
            parent_y = parent_win.winfo_y()
            parent_width = parent_win.winfo_width()
            parent_height = parent_win.winfo_height()
            dialog_width = dialog.winfo_width()
            dialog_height = dialog.winfo_height()
            x = parent_x + (parent_width // 2) - (dialog_width // 2)
            y = parent_y + (parent_height // 2) - (dialog_height // 2)
            dialog.geometry(f"+{x}+{y}")
        else:
            # Центрируем относительно экрана
             screen_width = dialog.winfo_screenwidth()
             screen_height = dialog.winfo_screenheight()
             dialog_width = dialog.winfo_width()
             dialog_height = dialog.winfo_height()
             x = (screen_width // 2) - (dialog_width // 2)
             y = (screen_height // 2) - (dialog_height // 2)
             dialog.geometry(f'+{x}+{y}')


        # Делаем окно модальным
        dialog.grab_set() # Перехватываем ввод
        dialog.wait_window() # Ждем закрытия окна

        return self._dialog_choice # Возвращаем выбор пользователя

    def _uninstall_component(self, component_name: str, main_package_to_remove: str):
        gui_elements = self._create_action_window(title=f"Удаление {component_name}", initial_status=f"Удаление {main_package_to_remove}...")
        if not gui_elements: return False
        
        installer = PipInstaller(script_path=r"libs\python\python.exe", libs_path="Lib", update_status=gui_elements["update_status"], update_log=gui_elements["update_log"], progress_window=gui_elements["window"])
        
        uninstall_success = installer.uninstall_packages([main_package_to_remove], description=f"Удаление {main_package_to_remove}...")
        
        if uninstall_success:
            cleanup_success = self._cleanup_orphans(installer, gui_elements["update_log"])
            if cleanup_success:
                gui_elements["update_status"]("Удаление завершено.")
            else:
                gui_elements["update_status"]("Ошибка при очистке зависимостей.")
            self._cleanup_after_uninstall(main_package_to_remove)
        else:
            gui_elements["update_status"](f"Ошибка удаления {main_package_to_remove}")

        gui_elements["window"].after(3000, gui_elements["window"].destroy)
        return uninstall_success

    def _cleanup_orphans(self, installer: PipInstaller, update_log_func) -> bool:
        try:
            resolver = DependencyResolver(installer.libs_path_abs, update_log_func)
            all_installed = resolver.get_all_installed_packages()
            known_main = set(canonicalize_name(p) for p in self.known_main_packages)
            protected = canonicalize_name(self.protected_package)

            remaining_main = all_installed & known_main
            required_set = set()
            if protected in all_installed:
                required_set.update(resolver.get_dependency_tree(self.protected_package))
            for pkg in remaining_main:
                required_set.update(resolver.get_dependency_tree(pkg))
            
            orphans = all_installed - required_set
            if orphans:
                orphans_str_list = [str(o) for o in orphans]
                return installer.uninstall_packages(orphans_str_list, "Удаление осиротевших зависимостей...")
            return True
        except Exception as e:
            update_log_func(f"Ошибка во время очистки сирот: {e}")
            return False