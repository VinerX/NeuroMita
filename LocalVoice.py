# LocalVoice.py
# Файл для установки локальной озвучки. 
# Из того, что можно сделать - вынести ffmpeg функцию в AudioConverter.py

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

from packaging.utils import canonicalize_name, NormalizedName
from utils.PipInstaller import PipInstaller, DependencyResolver

from SettingsManager import SettingsManager

def getTranslationVariant(ru_str, en_str=""):
    if en_str and SettingsManager.get("LANGUAGE") == "EN":
        return en_str
    return ru_str

_ = getTranslationVariant


import json
from docs import DocsManager
from Logger import logger
last_used_tts_rvc = None
tts_rvc = None
fish_speech_tts = None
last_compile = None

class LocalVoice:
    def __init__(self, parent=None):
        self.first_compiled = None
        self.parent = parent
        self.current_model = None
        self.pth_path = None
        self.index_path = None
        self.clone_voice_folder = "Models"
        self.clone_voice_filename = None
        self.clone_voice_text = None

        self.current_tts_rvc = None
        self.current_fish_speech = None
        self.current_silero_model = None 
        self.current_silero_sample_rate = 48000 
        self.silero_models_dir = "checkpoints/silero" 
        self.current_character_name = ""

        self.voice_language = self.parent.settings.get("VOICE_LANGUAGE", "ru")

        self.initialized_models = set()
        self.docs_manager = DocsManager()

        self.tts_rvc_module = None
        self.fish_speech_module = None
        self.zonos_module = None
        
        self.amd_test = os.environ.get('TEST_AS_AMD', '').upper() == 'TRUE'

        self.provider = check_gpu_provider()

        if self.provider in ["AMD"] or self.amd_test:
            logger.info("KMP_DUPLICATE_LIB_OK = TRUE")
            os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

        self.known_main_packages = ["tts-with-rvc", "fish-speech-lib", "triton-windows"]
        self.protected_package = "g4f"

        self.cuda_found = False
        self.winsdk_found = False
        self.msvc_found = False
        self.triton_installed = False
        self.triton_checks_performed = False
        self._dialog_choice = None

        try:
            from tts_with_rvc import TTS_RVC
            self.tts_rvc_module = TTS_RVC
        except ImportError:
            logger.info(_("Модуль tts_with_rvc не установлен", "Module tts_with_rvc is not installed"))


        try:
            from fish_speech_lib.inference import FishSpeech
            self.fish_speech_module = FishSpeech
        except ImportError:
            logger.info(_("Модуль fish_speech_lib не установлен", "Module fish_speech_lib is not installed"))


        try:
            import zonos123
            self.zonos_module = zonos123
        except ImportError:
            logger.info("Некий модуль.")

        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
            alt_base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(__file__)
            alt_base_dir = base_dir

        try: 
            self._check_system_dependencies()
        except:
            logger.info(_("Triton не установлен корректно.", "Triton is not installed correctly."))

    def uninstall_edge_tts_rvc(self):
        return self._uninstall_component("EdgeTTS+RVC", "tts-with-rvc")

    def uninstall_fish_speech(self):
        return self._uninstall_component("Fish Speech", "fish-speech-lib")

    def uninstall_triton_component(self):
        return self._uninstall_component("Triton", "triton-windows")

    def download_model(self, model_id):
        """Загрузка модели по её идентификатору"""
        if model_id == "low":
            try:
                if not self.is_edge_tts_rvc_installed():
                    if not self.download_edge_tts_rvc():
                        return False

                self.current_model = "low"
                return True
            except Exception as ex:
                logger.info("error:", ex)
                return False
        elif model_id == "low+": # Добавлен блок
            try:
                if not self.is_edge_tts_rvc_installed():
                    if not self.download_edge_tts_rvc():
                        return False
                # Загрузка самой модели Silero происходит при инициализации
                self.current_model = "low+"
                return True
            except Exception as ex:
                logger.info("error:", ex)
                return False

        elif model_id == "medium":
            try:
                if not self.is_fish_speech_installed():
                    if not self.download_fish_speech():
                        return False
                self.current_model = "medium"
                return True
            except Exception as ex:
                logger.info("error:", ex)
                return False
        elif model_id == "medium+":
            try:
                if not self.is_fish_speech_installed():
                    if not self.download_fish_speech():
                        return False
                if not self.is_triton_installed():
                    if not self.download_triton():
                        return False
                self.current_model = "medium+"
                return True
            except Exception as ex:
                logger.info("error:", ex)
                return False

        elif model_id == "medium+low":
            try:
                if not self.is_fish_speech_installed():
                    if not self.download_fish_speech():
                        return False
                if not self.is_edge_tts_rvc_installed():
                    if not self.download_edge_tts_rvc():
                        return False
                if not self.is_triton_installed():
                    if not self.download_triton():
                        return False
                self.current_model = "medium+low"
                return True
            except Exception as ex:
                logger.info("error:", ex)
                return False
        # elif model_id == "high":
        #     return self.download_zonos()
        else:
            try:
                raise ValueError(f"Неизвестный идентификатор модели: {model_id}")
            except Exception as ex:
                logger.info("error:", ex)
                return False

    def _cleanup_after_uninstall(self, removed_package_name: str):
        logger.info(f"Очистка состояния LocalVoice после удаления пакета: {removed_package_name}")
        original_current_model = self.current_model
        model_id_to_clear = None

        if removed_package_name == "tts-with-rvc":
            if self.current_model in ["low", "low+"]: 
                self.current_model = None
            if "low" in self.initialized_models: 
                self.initialized_models.remove("low")
            if "low+" in self.initialized_models: 
                self.initialized_models.remove("low+")
            if self.current_tts_rvc: 
                self.current_tts_rvc = None
            if self.current_silero_model: 
                self.current_silero_model = None 

            self.tts_rvc_module = None
            model_id_to_clear = "low/low+" 
        elif removed_package_name == "fish-speech-lib":
            if self.current_model in ["medium", "medium+", "medium+low"]: 
                self.current_model = None
            if "medium" in self.initialized_models: 
                self.initialized_models.remove("medium")
            if self.current_fish_speech: 
                self.current_fish_speech = None

            self.fish_speech_module = None
            model_id_to_clear = "medium"

        elif removed_package_name == "triton-windows":
            if self.current_model in ["medium+", "medium+low"]: 
                self.current_model = None
            if "medium+" in self.initialized_models: 
                self.initialized_models.remove("medium+")
            if "medium+low" in self.initialized_models: 
                self.initialized_models.remove("medium+low")

            self.triton_installed = False
            self.triton_checks_performed = False
            self.cuda_found = False
            self.winsdk_found = False
            self.msvc_found = False
            self.triton_module = False
            model_id_to_clear = "triton"

        if model_id_to_clear: 
            logger.info(f"Состояние для компонента '{model_id_to_clear}' сброшено.")
        if original_current_model and original_current_model == self.current_model:
            pass 
        elif original_current_model and original_current_model != self.current_model:
            logger.info(f"Текущая модель сброшена (была {original_current_model}).")

        try: importlib.invalidate_caches()
        except Exception: pass

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
        logger.info("Triton импортирован успешно внутри _check_system_dependencies.")

        # --- Проверка CUDA, WinSDK, MSVC с обработкой ошибок ---
        try:
            # CUDA
            try:
                cuda_result = find_cuda()
                logger.info(f"CUDA find_cuda() result: {cuda_result}")
                if isinstance(cuda_result, (tuple, list)) and len(cuda_result) >= 1:
                    cuda_path = cuda_result[0]
                    self.cuda_found = cuda_path is not None and os.path.exists(str(cuda_path))
                else: self.cuda_found = False
            except Exception as e_cuda:
                logger.warning(f"Ошибка при проверке CUDA: {e_cuda}") # Warning, т.к. не критично для самой проверки
                self.cuda_found = False
            logger.info(f"CUDA Check: Found={self.cuda_found}")

            # WinSDK
            try:
                winsdk_result = find_winsdk(False)
                logger.info(f"WinSDK find_winsdk() result: {winsdk_result}")
                if isinstance(winsdk_result, (tuple, list)) and len(winsdk_result) >= 1:
                    winsdk_paths = winsdk_result[0]
                    self.winsdk_found = isinstance(winsdk_paths, list) and bool(winsdk_paths)
                else: self.winsdk_found = False
            except Exception as e_winsdk:
                logger.warning(f"Ошибка при проверке WinSDK: {e_winsdk}")
                self.winsdk_found = False
            logger.info(f"WinSDK Check: Found={self.winsdk_found}")

            # MSVC
            try:
                msvc_result = find_msvc(False)
                logger.info(f"MSVC find_msvc() result: {msvc_result}")
                if isinstance(msvc_result, (tuple, list)) and len(msvc_result) >= 1:
                    msvc_paths = msvc_result[0]
                    self.msvc_found = isinstance(msvc_paths, list) and bool(msvc_paths)
                else: self.msvc_found = False
            except Exception as e_msvc:
                logger.warning(f"Ошибка при проверке MSVC: {e_msvc}")
                self.msvc_found = False
            logger.info(f"MSVC Check: Found={self.msvc_found}")

            # Если дошли сюда без общих ошибок, считаем проверки выполненными
            self.triton_checks_performed = True

        except Exception as e:
            logger.error(f"Общая ошибка при выполнении проверок find_* в Triton: {e}")
            traceback.print_exc()
            # triton_installed остается True, но проверки не выполнены
            self.triton_checks_performed = False
    
    def _create_installation_window(self, title, initial_status="Подготовка..."):
        """Создает и настраивает окно прогресса установки."""
        progress_window = None
        try:
            # --- Настройка окна прогресса ---
            if not hasattr(self, '_installation_fonts_created'):
                try:
                    title_font_name = "LocalVoiceInstallTitle"
                    status_font_name = "LocalVoiceInstallStatus"
                    log_font_name = "LocalVoiceInstallLog"

                    try:
                        self._title_font = tkFont.Font(name=title_font_name)
                        # Если шрифт существует, просто обновим его параметры (если нужно)
                        self._title_font.config(family="Segoe UI", size=12, weight="bold")
                        logger.info(f"Используется существующий шрифт: {title_font_name}")
                    except tk.TclError:
                        # Если не существует, создаем
                        self._title_font = tkFont.Font(name=title_font_name, family="Segoe UI", size=12, weight="bold")
                        logger.info(f"Создан новый шрифт: {title_font_name}")

                    try:
                        self._status_font_prog = tkFont.Font(name=status_font_name)
                        self._status_font_prog.config(family="Segoe UI", size=9)
                        logger.info(f"Используется существующий шрифт: {status_font_name}")
                    except tk.TclError:
                        self._status_font_prog = tkFont.Font(name=status_font_name, family="Segoe UI", size=9)
                        logger.info(f"Создан новый шрифт: {status_font_name}")

                    try:
                        self._log_font = tkFont.Font(name=log_font_name)
                        self._log_font.config(family="Consolas", size=9)
                        logger.info(f"Используется существующий шрифт: {log_font_name}")
                    except tk.TclError:
                        self._log_font = tkFont.Font(name=log_font_name, family="Consolas", size=9)
                        logger.info(f"Создан новый шрифт: {log_font_name}")

                    self._installation_fonts_created = True

                except tk.TclError as e:
                    logger.info(f"Критическая ошибка при создании/получении шрифтов: {e}")
                    return None

            
            title_font = self._title_font
            status_font_prog = self._status_font_prog
            log_font = self._log_font

            bg_color = "#1e1e1e"
            fg_color = "#ffffff"
            log_bg_color = "#101010"
            log_fg_color = "#cccccc"
            progress_bar_bg = "#333333" # Фон полосы прогресса (не используется напрямую для canvas)
            progress_bar_trough = "#555555" # Цвет желоба
            progress_bar_color = "#4CAF50" # Цвет самой полосы
            button_bg = "#333333" # Для возможных будущих кнопок

            progress_window = tk.Toplevel(self.parent.root if self.parent and hasattr(self.parent, 'root') else None)
            progress_window.title(title)
            progress_window.geometry("700x400")
            progress_window.configure(bg=bg_color)
            progress_window.resizable(False, False)
            progress_window.attributes('-topmost', True)

            
            tk.Label(progress_window, text=title, font=title_font, bg=bg_color, fg=fg_color).pack(pady=10)

            # Фрейм для статуса и процента
            info_frame = tk.Frame(progress_window, bg=bg_color)
            info_frame.pack(fill=tk.X, padx=10)
            status_label = tk.Label(info_frame, text=initial_status, anchor="w", font=status_font_prog, bg=bg_color, fg=fg_color)
            status_label.pack(side=tk.LEFT, pady=5, fill=tk.X, expand=True)
            progress_value_label = tk.Label(info_frame, text="0%", font=status_font_prog, bg=bg_color, fg=fg_color)
            progress_value_label.pack(side=tk.RIGHT, pady=5)

            # --- Ручной Progress Bar ---
            progress_bar_height = 10
            progress_bar_frame = tk.Frame(progress_window, bg=progress_bar_trough, height=progress_bar_height, relief=tk.FLAT, borderwidth=0)
            progress_bar_frame.pack(pady=5, padx=10, fill=tk.X)
            progress_bar_canvas = tk.Canvas(progress_bar_frame, bg=progress_bar_trough, height=progress_bar_height, highlightthickness=0)
            progress_bar_canvas.pack(fill=tk.BOTH, expand=True)
            progress_rectangle = progress_bar_canvas.create_rectangle(0, 0, 0, progress_bar_height, fill=progress_bar_color, outline="")

            def update_progress_bar(value):
                value = max(0, min(100, int(value)))
                if progress_window and progress_window.winfo_exists():
                    max_width = progress_bar_canvas.winfo_width()
                    if max_width <= 1: 
                        progress_window.after(50, lambda: update_progress_bar(value))
                        return
                    fill_width = (value / 100) * max_width
                    progress_bar_canvas.coords(progress_rectangle, 0, 0, fill_width, progress_bar_height)
                    progress_value_label.config(text=f"{value}%") 
                    progress_window.update_idletasks()

            # --- Лог ---
            log_frame = tk.Frame(progress_window, bg=bg_color)
            log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            log_text = tk.Text(log_frame, height=15, bg=log_bg_color, fg=log_fg_color, wrap=tk.WORD, font=log_font, relief=tk.FLAT, borderwidth=1, highlightthickness=0, insertbackground=fg_color)
            log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            # Используем tk.Scrollbar
            scrollbar = tk.Scrollbar(log_frame, command=log_text.yview, relief=tk.FLAT, troughcolor=bg_color, bg=button_bg, activebackground=progress_bar_trough, elementborderwidth=0, borderwidth=0)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            log_text.config(yscrollcommand=scrollbar.set)
            log_text.config(state=tk.DISABLED) # Блокируем редактирование

            # Центрирование окна
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

            progress_window.grab_set() # Модальное окно

            # --- Вспомогательные функции для обновления GUI (возвращаемые) ---
            def update_status(message):
                 if progress_window and progress_window.winfo_exists():
                    status_label.config(text=message)
                    progress_window.update()

            def update_log(text):
                 if progress_window and progress_window.winfo_exists():
                    log_text.config(state=tk.NORMAL)
                    log_text.insert(tk.END, text + "\n")
                    log_text.see(tk.END) # Автопрокрутка
                    log_text.config(state=tk.DISABLED)
                    progress_window.update()

            # Возвращаем словарь с элементами управления
            return {
                "window": progress_window,
                "update_progress": update_progress_bar,
                "update_status": update_status,
                "update_log": update_log
            }

        except Exception as e:
            logger.info(f"Ошибка при создании окна установки: {e}")
            traceback.print_exc()
            if progress_window and progress_window.winfo_exists():
                try:
                    progress_window.destroy()
                except:
                    pass
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
            progress_window.attributes('-topmost', True)

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
    
    # region Окна предупреждений:
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
    #endregion
    
    #region Установка моделей

    def _uninstall_component(self, component_name: str, main_package_to_remove: str):
        gui_elements = None
        uninstall_success = False
        cleanup_success = False
        try:
            gui_elements = self._create_action_window(
                title=_(f"Удаление {component_name}", f"Uninstalling {component_name}"),
                initial_status=_(f"Удаление основного пакета {main_package_to_remove}...", f"Uninstalling main package {main_package_to_remove}...")
            )
            if not gui_elements: return False
            update_status = gui_elements["update_status"]
            update_log = gui_elements["update_log"]

            installer = PipInstaller(
                script_path=r"libs\python\python.exe", libs_path="Lib",
                update_status=update_status, update_log=update_log,
                progress_window=gui_elements["window"]
            )

            # Этап 1: Удаление основного пакета
            update_log(_(f"Этап 1: Удаление основного пакета '{main_package_to_remove}'...", f"Step 1: Uninstalling main package '{main_package_to_remove}'..."))
            uninstall_success = installer.uninstall_packages(
                packages_to_uninstall=[main_package_to_remove],
                description=_(f"Удаление {main_package_to_remove}...", f"Uninstalling {main_package_to_remove}...")
            )

            if not uninstall_success:
                update_log(_(f"Не удалось удалить основной пакет '{main_package_to_remove}'. Процесс остановлен.", f"Failed to uninstall main package '{main_package_to_remove}'. Process stopped."))
                update_status(_(f"Ошибка удаления {main_package_to_remove}", f"Error uninstalling {main_package_to_remove}"))
            else:
                update_log(_(f"Основной пакет '{main_package_to_remove}' успешно удален (или отсутствовал).", f"Main package '{main_package_to_remove}' successfully uninstalled (or was missing)."))
                update_status(_("Очистка неиспользуемых зависимостей...", "Cleaning up unused dependencies..."))
                update_log(_("Этап 2: Поиск и удаление 'осиротевших' зависимостей...", "Step 2: Finding and removing 'orphaned' dependencies..."))
                cleanup_success = self._cleanup_orphans(installer, update_log)
                if cleanup_success:
                    update_status(_("Удаление завершено.", "Uninstallation complete."))
                    update_log(_("Очистка зависимостей завершена.", "Dependency cleanup complete."))
                else:
                    update_status(_("Ошибка при очистке зависимостей.", "Error during dependency cleanup."))
                    update_log(_("Не удалось удалить некоторые 'осиротевшие' зависимости.", "Failed to remove some 'orphaned' dependencies."))

            # Обновляем состояние LocalVoice только если основной пакет удален успешно
            if uninstall_success:
                 self._cleanup_after_uninstall(main_package_to_remove) # Используем имя пакета для очистки

            if gui_elements and gui_elements["window"].winfo_exists():
                gui_elements["window"].after(3000, gui_elements["window"].destroy)

            # Возвращаем успех, только если оба этапа прошли (или очистка не требовалась)
            return uninstall_success and cleanup_success

        except Exception as e:
            logger.error(f"{_('Критическая ошибка при удалении', 'Critical error during')} {component_name} {_('удалении:', 'uninstallation:')} {e}")
            traceback.print_exc()
            if gui_elements and gui_elements["window"] and gui_elements["window"].winfo_exists():
                try:
                    gui_elements["update_log"](f"{_('КРИТИЧЕСКАЯ ОШИБКА:', 'CRITICAL ERROR:')} {e}\n{traceback.format_exc()}")
                    gui_elements["update_status"](_("Критическая ошибка удаления!", "Critical uninstallation error!"))
                    gui_elements["window"].after(5000, gui_elements["window"].destroy)
                except: pass
            return False

    def _cleanup_orphans(self, installer: PipInstaller, update_log_func) -> bool:
        try:
            resolver = DependencyResolver(installer.libs_path_abs, update_log_func)

            all_installed_canon = resolver.get_all_installed_packages()
            known_main_canon = set(canonicalize_name(p) for p in self.known_main_packages)
            protected_canon = canonicalize_name(self.protected_package)

            remaining_main_canon = (all_installed_canon & known_main_canon)
            update_log_func(_(f"Обнаружены установленные основные пакеты (кроме g4f): {remaining_main_canon or 'Нет'}", f"Detected installed main packages (excluding g4f): {remaining_main_canon or 'None'}"))

            g4f_deps_canon = set()
            if protected_canon in all_installed_canon:
                update_log_func(_(f"Построение дерева зависимостей для защищенного пакета: {self.protected_package}", f"Building dependency tree for protected package: {self.protected_package}"))
                g4f_deps_canon = resolver.get_dependency_tree(self.protected_package)
                if not g4f_deps_canon:
                    g4f_deps_canon = {protected_canon}
                update_log_func(_(f"Зависимости {self.protected_package}: {g4f_deps_canon or 'Нет'}", f"Dependencies of {self.protected_package}: {g4f_deps_canon or 'None'}"))
            else:
                update_log_func(_(f"Защищенный пакет {self.protected_package} не установлен.", f"Protected package {self.protected_package} is not installed."))

            other_required_deps_canon = set()
            if remaining_main_canon:
                update_log_func(_("Построение дерева зависимостей для оставшихся основных пакетов...", "Building dependency tree for remaining main packages..."))

                for pkg_canon in remaining_main_canon:
                    deps = resolver.get_dependency_tree(pkg_canon) 
                    other_required_deps_canon.update(deps) 
                update_log_func(_(f"Зависимости оставшихся: {other_required_deps_canon or 'Нет'}", f"Dependencies of remaining: {other_required_deps_canon or 'None'}"))

            required_set_canon = g4f_deps_canon | other_required_deps_canon
            update_log_func(_(f"Полный набор необходимых пакетов: {required_set_canon or 'Нет'}", f"Full set of required packages: {required_set_canon or 'None'}"))

            orphans_canon = all_installed_canon - required_set_canon
            update_log_func(_(f"Обнаружены 'осиротевшие' пакеты: {orphans_canon or 'Нет'}", f"Detected 'orphaned' packages: {orphans_canon or 'None'}"))

            if orphans_canon:
                installed_packages_map = {}
                if os.path.exists(installer.libs_path_abs):
                    for item in os.listdir(installer.libs_path_abs):
                         if item.endswith(".dist-info"):
                             try:
                                 dist_name = item.split('-')[0]
                                 installed_packages_map[canonicalize_name(dist_name)] = dist_name
                             except Exception: pass

                orphans_original_names = [installed_packages_map.get(o_canon, str(o_canon)) for o_canon in orphans_canon] # Преобразуем NormalizedName в строку на всякий случай
                update_log_func(_(f"Попытка удаления сирот: {orphans_original_names}", f"Attempting to uninstall orphans: {orphans_original_names}"))
                return installer.uninstall_packages(orphans_original_names, _("Удаление осиротевших зависимостей...", "Uninstalling orphaned dependencies..."))
            else:
                update_log_func(_("Осиротевшие зависимости не найдены.", "Orphaned dependencies not found."))
                return True
        except Exception as e:
            update_log_func(_(f"Ошибка во время очистки сирот: {e}", f"Error during orphan cleanup: {e}"))
            update_log_func(traceback.format_exc())
            return False
    
    def download_triton(self):
        """
        Устанавливает Triton, применяет патчи, проверяет зависимости
        (с возможностью повторной попытки при ошибке DLL) и инициализирует ядро.
        """
        gui_elements = None
        self.triton_module = False 

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

            script_path = r"libs\python\python.exe"
            libs_path = "Lib"
            libs_path_abs = os.path.abspath(libs_path)

            if not os.path.exists(libs_path):
                os.makedirs(libs_path)
                update_log(_(f"Создана директория: {libs_path}", f"Created directory: {libs_path}"))

            if libs_path_abs not in sys.path:
                sys.path.insert(0, libs_path_abs)
                update_log(_(f"Добавлен путь {libs_path_abs} в sys.path", f"Added path {libs_path_abs} to sys.path"))

            update_progress(10)
            update_log(_("Начало установки Triton...", "Starting Triton installation..."))

            update_progress(20)
            update_status(_("Установка библиотеки Triton...", "Installing Triton library..."))
            update_log(_("Установка пакета triton-windows...", "Installing triton-windows package..."))

            installer = PipInstaller(
                script_path=script_path,
                libs_path=libs_path,
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
                update_log(_("Не удалось установить пакет Triton. Проверьте лог выше.", "Failed to install Triton package. Check the log above."))
                if progress_window and progress_window.winfo_exists():
                    progress_window.after(5000, progress_window.destroy)
                return False # Установка пакета не удалась, дальше нет смысла

            # --- Патчи ---
            update_progress(50)
            update_status(_("Применение патчей...", "Applying patches..."))
            update_log(_("Применение необходимых патчей для Triton...", "Applying necessary patches for Triton..."))

            update_log(_("Применение патча к build.py...", "Applying patch to build.py..."))
            build_py_path = os.path.join(libs_path_abs, "triton", "runtime", "build.py")
            if os.path.exists(build_py_path):
                try:
                    with open(build_py_path, "r", encoding="utf-8") as f: source = f.read()
                    # Патч 1: Путь к tcc.exe
                    try:
                        old_line_tcc = f'cc = os.path.join(sysconfig.get_paths()["platlib"], "triton", "runtime", "tcc", "tcc.exe")'
                    except KeyError: # На случай, если platlib не определен
                        old_line_tcc = 'os.path.join(sysconfig.get_paths()["platlib"], "triton", "runtime", "tcc", "tcc.exe")' 
                        update_log("Предупреждение: Не удалось точно определить старую строку tcc в build.py, используется предположение.")

                    new_line_tcc = 'cc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tcc", "tcc.exe")'
                    
                    # Патч 2: Удаление -fPIC
                    old_line_fpic = 'cc_cmd = [cc, src, "-O3", "-shared", "-fPIC", "-Wno-psabi", "-o", out]'
                    new_line_fpic = 'cc_cmd = [cc, src, "-O3", "-shared", "-Wno-psabi", "-o", out]'

                    patched_source = source
                    applied_patch_tcc = False
                    applied_patch_fpic = False

                    if old_line_tcc in patched_source:
                        patched_source = patched_source.replace(old_line_tcc, new_line_tcc)
                        applied_patch_tcc = True
                    else:
                        update_log(_("Патч (путь tcc.exe) для build.py уже применен или строка не найдена.", "Patch (tcc.exe path) for build.py already applied or line not found."))

                    if old_line_fpic in patched_source:
                        patched_source = patched_source.replace(old_line_fpic, new_line_fpic)
                        applied_patch_fpic = True
                    else:
                        update_log(_("Патч (удаление -fPIC) для build.py уже применен или строка не найдена.", "Patch (removing -fPIC) for build.py already applied or line not found."))

                    if applied_patch_tcc or applied_patch_fpic:
                        with open(build_py_path, "w", encoding="utf-8") as f: f.write(patched_source)
                        if applied_patch_tcc: update_log(_("Патч (путь tcc.exe) успешно применен к build.py", "Patch (tcc.exe path) successfully applied to build.py"))
                        if applied_patch_fpic: update_log(_("Патч (удаление -fPIC) успешно применен к build.py", "Patch (removing -fPIC) successfully applied to build.py"))

                except Exception as e:
                    update_log(_(f"Ошибка при патче build.py: {e}", f"Error patching build.py: {e}"))
                    update_log(traceback.format_exc())
            else:
                update_log(_("Предупреждение: файл build.py не найден, пропускаем патч", "Warning: build.py file not found, skipping patch"))

            # Патч windows_utils.py
            update_progress(60)
            update_log(_("Применение патча к windows_utils.py...", "Applying patch to windows_utils.py..."))
            windows_utils_path = os.path.join(libs_path_abs, "triton", "windows_utils.py")
            if os.path.exists(windows_utils_path):
                try:
                    with open(windows_utils_path, "r", encoding="utf-8") as f: source = f.read()
                    old_code_win = "output = subprocess.check_output(command, text=True).strip()"
                    # Добавляем CREATE_NO_WINDOW и другие флаги для стабильности
                    new_code_win = "output = subprocess.check_output(\n            command, text=True, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE\n        ).strip()"
                    if old_code_win in source:
                        patched_source = source.replace(old_code_win, new_code_win)
                        with open(windows_utils_path, "w", encoding="utf-8") as f: f.write(patched_source)
                        update_log(_("Патч успешно применен к windows_utils.py", "Patch successfully applied to windows_utils.py"))
                    else:
                        update_log(_("Патч для windows_utils.py уже применен или строка не найдена.", "Patch for windows_utils.py already applied or line not found."))
                except Exception as e:
                    update_log(_(f"Ошибка при патче windows_utils.py: {e}", f"Error patching windows_utils.py: {e}"))
                    update_log(traceback.format_exc())
            else:
                update_log(_("Предупреждение: файл windows_utils.py не найден, пропускаем патч", "Warning: windows_utils.py file not found, skipping patch"))

            # Патч compiler.py
            update_progress(70)
            update_log(_("Применение патча к compiler.py...", "Applying patch to compiler.py..."))
            compiler_path = os.path.join(libs_path_abs, "triton", "backends", "nvidia", "compiler.py")
            if os.path.exists(compiler_path):
                try:
                    with open(compiler_path, "r", encoding="utf-8") as f: source = f.read()
                    old_code_comp_line = 'version = subprocess.check_output([_path_to_binary("ptxas")[0], "--version"]).decode("utf-8")'
                    # Добавляем CREATE_NO_WINDOW и другие флаги
                    new_code_comp_line = 'version = subprocess.check_output([_path_to_binary("ptxas")[0], "--version"], creationflags=subprocess.CREATE_NO_WINDOW, stderr=subprocess.PIPE, close_fds=True, stdin=subprocess.DEVNULL).decode("utf-8")'
                    if old_code_comp_line in source:
                        patched_source = source.replace(old_code_comp_line, new_code_comp_line)
                        with open(compiler_path, "w", encoding="utf-8") as f: f.write(patched_source)
                        update_log(_("Патч успешно применен к compiler.py", "Patch successfully applied to compiler.py"))
                    else:
                        update_log(_("Патч для compiler.py уже применен или строка не найдена.", "Patch for compiler.py already applied or line not found."))
                except Exception as e:
                    update_log(_(f"Ошибка при патче compiler.py: {e}", f"Error patching compiler.py: {e}"))
                    update_log(traceback.format_exc())
            else:
                update_log(_("Предупреждение: файл compiler.py не найден, пропускаем патч", "Warning: compiler.py file not found, skipping patch"))

            # Патч cache.py
            update_log(_("Применение патча к cache.py...", "Applying patch to cache.py..."))
            cache_py_path = os.path.join(libs_path_abs, "triton", "runtime", "cache.py")
            if os.path.exists(cache_py_path):
                try:
                    with open(cache_py_path, "r", encoding="utf-8") as f: source = f.read()
                    old_line = 'temp_dir = os.path.join(self.cache_dir, f"tmp.pid_{pid}_{rnd_id}")'
                    # Укорачиваем имена временных папок
                    new_line = 'temp_dir = os.path.join(self.cache_dir, f"tmp.pid_{str(pid)[:5]}_{str(rnd_id)[:5]}")'
                    if old_line in source:
                        patched_source = source.replace(old_line, new_line)
                        with open(cache_py_path, "w", encoding="utf-8") as f: f.write(patched_source)
                        update_log(_("Патч успешно применен к cache.py", "Patch successfully applied to cache.py"))
                    else:
                        update_log(_("Патч для cache.py уже применен или строка не найдена.", "Patch for cache.py already applied or line not found."))
                except Exception as e:
                    update_log(_(f"Ошибка при патче cache.py: {e}", f"Error patching cache.py: {e}"))
                    update_log(traceback.format_exc())
            else:
                update_log(_("Предупреждение: файл cache.py не найден, пропускаем патч", "Warning: cache.py file not found, skipping patch"))


            # --- Проверка зависимостей с возможностью повтора ---
            update_progress(80)
            update_status(_("Проверка системных зависимостей...", "Checking system dependencies..."))
            update_log(_("Проверка наличия Triton, CUDA, Windows SDK, MSVC...", "Checking for Triton, CUDA, Windows SDK, MSVC..."))


            max_retries = 100 # Сколько раз можно нажать "Попробовать снова"
            retries_left = max_retries
            check_successful = False # Флаг успешной проверки без ошибок DLL/импорта/find_*

            while retries_left >= 0:
                show_vc_redist_warning = False
                dependencies_check_error = False # Ошибка внутри _check_system_dependencies (не DLL)
                import_error_occurred = False # Флаг, что была ошибка импорта (любая)

                # Сбрасываем состояние перед каждой попыткой
                self.triton_installed = False
                self.triton_checks_performed = False
                self.cuda_found = False
                self.winsdk_found = False
                self.msvc_found = False

                # --- Дебажный флаг (срабатывает только при первой попытке) ---
                force_dll_error = os.environ.get("TRITON_DLL_ERROR", "0") == "1"
                if force_dll_error and retries_left == max_retries:
                    update_log(_("TRITON_DLL_ERROR=1 установлен. Симуляция ошибки DLL load failed...", "TRITON_DLL_ERROR=1 set. Simulating DLL load failed error..."))
                    show_vc_redist_warning = True
                    import_error_occurred = True # Считаем ошибкой импорта
                else:
                    try:
                        importlib.invalidate_caches()
                        if "triton" in sys.modules:
                            try:
                                del sys.modules["triton"]
                                update_log(_("Удален модуль 'triton' из sys.modules перед проверкой.", "Removed 'triton' module from sys.modules before check."))
                            except KeyError:
                                pass # Модуль мог быть уже удален

                        # Вызываем проверку
                        self._check_system_dependencies()
                        # Если нет исключений, _check_system_dependencies установила флаги
                        update_log(_("_check_system_dependencies выполнена успешно.", "_check_system_dependencies executed successfully."))
                        check_successful = True # Проверка прошла без ошибок импорта/DLL

                    except ImportError as e:
                        error_message = str(e)
                        import_error_occurred = True # Была ошибка импорта
                        if error_message.startswith("DLL load failed while importing libtriton"):
                            update_log(_(f"ОШИБКА: Импорт Triton не удался (DLL load failed): {error_message}", f"ERROR: Triton import failed (DLL load failed): {error_message}"))
                            show_vc_redist_warning = True # Показать окно VC Redist
                        else:
                            update_log(_(f"ОШИБКА: Неожиданная ошибка импорта: {error_message}", f"ERROR: Unexpected import error: {error_message}"))
                            update_log(traceback.format_exc())
                            # Не показываем окно VC Redist для других ошибок импорта
                        # Флаги triton_installed/checks_performed остаются False
                    except Exception as e:
                        # Другие ошибки из _check_system_dependencies (например, при вызове find_*)
                        update_log(_(f"ОШИБКА: Общая ошибка во время _check_system_dependencies: {e}", f"ERROR: General error during _check_system_dependencies: {e}"))
                        update_log(traceback.format_exc())
                        dependencies_check_error = True # Была другая ошибка
                        # Флаги triton_installed/checks_performed остаются False

                # --- Обработка результата попытки ---
                if show_vc_redist_warning:
                    update_status(_("Ошибка загрузки Triton! Проверьте VC Redist.", "Triton load error! Check VC Redist."))
                    if progress_window and progress_window.winfo_exists():
                        progress_window.update_idletasks()
                        progress_window.grab_release()
                        progress_window.attributes('-topmost', False)
                    # Показываем окно и получаем выбор пользователя
                    user_choice = self._show_vc_redist_warning_dialog()
                    if progress_window and progress_window.winfo_exists():
                        progress_window.attributes('-topmost', True)
                        progress_window.grab_set()

                    if user_choice == "retry" and retries_left > 0:
                        update_log(_("Пользователь выбрал повторить попытку импорта Triton...", "User chose to retry Triton import..."))
                        retries_left -= 1
                        check_successful = False # Сбрасываем флаг успеха перед новой попыткой
                        continue # Переходим к следующей итерации цикла while
                    else:
                        if user_choice == "retry":
                            update_log(_("Достигнут лимит попыток для импорта Triton.", "Retry limit reached for Triton import."))
                        else: # user_choice == "close" или None
                            update_log(_("Пользователь закрыл окно предупреждения VC Redist, не решая проблему.", "User closed the VC Redist warning window without resolving the issue."))
                        check_successful = False # Ошибка DLL осталась нерешенной
                        break # Выходим из цикла while
                else:
                    # Если ошибки DLL не было (но могли быть другие ошибки)
                    check_successful = not import_error_occurred and not dependencies_check_error
                    if not check_successful:
                        if import_error_occurred:
                            update_log(_("Проверка зависимостей не удалась из-за ошибки импорта (не DLL).", "Dependency check failed due to import error (not DLL)."))
                        elif dependencies_check_error:
                            update_log(_("Проверка зависимостей не удалась из-за ошибки внутри _check_system_dependencies.", "Dependency check failed due to an error within _check_system_dependencies."))
                    break 

            skip_init = False
            user_action_deps = None 

            if not check_successful:
                if show_vc_redist_warning:
                    update_log(_("Импорт Triton не удался (возможно, из-за VC Redist), инициализация ядра будет пропущена.", "Triton import failed (possibly due to VC Redist), kernel initialization will be skipped."))
                elif import_error_occurred:
                    update_log(_("Не удалось импортировать Triton, инициализация ядра будет пропущена.", "Failed to import Triton, kernel initialization will be skipped."))
                else:
                    update_log(_("Проверка зависимостей Triton завершилась с ошибкой. Инициализация ядра будет пропущена.", "Triton dependency check finished with an error. Kernel initialization will be skipped."))
                skip_init = True
                self.triton_module = False
            elif self.triton_installed and self.triton_checks_performed:

                self.triton_module = True # Установка и проверка базово успешны
                if not (self.cuda_found and self.winsdk_found and self.msvc_found):
                    update_log(_("Обнаружено отсутствие зависимостей (CUDA/WinSDK/MSVC).", "Missing dependencies detected (CUDA/WinSDK/MSVC)."))
                    update_status(_("Требуется внимание: зависимости Triton", "Attention required: Triton dependencies"))
                    if progress_window and progress_window.winfo_exists():
                        progress_window.grab_release()
                        progress_window.attributes('-topmost', False)
                    # Показываем диалог о CUDA/SDK/MSVC
                    user_action_deps = self._show_triton_init_warning_dialog()
                    if progress_window and progress_window.winfo_exists():
                        progress_window.attributes('-topmost', True)
                        progress_window.grab_set()

                    if user_action_deps == "skip":
                        update_log(_("Пользователь выбрал пропустить инициализацию ядра из-за отсутствия зависимостей.", "User chose to skip kernel initialization due to missing dependencies."))
                        skip_init = True
                    elif user_action_deps == "continue":
                        update_log(_("Пользователь выбрал продолжить инициализацию ядра, несмотря на отсутствующие зависимости.", "User chose to continue kernel initialization despite missing dependencies."))
                        skip_init = False
                    else:
                        update_log(_("Диалог зависимостей закрыт, инициализация ядра будет пропущена.", "Dependency dialog closed, kernel initialization will be skipped."))
                        skip_init = True
                else:
                    update_log(_("Все зависимости Triton (CUDA, WinSDK, MSVC) найдены.", "All Triton dependencies (CUDA, WinSDK, MSVC) found."))
                    skip_init = False
            else:
                update_log(_("Неожиданное состояние после проверки зависимостей (check_successful=True, но флаги не установлены). Пропуск инициализации ядра.", "Unexpected state after dependency check (check_successful=True, but flags not set). Skipping kernel initialization."))
                skip_init = True
                self.triton_module = False

            # --- Инициализация ядра (init.py) ---
            if not skip_init:
                update_progress(90)
                update_status(_("Инициализация ядра Triton...", "Initializing Triton kernel..."))
                update_log(_("Начало инициализации ядра (запуск init.py)...", "Starting kernel initialization (running init.py)..."))
                try:
                    temp_dir = "temp"
                    if not os.path.exists(temp_dir):
                        os.makedirs(temp_dir)
                        update_log(_(f"Создана директория: {temp_dir}", f"Created directory: {temp_dir}"))

                    update_log(_("Запуск скрипта инициализации...", "Running initialization script..."))
                    init_cmd = [script_path, "init.py"]
                    update_log(_(f"Выполняем: {' '.join(init_cmd)}", f"Executing: {' '.join(init_cmd)}"))
                    try:
                        # Запускаем и ждем завершения, захватывая вывод
                        result = subprocess.run(
                            init_cmd,
                            capture_output=True, # Захватываем stdout и stderr
                            text=True,           # Декодируем как текст
                            encoding='utf-8',
                            errors='ignore',     # Игнорируем ошибки декодирования
                            check=False,         # Не выбрасывать исключение при ненулевом коде возврата
                            creationflags=subprocess.CREATE_NO_WINDOW # Не показывать консольное окно
                        )
                        # Логируем вывод
                        if result.stdout:
                            update_log(_("--- Вывод init.py (stdout) ---", "--- init.py Output (stdout) ---"))
                            for line in result.stdout.splitlines():
                                update_log(line)
                            update_log(_("--- Конец вывода init.py (stdout) ---", "--- End of init.py Output (stdout) ---"))
                        if result.stderr:
                            update_log(_("--- Вывод init.py (stderr) ---", "--- init.py Output (stderr) ---"))
                            for line in result.stderr.splitlines():
                                update_log(f"STDERR: {line}")
                            update_log(_("--- Конец вывода init.py (stderr) ---", "--- End of init.py Output (stderr) ---"))

                        update_log(_(f"Скрипт init.py завершился с кодом: {result.returncode}", f"Script init.py finished with code: {result.returncode}"))
                        init_success = (result.returncode == 0)

                    except FileNotFoundError:
                        update_log(_(f"ОШИБКА: Не найден скрипт инициализации init.py или python.exe по пути: {script_path}", f"ERROR: Initialization script init.py or python.exe not found at path: {script_path}"))
                        init_success = False
                    except Exception as sub_e:
                        update_log(_(f"Ошибка при запуске init.py через subprocess.run: {sub_e}", f"Error running init.py via subprocess.run: {sub_e}"))
                        update_log(traceback.format_exc())
                        init_success = False

                    if not init_success:
                        update_status(_("Ошибка при инициализации ядра", "Error during kernel initialization"))
                        update_log(_("Ошибка при запуске init.py. Проверьте лог выше.", "Error running init.py. Check the log above."))
                    else:
                        output_file_path = os.path.join(temp_dir, "inited.wav")
                        if os.path.exists(output_file_path):
                            update_log(_(f"Проверка успешна: файл {output_file_path} создан", f"Check successful: file {output_file_path} created"))
                            update_progress(95)
                            update_status(_("Инициализация ядра успешно завершена!", "Kernel initialization completed successfully!"))
                        else:
                            update_log(_(f"Предупреждение: Файл {output_file_path} не найден после успешного запуска init.py", f"Warning: File {output_file_path} not found after successful run of init.py"))
                            update_status(_("Предупреждение: Файл инициализации не создан", "Warning: Initialization file not created"))
                            update_progress(90)

                except Exception as e:
                    update_log(_(f"Непредвиденная ошибка при инициализации ядра: {str(e)}", f"Unexpected error during kernel initialization: {str(e)}"))
                    update_log(traceback.format_exc())
                    update_status(_("Ошибка инициализации ядра", "Kernel initialization error"))
                    update_progress(85)

            else:
                update_log(_("Инициализация ядра Triton пропущена.", "Triton kernel initialization skipped."))
                update_status(_("Инициализация ядра пропущена", "Kernel initialization skipped"))
                update_progress(95) 

            # --- Завершение ---
            update_progress(100)
            final_message = _("Установка Triton завершена.", "Triton installation complete.")
            if not check_successful and show_vc_redist_warning:
                final_message += _(" ВНИМАНИЕ: Ошибка загрузки DLL (VC Redist?)!", " WARNING: DLL load error (VC Redist?)!")
            elif not check_successful:
                final_message += _(" ВНИМАНИЕ: Ошибка при проверке зависимостей!", " WARNING: Error during dependency check!")
            elif skip_init and user_action_deps == "skip":
                final_message += _(" Инициализация ядра пропущена по выбору.", " Kernel initialization skipped by choice.")
            elif skip_init:
                final_message += _(" Инициализация ядра пропущена.", " Kernel initialization skipped.")

            # Предупреждение о CUDA/SDK/MSVC, если они не найдены, но проверка прошла и ядро не пропускалось
            if check_successful and not skip_init and not (self.cuda_found and self.winsdk_found and self.msvc_found):
                missing_deps = [dep for dep, found in [("CUDA", self.cuda_found), ("WinSDK", self.winsdk_found), ("MSVC", self.msvc_found)] if not found]
                final_message += _(f" Внимание: не найдены зависимости ({', '.join(missing_deps)})!", f" Warning: missing dependencies ({', '.join(missing_deps)})!")

            update_status(final_message)
            update_log(final_message)

            # Добавляем финальный совет
            if not check_successful:
                update_log(_("Если модель medium+ не заработает, проверьте лог, зависимости (особенно VC Redist) и документацию.", "If the medium+ model doesn't work, check the log, dependencies (especially VC Redist), and documentation."))
            elif skip_init:
                update_log(_("Если модель medium+ не заработает, возможно, потребуется запустить init_triton.bat вручную.", "If the medium+ model doesn't work, you might need to run init_triton.bat manually."))
            elif not (self.cuda_found and self.winsdk_found and self.msvc_found):
                update_log(_("Если модель medium+ не заработает, проверьте установку недостающих зависимостей (CUDA/WinSDK/MSVC).", "If the medium+ model doesn't work, check the installation of missing dependencies (CUDA/WinSDK/MSVC)."))


            self.current_model = "medium+" # Устанавливаем модель в любом случае
            if progress_window and progress_window.winfo_exists():
                progress_window.after(5000, progress_window.destroy)

            # Возвращаем True, т.к. сам пакет установился. Состояние модуля хранится в self.triton_module
            return True

        except Exception as e:
            logger.error(_(f"Критическая ошибка при установке Triton: {e}", f"Critical error during Triton installation: {e}"))
            logger.error(traceback.format_exc())
            try:
                if gui_elements and gui_elements["window"] and gui_elements["window"].winfo_exists():
                    gui_elements["update_log"](f"{_('КРИТИЧЕСКАЯ ОШИБКА:', 'CRITICAL ERROR:')} {e}\n{traceback.format_exc()}")
                    gui_elements["update_status"](_("Критическая ошибка установки!", "Critical installation error!"))
                    gui_elements["window"].after(10000, gui_elements["window"].destroy)
            except Exception as e_inner:
                logger.info(_(f"Ошибка при попытке обновить лог в окне прогресса: {e_inner}", f"Error trying to update log in progress window: {e_inner}"))
            self.triton_module = False
            return False
        finally:
            pass

    def download_edge_tts_rvc(self):
        """Загружает Edge-TTS + RVC модель"""
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

            script_path = r"libs\python\python.exe"
            installer = PipInstaller(
                script_path=script_path,
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

            # Устанавливаем основную библиотеку
            update_status(_("Установка основной библиотеки...", "Installing main library..."))
            try:
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

            except Exception as e:
                update_log(_(f"Ошибка при установке tts-with-rvc: {e}", f"Error installing tts-with-rvc: {e}"))
                if progress_window and progress_window.winfo_exists():
                    progress_window.after(5000, progress_window.destroy)
                return False

            
            libs_path = "Lib"
            libs_path_abs = os.path.abspath(libs_path)
            update_progress(95)
            update_status(_("Применение патчей...", "Applying patches..."))
            config_path = os.path.join(libs_path_abs, "fairseq", "dataclass", "configs.py")
            if os.path.exists(config_path):
                try:
                    import re
                    with open(config_path, "r", encoding="utf-8") as f:
                        source = f.read()
                    patched_source = re.sub(r"metadata=\{(.*?)help:", r'metadata={\1"help":', source)
                    with open(config_path, "w", encoding="utf-8") as f:
                        f.write(patched_source)
                    update_log(_("Патч успешно применен к configs.py", "Patch successfully applied to configs.py"))
                except Exception as e:
                    update_log(_(f"Ошибка при патче configs.py: {e}", f"Error patching configs.py: {e}"))
            else:
                update_log(_("Предупреждение: файл configs.py не найден, пропускаем патч", "Warning: configs.py file not found, skipping patch"))

            update_progress(100)

            update_status(_("Попытка импорта модуля...", "Attempting to import module..."))
            update_log(_("Установка успешно завершена! Попытка импорта модуля...", "Installation successful! Attempting to import module..."))

            # Пытаемся импортировать модуль
            try:
                import importlib
                import sys

                # Удаляем старые импорты, если они есть
                if "tts_with_rvc" in sys.modules: del sys.modules["tts_with_rvc"]
                if "tts_with_rvc_onnx" in sys.modules: del sys.modules["tts_with_rvc_onnx"]
                # Очищаем кэш импорта для пути Lib
                importlib.invalidate_caches()

                # Добавляем путь снова, если его нет (на всякий случай)
                if libs_path_abs not in sys.path:
                    sys.path.insert(0, libs_path_abs)

                # Импортируем
                from tts_with_rvc import TTS_RVC
                self.tts_rvc_module = TTS_RVC
                update_log(_("Модуль успешно загружен без перезапуска программы!", "Module successfully loaded without restarting the program!"))
            except ImportError as ie:
                update_log(_(f"Предупреждение: Модуль установлен, но не может быть загружен немедленно: {ie}", f"Warning: Module installed, but cannot be loaded immediately: {ie}"))
                update_log(_("При следующем использовании он будет доступен.", "It will be available on next use."))
            except Exception as e_imp:
                update_log(_(f"Ошибка при попытке импорта модуля после установки: {e_imp}", f"Error attempting to import module after installation: {e_imp}"))
                traceback.print_exc()


            if progress_window and progress_window.winfo_exists():
                progress_window.after(3000, progress_window.destroy)

            self.current_model = "low"
            return True

        except Exception as e:
            logger.info(_(f"Ошибка при установке Edge-TTS + RVC: {e}", f"Error installing Edge-TTS + RVC: {e}"))
            traceback.print_exc()
            if gui_elements and gui_elements["window"] and gui_elements["window"].winfo_exists():
                try:
                    gui_elements["update_log"](f"{_('КРИТИЧЕСКАЯ ОШИБКА:', 'CRITICAL ERROR:')} {e}\n{traceback.format_exc()}")
                    gui_elements["update_status"](_("Критическая ошибка установки!", "Critical installation error!"))
                    gui_elements["window"].after(10000, gui_elements["window"].destroy)
                except: pass
            return False
        finally:
            if gui_elements and gui_elements["window"] and gui_elements["window"].winfo_exists():
                pass

    def download_fish_speech(self):
        """Загружает Fish Speech модель"""
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

            # script_path = r"libs\python\python.exe"
            

            script_path = r"libs\python\python.exe"
            installer = PipInstaller(
                script_path=script_path,
                libs_path="Lib",
                update_status=update_status,
                update_log=update_log,
                progress_window=progress_window
            )

            update_progress(10)
            update_log(_("Начало установки Fish Speech...", "Starting Fish Speech installation..."))

            # Сначала устанавливаем PyTorch с CUDA 12.4 (если нужно)
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
                 update_progress(40) # Пропускаем шаг PyTorch, но двигаем прогресс

            update_status(_("Установка библиотеки Fish Speech...", "Installing Fish Speech library..."))

            try:
                force_install_unsupported = os.environ.get("ALLOW_UNSUPPORTED_GPU", "0") == "1"
                if self.provider in ["NVIDIA"] or force_install_unsupported:
                    if force_install_unsupported:
                        update_log("--------------------------------")
                        update_log(_(f"ВНИМАНИЕ! УСТАНОВКА НА ВИДЕОКАРТУ {self.provider} НЕСОВМЕСТИМОЙ МОДЕЛИ!!", f"WARNING! INSTALLING INCOMPATIBLE MODEL ON {self.provider} GPU!!"))
                        update_log("--------------------------------")

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

                    # Дополнительно устанавливаем librosa
                    update_status(_("Установка дополнительных библиотек...", "Installing additional libraries..."))
                    success = installer.install_package(
                        "librosa==0.9.1",
                        description=_("Установка дополнительной библиотеки librosa...", "Installing additional library librosa...")
                    )

                    if not success:
                        update_status(_("Ошибка при установке librosa", "Error installing librosa"))
                        update_log(_("Предупреждение: Fish Speech может работать некорректно без librosa", "Warning: Fish Speech may not work correctly without librosa"))
                else:
                    update_log(_(f"Ошибка: не найдена подходящая видеокарта: {self.provider}", f"Error: suitable graphics card not found: {self.provider}"))
                    update_status(_("Требуется NVIDIA GPU", "NVIDIA GPU required"))
                    if progress_window and progress_window.winfo_exists():
                        progress_window.after(5000, progress_window.destroy)
                    return False

            except Exception as e:
                update_log(_(f"Ошибка при установке Fish Speech: {e}", f"Error installing Fish Speech: {e}"))
                if progress_window and progress_window.winfo_exists():
                    progress_window.after(5000, progress_window.destroy)
                return False

            update_progress(100)
            
            update_status(_("Попытка импорта модуля...", "Attempting to import module..."))
            update_log(_("Установка успешно завершена! Попытка импорта модуля...", "Installation successful! Attempting to import module..."))

            # Пытаемся импортировать модуль
            try:
                import importlib
                import sys
                libs_path = "Lib"
                libs_path_abs = os.path.abspath(libs_path)

                if "fish_speech_lib" in sys.modules: del sys.modules["fish_speech_lib"]
                importlib.invalidate_caches()
                if libs_path_abs not in sys.path:
                    sys.path.insert(0, libs_path_abs)

                from fish_speech_lib.inference import FishSpeech
                self.fish_speech_module = FishSpeech
                update_log(_("Модуль успешно загружен без перезапуска программы!", "Module successfully loaded without restarting the program!"))
            except ImportError as ie:
                update_log(_(f"Предупреждение: Модуль установлен, но не может быть загружен немедленно: {ie}", f"Warning: Module installed, but cannot be loaded immediately: {ie}"))
                update_log(_("При следующем использовании он будет доступен.", "It will be available on next use."))
            except Exception as e_imp:
                 update_log(_(f"Ошибка при попытке импорта модуля после установки: {e_imp}", f"Error attempting to import module after installation: {e_imp}"))
                 traceback.print_exc()

            if progress_window and progress_window.winfo_exists():
                progress_window.after(5000, progress_window.destroy)

            self.current_model = "medium"
            return True

        except Exception as e:
            logger.info(_(f"Ошибка при установке Fish Speech: {e}", f"Error installing Fish Speech: {e}"))
            traceback.print_exc()
            if gui_elements and gui_elements["window"] and gui_elements["window"].winfo_exists():
                try:
                    gui_elements["update_log"](f"{_('КРИТИЧЕСКАЯ ОШИБКА:', 'CRITICAL ERROR:')} {e}\n{traceback.format_exc()}")
                    gui_elements["update_status"](_("Критическая ошибка установки!", "Critical installation error!"))
                    gui_elements["window"].after(10000, gui_elements["window"].destroy)
                except: pass
            return False
        finally:
             if gui_elements and gui_elements["window"] and gui_elements["window"].winfo_exists():
                pass
             
    #endregion
    async def voiceover(self, text, output_file="output.wav", character=None):
        """Создает озвучку текста с использованием текущей модели"""
        if self.current_model is None:
            raise ValueError("Модель не выбрана. Сначала скачайте и выберите модель.")

        # Получаем путь к модели персонажа, если есть
        if character is not None:
            is_nvidia = self.provider in ["NVIDIA"]
            short_name = str(getattr(character, 'short_name', None))
            self.current_character_name = short_name
            self.pth_path = os.path.join(os.path.abspath(self.clone_voice_folder), f"{short_name}.{'pth' if is_nvidia else 'onnx'}")
            self.index_path = os.path.join(os.path.abspath(self.clone_voice_folder), f"{short_name}.index")
            self.clone_voice_filename = os.path.join(os.path.abspath(self.clone_voice_folder), f"{short_name}.wav")
            self.clone_voice_text = os.path.join(os.path.abspath(self.clone_voice_folder), f"{short_name}.txt")
            logger.info(f"Используем модель персонажа: {self.pth_path if self.pth_path else 'не указана'}")
            logger.info(f"Используем .index файл персонажа: {self.index_path if self.index_path else 'не указан'}")

        # Проверяем, инициализирована ли текущая модель
        if self.current_model == "low" and not self.is_model_initialized("low"):
            if not self.initialize_model("low"):
                raise Exception("Не удалось инициализировать модель low")
        elif self.current_model == "low+" and not self.is_model_initialized("low+"):
            if not self.initialize_model("low+"):
                raise Exception("Не удалось инициализировать модель low+")
        elif self.current_model == "medium" and not self.is_model_initialized("medium"):
            if not self.initialize_model("medium"):
                raise Exception("Не удалось инициализировать модель medium")
        elif self.current_model == "medium+" and not self.is_model_initialized("medium"):
            if not self.initialize_model("medium+"):
                raise Exception("Не удалось инициализировать модель medium+")
        elif self.current_model == "medium+low" and not self.is_model_initialized("medium+low"):
            if not self.initialize_model("medium+low"):
                raise Exception("Не удалось инициализировать модель medium+low")

        # Используем соответствующий метод озвучки
        if self.current_model == "low":
            return await self.voiceover_edge_tts_rvc(text)
        elif self.current_model == "low+": # Добавлено
            return await self.voiceover_silero_rvc(text, character)
        elif self.current_model == "medium":
            return await self.voiceover_fish_speech(text)
        elif self.current_model == "medium+":
            return await self.voiceover_fish_speech(text, compile=True)
        elif self.current_model == "medium+low":
            return await self.voiceover_fish_speech(text, compile=True, with_rvc=True)
        elif self.current_model == "high":
            return await self.voiceover_zonos(text, character)
        else:
            raise ValueError(f"Неизвестная модель: {self.current_model}")
        
    def change_voice_language(self, new_voice_language: str):
        logger.info(f"Запрос на изменение языка озвучки на '{new_voice_language}'...")

        self.voice_language = new_voice_language
        logger.info(f"Установлен язык озвучки: {self.voice_language}")

        if hasattr(self, 'current_tts_rvc') and self.current_tts_rvc:
            logger.info(f"Обновление голоса для текущего экземпляра RVC ({type(self.current_tts_rvc).__name__})...")
            try:
                if new_voice_language == "ru":
                    self.current_tts_rvc.set_voice("ru-RU-SvetlanaNeural")
                    logger.info("Установлен голос RVC: ru-RU-SvetlanaNeural")
                elif new_voice_language == "en":
                    self.current_tts_rvc.set_voice("en-US-MichelleNeural")
                    logger.info("Установлен голос RVC: en-US-MichelleNeural")
                else:
                    self.current_tts_rvc.set_voice("en-US-AvaMultilingualNeural")
                    logger.info(f"Установлен голос RVC по умолчанию/fallback: en-US-AvaMultilingualNeural (для языка {new_voice_language})")
            except AttributeError:
                logger.warning(f"Экземпляр RVC ({type(self.current_tts_rvc).__name__}) не имеет метода 'set_voice'. Пропуск установки голоса.")
            except Exception as e:
                logger.error(f"Неожиданная ошибка при установке голоса RVC: {e}")
        else:
            logger.info("Экземпляр RVC (self.current_tts_rvc) не инициализирован или отсутствует атрибут, пропуск установки голоса RVC.")

        if hasattr(self, 'initialized_models') and isinstance(self.initialized_models, set):
            # Используем discard, чтобы не вызывать ошибку, если 'low+' там нет
            self.initialized_models.discard("low+")
            logger.info("Модель 'low+' удалена из списка инициализированных (если была там).")
        else:
             logger.warning("Атрибут 'initialized_models' отсутствует или не является множеством. Не удалось проверить/удалить 'low+'.")

        logger.info(f"Изменение языка озвучки на '{new_voice_language}' и связанные операции завершены.")

    # region На вынос в AudioConverter.py
    async def convert_wav_to_stereo(self, input_path, output_path, atempo: float = 1, volume: str = "1.0"):
        """
        Конвертирует WAV из 40 кГц моно в 44.1 кГц стерео с замедлением для компенсации
        разницы между 40 кГц и 32 кГц при воспроизведении.
        """
        try:
            if not os.path.exists(input_path):
                logger.info(f"Файл {input_path} не найден при попытке конвертации.")
                return None

            logger.info(f"Начинаю конвертацию {input_path} в {output_path} с помощью ffmpeg")

            (
                ffmpeg
                .input(input_path)
                .filter('atempo', atempo) # Замедляем аудио на x%
                .filter('volume', volume=volume)  
                .output(
                    output_path,
                    format="wav",      # Указываем формат WAV
                    acodec="pcm_s16le", # 16-битный PCM
                    ar="44100",        # Частота дискретизации 44100 Hz
                    ac=2               # Количество каналов (2 = стерео)
                )
                .run(cmd=["ffmpeg", "-nostdin"], capture_stdout=True, capture_stderr=True)
            )

            logger.info(f"Конвертация завершена: {output_path}")
            return output_path
        except Exception as e:
            logger.info(f"Ошибка при конвертации WAV в стерео: {e}")
            return None
    # endregion
    async def voiceover_edge_tts_rvc(self, text, TEST_WITH_DONE_AUDIO: str = None):
        if self.tts_rvc_module is None:
            raise ImportError("Модуль tts_with_rvc не установлен. Сначала установите модель 'low' или 'medium+low'.")
        try:
            if not self.current_tts_rvc:
                model_to_init = None
                if self.current_model == "low":
                    model_to_init = "low"
                elif self.current_model == "medium+low":
                    model_to_init = "medium+low"
                if model_to_init:
                    logger.info(f"Предупреждение: Экземпляр TTS_RVC не инициализирован для модели {self.current_model}. Попытка инициализации...")
                    if not self.initialize_model(model_to_init):
                        raise Exception(f"Не удалось инициализировать компонент TTS_RVC для модели {self.current_model}")
                else:
                    raise Exception(f"Неожиданный вызов voiceover_edge_tts_rvc для модели {self.current_model}, которая не использует RVC.")
            settings = self.load_model_settings(self.current_model)
            if not settings:
                logger.info(f"Предупреждение: Не найдены настройки для модели {self.current_model}. Используются значения по умолчанию.")

            is_combined_model = self.current_model == "medium+low"

            pitch_key = "fsprvc_rvc_pitch" if is_combined_model else "pitch"
            index_rate_key = "fsprvc_index_rate" if is_combined_model else "index_rate"
            protect_key = "fsprvc_protect" if is_combined_model else "protect"
            tts_rate_key = "tts_rate"
            filter_radius_key = "fsprvc_filter_radius" if is_combined_model else "filter_radius"
            rms_mix_rate_key = "fsprvc_rvc_rms_mix_rate" if is_combined_model else "rms_mix_rate"
            is_half_key = "fsprvc_is_half" if is_combined_model else "is_half"
            f0method_key = "fsprvc_f0method" if is_combined_model else "f0method"
            use_index_file_key = "fsprvc_use_index_file" if is_combined_model else "use_index_file"

            pitch = float(settings.get(pitch_key, 0)) if self.current_character_name != "Player" else -12
            index_rate = float(settings.get(index_rate_key, 0.75))
            protect = float(settings.get(protect_key, 0.33))
            filter_radius = int(settings.get(filter_radius_key, 3))
            rms_mix_rate = float(settings.get(rms_mix_rate_key, 0.5))
            is_half_str = settings.get(is_half_key, "True")
            is_half = is_half_str.lower() == "true"
            use_index_file = settings.get(use_index_file_key, True)

            if use_index_file:
                self.current_tts_rvc.set_index_path(self.index_path)
                logger.info("Используем индексную базу для RVC:", self.index_path)
            else:
                self.current_tts_rvc.set_index_path("")
                logger.info("Не используем индексную базу для RVC.")

            f0method_override = settings.get(f0method_key, None)

            tts_rate = int(settings.get(tts_rate_key, 0)) if not is_combined_model else 0

            if self.provider in ["NVIDIA"]:
                inference_params = {
                    "pitch": pitch,
                    "f0method": f0method_override,
                    "index_rate": index_rate,
                    "protect": protect,
                    "filter_radius": filter_radius,
                    "rms_mix_rate": rms_mix_rate,
                    "is_half": is_half,
                }
            else:
                inference_params = {
                    "pitch": pitch,
                    "f0method": f0method_override,
                    "index_rate": index_rate,
                    "protect": protect,
                    "filter_radius": filter_radius,
                    "rms_mix_rate": rms_mix_rate
                }
            if f0method_override:
                inference_params["f0method"] = f0method_override

            output_file_rvc = None
            if os.path.abspath(self.pth_path) != os.path.abspath(self.current_tts_rvc.current_model):
                if self.provider in ["NVIDIA"]:
                    self.current_tts_rvc.current_model = self.pth_path
                elif self.provider in ["AMD"]:
                    self.current_tts_rvc.current_model = self.pth_path
                    self.current_tts_rvc.set_model(self.pth_path)

            if not TEST_WITH_DONE_AUDIO:
                logger.info(f"Начинаем генерацию аудио RVC (TTS) для текста: {text[:50]}...")
                if not is_combined_model:
                    inference_params["tts_rate"] = tts_rate
                output_file_rvc = self.current_tts_rvc(text=text, **inference_params)
            else:
                logger.info(f"Обрабатываем существующее аудио RVC: {TEST_WITH_DONE_AUDIO}")
                output_file_rvc = self.current_tts_rvc.voiceover_file(
                    input_path=TEST_WITH_DONE_AUDIO,
                    **inference_params
                )

            logger.info(f"Аудио сгенерировано RVC, путь: {output_file_rvc}")

            if not output_file_rvc or not os.path.exists(output_file_rvc) or os.path.getsize(output_file_rvc) == 0:
                logger.info(f"Внимание: сгенерированный RVC файл {output_file_rvc} отсутствует или имеет нулевой размер!")
                return None
            
            logger.info(f"RVC файл создан успешно, размер: {os.path.getsize(output_file_rvc)} байт")

            stereo_output_file = output_file_rvc.replace(".wav", "_stereo.wav")
            final_output_path = output_file_rvc
            atempo_value = 1.0

            if self.current_model == "low" and TEST_WITH_DONE_AUDIO is None:
                atempo_value = 1.0

            converted_file = await self.convert_wav_to_stereo(output_file_rvc, stereo_output_file, atempo=atempo_value)

            if converted_file and os.path.exists(converted_file):
                logger.info(f"Файл успешно конвертирован в стерео: {stereo_output_file}")
                final_output_path = stereo_output_file
                try:
                    os.remove(output_file_rvc)
                    logger.info(f"Удален промежуточный файл: {output_file_rvc}")
                except OSError as error:
                    logger.info(f"Не удалось удалить промежуточный файл {output_file_rvc}: {error}")
            else:
                logger.info("Не удалось конвертировать файл в стерео формат, используется исходный RVC файл.")

            logger.info(f"Озвучка создана: {final_output_path}")
            if self.parent.ConnectedToGame == True and TEST_WITH_DONE_AUDIO is None:
                self.parent.patch_to_sound_file = final_output_path
                
            return final_output_path
        except Exception as error:
            import traceback
            traceback.print_exc()
            logger.info(f"Ошибка при создании озвучки с Edge-TTS + RVC ({self.current_model}): {error}")
            return None

    def _preprocess_text_to_ssml(self, text: str):
        if not hasattr(self, 'voice_language'):
            self.voice_language = 'en'

        defaults = {
            'en': {'pitch': 6, 'speaker': "en_88"},
            'ru': {'pitch': 2, 'speaker': "kseniya"},
        }
        lang_defaults = defaults.get(self.voice_language, defaults['en'])

        if not text:
            return "<speak></speak>", lang_defaults['pitch'], lang_defaults['speaker']

        # (rvc_pitch, silero_speaker_id)
        char_params = {
            'en': {
                "CappieMita":    (6, "en_26"),
                "CrazyMita":   (6, "en_60"),
                "GhostMita":   (6, "en_33"),
                "Mila":        (6, "en_88"),
                "MitaKind":    (3, "en_33"),
                "ShorthairMita": (6, "en_60"),
                "SleepyMita":  (6, "en_33"),
                "TinyMita":    (2, "en_60"),
                "Player":      (0, "en_27")
            },
            'ru': {
                "CappieMita":    (6, "kseniya"),
                "MitaKind":    (1, "kseniya"),
                "ShorthairMita": (2, "kseniya"),
                "CrazyMita":   (2, "kseniya"),
                "Mila":        (2, "kseniya"),
                "TinyMita":    (-3, "baya"),
                "SleepyMita":  (2, "baya"),
                "GhostMita":   (1, "baya"),
                "Player":      (0, "aidar")
            }
        }

        character_rvc_pitch = lang_defaults['pitch']
        character_speaker = lang_defaults['speaker']
        character_short_name = "Unknown"

        current_char_obj = getattr(self, 'current_character', None)
        if current_char_obj:
            char_short_name_attr = getattr(current_char_obj, 'short_name', None)
            if char_short_name_attr:
                character_short_name = str(char_short_name_attr)

        current_lang_params = char_params.get(self.voice_language, char_params['en'])
        specific_params = current_lang_params.get(character_short_name)

        if specific_params:
            character_rvc_pitch, character_speaker = specific_params

        text = re.sub(r'<[^>]*>', '', text)
        text = escape(text)
        text = text.replace("Mita", "M+ita").replace("Mila", "M+ila")
        text = text.replace("mita", "m+ita").replace("mila", "m+ila")

        split_pattern = r'([.!?]+[^A-Za-zА-Яа-я0-9_]*)(\s+)'
        parts = re.split(split_pattern, text.strip())
        processed_text = ""
        i = 0
        while i < len(parts):
            text_part = parts[i]
            if text_part:
                processed_text += text_part

            if i + 1 < len(parts) and i + 2 < len(parts):
                punctuation_part = parts[i+1]
                whitespace_part = parts[i+2]
                if punctuation_part:
                    processed_text += punctuation_part
                if whitespace_part and i + 3 < len(parts) and parts[i+3]:
                    processed_text += f' <break time="300ms"/> '
                elif whitespace_part:
                    processed_text += whitespace_part
            i += 3
        ssml_content = processed_text.strip()

        if ssml_content:
            ssml_output = f'<speak><p>{ssml_content}</p></speak>'
        else:
            ssml_output = '<speak></speak>'
            character_rvc_pitch = lang_defaults['pitch']
            character_speaker = lang_defaults['speaker']

        return ssml_output, character_rvc_pitch, character_speaker
    
    async def voiceover_silero_rvc(self, text, character=None):
        if self.current_silero_model is None or self.current_tts_rvc is None:
            raise Exception("Модель Silero или RVC не инициализирована для low+")

        self.current_character = character if character is not None else getattr(self, 'current_character', None)

        temp_wav = None
        try:
            ssml_text, character_base_rvc_pitch, character_speaker = self._preprocess_text_to_ssml(text)

            settings = self.load_model_settings("low+")
            if not settings:
                logger.info("Предупреждение: Не найдены настройки для модели low+. Используются значения по умолчанию.")

            silero_put_accent = settings.get("silero_put_accent", True)
            silero_put_yo = settings.get("silero_put_yo", True)
            speaker = character_speaker

            logger.info(f"Начинаем генерацию аудио Silero для SSML: {ssml_text[:100]}...")
            audio_tensor = self.current_silero_model.apply_tts(
                ssml_text=ssml_text,
                speaker=speaker,
                sample_rate=self.current_silero_sample_rate,
                put_accent=silero_put_accent,
                put_yo=silero_put_yo
            )

            audio_numpy = audio_tensor.cpu().numpy()
            temp_wav_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_wav = temp_wav_file.name
            temp_wav_file.close()
            sf.write(temp_wav, audio_numpy, self.current_silero_sample_rate)

            if not os.path.exists(temp_wav) or os.path.getsize(temp_wav) == 0:
                 logger.info(f"Внимание: сгенерированный Silero файл {temp_wav} отсутствует или имеет нулевой размер!")
                 return None
            logger.info(f"Silero файл создан успешно: {temp_wav}, размер: {os.path.getsize(temp_wav)} байт")

            base_rvc_pitch_from_settings = float(settings.get("pitch", 6))
            final_rvc_pitch = base_rvc_pitch_from_settings - (6 - character_base_rvc_pitch)

            index_rate = float(settings.get("index_rate", 0.75))
            protect = float(settings.get("protect", 0.33))
            filter_radius = int(settings.get("filter_radius", 3))
            rms_mix_rate = float(settings.get("rms_mix_rate", 0.5))
            is_half_str = settings.get("is_half", "True")
            is_half = is_half_str.lower() == "true"
            use_index_file = settings.get("use_index_file", True)
            f0method_override = settings.get("f0method", None)

            # Используем оригинальную логику определения путей на основе аргумента character или дефолта
            active_character_for_rvc_path = character # Используем аргумент функции
            is_nvidia = self.provider in ["NVIDIA"]
            model_ext = 'pth' if is_nvidia else 'onnx'

            if active_character_for_rvc_path is not None:
                # Пытаемся получить short_name из переданного объекта character
                rvc_model_short_name = str(getattr(active_character_for_rvc_path, 'short_name', None))
                if not rvc_model_short_name:
                    logger.info(f"Предупреждение: Не удалось получить short_name из объекта character. Используется имя по умолчанию 'Mila'.")
                    rvc_model_short_name = "Mila"
            else:
                # Если character не передан, используем имя по умолчанию
                rvc_model_short_name = "Mila"

            self.pth_path = os.path.join(os.path.abspath(self.clone_voice_folder), f"{rvc_model_short_name}.{model_ext}")
            self.index_path = os.path.join(os.path.abspath(self.clone_voice_folder), f"{rvc_model_short_name}.index")

            logger.info(f"Выбрана RVC модель: {rvc_model_short_name}, Путь: {self.pth_path}")

            if not os.path.exists(self.pth_path):
                 # Можно добавить обработку ошибки или fallback на дефолтную модель, если основная не найдена
                 raise Exception(f"Файл модели RVC не найден: {self.pth_path}")

            if os.path.abspath(self.pth_path) != os.path.abspath(getattr(self.current_tts_rvc, 'current_model', '')):
                if self.provider in ["NVIDIA"]:
                    self.current_tts_rvc.current_model = self.pth_path
                elif self.provider in ["AMD"]:
                    self.current_tts_rvc.current_model = self.pth_path
                    self.current_tts_rvc.set_model(self.pth_path)

            if use_index_file and self.index_path and os.path.exists(self.index_path):
                self.current_tts_rvc.set_index_path(self.index_path)
                logger.info(f"Используем индексную базу для RVC: {self.index_path}")
            else:
                self.current_tts_rvc.set_index_path("")
                logger.info("Не используем индексную базу для RVC (файл не найден или отключен).")

            rvc_params = {
                "pitch": final_rvc_pitch,
                "index_rate": index_rate,
                "protect": protect,
                "filter_radius": filter_radius,
                "rms_mix_rate": rms_mix_rate,
            }
            if self.provider == "NVIDIA":
                rvc_params["is_half"] = is_half
            if f0method_override:
                rvc_params["f0method"] = f0method_override

            logger.info(f"Текущая модель: {self.current_tts_rvc.current_model}")
            logger.info(f"Обрабатываем аудио RVC: {temp_wav} с питчем {final_rvc_pitch}")
            output_file_rvc = self.current_tts_rvc.voiceover_file(
                input_path=temp_wav,
                **rvc_params
            )

            logger.info(f"Аудио сгенерировано RVC, путь: {output_file_rvc}")

            if not output_file_rvc or not os.path.exists(output_file_rvc) or os.path.getsize(output_file_rvc) == 0:
                logger.info(f"Внимание: сгенерированный RVC файл {output_file_rvc} отсутствует или имеет нулевой размер!")
                return None

            logger.info(f"RVC файл создан успешно, размер: {os.path.getsize(output_file_rvc)} байт")

            stereo_output_file = output_file_rvc.replace(".wav", "_stereo.wav")
            final_output_path = output_file_rvc
            atempo_value = 1.0

            converted_file = await self.convert_wav_to_stereo(output_file_rvc, stereo_output_file, atempo=atempo_value)

            if converted_file and os.path.exists(converted_file):
                logger.info(f"Файл успешно конвертирован в стерео: {stereo_output_file}")
                final_output_path = stereo_output_file
                try:
                    os.remove(output_file_rvc)
                    logger.info(f"Удален промежуточный файл RVC: {output_file_rvc}")
                except OSError as error:
                    logger.info(f"Не удалось удалить промежуточный файл RVC {output_file_rvc}: {error}")
            else:
                logger.info("Не удалось конвертировать файл в стерео формат, используется исходный RVC файл.")

            logger.info(f"Озвучка создана: {final_output_path}")
            if hasattr(self, 'parent') and getattr(self.parent, 'ConnectedToGame', False):
                self.parent.patch_to_sound_file = final_output_path

            return final_output_path

        except Exception as error:
            import traceback
            traceback.print_exc()
            logger.info(f"Ошибка при создании озвучки с Silero + RVC: {error}")
            return None
        finally:
            if temp_wav and os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                    logger.info(f"Удален временный файл Silero: {temp_wav}")
                except OSError as e:
                    logger.info(f"Не удалось удалить временный файл Silero {temp_wav}: {e}")

    async def voiceover_fish_speech(self, text, compile=False, with_rvc=False):
        if self.fish_speech_module is None:
            raise ImportError("Модуль fish_speech_lib не установлен. Сначала установите модель 'medium', 'medium+' или 'medium+low'.")

        try:
            if not self.current_fish_speech:
                logger.info(f"Предупреждение: Экземпляр FishSpeech не инициализирован для модели {self.current_model}. Попытка инициализации...")
                if not self.initialize_model(self.current_model):
                    raise Exception(f"Не удалось инициализировать модель FishSpeech для {self.current_model}")

            settings = self.load_model_settings(self.current_model)
            if not settings:
                logger.info(f"Предупреждение: Не найдены настройки для модели {self.current_model}. Используются значения по умолчанию.")

            is_combined_model = self.current_model == "medium+low"

            temp_key = "fsprvc_fsp_temperature" if is_combined_model else "temperature"
            top_p_key = "fsprvc_fsp_top_p" if is_combined_model else "top_p"
            rep_penalty_key = "fsprvc_fsp_repetition_penalty" if is_combined_model else "repetition_penalty"
            chunk_len_key = "fsprvc_fsp_chunk_length" if is_combined_model else "chunk_length"
            max_tokens_key = "fsprvc_fsp_max_tokens" if is_combined_model else "max_new_tokens"

            temperature = float(settings.get(temp_key, 0.7))
            top_p = float(settings.get(top_p_key, 0.7))
            repetition_penalty = float(settings.get(rep_penalty_key, 1.2))
            chunk_length = int(settings.get(chunk_len_key, 200))
            max_new_tokens = int(settings.get(max_tokens_key, 1024))
            use_memory_cache = True

            reference_audio_path = None
            reference_text = ""
            if self.clone_voice_filename and os.path.exists(self.clone_voice_filename):
                reference_audio_path = self.clone_voice_filename
                logger.info(f"Используем референс аудио: {reference_audio_path}")
                if self.clone_voice_text and os.path.exists(self.clone_voice_text):
                    try:
                        with open(self.clone_voice_text, "r", encoding="utf-8") as file:
                            reference_text = file.read().strip()
                        logger.info(f"Используем референс текст: '{reference_text[:50]}...'")
                    except Exception as error:
                        logger.info(f"Ошибка чтения файла референс текста {self.clone_voice_text}: {error}")
                else:
                    logger.info(f"Предупреждение: Файл референс текста не найден или не указан ({self.clone_voice_text}).")
            else:
                logger.info(f"Предупреждение: Файл референс аудио не найден или не указан ({self.clone_voice_filename}). Генерация без клонирования голоса.")

            logger.info(f"Начинаем генерацию аудио FishSpeech для текста: {text[:50]}...")
            sample_rate, audio_data = self.current_fish_speech(
                text=text,
                reference_audio=reference_audio_path,
                reference_audio_text=reference_text,
                top_p=top_p,
                temperature=temperature,
                repetition_penalty=repetition_penalty,
                max_new_tokens=max_new_tokens,
                chunk_length=chunk_length,
                use_memory_cache=use_memory_cache,
            )

            current_time_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            hash_object = hashlib.sha1(f"{text[:20]}_{current_time_str}".encode())
            random_name = hash_object.hexdigest()[:10]
            temp_dir = "temp"
            os.makedirs(temp_dir, exist_ok=True)
            raw_output_filename = f"fish_raw_{random_name}.wav"
            raw_output_path = os.path.abspath(os.path.join(temp_dir, raw_output_filename))

            import soundfile as sf
            sf.write(raw_output_path, audio_data, sample_rate, format='WAV')

            if not os.path.exists(raw_output_path) or os.path.getsize(raw_output_path) == 0:
                logger.info(f"Внимание: сгенерированный FishSpeech файл {raw_output_path} отсутствует или имеет нулевой размер!")
                return None

            logger.info(f"FishSpeech файл создан успешно: {raw_output_path}, размер: {os.path.getsize(raw_output_path)} байт")

            stereo_output_filename = raw_output_filename.replace("_raw", "_stereo")
            stereo_output_path = os.path.abspath(os.path.join(temp_dir, stereo_output_filename))
            volume_adjustment = 1.5
            converted_file = await self.convert_wav_to_stereo(raw_output_path, stereo_output_path, volume=str(volume_adjustment))

            processed_output_path = raw_output_path

            if converted_file and os.path.exists(converted_file):
                logger.info(f"Файл успешно конвертирован в стерео: {stereo_output_path}")
                processed_output_path = stereo_output_path
                try:
                    os.remove(raw_output_path)
                    logger.info(f"Удален промежуточный файл: {raw_output_path}")
                except OSError as error:
                    logger.info(f"Не удалось удалить промежуточный файл {raw_output_path}: {error}")
            else:
                logger.info("Не удалось конвертировать файл в стерео формат, используется исходный FishSpeech файл.")

            final_output_path = processed_output_path

            if with_rvc:
                logger.info(f"Применяем RVC к файлу: {final_output_path}")
                if not self.current_tts_rvc:
                    logger.info(f"Предупреждение: Экземпляр TTS_RVC не инициализирован для модели {self.current_model}. Попытка инициализации...")
                    if not self.initialize_model(self.current_model):
                        raise Exception(f"Не удалось инициализировать компонент RVC для модели {self.current_model}")

                rvc_output_path = await self.voiceover_edge_tts_rvc(text=None, TEST_WITH_DONE_AUDIO=final_output_path)

                if rvc_output_path and os.path.exists(rvc_output_path):
                    logger.info(f"RVC обработка завершена: {rvc_output_path}")
                    if final_output_path != rvc_output_path:
                        try:
                            os.remove(final_output_path)
                            logger.info(f"Удален промежуточный файл перед RVC: {final_output_path}")
                        except OSError as error:
                            logger.info(f"Не удалось удалить промежуточный файл {final_output_path}: {error}")
                    final_output_path = rvc_output_path
                else:
                    logger.info("Ошибка во время обработки RVC. Возвращается результат до RVC.")

            logger.info(f"Итоговая озвучка создана: {final_output_path}")

            if self.parent and hasattr(self.parent, 'patch_to_sound_file'):
                self.parent.patch_to_sound_file = final_output_path

            return final_output_path

        except Exception as error:
            import traceback
            traceback.print_exc()
            logger.info(f"Ошибка при создании озвучки с Fish Speech ({self.current_model}): {error}")
            return None
        
    async def voiceover_zonos(self, text, output_file="output.wav"):
        """Создает озвучку с помощью Zonos"""
        # Заглушка - в реальном коде здесь будет реализация Zonos
        try:
            # Имитируем работу
            await asyncio.sleep(3)
            self.create_dummy_wav(output_file)
            return output_file
        except Exception as e:
            logger.info(f"Ошибка при создании озвучки с Zonos: {e}")
            return None

    def create_dummy_wav(self, output_file):
        """Создает пустой WAV файл для тестирования"""
        import wave
        import struct
        
        # Создаем пустой WAV файл (1 секунда тишины)
        with wave.open(output_file, 'w') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(44100)
            for i in range(44100):
                value = int(0)
                data = struct.pack('<h', value)
                f.writeframesraw(data)

    async def play(self, file_path):
        """Проигрывает WAV файл."""
        if not os.path.exists(file_path):
            logger.info(f"Файл {file_path} не найден")
            return False

        def play_func():
            pygame.mixer.init()
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            pygame.mixer.music.stop()  
            pygame.mixer.quit() 

        # Выполняем блокирующую функцию в отдельном потоке
        await asyncio.to_thread(play_func)
        return True


    def is_model_installed(self, model_id):
        """Проверяет, установлена ли модель по её идентификатору"""
        if model_id == "low":
            return self.is_edge_tts_rvc_installed()
        elif model_id == "low+": 
            return self.is_edge_tts_rvc_installed() # and self.provider in ["NVIDIA"]
        elif model_id == "medium":
            return self.is_fish_speech_installed()
        elif model_id == "medium+":
            return self.is_fish_speech_installed() and self.is_triton_installed()
        elif model_id == "medium+low":
            return self.is_edge_tts_rvc_installed() and self.is_fish_speech_installed() and self.is_triton_installed()

        elif model_id == "high":
            return self.is_zonos_installed()
        return False

    def is_edge_tts_rvc_installed(self):
        """Проверяет, установлен ли Edge-TTS + RVC"""
        return self.tts_rvc_module is not None

    def is_fish_speech_installed(self):
        """Проверяет, установлен ли Fish Speech"""
        return self.fish_speech_module is not None

    def is_zonos_installed(self):
        """Проверяет, установлен ли Zonos"""
        return self.zonos_module is not None 
    
    def is_triton_installed(self):
        """Проверяет, установлен ли Triton"""
        try:
            import triton
            return True
        except ImportError:
            return False
    
    def is_cuda_available(self):
        """Проверяет доступность CUDA"""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
    
        
    #region Settings region:
    def load_model_settings(self, model_id):
        """Загружает настройки для указанной модели из файла настроек"""
        try:
            settings_file = os.path.join("Settings", "voice_model_settings.json")
            if os.path.exists(settings_file):
                with open(settings_file, "r", encoding="utf-8") as f:
                    all_settings = json.load(f)
                    if model_id in all_settings:
                        return all_settings[model_id]
            return {}
        except Exception as e:
            logger.info(f"Ошибка при загрузке настроек модели {model_id}: {e}")
            return {}
    #endregion

    def add_to_initialized(self, model_id):
        self.initialized_models.add(model_id)
        if model_id == "medium+" and "low" in self.initialized_models:
            self.initialized_models.add("medium+low")
        elif model_id == "medium+low":
            self.initialized_models.add("medium+")

    def is_model_initialized(self, model_id):
        """Проверяет, инициализирована ли модель с указанным ID"""
        if model_id in self.initialized_models:
            return True
        return False

    #region Big fucntion to initialize model
    def initialize_model(self, model_id, init=False):
        """Инициализирует модель с указанным ID и параметрами из настроек"""
        if model_id not in ["low", "low+", "medium", "medium+", "medium+low"]: 
            logger.info(f"Неизвестный ID модели: {model_id}")
            return False

        if self.is_model_initialized(model_id):
            return True
        
        # Загружаем настройки для модели
        settings = self.load_model_settings(model_id)
        if not settings and model_id != "low+":
            logger.info(f"Предупреждение: Не найдены настройки для модели {model_id}. Используются значения по умолчанию.")
        
        try:
            if model_id == "low":
                # Edge-TTS + RVC
                if self.tts_rvc_module is None:
                    logger.info("Модуль tts_with_rvc не установлен")
                    return False
                    
                # Получаем параметры из настроек
                device = settings.get("device", "cuda:0" if self.provider == "NVIDIA" else "dml" if self.provider == "AMD" else "cpu")
                f0_method = settings.get("f0method", "rmvpe" if self.provider == "NVIDIA" else "pm")
                
                if (self.pth_path and os.path.exists(self.pth_path)) or os.path.exists("Models\\Mila.pth") or os.path.exists("Models\\Mila.onnx"):
                    # Инициализируем модель с настройками
                    self.current_tts_rvc = None
                    if self.provider == "NVIDIA":
                        self.current_tts_rvc = self.tts_rvc_module(
                            model_path=self.pth_path if self.pth_path else "Models\\Mila.pth",
                            device=device,
                            f0_method=f0_method
                        )
                    elif self.provider == "AMD":
                        self.current_tts_rvc = self.tts_rvc_module(
                            model_path=self.pth_path if self.pth_path else "Models\\Mila.onnx",
                            device=device,
                            f0_method=f0_method
                        )
                    
                    if self.voice_language == "ru":
                        self.current_tts_rvc.set_voice("ru-RU-SvetlanaNeural")
                    elif self.voice_language == "en":
                        self.current_tts_rvc.set_voice("en-US-MichelleNeural")
                    else:
                        self.current_tts_rvc.set_voice("en-US-AvaMultilingualNeural")

                    if init:
                        init_text = f"Инициализация модели {model_id}" if self.voice_language == "ru" else f"{model_id} Model Initialization"
                        pitch = float(settings.get("pitch", 6))
                        index_rate = float(settings.get("index_rate", 0.75))
                        protect = float(settings.get("protect", 0.33))
                        tts_rate = int(settings.get("tts_rate", 0))
                        # output_gain = float(settings.get("output_gain", 0.75))
                        filter_radius = int(settings.get("filter_radius", 3))
                        rms_mix_rate = float(settings.get("rms_mix_rate", 0.5))
                        is_half = settings.get("is_half", "True") == "True"
                        
                        try:
                            if self.provider == "NVIDIA":
                                self.current_tts_rvc(
                                    text=init_text,
                                    pitch=pitch,
                                    index_rate=index_rate,
                                    protect=protect,
                                    tts_rate=tts_rate,
                                    # output_gain=output_gain,
                                    filter_radius=filter_radius,
                                    rms_mix_rate=rms_mix_rate,
                                    is_half=is_half
                                )
                            else:
                                self.current_tts_rvc(
                                    text=init_text,
                                    pitch=pitch,
                                    index_rate=index_rate,
                                    protect=protect,
                                    tts_rate=tts_rate,
                                    # output_gain=output_gain,
                                    filter_radius=filter_radius,
                                    rms_mix_rate=rms_mix_rate
                                )
                        except Exception as e:
                            logger.info(f"Ошибка при инициализации модели с тестовым текстом: {e}")
                            return False
                    
                    self.current_model = model_id
                    self.add_to_initialized(model_id)
                    return True
                else:
                    logger.info(f"Не найден файл модели по пути: {self.pth_path}")
                    return False
                    
            elif model_id == "low+":
                if self.tts_rvc_module is None:
                    logger.info("Модуль tts_with_rvc не установлен (необходим для low+)")
                    return False

                # Инициализация RVC части 
                rvc_device = settings.get("device", "cuda:0" if self.provider == "NVIDIA" else "dml" if self.provider == "AMD" else "cpu")
                rvc_f0_method = settings.get("f0method", "rmvpe" if self.provider == "NVIDIA" else "pm")

                rvc_is_half_str = settings.get("is_half", "True")

                rvc_is_half = rvc_is_half_str.lower() == "true"

                default_model_name = "Mila"

                is_nvidia = self.provider in ["NVIDIA"]

                default_pth_path = os.path.join(os.path.abspath(self.clone_voice_folder), f"{default_model_name}.{'pth' if is_nvidia else 'onnx'}")
                model_path_to_use = default_pth_path

                if self.pth_path and os.path.exists(self.pth_path):
                    model_path_to_use = self.pth_path
                elif not os.path.exists(default_pth_path):
                     logger.info(f"Не найден файл RVC модели по умолчанию: {default_pth_path}")
                     return False

                if self.current_tts_rvc == None:
                    try:
                        self.current_tts_rvc = self.tts_rvc_module(
                            model_path=model_path_to_use, device=rvc_device, f0_method=rvc_f0_method
                        )
                        
                        if self.voice_language == "ru":
                            self.current_tts_rvc.set_voice("ru-RU-SvetlanaNeural")
                        elif self.voice_language == "en":
                            self.current_tts_rvc.set_voice("en-US-MichelleNeural")
                        else:
                            self.current_tts_rvc.set_voice("en-US-AvaMultilingualNeural")
                            
                        logger.info("RVC компонент для low+ инициализирован.")
                    except Exception as e:
                        logger.error(f"Ошибка инициализации RVC компонента для low+: {e}")
                        #traceback.print_exc()
                        return False


                # Инициализация Silero части (загрузка из кэша torch.hub)
                silero_device = settings.get("silero_device", "cuda" if self.provider == "NVIDIA" else "cpu")
                silero_sample_rate = int(settings.get("silero_sample_rate", 48000))
                if self.voice_language == 'en':
                    language = 'en'
                    model_id_silero = 'v3_en'
                    logger.info(f"Selected ENGLISH language ({language}/{model_id_silero}) for Silero+RVC (low+).")
                elif self.voice_language == 'ru':
                    language = 'ru'
                    model_id_silero = 'v4_ru'
                    logger.info(f"Выбран РУССКИЙ язык ({language}/{model_id_silero}) для Silero (low+).")
                else:
                    logger.error(f"Unsupported language '{self.voice_language}' for low+. Using RUSSIAN as default.")
                    language = 'ru'
                    model_id_silero = 'v4_ru'
                self.current_silero_model = None
                try:
                    import torch
                    logger.info(f"Загрузка модели Silero ({language}/{model_id_silero}) из torch.hub...")

                    model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models',
                                              model='silero_tts',
                                              language=language,
                                              speaker=model_id_silero,
                                              trust_repo=True)

                    # Перемещаем модель на нужное устройство
                    logger.info(f"SILERO LOCAL: Перемещаем модель на нужное устройство {silero_device}")
                    model.to(silero_device)
                    self.current_silero_model = model
                    self.current_silero_sample_rate = silero_sample_rate
                    logger.info(f"Silero компонент для low+ инициализирован на устройстве {silero_device}.")

                except Exception as e:
                    logger.error(f"Ошибка инициализации Silero компонента для low+: {e}")
                    #traceback.print_exc()

                    try:
                        logger.info("Попытка очистить кэш torch.hub и загрузить Silero снова...")

                        model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models',
                                                  model='silero_tts',
                                                  language=language,
                                                  speaker=model_id_silero,
                                                  force_reload=True, # Принудительная перезагрузка
                                                  trust_repo=True)
                        
                        logger.info("SILERO LOCAL: Перемещаем модель на нужное устройство", silero_device)
                        model.to(silero_device)
                        self.current_silero_model = model
                        self.current_silero_sample_rate = silero_sample_rate
                        logger.info(f"Silero компонент успешно загружен после перезагрузки на {silero_device}.")
                    except Exception as e2:
                        logger.error(f"Повторная ошибка инициализации Silero компонента для low+: {e2}")
                        #traceback.print_exc()
                        return False # Если и вторая попытка не удалась, выходим

                # Если нужна инициализация с тестовым текстом
                if init:
                    init_text = f"Инициализация модели {model_id}"
                    try:
                        # Устанавливаем .index для RVC перед тестом
                        rvc_use_index_file = settings.get("use_index_file", True)
                        index_path_to_use = None
                        if rvc_use_index_file:
                            default_index_path = os.path.join(os.path.abspath(self.clone_voice_folder), f"{default_model_name}.index")
                            if self.index_path and os.path.exists(self.index_path):
                                index_path_to_use = self.index_path
                            elif os.path.exists(default_index_path):
                                index_path_to_use = default_index_path
                        self.current_tts_rvc.set_index_path(index_path_to_use if index_path_to_use else "")

                        # Вызываем voiceover_silero_rvc
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self.voiceover_silero_rvc(init_text))
                        loop.close()
                        logger.info(f"Тестовый прогон для {model_id} завершен.")
                    except Exception as e:
                        logger.error(f"Ошибка при инициализации модели {model_id} с тестовым текстом: {e}")
                        #traceback.print_exc()
                        # return False # Не прерываем

                self.current_model = model_id
                self.add_to_initialized(model_id)
                logger.info(f"Модель {model_id} успешно инициализирована.")
                return True

            elif model_id == "medium":
                # Fish Speech
                if self.fish_speech_module is None:
                    logger.info("Модуль fish_speech_lib не установлен")
                    return False
                    
                # Получаем параметры из настроек
                device = settings.get("device", "cuda")
                half = settings.get("half", "False") == "True"
                temperature = float(settings.get("temperature", 0.7))
                top_p = float(settings.get("top_p", 0.7))
                repetition_penalty = float(settings.get("repetition_penalty", 1.2))
                chunk_length = int(settings.get("chunk_length", 200))
                max_new_tokens = int(settings.get("max_new_tokens", 1024))
                compile_model = settings.get("compile_model", "False") == "True"
                
                # Инициализируем модель
                self.current_fish_speech = None
                self.current_fish_speech = self.fish_speech_module(
                    device=device,
                    half=half,
                    compile_model=compile_model
                )
                if not self.first_compiled:
                    self.first_compiled = False


                if init and (self.clone_voice_filename and os.path.exists(self.clone_voice_filename) or os.path.exists("Models\\Mila.wav")) :
                    init_text = f"Инициализация модели {model_id}" if self.voice_language == "ru" else f"{model_id} Model Initialization"
                    ref_text = ""
                    if self.clone_voice_text and os.path.exists(self.clone_voice_text):
                        with open(self.clone_voice_text, "r", encoding="utf-8") as f:
                            ref_text = f.read()
                    
                    try:
                        import soundfile as sf
                        sample_rate, audio_data = self.current_fish_speech(
                            init_text,
                            reference_audio=self.clone_voice_filename if self.clone_voice_filename else "Models\\Mila.wav",
                            reference_audio_text=ref_text if self.clone_voice_filename else "Models\\Mila.txt",
                            top_p=top_p,
                            temperature=temperature,
                            repetition_penalty=repetition_penalty,
                            max_new_tokens=min(max_new_tokens, 100),
                            chunk_length=chunk_length,
                            use_memory_cache=False
                        )
                        
                        # Сохраняем результат для проверки
                        import hashlib
                        from datetime import datetime
                        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                        hash_object = hashlib.md5(current_time.encode())
                        random_name = hash_object.hexdigest()[:8]
                        output_path = f"temp/init-{random_name}.wav"
                        os.makedirs("temp", exist_ok=True)
                        sf.write(output_path, audio_data, sample_rate, format='WAV')
                    except Exception as e:
                        logger.info(f"Ошибка при инициализации Fish Speech с тестовым текстом: {e}")
                        return False
                
                self.current_model = model_id
                self.add_to_initialized(model_id)
                return True
                
            elif model_id == "medium+":
                # Fish Speech+
                if self.fish_speech_module is None:
                    logger.info("Модуль fish_speech_lib не установлен")
                    return False
                    
                if not self.is_triton_installed():
                    logger.info("Модуль triton не установлен, требуется для Fish Speech+")
                    return False
                    
                # Получаем параметры из настроек
                device = settings.get("device", "cuda")
                half = settings.get("half", "True") == "True"
                temperature = float(settings.get("temperature", 0.7))
                top_p = float(settings.get("top_p", 0.8))
                repetition_penalty = float(settings.get("repetition_penalty", 1.1))
                chunk_length = int(settings.get("chunk_length", 200))
                max_new_tokens = int(settings.get("max_new_tokens", 1024))
                compile_model = settings.get("compile_model", "True") == "True"
                
                # Инициализируем модель с компиляцией
                try:
                    self.current_fish_speech = None
                    self.current_fish_speech = self.fish_speech_module(
                        device=device,
                        half=half,
                        compile_model=compile_model
                    )
                    if not self.first_compiled:
                        self.first_compiled = True
                    
                    if init and (self.clone_voice_filename and os.path.exists(self.clone_voice_filename) or os.path.exists("Models\\Mila.wav")):
                        init_text = f"Инициализация модели {model_id}" if self.voice_language == "ru" else f"{model_id} Model Initialization"
                        ref_text = ""
                        if self.clone_voice_text and os.path.exists(self.clone_voice_text):
                            with open(self.clone_voice_text, "r", encoding="utf-8") as f:
                                ref_text = f.read()
                        
                        try:
                            import soundfile as sf
                            sample_rate, audio_data = self.current_fish_speech(
                                init_text,
                                reference_audio=self.clone_voice_filename if self.clone_voice_filename else "Models\\Mila.wav",
                                reference_audio_text=ref_text if self.clone_voice_filename else "Models\\Mila.txt",
                                top_p=top_p,
                                temperature=temperature,
                                repetition_penalty=repetition_penalty,
                                max_new_tokens=min(max_new_tokens, 100),
                                chunk_length=chunk_length,
                                use_memory_cache=False
                            )
                            
                            # Сохраняем результат для проверки
                            import hashlib
                            from datetime import datetime
                            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                            hash_object = hashlib.md5(current_time.encode())
                            random_name = hash_object.hexdigest()[:8]
                            output_path = f"temp/init-{random_name}.wav"
                            os.makedirs("temp", exist_ok=True)
                            sf.write(output_path, audio_data, sample_rate, format='WAV')
                        except Exception as e:
                            logger.info(f"Ошибка при инициализации Fish Speech+ с тестовым текстом: {e}")
                            return False
                    
                    self.current_model = model_id
                    self.add_to_initialized(model_id)
                    return True
                except Exception as e:
                    logger.info(f"Ошибка при инициализации Fish Speech+: {e}")
                    return False
                    
            elif model_id == "medium+low":
                # Fish Speech+ + RVC
                if self.fish_speech_module is None or self.tts_rvc_module is None:
                    logger.info("Не хватает необходимых модулей для medium+low")
                    return False
                    
                if not self.is_triton_installed():
                    logger.info("Модуль triton не установлен, требуется для Fish Speech+")
                    return False
                    
                # Получаем параметры для Fish Speech+ из настроек
                fsp_device = settings.get("fsprvc_fsp_device", "cuda")
                fsp_half = settings.get("fsprvc_fsp_half", "True") == "True"
                fsp_temperature = float(settings.get("fsprvc_fsp_temperature", 0.7))
                fsp_top_p = float(settings.get("fsprvc_fsp_top_p", 0.8))
                fsp_repetition_penalty = float(settings.get("fsprvc_fsp_repetition_penalty", 1.1))
                fsp_chunk_length = int(settings.get("fsprvc_fsp_chunk_length", 200))
                fsp_max_tokens = int(settings.get("fsprvc_fsp_max_tokens", 1024))
                
                # Получаем параметры для RVC из настроек
                rvc_device = settings.get("fsprvc_rvc_device", "cuda:0" if self.provider == "NVIDIA" else "dml")
                rvc_is_half = settings.get("fsprvc_is_half", "True") == "True"
                rvc_f0method = settings.get("fsprvc_f0method", "rmvpe" if self.provider == "NVIDIA" else "dio")
                rvc_pitch = float(settings.get("fsprvc_rvc_pitch", 0))
                rvc_index_rate = float(settings.get("fsprvc_index_rate", 0.75))
                rvc_protect = float(settings.get("fsprvc_protect", 0.33))
                # rvc_output_gain = float(settings.get("fsprvc_output_gain", 0.75))
                rvc_filter_radius = int(settings.get("fsprvc_filter_radius", 3))
                rvc_rms_mix_rate = float(settings.get("fsprvc_rvc_rms_mix_rate", 0.5))
                
                # Инициализируем Fish Speech+
                try:
                    self.current_fish_speech = None
                    self.current_fish_speech = self.fish_speech_module(
                        device=fsp_device,
                        half=fsp_half,
                        compile_model=True
                    )

                    if not self.first_compiled:
                        self.first_compiled = True
                    
                    # Инициализируем RVC, если у нас есть путь к модели
                    if (self.pth_path and os.path.exists(self.pth_path)) or os.path.exists("Models\\Mila.pth"):
                        self.current_tts_rvc = self.tts_rvc_module(
                            model_path=self.pth_path if self.pth_path else "Models\\Mila.pth",
                            device=rvc_device,
                            f0_method=rvc_f0method
                        )
                    else:
                        logger.info("Не удалось найти файл модели RVC")
                        return False
                    
                    # Если нужна инициализация с тестовым текстом
                    if init and (self.clone_voice_filename and os.path.exists(self.clone_voice_filename)) or os.path.exists("Models\\Mila.wav"):
                        init_text = f"Инициализация модели {model_id}" if self.voice_language == "ru" else f"{model_id} Model Initialization"
                        ref_text = ""
                        if self.clone_voice_text and os.path.exists(self.clone_voice_text):
                            with open(self.clone_voice_text, "r", encoding="utf-8") as f:
                                ref_text = f.read()
                        else:
                            if os.path.exists("Models\\Mila.txt"):
                                with open("Models\\Mila.txt", "r", encoding="utf-8") as f:
                                    ref_text = f.read()

                        
                        try:
                            import soundfile as sf
                            sample_rate, audio_data = self.current_fish_speech(
                                init_text,
                                reference_audio=self.clone_voice_filename if self.clone_voice_filename else "Models\\Mila.wav",
                                reference_audio_text=ref_text if self.clone_voice_filename else "Models\\Mila.txt",
                                top_p=fsp_top_p,
                                temperature=fsp_temperature,
                                repetition_penalty=fsp_repetition_penalty,
                                max_new_tokens=min(fsp_max_tokens, 100),
                                chunk_length=fsp_chunk_length,
                                use_memory_cache=False
                            )
                            
                            import hashlib
                            from datetime import datetime
                            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                            hash_object = hashlib.md5(current_time.encode())
                            random_name = hash_object.hexdigest()[:8]
                            temp_output_path = f"temp/init-fsp-{random_name}.wav"
                            os.makedirs("temp", exist_ok=True)
                            sf.write(temp_output_path, audio_data, sample_rate, format='WAV')
                            

                            if not self.pth_path and os.path.exists("Models\\Mila.pth"):
                                self.current_tts_rvc.current_model = "Models\\Mila.pth"
                            else:
                                self.current_tts_rvc.current_model = self.pth_path
                            output_path = self.current_tts_rvc.voiceover_file(
                                input_path=temp_output_path,
                                pitch=rvc_pitch,
                                index_rate=rvc_index_rate,
                                protect=rvc_protect,
                                # output_gain=rvc_output_gain,
                                filter_radius=rvc_filter_radius,
                                rms_mix_rate=rvc_rms_mix_rate,
                                is_half=rvc_is_half
                            )
                            
                            # Проверяем результат
                            if not os.path.exists(output_path):
                                logger.info(f"Ошибка при инициализации RVC: файл {output_path} не создан")
                                return False
                        except Exception as e:
                            logger.info(f"Ошибка при инициализации Fish Speech+ + RVC: {e}")
                            return False
                    
                    self.current_model = model_id
                    self.add_to_initialized(model_id)
                    return True
                except Exception as e:
                    # Get the full traceback information
                    tb_str = traceback.format_exc()

                    # Log the original concise error message AND the full traceback
                    logger.error(f"Ошибка при инициализации Fish Speech+ + RVC: {e}") # Log the specific error
                    logger.error("Full Traceback:")
                    logger.error(tb_str) # Log the detailed traceback

                    # Optionally print to console as well during debugging
                    print(f"ERROR: Ошибка при инициализации Fish Speech+ + RVC: {e}")
                    print("--- Full Traceback ---")
                    print(tb_str)
                    print("--- End Traceback ---")

                    return False # Or handle the error as appropriate
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.info(f"Непредвиденная ошибка при инициализации модели {model_id}: {e}")
            return False
    #endregion

    
    