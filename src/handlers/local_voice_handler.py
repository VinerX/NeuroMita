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
import time
import ffmpeg
from utils.gpu_utils import check_gpu_provider

from copy import deepcopy
import hashlib
from datetime import datetime
import traceback
import site
import tempfile
import gc
import soundfile as sf
import re
from xml.sax.saxutils import escape
from typing import Dict, Optional, Any, List

from packaging.utils import canonicalize_name, NormalizedName
from utils.pip_installer import PipInstaller, DependencyResolver
from managers.settings_manager import SettingsManager

# --- Новые импорты для модульной структуры ---
from handlers.voice_models.base_model import IVoiceModel
from handlers.voice_models.edge_tts_rvc_model import EdgeTTS_RVC_Model
from handlers.voice_models.fish_speech_model import FishSpeechModel
from handlers.voice_models.f5_tts_model import F5TTSModel

from docs import DocsManager
from main_logger import logger

from utils import getTranslationVariant as _, get_character_voice_paths


from PyQt6.QtCore import QMetaObject, QThread, Qt, QObject

class LocalVoice:
    def __init__(self, parent=None):
        self.parent = parent.view
        self.settings = parent.settings if parent else SettingsManager()
        
        self.first_compiled: Optional[bool] = None

        self.current_model_id: Optional[str] = None
        self.active_model_instance: Optional[IVoiceModel] = None
        
        # Создаем один экземпляр для всех RVC-моделей
        edge_rvc_handler = EdgeTTS_RVC_Model(self, "edge_rvc_handler")
        fish_handler = FishSpeechModel(self, "fish_handler", rvc_handler=edge_rvc_handler)
        f5_handler = F5TTSModel(self, "f5_handler", rvc_handler=edge_rvc_handler)

        self.models: Dict[str, IVoiceModel] = {
            "low": edge_rvc_handler,
            "low+": edge_rvc_handler,
            "medium":        fish_handler,
            "medium+":       fish_handler,
            "medium+low":    fish_handler,
            "high": f5_handler,
            "high+low": f5_handler,
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
        self.protected_packages = ["g4f", "gigaam", "pillow", "silero-vad"]
        
        if self.is_triton_installed():
            try:
                self._check_system_dependencies()
            except Exception:
                logger.info(_("Triton установлен, но проверка зависимостей не удалась.", "Triton is installed, but dependency check failed."))

    # =========================================================================
    # НОВЫЕ ПУБЛИЧНЫЕ МЕТОДЫ (Упрощенный интерфейс)
    # =========================================================================

    # LocalVoice.py  ── внутри класса LocalVoice
    def download_model(
            self, model_id: str,
            progress_cb=None, status_cb=None, log_cb=None
        ) -> bool:
        logger.info(f"[DEBUG] LocalVoice.download_model('{model_id}') вызван")
        """
        progress_cb(int 0-100), status_cb(str), log_cb(str)
        передаются из GUI-потока; PipInstaller будет их вызывать.
        """
        model = self.models.get(model_id)
        if not model:
            logger.error(f"Unknown model id {model_id}")
            return False

        # сохраняем колбэки для install-методов
        self._external_progress = progress_cb or (lambda *_: None)
        self._external_status   = status_cb   or (lambda *_: None)
        self._external_log      = log_cb      or (lambda *_: None)

        try:
            ok = model.install(model_id)
            logger.info(f"[DEBUG] LocalVoice.download_model → install() вернул {ok}")
            if ok:
                self.current_model_id = model_id
            return ok
        finally:
            # очистка, чтобы следующий вызов был «чистым»
            for attr in ("_external_progress", "_external_status", "_external_log"):
                if hasattr(self, attr):
                    delattr(self, attr)

    def uninstall_model(self, model_id: str, status_cb=None, log_cb=None) -> bool:
        """
        Удаляет модель по ID с поддержкой колбеков для GUI
        status_cb(str), log_cb(str) передаются из GUI-потока
        """
        logger.info(f"LocalVoice.uninstall_model('{model_id}') вызван")
        
        self._external_status = status_cb or (lambda *_: None)
        self._external_log = log_cb or (lambda *_: None)
        
        try:
            if model_id in ("low", "low+"):
                return self.uninstall_edge_tts_rvc()
            elif model_id == "medium":
                return self.uninstall_fish_speech()
            elif model_id in ("medium+", "medium+low"):
                return self.uninstall_triton_component()
            elif model_id in ("high", "high+low"):
                return self.uninstall_f5_tts()
            else:
                logger.error(f"Unknown model_id for uninstall: {model_id}")
                self._external_log(_(f"Неизвестная модель: {model_id}", f"Unknown model: {model_id}"))
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при удалении модели {model_id}: {e}", exc_info=True)
            if self._external_log:
                self._external_log(f"{_('Ошибка:', 'Error:')} {str(e)}")
            return False
            
        finally:
            for attr in ("_external_status", "_external_log"):
                if hasattr(self, attr):
                    delattr(self, attr)

    def get_all_model_configs(self) -> List[Dict[str, Any]]:
        """
        Возвращает ПОЛНЫЕ конфиги из handlers.voice_models.* без каких-либо правок.
        Делает deepcopy, чтобы дальнейшая адаптация в контроллере не мутировала исходные структуры.
        """
        all_configs: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        for _mid, handler in self.models.items():
            if not handler or not hasattr(handler, "get_model_configs"):
                continue
            try:
                for cfg in (handler.get_model_configs() or []):
                    mid = cfg.get("id")
                    if not mid or mid in seen_ids:
                        continue
                    all_configs.append(cfg)
                    seen_ids.add(mid)
            except Exception as e:
                logger.warning(f"get_model_configs() у {handler} завершился ошибкой: {e}")

        return deepcopy(all_configs)
    
    def initialize_model(self, model_id: str, init: bool = False) -> bool:
        model_to_init = self.models.get(model_id)
        if not model_to_init:
            logger.error(f"Неизвестный идентификатор модели для инициализации: {model_id}")
            return False
        
        if not model_to_init.is_installed(model_id):
            logger.error(f"Модель {model_id} не установлена. Пожалуйста, установите ее сначала.")
            return False
        
        # Шаг 1: Устанавливаем ID модели, которую мы СОБИРАЕМСЯ инициализировать.
        # Это дает дочернему классу правильный контекст.
        self.current_model_id = model_id
        logger.info(f"Попытка инициализации и активации модели '{model_id}'...")

        # Шаг 2: Устанавливаем пути по умолчанию ДО инициализации
        voice_paths = get_character_voice_paths(None, self.provider)
        self.pth_path = voice_paths['pth_path']
        self.index_path = voice_paths['index_path']
        self.clone_voice_filename = voice_paths['clone_voice_filename']
        self.clone_voice_text = voice_paths['clone_voice_text']
        self.current_character_name = voice_paths['character_name']

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
        logger.success(f"Модель '{model_id}' успешно установлена как активная.")
        
        return True

    async def voiceover(self, text: str, output_file="output.wav", character: Optional[Any] = None) -> Optional[str]:
        if self.active_model_instance is None or not self.active_model_instance.initialized:
            if self.current_model_id:
                logger.warning(f"Активная модель '{self.current_model_id}' не инициализирована. Попытка автоматической инициализации...")
                if not self.initialize_model(self.current_model_id, init=False):
                    raise Exception(f"Не удалось инициализировать модель '{self.current_model_id}'.")
            else:
                raise ValueError("Модель не выбрана или не инициализирована.")
        logger.info(f"Запуск озвучки c персонажем: {character} ")

        if character is not None:
            self.current_character = character
            voice_paths = get_character_voice_paths(character, self.provider)
            self.current_character_name = voice_paths['character_name']
            self.pth_path = voice_paths['pth_path']
            self.index_path = voice_paths['index_path']
            self.clone_voice_filename = voice_paths['clone_voice_filename']
            self.clone_voice_text = voice_paths['clone_voice_text']

        return await self.active_model_instance.voiceover(text, character)

    # =========================================================================
    # Методы для управления и проверки состояния
    # =========================================================================
    
    def is_model_installed(self, model_id: str) -> bool:
        model = self.models.get(model_id)
        if model:
            return model.is_installed(model_id)
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
        return self.models["low"].uninstall("low")

    def uninstall_fish_speech(self):
        return self.models["medium"].uninstall("medium")

    def uninstall_f5_tts(self):
        return self.models["high"].uninstall("high")

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
            model_to_reset_ids = ["high", "high+low"]
            
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


    def select_model(self, model_id: str) -> None:
        """
        Делает указанную ИНИЦИАЛИЗИРОВАННУЮ модель активной.
        Исключений не бросает – вызывающий уже проверил is_model_initialized().
        """
        model = self.models.get(model_id)
        if not model or not model.initialized:
            raise RuntimeError(f"Model '{model_id}' is not initialised")
        self.current_model_id      = model_id
        self.active_model_instance = model
        logger.info(f"Active local voice model set to '{model_id}'")

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

    def convert_wav_to_stereo(
        self,
        input_path      : str,
        output_path     : str,
        *,
        atempo : float  = 1.0,
        volume : str    = "1.0",
        pitch  : float  = 0.0,
        show_call_stack: bool = False,
        save_err_to    : str | None = None   # путь для сохранения stderr
    ) -> str | None:
        """
        Конвертирует WAV → стерео WAV.
        При ошибке:
        •  логирует полный traceback,
        •  выводит stderr FFmpeg,
        •  (опция) записывает stderr в файл.
        """

        if show_call_stack:
            logger.debug(
                "[convert_wav_to_stereo] call-stack:\n" +
                "".join(traceback.format_stack(limit=15))
            )

        if not os.path.exists(input_path):
            err = f"Файл не найден: {input_path}"
            logger.error(err)
            raise FileNotFoundError(err)

        try:
            pitch_ratio = 2 ** (pitch / 12.0)
            # ───────── запуск FFmpeg ─────────
            out, err = (
                ffmpeg
                .input(input_path)
                .filter("rubberband", pitch=pitch_ratio, pitchq="quality")
                .filter("atempo", atempo)
                .filter("volume", volume=volume)
                .output(
                    output_path,
                    format="wav",
                    acodec="pcm_s16le",
                    ar="44100",
                    ac=2
                )
                .run(
                    cmd=["ffmpeg", "-nostdin"],
                    capture_stdout=True,
                    capture_stderr=True,
                    overwrite_output=True
                )
            )
            # Можно залогировать вывод, если нужен
            logger.debug(f"FFmpeg stdout:\n{out.decode(errors='ignore')}")
            return output_path

        except ffmpeg.Error as fe:
            # Здесь уже полноценный трейс + stderr FFmpeg
            tb = traceback.format_exc()
            ff_err = fe.stderr.decode(errors="ignore") if fe.stderr else "«stderr пуст»"

            logger.error(
                "[convert_wav_to_stereo] FFmpeg ERROR\n" +
                "-"*60 + "\n" +
                ff_err + "\n" +
                "-"*60 + "\n" +
                tb
            )

            # Сохраняем stderr на диск (по желанию)
            if save_err_to:
                try:
                    with open(save_err_to, "w", encoding="utf-8", errors="ignore") as f:
                        f.write(ff_err)
                    logger.info(f"stderr FFmpeg сохранён в {save_err_to}")
                except Exception as save_e:
                    logger.warning(f"Не удалось сохранить stderr: {save_e}")

            raise   # пробрасываем наружу – пусть вызывающий решает, что делать

        except Exception:
            # Любая другая ошибка
            logger.error("[convert_wav_to_stereo] Unexpected error:\n" + traceback.format_exc())
            raise

    def _check_system_dependencies(self):
        """Проверяет наличие CUDA, Windows SDK и MSVC с помощью triton.
        Предполагается, что вызывающий код обработает ImportError при импорте triton."""
        self.cuda_found = False
        self.winsdk_found = False
        self.msvc_found = False
        self.triton_installed = False
        self.triton_checks_performed = False

        libs_path_abs = os.path.abspath("Lib")
        if libs_path_abs not in sys.path:
            sys.path.insert(0, libs_path_abs)
            logger.info(f"Добавлен путь {libs_path_abs} в sys.path для поиска Triton")

        # Попытка импорта (ImportError ловится выше в download_triton)
        import triton
        from triton.windows_utils import find_cuda, find_winsdk, find_msvc

        self.triton_installed = True # Импорт успешен
        logger.success("Triton импортирован успешно внутри _check_system_dependencies.")

        # --- Проверка CUDA, WinSDK, MSVC с обработкой ошибок ---
        try:
            # CUDA
            try:
                cuda_result = find_cuda()
                logger.info(f"CUDA find_cuda() result: {cuda_result}")
                if isinstance(cuda_result, (tuple, list)) and len(cuda_result) >= 1:
                    cuda_path = cuda_result[0]
                    self.cuda_found = cuda_path is not None and os.path.exists(str(cuda_path))
                else: 
                    self.cuda_found = False
            except Exception as e_cuda:
                logger.warning(f"Ошибка при проверке CUDA: {e_cuda}")
                self.cuda_found = False
            logger.info(f"CUDA Check: Found={self.cuda_found}")

            # WinSDK
            try:
                winsdk_result = find_winsdk(False)
                logger.info(f"WinSDK find_winsdk() result: {winsdk_result}")
                if isinstance(winsdk_result, (tuple, list)) and len(winsdk_result) >= 1:
                    winsdk_paths = winsdk_result[0]
                    self.winsdk_found = isinstance(winsdk_paths, list) and bool(winsdk_paths)
                else: 
                    self.winsdk_found = False
            except Exception as e_winsdk:
                logger.warning(f"Ошибка при проверке WinSDK: {e_winsdk}")
                self.winsdk_found = False
            logger.info(f"WinSDK Check: Found={self.winsdk_found}")

            # MSVC
            try:
                msvc_result = find_msvc(False)
                logger.info(f"MSVC find_msvc() result: {msvc_result}")
                cl_path = None
                inc_paths, lib_paths = [], []
                if isinstance(msvc_result, (tuple, list)):
                    if len(msvc_result) >= 1:
                        cl_path = msvc_result[0]
                    if len(msvc_result) >= 2:
                        inc_paths = msvc_result[1] or []
                    if len(msvc_result) >= 3:
                        lib_paths = msvc_result[2] or []
                self.msvc_found = bool((cl_path and os.path.exists(str(cl_path))) or inc_paths or lib_paths)
            except Exception as e_msvc:
                logger.warning(f"Ошибка при проверке MSVC: {e_msvc}")
                self.msvc_found = False
            logger.info(f"MSVC Check: Found={self.msvc_found}")

            # Если дошли сюда без общих ошибок, считаем проверки выполненными
            self.triton_checks_performed = True

        except Exception as e:
            logger.error(f"Общая ошибка при выполнении проверок find_* в Triton: {e}")
            logger.error(traceback.format_exc())
            # triton_installed остается True, но проверки не выполнены
            self.triton_checks_performed = False

    def _show_vc_redist_warning_dialog(self):
        from core.events import get_event_bus, Events
        event_bus = get_event_bus()
        
        result = event_bus.emit_and_wait(Events.Audio.SHOW_VC_REDIST_DIALOG, timeout=60.0)
        return result[0] if result else 'close'

    def _show_triton_init_warning_dialog(self):
        from core.events import get_event_bus, Events
        event_bus = get_event_bus()
        
        dependencies_data = {
            'cuda_found': self.cuda_found,
            'winsdk_found': self.winsdk_found,
            'msvc_found': self.msvc_found
        }
        
        result = event_bus.emit_and_wait(Events.Audio.SHOW_TRITON_DIALOG, dependencies_data, timeout=60.0)
        return result[0] if result else 'skip'

    def get_triton_status(self):
        """Возвращает текущий статус зависимостей Triton"""
        return {
            'cuda_found': self.cuda_found,
            'winsdk_found': self.winsdk_found,
            'msvc_found': self.msvc_found,
            'triton_installed': self.triton_installed,
            'triton_checks_performed': self.triton_checks_performed
        }

    def _uninstall_component(self, component_name: str, main_package_to_remove: str) -> bool:
        try:
            status_cb = getattr(self, '_external_status', lambda *_: None)
            log_cb = getattr(self, '_external_log', lambda *_: None)

            installer = PipInstaller(
                script_path=r"libs\python\python.exe", libs_path="Lib",
                update_status=status_cb, update_log=log_cb,
                progress_window=None
            )

            log_cb(_(f"Удаление '{main_package_to_remove}'...", f"Uninstalling '{main_package_to_remove}'..."))
            uninstall_success = installer.uninstall_packages(
                [main_package_to_remove],
                _(f"Удаление {main_package_to_remove}...", f"Uninstalling {main_package_to_remove}...")
            )

            if not uninstall_success:
                log_cb(_(f"Не удалось удалить '{main_package_to_remove}'.", f"Failed to uninstall '{main_package_to_remove}'."))
                status_cb(_(f"Ошибка удаления {main_package_to_remove}", f"Error uninstalling {main_package_to_remove}"))
                return False

            status_cb(_("Очистка зависимостей...", "Cleaning up dependencies..."))
            log_cb(_("Поиск 'осиротевших' зависимостей...", "Finding 'orphaned' dependencies..."))
            cleanup_success = self._cleanup_orphans(installer, log_cb)

            if cleanup_success:
                status_cb(_("Удаление завершено.", "Uninstallation complete."))
                log_cb(_("Очистка завершена.", "Cleanup complete."))
            else:
                status_cb(_("Ошибка очистки.", "Cleanup error."))
                log_cb(_("Не удалось удалить некоторые зависимости.", "Failed to remove some dependencies."))

            self._cleanup_after_uninstall(main_package_to_remove)
            return uninstall_success and cleanup_success

        except Exception as e:
            logger.error(f"Ошибка при удалении {component_name}: {e}")
            traceback.print_exc()
            if hasattr(self, '_external_log'):
                self._external_log(f"{_('Ошибка:', 'Error:')} {e}\n{traceback.format_exc()}")
            if hasattr(self, '_external_status'):
                self._external_status(_("Критическая ошибка!", "Critical error!"))
            return False

    def _cleanup_orphans(self, installer: PipInstaller, update_log_func) -> bool:
        try:
            resolver = DependencyResolver(installer.libs_path_abs, update_log_func)
            all_installed_canon = resolver.get_all_installed_packages()  # set[NormalizedName]
            known_main_canon = set(canonicalize_name(p) for p in self.known_main_packages)
            remaining_main_canon = all_installed_canon & known_main_canon

            # Защищённые пакеты и их deps (универсально для списка)
            protected_deps_canon = set()
            for prot_pkg in self.protected_packages:
                prot_canon = canonicalize_name(prot_pkg)
                if prot_canon in all_installed_canon:
                    deps = resolver.get_dependency_tree(prot_pkg) or {prot_canon}  # Включаем себя, если deps пустые
                    protected_deps_canon.update(deps)
                    update_log_func(_(f"Зависимости {prot_pkg}: {deps or 'Нет'}", f"Dependencies of {prot_pkg}: {deps or 'None'}"))

            # Deps оставшихся main пакетов
            other_required_deps_canon = set()
            for pkg_canon in remaining_main_canon:
                deps = resolver.get_dependency_tree(str(pkg_canon)) or {pkg_canon}  # str на случай, если нужно original
                other_required_deps_canon.update(deps)

            required_set_canon = protected_deps_canon | other_required_deps_canon
            orphans_canon = all_installed_canon - required_set_canon

            if not orphans_canon:
                update_log_func(_("Осиротевшие не найдены.", "No orphans found."))
                return True

            # Получаем original names из dist-info
            installed_packages_map = {}
            if os.path.exists(installer.libs_path_abs):
                for item in os.listdir(installer.libs_path_abs):
                    if item.endswith(".dist-info"):
                        try:
                            dist_name = item.split('-')[0]
                            installed_packages_map[canonicalize_name(dist_name)] = dist_name
                        except Exception:
                            pass

            orphans_original_names = [installed_packages_map.get(o, str(o)) for o in orphans_canon]
            update_log_func(_(f"Удаление сирот: {orphans_original_names}", f"Uninstalling orphans: {orphans_original_names}"))

            return installer.uninstall_packages(
                orphans_original_names,  # Позиционный аргумент: список пакетов
                _("Удаление осиротевших...", "Uninstalling orphaned...")
            )

        except Exception as e:
            update_log_func(_(f"Ошибка очистки: {e}", f"Cleanup error: {e}"))
            update_log_func(traceback.format_exc())
            return False