import os
import sys
import importlib
import traceback
import hashlib
from datetime import datetime
import asyncio

from .base_model import IVoiceModel
from typing import Optional, Any, List, Dict
from main_logger import logger

from .edge_tts_rvc_model import EdgeTTS_RVC_Model
import importlib.util

import subprocess
from PyQt6.QtCore import QTimer, Qt

from utils.pip_installer import PipInstaller

from managers.settings_manager import SettingsManager

from utils import getTranslationVariant as _, get_character_voice_paths

from core.events import get_event_bus, Events


class FishSpeechModel(IVoiceModel):
    def __init__(self, parent: 'LocalVoice', model_id: str, rvc_handler: Optional[IVoiceModel] = None):
        super().__init__(parent, model_id)
        self.fish_speech_module = None
        self.current_fish_speech = None
        self.events = get_event_bus()
        self.rvc_handler = rvc_handler

    MODEL_CONFIGS = [
        {
            "id": "medium",
            "name": "Fish Speech",
            "min_vram": 3, "rec_vram": 6,
            "gpu_vendor": ["NVIDIA"],
            "size_gb": 5,
            "languages": ["Russian", "English", "Chinese", "German", "Japanese", "French", "Korean", "Arabic", "Dutch", "Italian", "Polish", "Portuguese"],
            "intents": [_("Качество", "Quality"), _("Сбалансировано", "Balanced")],
            "description": _(
                "Генерация речи хорошего качества. Требует больше ресурсов, чем быстрые модели.",
                "Speech generation with good quality. Requires more resources than fast models."
            ),
            "settings": [
                {"key": "device", "label": _("Устройство", "Device"), "type": "combobox",
                 "options": {"values": ["cuda", "cpu", "mps"], "default": "cuda"},
                 "help": _("Устройство вычислений для модели.", "Compute device for the model.")},
                {"key": "half", "label": _("Half-precision", "Half-precision"), "type": "combobox",
                 "options": {"values": ["False", "True"], "default": "False"},
                 "help": _("FP16 для экономии VRAM и ускорения (если поддерживается).", "FP16 for VRAM saving and speed (if supported).")},
                {"key": "temperature", "label": _("Температура", "Temperature"), "type": "entry", "options": {"default": "0.7"},
                 "help": _("Случайность сэмплирования (>0): выше — разнообразнее, но нестабильнее.", "Sampling randomness (>0): higher — more diverse, less stable.")},
                {"key": "top_p", "label": _("Top-P", "Top-P"), "type": "entry", "options": {"default": "0.7"},
                 "help": _("Ядерное сэмплирование (0..1): ограничивает выбор наиболее вероятными токенами.", "Nucleus sampling (0..1): keep only most probable tokens.")},
                {"key": "repetition_penalty", "label": _("Штраф повторений", "Repetition Penalty"), "type": "entry", "options": {"default": "1.2"},
                 "help": _(">1 уменьшает зацикливание на повторах.", ">1 reduces looping on repeats.")},
                {"key": "chunk_length", "label": _("Размер чанка (~символов)", "Chunk Size (~chars)"), "type": "entry", "options": {"default": "200"},
                 "help": _("Сколько текста обрабатывается за раз (влияет на память).", "How much text is processed at once (affects memory).")},
                {"key": "max_new_tokens", "label": _("Макс. токены", "Max Tokens"), "type": "entry", "options": {"default": "1024"},
                 "help": _("Ограничение длины генерируемой последовательности.", "Limit of generated sequence length.")},
                {"key": "compile_model", "label": _("Компиляция модели", "Compile Model"), "type": "combobox",
                 "options": {"values": ["False", "True"], "default": "False"},
                 "locked": True,
                 "help": _("torch.compile() ускоряет на GPU после первого запуска.", "torch.compile() speeds up on GPU after warmup.")},
                {"key": "seed", "label": _("Seed", "Seed"), "type": "entry", "options": {"default": "0"},
                 "help": _("Инициализация генератора случайности.", "Random seed.")},
                {"key": "volume", "label": _("Громкость (volume)", "Volume"), "type": "entry", "options": {"default": "1.0"},
                 "help": _("Итоговая громкость.", "Final loudness.")}
            ]
        },
        {
            "id": "medium+",
            "name": "Fish Speech+",
            "min_vram": 3, "rec_vram": 6,
            "gpu_vendor": ["NVIDIA"],
            "size_gb": 10,
            "rtx30plus": True,
            "languages": ["Russian", "English", "Chinese", "German", "Japanese", "French", "Korean", "Arabic", "Dutch", "Italian", "Polish", "Portuguese"],
            "intents": [_("Качество", "Quality"), _("RTX 30+/40+", "RTX 30+/40+")],
            "description": _(
                "Версия Fish Speech, скомпилированная под GPU. Требует больше места и современную NVIDIA.",
                "Fish Speech version compiled for GPU. Needs more disk space and a modern NVIDIA GPU."
            ),
            "settings": [
                {"key": "device", "label": _("Устройство", "Device"), "type": "combobox",
                 "options": {"values": ["cuda", "cpu", "mps"], "default": "cuda"},
                 "help": _("Устройство вычислений для модели.", "Compute device for the model.")},
                {"key": "half", "label": _("Half-precision", "Half-precision"), "type": "combobox",
                 "options": {"values": ["True", "False"], "default": "False"},
                 "locked": True,
                 "help": _("FP16 принудительно, параметр заблокирован для совместимости.", "FP16 enforced; parameter locked for compatibility.")},
                {"key": "temperature", "label": _("Температура", "Temperature"), "type": "entry", "options": {"default": "0.7"},
                 "help": _("Случайность сэмплирования (>0): выше — разнообразнее, но нестабильнее.", "Sampling randomness (>0): higher — more diverse, less stable.")},
                {"key": "top_p", "label": _("Top-P", "Top-P"), "type": "entry", "options": {"default": "0.8"},
                 "help": _("Ядерное сэмплирование (0..1): ограничивает выбор наиболее вероятными токенами.", "Nucleus sampling (0..1): keep only most probable tokens.")},
                {"key": "repetition_penalty", "label": _("Штраф повторений", "Repetition Penalty"), "type": "entry", "options": {"default": "1.1"},
                 "help": _(">1 уменьшает зацикливание на повторах.", ">1 reduces looping on repeats.")},
                {"key": "chunk_length", "label": _("Размер чанка (~символов)", "Chunk Size (~chars)"), "type": "entry", "options": {"default": "200"},
                 "help": _("Сколько текста обрабатывается за раз (влияет на память).", "How much text is processed at once (affects memory).")},
                {"key": "max_new_tokens", "label": _("Макс. токены", "Max Tokens"), "type": "entry", "options": {"default": "1024"},
                 "help": _("Ограничение длины генерируемой последовательности.", "Limit of generated sequence length.")},
                {"key": "compile_model", "label": _("Компиляция модели", "Compile Model"), "type": "combobox",
                 "options": {"values": ["False", "True"], "default": "True"},
                 "locked": True,
                 "help": _("torch.compile() включён и заблокирован для ускорения.", "torch.compile() enabled and locked for speed.")},
                {"key": "seed", "label": _("Seed", "Seed"), "type": "entry", "options": {"default": "0"},
                 "help": _("Инициализация генератора случайности.", "Random seed.")},
                {"key": "volume", "label": _("Громкость (volume)", "Volume"), "type": "entry", "options": {"default": "1.0"},
                 "help": _("Итоговая громкость.", "Final loudness.")}
            ]
        },
        {
            "id": "medium+low",
            "name": "Fish Speech+ + RVC",
            "min_vram": 5, "rec_vram": 8,
            "gpu_vendor": ["NVIDIA"],
            "size_gb": 15,
            "rtx30plus": True,
            "languages": ["Russian", "English", "Chinese", "German", "Japanese", "French", "Korean", "Arabic", "Dutch", "Italian", "Polish", "Portuguese"],
            "intents": [_("Качество", "Quality"), _("Конверсия голоса", "Voice conversion")],
            "description": _(
                "Комбинация Fish Speech+ и RVC для высококачественного изменения тембра.",
                "Combination of Fish Speech+ and RVC for high‑quality timbre conversion."
            ),
            "settings": [
                {"key": "fsprvc_fsp_device", "label": _("[FSP] Устройство", "[FSP] Device"), "type": "combobox",
                 "options": {"values": ["cuda", "cpu", "mps"], "default": "cuda"},
                 "help": _("Устройство для части Fish Speech+.", "Device for Fish Speech+ part.")},
                {"key": "fsprvc_fsp_half", "label": _("[FSP] Half-precision", "[FSP] Half-precision"), "type": "combobox",
                 "options": {"values": ["True", "False"], "default": "False"},
                 "locked": True,
                 "help": _("FP16 для ускорения; параметр заблокирован.", "FP16 for speed; parameter locked.")},
                {"key": "fsprvc_fsp_temperature", "label": _("[FSP] Температура", "[FSP] Temperature"), "type": "entry", "options": {"default": "0.7"},
                 "help": _("Случайность генерации в части Fish Speech+.", "Sampling randomness in Fish Speech+ part.")},
                {"key": "fsprvc_fsp_top_p", "label": _("[FSP] Top-P", "[FSP] Top-P"), "type": "entry", "options": {"default": "0.7"},
                 "help": _("Нуклеус‑сэмплинг для Fish Speech+.", "Nucleus sampling for Fish Speech+.")},
                {"key": "fsprvc_fsp_repetition_penalty", "label": _("[FSP] Штраф повторений", "[FSP] Repetition Penalty"), "type": "entry", "options": {"default": "1.2"},
                 "help": _("Снижает повторения в тексте.", "Reduces repetitions.")},
                {"key": "fsprvc_fsp_chunk_length", "label": _("[FSP] Размер чанка (слов)", "[FSP] Chunk Size (words)"), "type": "entry", "options": {"default": "200"},
                 "help": _("Размер порции текста для Fish Speech+.", "Chunk size for Fish Speech+.")},
                {"key": "fsprvc_fsp_max_tokens", "label": _("[FSP] Макс. токены", "[FSP] Max Tokens"), "type": "entry", "options": {"default": "1024"},
                 "help": _("Ограничение длины генерации.", "Generation length limit.")},
                {"key": "compile_model", "label": _("Компиляция модели", "Compile Model"), "type": "combobox",
                 "options": {"values": ["False", "True"], "default": "False"},
                 "locked": True,
                 "help": _("torch.compile() ускоряет на GPU после первого запуска.", "torch.compile() speeds up on GPU after warmup.")},
                {"key": "fsprvc_fsp_seed", "label": _("[FSP] Seed", "[FSP] Seed"), "type": "entry", "options": {"default": "0"},
                 "help": _("Сид генерации для Fish Speech+.", "Seed value for Fish Speech+.")},
                {"key": "fsprvc_rvc_device", "label": _("[RVC] Устройство", "[RVC] Device"), "type": "combobox",
                 "options": {"values": ["cuda:0", "cpu", "mps:0", "dml"], "default_nvidia": "cuda:0", "default_amd": "dml"},
                 "help": _("Устройство для части RVC.", "Device for RVC part.")},
                {"key": "fsprvc_is_half", "label": _("[RVC] Half-precision", "[RVC] Half-precision"), "type": "combobox",
                 "options": {"values": ["True", "False"], "default_nvidia": "True", "default_amd": "False"},
                 "help": _("FP16 для RVC на совместимых GPU.", "FP16 for RVC on compatible GPUs.")},
                {"key": "fsprvc_f0method", "label": _("[RVC] Метод F0", "[RVC] F0 Method"), "type": "combobox",
                 "options": {"values": ["pm", "rmvpe", "crepe", "harvest", "fcpe", "dio"], "default_nvidia": "rmvpe", "default_amd": "dio"},
                 "help": _("Алгоритм извлечения высоты тона.", "Pitch extraction algorithm.")},
                {"key": "fsprvc_rvc_pitch", "label": _("[RVC] Высота голоса (пт)", "[RVC] Pitch (semitones)"), "type": "entry", "options": {"default": "0"},
                 "help": _("Смещение высоты в полутонах.", "Pitch shift in semitones.")},
                {"key": "fsprvc_use_index_file", "label": _("[RVC] Исп. .index файл", "[RVC] Use .index file"), "type": "checkbutton", "options": {"default": True},
                 "help": _("Улучшает совпадение тембра.", "Improves timbre matching.")},
                {"key": "fsprvc_index_rate", "label": _("[RVC] Соотн. индекса", "[RVC] Index Rate"), "type": "entry", "options": {"default": "0.75"},
                 "help": _("Степень влияния .index (0..1).", "How much .index affects result (0..1).")},
                {"key": "fsprvc_protect", "label": _("[RVC] Защита согласных", "[RVC] Consonant Protection"), "type": "entry", "options": {"default": "0.33"},
                 "help": _("Защита глухих согласных (0..0.5).", "Protect voiceless consonants (0..0.5).")},
                {"key": "fsprvc_filter_radius", "label": _("[RVC] Радиус фильтра F0", "[RVC] F0 Filter Radius"), "type": "entry", "options": {"default": "3"},
                 "help": _("Сглаживание кривой F0 (рекоменд. ≥3).", "Smooth F0 curve (recommended ≥3).")},
                {"key": "fsprvc_rvc_rms_mix_rate", "label": _("[RVC] Смешивание RMS", "[RVC] RMS Mixing"), "type": "entry", "options": {"default": "0.5"},
                 "help": _("Смешивание громкости исходника и RVC (0..1).", "Mix source loudness and RVC result (0..1).")},
                {"key": "volume", "label": _("Громкость (volume)", "Volume"), "type": "entry", "options": {"default": "1.0"},
                 "help": _("Итоговая громкость.", "Final loudness.")}
            ]
        }
    ]

    def get_model_configs(self) -> List[Dict[str, Any]]:
        return self.MODEL_CONFIGS

    def _load_module(self):
        if self.fish_speech_module is not None:
            return
        if getattr(self, "_import_attempted", False):
            return

        self._import_attempted = True
        try:
            from fish_speech_lib.inference import FishSpeech
            self.fish_speech_module = FishSpeech
        except ImportError as ex:
            logger.info(ex)
            self.fish_speech_module = None

    def get_display_name(self) -> str:
        mode = self._mode()
        if mode == "medium":
            return "Fish Speech"
        elif mode == "medium+":
            return "Fish Speech+"
        elif mode == "medium+low":
            return "Fish Speech+ + RVC"
        return None

    def is_installed(self, model_id) -> bool:
        self._load_module()
        mode = model_id
        if self.fish_speech_module is None:
            return False
        if mode in ("medium+", "medium+low"):
            if not self.parent.is_triton_installed():
                return False
        if mode == "medium+low":
            if self.rvc_handler is None or not self.rvc_handler.is_installed("low"):
                return False
        return True

    def install(self, model_id) -> bool:
        self._load_module()
        if self.fish_speech_module is None:
            if not self._install_fish_speech():
                return False

        mode = model_id
        if mode in ("medium+", "medium+low"):
            if not self.parent.is_triton_installed():
                logger.info("Компонент Fish Speech установлен, приступаем к установке Triton...")
                if not self._install_triton():
                    return False

        if mode == "medium+low":
            if self.rvc_handler and not self.rvc_handler.is_installed("low"):
                logger.info("Компоненты Fish Speech и Triton установлены, приступаем к установке RVC...")
                return self.rvc_handler.install("low")

        return True

    def _install_fish_speech(self):
        try:
            progress_cb = getattr(self.parent, '_external_progress', lambda *_: None)
            status_cb = getattr(self.parent, '_external_status', lambda *_: None)
            log_cb = getattr(self.parent, '_external_log', lambda *_: None)

            installer = PipInstaller(
                script_path=r"libs\python\python.exe",
                libs_path="Lib",
                update_status=status_cb,
                update_log=log_cb,
                progress_window=None
            )

            progress_cb(10)
            log_cb(_("Начало установки Fish Speech...", "Starting Fish Speech installation..."))

            if self.parent.provider in ["NVIDIA"] and not self.parent.is_cuda_available():
                status_cb(_("Установка PyTorch с поддержкой CUDA 12.8...", "Installing PyTorch with CUDA 12.8 support..."))
                progress_cb(20)
                success = installer.install_package(
                    ["torch==2.7.1", "torchaudio==2.7.1"],
                    description=_("Установка PyTorch с поддержкой CUDA 12.8...", "Installing PyTorch with CUDA 12.8 support..."),
                    extra_args=["--index-url", "https://download.pytorch.org/whl/cu128"],
                )
                if not success:
                    status_cb(_("Ошибка при установке PyTorch", "Error installing PyTorch"))
                    return False
                progress_cb(40)
            else:
                progress_cb(40)

            status_cb(_("Установка библиотеки Fish Speech...", "Installing Fish Speech library..."))
            force_install_unsupported = os.environ.get("ALLOW_UNSUPPORTED_GPU", "0") == "1"
            if self.parent.provider in ["NVIDIA"] or force_install_unsupported:
                success = installer.install_package(
                    "fish_speech_lib",
                    description=_("Установка библиотеки Fish Speech...", "Installing Fish Speech library...")
                )
                if not success:
                    status_cb(_("Ошибка при установке Fish Speech", "Error installing Fish Speech"))
                    return False
                progress_cb(80)

                success = installer.install_package(
                    "librosa==0.9.1",
                    description=_("Установка дополнительной библиотеки librosa...", "Installing additional library librosa...")
                )
                if not success:
                    log_cb(_("Предупреждение: Fish Speech может работать некорректно без librosa", "Warning: Fish Speech may not work correctly without librosa"))
            else:
                log_cb(_(f"Ошибка: не найдена подходящая видеокарта: {self.parent.provider}", f"Error: suitable graphics card not found: {self.parent.provider}"))
                status_cb(_("Требуется NVIDIA GPU", "NVIDIA GPU required"))
                return False

            progress_cb(100)
            status_cb(_("Установка успешно завершена!", "Installation successful!"))

            setattr(self, "_import_attempted", False)
            self._load_module()

            return True
        except Exception as e:
            logger.error(f"Ошибка при установке Fish Speech: {e}", exc_info=True)
            return False

    def _apply_triton_patches(self, libs_path_abs: str, progress_cb, status_cb, log_cb) -> None:
        progress_cb(50)
        status_cb(_("Применение патчей...", "Applying patches..."))
        log_cb(_("Применение необходимых патчей для Triton...", "Applying necessary patches for Triton..."))

        build_py_path = os.path.join(libs_path_abs, "triton", "runtime", "build.py")
        if os.path.exists(build_py_path):
            try:
                import sysconfig
                with open(build_py_path, "r", encoding="utf-8") as f:
                    source = f.read()

                try:
                    old_line_tcc = 'cc = os.path.join(sysconfig.get_paths()["platlib"], "triton", "runtime", "tcc", "tcc.exe")'
                except Exception:
                    old_line_tcc = 'os.path.join(sysconfig.get_paths()["platlib"], "triton", "runtime", "tcc", "tcc.exe")'
                    log_cb(_("Предупреждение: не удалось определить точную старую строку tcc в build.py, используется запасной вариант.", "Warning: failed to detect exact old tcc line in build.py, using fallback."))

                new_line_tcc = 'cc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tcc", "tcc.exe")'
                old_line_fpic = 'cc_cmd = [cc, src, "-O3", "-shared", "-fPIC", "-Wno-psabi", "-o", out]'
                new_line_fpic = 'cc_cmd = [cc, src, "-O3", "-shared", "-Wno-psabi", "-o", out]'

                patched_source = source
                applied_patch_tcc = False
                applied_patch_fpic = False

                if old_line_tcc in patched_source:
                    patched_source = patched_source.replace(old_line_tcc, new_line_tcc)
                    applied_patch_tcc = True
                else:
                    log_cb(_("Патч (путь tcc.exe) для build.py уже применен или строка не найдена.", "Patch (tcc.exe path) for build.py already applied or line not found."))

                if old_line_fpic in patched_source:
                    patched_source = patched_source.replace(old_line_fpic, new_line_fpic)
                    applied_patch_fpic = True
                else:
                    log_cb(_("Патч (удаление -fPIC) для build.py уже применен или строка не найдена.", "Patch (removing -fPIC) for build.py already applied or line not found."))

                if applied_patch_tcc or applied_patch_fpic:
                    with open(build_py_path, "w", encoding="utf-8") as f:
                        f.write(patched_source)
                    if applied_patch_tcc:
                        log_cb(_("Патч (путь tcc.exe) успешно применен к build.py", "Patch (tcc.exe path) successfully applied to build.py"))
                    if applied_patch_fpic:
                        log_cb(_("Патч (удаление -fPIC) успешно применен к build.py", "Patch (removing -fPIC) successfully applied to build.py"))
            except Exception as e:
                log_cb(_(f"Ошибка при патче build.py: {e}", f"Error patching build.py: {e}"))
                log_cb(traceback.format_exc())
        else:
            log_cb(_("Предупреждение: файл build.py не найден, пропускаем патч", "Warning: build.py file not found, skipping patch"))

        progress_cb(60)
        windows_utils_path = os.path.join(libs_path_abs, "triton", "windows_utils.py")
        log_cb(_("Применение патча к windows_utils.py...", "Applying patch to windows_utils.py..."))
        if os.path.exists(windows_utils_path):
            try:
                with open(windows_utils_path, "r", encoding="utf-8") as f:
                    source = f.read()
                old_code_win = "output = subprocess.check_output(command, text=True).strip()"
                new_code_win = "output = subprocess.check_output(\n            command, text=True, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE\n        ).strip()"
                if old_code_win in source:
                    patched_source = source.replace(old_code_win, new_code_win)
                    with open(windows_utils_path, "w", encoding="utf-8") as f:
                        f.write(patched_source)
                    log_cb(_("Патч успешно применен к windows_utils.py", "Patch successfully applied to windows_utils.py"))
                else:
                    log_cb(_("Патч для windows_utils.py уже применен или строка не найдена.", "Patch for windows_utils.py already applied or line not found."))
            except Exception as e:
                log_cb(_(f"Ошибка при патче windows_utils.py: {e}", f"Error patching windows_utils.py: {e}"))
                log_cb(traceback.format_exc())
        else:
            log_cb(_("Предупреждение: файл windows_utils.py не найден, пропускаем патч", "Warning: windows_utils.py file not found, skipping patch"))

        progress_cb(70)
        compiler_path = os.path.join(libs_path_abs, "triton", "backends", "nvidia", "compiler.py")
        log_cb(_("Применение патча к compiler.py...", "Applying patch to compiler.py..."))
        if os.path.exists(compiler_path):
            try:
                with open(compiler_path, "r", encoding="utf-8") as f:
                    source = f.read()
                old_code_comp_line = 'version = subprocess.check_output([_path_to_binary("ptxas")[0], "--version"]).decode("utf-8")'
                new_code_comp_line = 'version = subprocess.check_output([_path_to_binary("ptxas")[0], "--version"], creationflags=subprocess.CREATE_NO_WINDOW, stderr=subprocess.PIPE, close_fds=True, stdin=subprocess.DEVNULL).decode("utf-8")'
                if old_code_comp_line in source:
                    patched_source = source.replace(old_code_comp_line, new_code_comp_line)
                    with open(compiler_path, "w", encoding="utf-8") as f:
                        f.write(patched_source)
                    log_cb(_("Патч успешно применен к compiler.py", "Patch successfully applied to compiler.py"))
                else:
                    log_cb(_("Патч для compiler.py уже применен или строка не найдена.", "Patch for compiler.py already applied or line not found."))
            except Exception as e:
                log_cb(_(f"Ошибка при патче compiler.py: {e}", f"Error patching compiler.py: {e}"))
                log_cb(traceback.format_exc())
        else:
            log_cb(_("Предупреждение: файл compiler.py не найден, пропускаем патч", "Warning: compiler.py file not found, skipping patch"))

        cache_py_path = os.path.join(libs_path_abs, "triton", "runtime", "cache.py")
        log_cb(_("Применение патча к cache.py...", "Applying patch to cache.py..."))
        if os.path.exists(cache_py_path):
            try:
                with open(cache_py_path, "r", encoding="utf-8") as f:
                    source = f.read()
                old_line = 'temp_dir = os.path.join(self.cache_dir, f"tmp.pid_{pid}_{rnd_id}")'
                new_line = 'temp_dir = os.path.join(self.cache_dir, f"tmp.pid_{str(pid)[:5]}_{str(rnd_id)[:5]}")'
                if old_line in source:
                    patched_source = source.replace(old_line, new_line)
                    with open(cache_py_path, "w", encoding="utf-8") as f:
                        f.write(patched_source)
                    log_cb(_("Патч успешно применен к cache.py", "Patch successfully applied to cache.py"))
                else:
                    log_cb(_("Патч для cache.py уже применен или строка не найдена.", "Patch for cache.py already applied or line not found."))
            except Exception as e:
                log_cb(_(f"Ошибка при патче cache.py: {e}", f"Error patching cache.py: {e}"))
                log_cb(traceback.format_exc())
        else:
            log_cb(_("Предупреждение: файл cache.py не найден, пропускаем патч", "Warning: cache.py file not found, skipping patch"))

    def _install_triton(self):
        """
        - Если Triton не установлен: ставим его (pip).
        - Всегда: патчи, проверка зависимостей, показ диалога зависимостей.
        - Если пользователь не нажал Skip: запускаем init.py (компиляция/инициализация).
        """
        self.parent.triton_module = False
        try:
            progress_cb = getattr(self.parent, '_external_progress', lambda *_: None)
            status_cb = getattr(self.parent, '_external_status', lambda *_: None)
            log_cb = getattr(self.parent, '_external_log', lambda *_: None)

            script_path = r"libs\python\python.exe"
            libs_path = "Lib"
            libs_path_abs = os.path.abspath(libs_path)
            os.makedirs(libs_path, exist_ok=True)
            if libs_path_abs not in sys.path:
                sys.path.insert(0, libs_path_abs)

            progress_cb(10)
            log_cb(_("Подготовка Triton...", "Preparing Triton..."))

            needs_install = not self.parent.is_triton_installed()
            if needs_install:
                status_cb(_("Установка библиотеки Triton...", "Installing Triton library..."))
                log_cb(_("Установка пакета triton-windows...", "Installing triton-windows package..."))
                installer = PipInstaller(
                    script_path=script_path,
                    libs_path=libs_path,
                    update_status=status_cb,
                    update_log=log_cb,
                    progress_window=None,
                    update_progress=progress_cb
                )
                ok = installer.install_package(
                    "triton-windows<3.4",
                    description=_("Установка библиотеки Triton...", "Installing Triton library..."),
                    extra_args=["--upgrade"]
                )
                if not ok:
                    status_cb(_("Ошибка при установке Triton", "Error installing Triton"))
                    log_cb(_("Не удалось установить пакет Triton. Проверьте лог выше.", "Failed to install Triton package. Check the log above."))
                    return False
            else:
                progress_cb(30)
                status_cb(_("Triton найден, пропускаем установку. Патчи/инициализация...", "Triton found, skipping install. Patching/initializing..."))
                log_cb(_("Triton уже установлен — пропускаем pip, продолжаем.", "Triton already installed — skipping pip step, continuing."))

            self._apply_triton_patches(libs_path_abs, progress_cb, status_cb, log_cb)

            progress_cb(80)
            status_cb(_("Проверка системных зависимостей...", "Checking system dependencies..."))
            log_cb(_("Проверка наличия Triton, CUDA, Windows SDK, MSVC...", "Checking for Triton, CUDA, Windows SDK, MSVC..."))

            dll_error = False
            try:
                importlib.invalidate_caches()
                if "triton" in sys.modules:
                    try:
                        del sys.modules["triton"]
                        log_cb(_("Удален модуль 'triton' из sys.modules перед проверкой.", "Removed 'triton' module from sys.modules before check."))
                    except KeyError:
                        pass

                self.parent._check_system_dependencies()
                log_cb(_("_check_system_dependencies выполнена успешно.", "_check_system_dependencies executed successfully."))
            except ImportError as e:
                msg = str(e)
                if msg.startswith("DLL load failed while importing libtriton"):
                    dll_error = True
                    log_cb(_(f"ОШИБКА: Импорт Triton не удался (DLL load failed): {msg}", f"ERROR: Triton import failed (DLL load failed): {msg}"))
                else:
                    log_cb(_(f"ОШИБКА: Неожиданная ошибка импорта: {msg}", f"ERROR: Unexpected import error: {msg}"))
                    log_cb(traceback.format_exc())
            except Exception as e:
                log_cb(_(f"ОШИБКА: Общая ошибка во время _check_system_dependencies: {e}", f"ERROR: General error during _check_system_dependencies: {e}"))
                log_cb(traceback.format_exc())

            if dll_error:
                status_cb(_("Ошибка загрузки Triton! Проверьте VC Redist.", "Triton load error! Check VC Redist."))
                res = self.events.emit_and_wait(Events.Audio.SHOW_VC_REDIST_DIALOG, timeout=6000.0)
                choice = res[0] if res else "close"
                if choice == "retry":
                    return self._install_triton()
                else:
                    status_cb(_("Инициализация ядра пропущена", "Kernel initialization skipped"))
                    progress_cb(95)
                    return False

            deps = {
                "cuda_found": bool(getattr(self.parent, "cuda_found", False)),
                "winsdk_found": bool(getattr(self.parent, "winsdk_found", False)),
                "msvc_found": bool(getattr(self.parent, "msvc_found", False)),
            }
            res_deps = self.events.emit_and_wait(Events.Audio.SHOW_TRITON_DIALOG, deps, timeout=6000.0)
            user_action = res_deps[0] if res_deps else "continue"
            skip_init = (user_action == "skip")

            if not skip_init:
                progress_cb(90)
                status_cb(_("Инициализация ядра Triton...", "Initializing Triton kernel..."))
                log_cb(_("Начало инициализации ядра (запуск init.py)... Это может занять до 5-10 минут", "Starting kernel initialization (running init.py)... It can take up to 5-10 minutes."))
                try:
                    temp_dir = "temp"
                    os.makedirs(temp_dir, exist_ok=True)

                    init_cmd = [script_path, "init.py"]
                    result = subprocess.run(
                        init_cmd,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore',
                        check=False,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if result.stdout:
                        for line in result.stdout.splitlines():
                            log_cb(line)
                    if result.stderr:
                        for line in result.stderr.splitlines():
                            log_cb(f"STDERR: {line}")

                    if result.returncode == 0 and os.path.exists(os.path.join(temp_dir, "inited.wav")):
                        progress_cb(95)
                        status_cb(_("Инициализация ядра успешно завершена!", "Kernel initialization completed successfully!"))
                    else:
                        status_cb(_("Ошибка при инициализации ядра", "Error during kernel initialization"))
                        log_cb(_("Ошибка при запуске init.py. Проверьте лог выше.", "Error running init.py. Check the log above."))
                except Exception as e:
                    log_cb(_(f"Непредвиденная ошибка при инициализации ядра: {str(e)}", f"Unexpected error during kernel initialization: {str(e)}"))
                    log_cb(traceback.format_exc())
                    status_cb(_("Ошибка инициализации ядра", "Kernel initialization error"))
                    progress_cb(85)
            else:
                status_cb(_("Инициализация ядра пропущена", "Kernel initialization skipped"))
                progress_cb(95)

            progress_cb(100)
            status_cb(_("Установка Triton завершена.", "Triton installation complete."))
            self.parent.triton_installed = True
            return True

        except Exception as e:
            logger.error(_(f"Критическая ошибка при установке Triton: {e}", f"Critical error during Triton installation: {e}"))
            logger.error(traceback.format_exc())
            try:
                if hasattr(self.parent, '_external_log'):
                    self.parent._external_log(f"{_('КРИТИЧЕСКАЯ ОШИБКА:', 'CRITICAL ERROR:')} {e}\n{traceback.format_exc()}")
                if hasattr(self.parent, '_external_status'):
                    self.parent._external_status(_("Критическая ошибка установки!", "Critical installation error!"))
            except Exception:
                pass
            self.parent.triton_module = False
            return False

    def uninstall(self, model_id) -> bool:
        mode = model_id
        if mode == "medium":
            return self.parent._uninstall_component("Fish Speech", "fish-speech-lib")
        elif mode in ("medium+", "medium+low"):
            return self.parent._uninstall_component("Triton", "triton-windows")
        else:
            logger.error(_('Неизвестная модель для удаления.', 'Unknown model for uninstall'))
            return False

    def cleanup_state(self):
        super().cleanup_state()
        self.current_fish_speech = None
        self.fish_speech_module = None
        if self.parent.first_compiled is not None:
            logger.info("Сброс состояния компиляции Fish Speech из-за удаления.")
            self.parent.first_compiled = None

        if self.rvc_handler and self.rvc_handler.initialized:
            self.rvc_handler.cleanup_state()

        logger.info(f"Состояние для модели {self.model_id} сброшено.")

    def initialize(self, init: bool = False) -> bool:
        if self.initialized:
            return True

        self._load_module()
        if self.fish_speech_module is None:
            logger.error("fish_speech_lib не установлен")
            return False

        mode = self._mode()
        compile_model = mode in ("medium+", "medium+low")

        if (self.parent.first_compiled is not None
                and self.parent.first_compiled != compile_model):
            logger.error("КОНФЛИКТ: нельзя переключиться между compile=True/False без перезапуска")
            return False

        if self.current_fish_speech is None:
            settings = self.parent.load_model_settings(mode)
            device = settings.get(
                "fsprvc_fsp_device" if mode == "medium+low" else "device",
                "cuda")
            half = settings.get(
                "fsprvc_fsp_half" if mode == "medium+low" else "half",
                "True" if compile_model else "False").lower() == "true"

            self.current_fish_speech = self.fish_speech_module(
                device=device, half=half, compile_model=compile_model)

            self.parent.first_compiled = compile_model
            logger.info(f"FishSpeech инициализирован (compile={compile_model})")

        if mode == "medium+low":
            if self.rvc_handler and not self.rvc_handler.initialized:
                logger.info("Инициализация RVC компонента для 'medium+low'...")
                rvc_success = self.rvc_handler.initialize(init=False)
                if not rvc_success:
                    logger.error("Не удалось инициализировать RVC компонент для 'medium+low'.")
                    return False

        self.initialized = True

        if init:
            init_text = f"Инициализация модели {self.model_id}" if self.parent.voice_language == "ru" else f"{self.model_id} Model Initialization"
            logger.info(f"Выполнение тестового прогона для {self.model_id}...")
            try:
                results = self.events.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
                main_loop = results[0] if results else None
                if not main_loop or not main_loop.is_running():
                    raise RuntimeError("Главный цикл событий asyncio недоступен.")

                future = asyncio.run_coroutine_threadsafe(self.voiceover(init_text), main_loop)
                result_path = future.result(timeout=3600)

                if not result_path or not os.path.exists(result_path) or os.path.getsize(result_path) == 0:
                    logger.error("Тестовый прогон не создал аудиофайл — инициализация неуспешна.")
                    self.initialized = False
                    return False

                logger.info(f"Тестовый прогон для {self.model_id} успешно завершен.")
            except Exception as e:
                logger.error(f"Ошибка во время тестового прогона модели {self.model_id}: {e}", exc_info=True)
                self.initialized = False
                return False

        return True

    async def voiceover(self, text: str, character: Optional[Any] = None, **kwargs) -> Optional[str]:
        if not self.initialized:
            raise Exception(f"Модель {self.model_id} не инициализирована.")
        if self.fish_speech_module is None:
            raise ImportError("Модуль fish_speech_lib не установлен.")

        try:
            mode = self._mode()
            settings = self.parent.load_model_settings(mode)
            is_combined_model = mode == "medium+low"

            temp_key = "fsprvc_fsp_temperature" if is_combined_model else "temperature"
            top_p_key = "fsprvc_fsp_top_p" if is_combined_model else "top_p"
            rep_penalty_key = "fsprvc_fsp_repetition_penalty" if is_combined_model else "repetition_penalty"
            chunk_len_key = "fsprvc_fsp_chunk_length" if is_combined_model else "chunk_length"
            max_tokens_key = "fsprvc_fsp_max_tokens" if is_combined_model else "max_new_tokens"
            seed_key = "fsprvc_fsp_seed" if is_combined_model else "seed"

            voice_paths = get_character_voice_paths(character, self.parent.provider)
            reference_audio_path = None
            reference_text = ""
            if os.path.exists(voice_paths['clone_voice_filename']):
                reference_audio_path = voice_paths['clone_voice_filename']
                if os.path.exists(voice_paths['clone_voice_text']):
                    with open(voice_paths['clone_voice_text'], "r", encoding="utf-8") as file:
                        reference_text = file.read().strip()

            seed_processed = int(settings.get(seed_key, 0))
            if seed_processed <= 0 or seed_processed > 2**31 - 1:
                seed_processed = 42

            vol = str(settings.get("volume", "1.0"))

            sample_rate, audio_data = self.current_fish_speech(
                text=text,
                reference_audio=reference_audio_path,
                reference_audio_text=reference_text,
                top_p=float(settings.get(top_p_key, 0.7)),
                temperature=float(settings.get(temp_key, 0.7)),
                repetition_penalty=float(settings.get(rep_penalty_key, 1.2)),
                max_new_tokens=int(settings.get(max_tokens_key, 1024)),
                chunk_length=int(settings.get(chunk_len_key, 200)),
                seed=seed_processed,
                use_memory_cache=True,
            )

            hash_object = hashlib.sha1(f"{text[:20]}_{datetime.now().timestamp()}".encode())
            raw_output_filename = f"fish_raw_{hash_object.hexdigest()[:10]}.wav"
            raw_output_path = os.path.abspath(os.path.join("temp", raw_output_filename))
            os.makedirs("temp", exist_ok=True)

            import soundfile as sf
            sf.write(raw_output_path, audio_data, sample_rate)

            if not os.path.exists(raw_output_path) or os.path.getsize(raw_output_path) == 0:
                return None

            stereo_output_path = raw_output_path.replace("_raw", "_stereo")
            converted_file = self.parent.convert_wav_to_stereo(raw_output_path, stereo_output_path, volume=str(0.5 + float(vol)))

            processed_output_path = stereo_output_path if converted_file and os.path.exists(converted_file) else raw_output_path
            if processed_output_path == stereo_output_path:
                try:
                    os.remove(raw_output_path)
                except OSError:
                    pass

            final_output_path = processed_output_path

            if mode == "medium+low" and self.rvc_handler:
                logger.info(f"Применяем RVC с параметрами FSP+RVC к файлу: {final_output_path}")
                rvc_output_path = await self.rvc_handler.apply_rvc_to_file(
                    filepath=final_output_path,
                    character=character,
                    pitch=float(settings.get("fsprvc_rvc_pitch", 0)),
                    index_rate=float(settings.get("fsprvc_index_rate", 0.75)),
                    protect=float(settings.get("fsprvc_protect", 0.33)),
                    filter_radius=int(settings.get("fsprvc_filter_radius", 3)),
                    rms_mix_rate=float(settings.get("fsprvc_rvc_rms_mix_rate", 0.5)),
                    is_half=settings.get("fsprvc_is_half", "True").lower() == "true",
                    f0method=settings.get("fsprvc_f0method", None),
                    use_index_file=settings.get("fsprvc_use_index_file", True),
                    volume=vol
                )
                if rvc_output_path and os.path.exists(rvc_output_path):
                    if final_output_path != rvc_output_path:
                        try:
                            os.remove(final_output_path)
                        except OSError:
                            pass
                    final_output_path = rvc_output_path
                else:
                    logger.warning("Ошибка во время обработки RVC. Возвращается результат до RVC.")
            elif mode == "medium+low" and not self.rvc_handler:
                logger.warning("Модель 'medium+low' требует RVC, но обработчик не был предоставлен.")

            res_conn = self.events.emit_and_wait(Events.Server.GET_GAME_CONNECTION)
            connected_to_game = res_conn[0] if res_conn else False
            if connected_to_game:
                self.events.emit(Events.Server.SET_PATCH_TO_SOUND_FILE, final_output_path)

            return final_output_path
        except Exception as error:
            traceback.print_exc()
            logger.info(f"Ошибка при создании озвучки с Fish Speech ({self.model_id}): {error}")
            return None

    def _mode(self) -> str:
        return (self.parent.current_model_id or "medium")