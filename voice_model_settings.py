# voice_model_settings.py

import tkinter as tk
from tkinter import ttk
import os
import platform
import time
import copy
import json
import threading 
import tkinter.messagebox
from docs import DocsManager
from Logger import logger
import traceback

from SettingsManager import SettingsManager

def getTranslationVariant(ru_str, en_str=""):
    if en_str and SettingsManager.get("LANGUAGE") == "EN":
        return en_str
    return ru_str

_ = getTranslationVariant

model_descriptions = {
    "low": "Быстрая модель, комбинация Edge-TTS для генерации речи и RVC для преобразования голоса. Низкие требования.",
    "low+": "Комбинация Silero TTS для генерации речи и RVC для преобразования голоса. Требования схожи с low.",
    "medium": "Модель Fish Speech для генерации речи с хорошим качеством. Требует больше ресурсов.",
    "medium+": "Скомпилированная на видеокарту версия Fish Speech. Требует больше места.",
    "medium+low": "Комбинация Fish Speech+ и RVC для высококачественного преобразования голоса.",
    "f5_tts": "Лучшая эмоциональная модель. Дифузионная модель, так что самая требовательная к видеокарте."
}

model_descriptions_en = {
    "low": "Fast model; a combination of Edge-TTS for speech generation and RVC for voice conversion. Low requirements.",
    "low+": "Combination of Silero TTS for speech generation and RVC for voice conversion. Requirements similar to the 'low' model.",
    "medium": "Fish Speech model for speech generation with good quality. Requires more resources.",
    "medium+": "GPU-compiled version of Fish Speech. Requires more disk space.",
    "medium+low": "Combination of Fish Speech+ and RVC for high-quality voice conversion.",
    "f5_tts": "Best emotional model. A diffusion model, therefore the most GPU-demanding."
}


setting_descriptions = {
    "device": "Устройство для вычислений (GPU или CPU). 'cuda:0' - первая GPU NVIDIA, 'cpu' - центральный процессор, 'mps:0' - GPU Apple Silicon.",
    "pitch": "Изменение высоты голоса в полутонах. Положительные значения - выше, отрицательные - ниже. 0 - без изменений.",
    "is_half": "Использовать вычисления с половинной точностью (float16). Ускоряет работу на совместимых GPU (NVIDIA RTX и новее) и экономит видеопамять, может незначительно повлиять на качество.",
    "output_gain": "Усиление громкости финального аудиофайла. Значение 1.0 - без изменений, <1 тише, >1 громче. Полезно для нормализации громкости разных голосов.",
    "f0method": "[RVC] Алгоритм извлечения основного тона (F0). Определяет высоту голоса. 'rmvpe' и 'crepe' точные, но медленные. 'pm', 'harvest' быстрее. Влияет на естественность интонаций.",
    "use_index_file": "[RVC] Использовать файл .index для улучшения соответствия тембра голоса модели. Отключение может быть полезно, если индексный файл низкого качества или вызывает артефакты.",
    "index_rate": "[RVC] Степень использования индексного файла (.index) для сохранения тембра голоса RVC (0 до 1). Выше значение = больше похоже на голос из модели, но может добавить артефакты, если индекс некачественный.",
    "filter_radius": "[RVC] Радиус медианного фильтра для сглаживания кривой F0 (высоты тона). Убирает резкие скачки, делает речь более плавной. Рекомендуется значение >= 3.",
    "rms_mix_rate": "[RVC] Степень смешивания RMS (громкости) исходного аудио (из TTS/FSP) и результата RVC (0 до 1). 0 = полностью громкость RVC, 1 = полностью громкость оригинала. Помогает сохранить исходную динамику речи.",
    "protect": "[RVC] Защита глухих согласных (ш, щ, с, ...) от искажения высотой тона (0 до 0.5). Меньшие значения обеспечивают большую защиту (согласные звучат чище), но могут немного повлиять на интонацию гласных рядом. Рекомендуется 0.3-0.4.",
    "tts_rate": "[EdgeTTS] Изменение скорости речи базового синтезатора Edge-TTS (до RVC) в процентах. 0 - стандартная скорость.",
    "tts_volume": "[EdgeTTS] Изменение громкости речи базового синтезатора Edge-TTS (до RVC) в процентах. 0 - стандартная громкость.",
    "silero_device": "[Silero] Устройство для генерации речи Silero (CPU или GPU).",
    "silero_sample_rate": "[Silero] Частота дискретизации для генерации речи Silero.", 
    "silero_put_accent": "[Silero] Автоматическая расстановка ударений.", 
    "silero_put_yo": "[Silero] Автоматическая замена 'е' на 'ё'.", 
    "half": "[FS/FSP] Использовать FP16 (половинную точность). Рекомендуется для скорости и экономии памяти на GPU.",
    "temperature": "[FS/FSP] Температура сэмплирования (>0). Контролирует случайность/разнообразие генерируемой речи. Выше = разнообразнее, но больше ошибок. Ниже = стабильнее.",
    "top_p": "[FS/FSP] Ядерное сэмплирование (Top-P, 0-1). Ограничивает выбор следующего токена только наиболее вероятными вариантами. Уменьшает вероятность генерации 'бреда'.",
    "repetition_penalty": "[FS/FSP] Штраф за повторение токенов (>1). Предотвращает зацикливание модели на одних и тех же словах/звуках. 1.0 - нет штрафа.",
    "chunk_length": "[FS/FSP] Размер чанка обработки текста (в токенах). Влияет на использование памяти и длину контекста, который модель 'видит' одновременно.",
    "max_new_tokens": "[FS/FSP] Максимальное количество генерируемых токенов за один шаг. Ограничивает длину аудиофрагмента, генерируемого за раз.",
    "compile_model": "[FSP] Использовать torch.compile() для JIT-компиляции модели. Значительно ускоряет выполнение на GPU после первого запуска, но требует доп. установки и время на компиляцию при старте.",
    "fsprvc_fsp_device": "[FSP+RVC][FSP] Устройство для части Fish Speech+.",
    "fsprvc_fsp_half": "[FSP+RVC][FSP] Half-precision для части Fish Speech+.",
    "fsprvc_fsp_temperature": "[FSP+RVC][FSP] Температура для части Fish Speech+.",
    "fsprvc_fsp_top_p": "[FSP+RVC][FSP] Top-P для части Fish Speech+.",
    "fsprvc_fsp_repetition_penalty": "[FSP+RVC][FSP] Штраф повторений для части Fish Speech+.",
    "fsprvc_fsp_chunk_length": "[FSP+RVC][FSP] Размер чанка для части Fish Speech+.",
    "fsprvc_fsp_max_tokens": "[FSP+RVC][FSP] Макс. токены для части Fish Speech+.",
    "fsprvc_rvc_device": "[FSP+RVC][RVC] Устройство для части RVC.",
    "fsprvc_is_half": "[FSP+RVC][RVC] Half-precision для части RVC.",
    "fsprvc_f0method": "[FSP+RVC][RVC] Метод F0 для части RVC.",
    "fsprvc_rvc_pitch": "[FSP+RVC][RVC] Высота голоса для части RVC.",
    "fsprvc_use_index_file": "[FSP+RVC][RVC] Использовать файл .index для улучшения соответствия тембра голоса модели. Отключение может быть полезно, если индексный файл низкого качества или вызывает артефакты.",
    "fsprvc_index_rate": "[FSP+RVC][RVC] Соотношение индекса для части RVC.",
    "fsprvc_protect": "[FSP+RVC][RVC] Защита согласных для части RVC.",
    "fsprvc_output_gain": "[FSP+RVC][RVC] Громкость (gain) для части RVC.",
    "fsprvc_filter_radius": "[FSP+RVC][RVC] Радиус фильтра F0 для части RVC.",
    "fsprvc_rvc_rms_mix_rate": "[FSP+RVC][RVC] Смешивание RMS для части RVC.",

    "speed": "[F5-TTS] Скорость генерируемой речи. 1.0 - нормальная скорость, >1.0 - быстрее, <1.0 - медленнее.",
    "remove_silence": "[F5-TTS] Автоматически удалять тишину в начале и конце сгенерированного аудио.",
    "nfe_step": "[F5-TTS] Количество шагов диффузии. Больше = лучше качество, но медленнее. Меньше = быстрее, но может быть хуже. (Рекомендуется: 3-10)",
    "cfg_strength": "[F5-TTS] Сила бесклассификаторного управления (CFG). Контролирует, насколько сильно генерация следует за референсным аудио. 0 - отключено. (Рекомендуется: 0.7)",
    "sway_sampling_coef": "[F5-TTS] Коэффициент сэмплирования 'Sway'. Добавляет вариативности в генерацию. 0 - отключено. (Рекомендуется: 0.0)",
    "target_rms": "[F5-TTS] Целевая громкость (RMS) для нормализации аудио. -1 отключает нормализацию. (Рекомендуется: -1)",
    "cross_fade_duration": "[F5-TTS] Длительность кроссфейда (в секундах) между аудио-чанками. (Рекомендуется: 0.015)",
    "fix_duration": "[F5-TTS] Фиксировать длительность фонем. Может улучшить стабильность, но снизить естественность. (Рекомендуется: False)",

    "tmp_directory": "Папка для временных файлов, создаваемых в процессе работы (например, промежуточные аудиофайлы).",
    "verbose": "Включить вывод подробной отладочной информации в консоль для диагностики проблем.",
    "cuda_toolkit": "Наличие установленного CUDA Toolkit от NVIDIA. Необходимо для некоторых функций (например, torch.compile) и работы с GPU NVIDIA.",
    "windows_sdk": "Наличие установленного Windows SDK. Может требоваться для компиляции некоторых зависимостей Python.",
    
}

setting_descriptions_en = {
    "device": "Device for computation (GPU or CPU). 'cuda:0' - first NVIDIA GPU, 'cpu' - central processor, 'mps:0' - Apple Silicon GPU.",
    "pitch": "Voice pitch change in semitones. Positive values - higher, negative - lower. 0 - no change.",
    "is_half": "Use half-precision computations (float16). Speeds up work on compatible GPUs (NVIDIA RTX and newer) and saves VRAM, may slightly affect quality.",
    "output_gain": "Volume gain for the final audio file. Value 1.0 - no change, <1 quieter, >1 louder. Useful for normalizing the volume of different voices.",
    "f0method": "[RVC] Fundamental frequency (F0) extraction algorithm. Determines voice pitch. 'rmvpe' and 'crepe' are accurate but slow. 'pm', 'harvest' are faster. Affects the naturalness of intonations.",
    "use_index_file": "[RVC] Use the .index file to improve the model's voice timbre matching. Disabling may be useful if the index file is low quality or causes artifacts.",
    "index_rate": "[RVC] Degree of using the index file (.index) to preserve the RVC voice timbre (0 to 1). Higher value = more similar to the model's voice, but may add artifacts if the index is poor quality.",
    "filter_radius": "[RVC] Radius of the median filter for smoothing the F0 curve (pitch). Removes sharp jumps, makes speech smoother. Recommended value >= 3.",
    "rms_mix_rate": "[RVC] Degree of mixing RMS (volume) of the source audio (from TTS/FSP) and the RVC result (0 to 1). 0 = fully RVC volume, 1 = fully original volume. Helps preserve the original speech dynamics.",
    "protect": "[RVC] Protection of voiceless consonants (sh, shch, s, ...) from pitch distortion (0 to 0.5). Lower values provide more protection (consonants sound cleaner), but may slightly affect the intonation of nearby vowels. Recommended 0.3-0.4.",
    "tts_rate": "[EdgeTTS] Change the speech rate of the base Edge-TTS synthesizer (before RVC) in percent. 0 - standard speed.",
    "tts_volume": "[EdgeTTS] Change the speech volume of the base Edge-TTS synthesizer (before RVC) in percent. 0 - standard volume.",
    "silero_device": "[Silero] Device for Silero speech generation (CPU or GPU).",
    "silero_sample_rate": "[Silero] Sample rate for Silero speech generation.",
    "silero_put_accent": "[Silero] Automatic stress placement.",
    "silero_put_yo": "[Silero] Automatic replacement of 'e' with 'yo'.",
    "half": "[FS/FSP] Use FP16 (half-precision). Recommended for speed and memory saving on GPU.",
    "temperature": "[FS/FSP] Sampling temperature (>0). Controls the randomness/diversity of generated speech. Higher = more diverse, but more errors. Lower = more stable.",
    "top_p": "[FS/FSP] Nucleus sampling (Top-P, 0-1). Limits the choice of the next token to only the most likely options. Reduces the probability of generating 'nonsense'.",
    "repetition_penalty": "[FS/FSP] Penalty for repeating tokens (>1). Prevents the model from looping on the same words/sounds. 1.0 - no penalty.",
    "chunk_length": "[FS/FSP] Text processing chunk size (in tokens). Affects memory usage and the length of the context the model 'sees' simultaneously.",
    "max_new_tokens": "[FS/FSP] Maximum number of generated tokens per step. Limits the length of the audio fragment generated at once.",
    "compile_model": "[FSP] Use torch.compile() for JIT compilation of the model. Significantly speeds up execution on GPU after the first run, but requires additional installation and compilation time at startup.",
    "fsprvc_fsp_device": "[FSP+RVC][FSP] Device for the Fish Speech+ part.",
    "fsprvc_fsp_half": "[FSP+RVC][FSP] Half-precision for the Fish Speech+ part.",
    "fsprvc_fsp_temperature": "[FSP+RVC][FSP] Temperature for the Fish Speech+ part.",
    "fsprvc_fsp_top_p": "[FSP+RVC][FSP] Top-P for the Fish Speech+ part.",
    "fsprvc_fsp_repetition_penalty": "[FSP+RVC][FSP] Repetition penalty for the Fish Speech+ part.",
    "fsprvc_fsp_chunk_length": "[FSP+RVC][FSP] Chunk size for the Fish Speech+ part.",
    "fsprvc_fsp_max_tokens": "[FSP+RVC][FSP] Max tokens for the Fish Speech+ part.",
    "fsprvc_rvc_device": "[FSP+RVC][RVC] Device for the RVC part.",
    "fsprvc_is_half": "[FSP+RVC][RVC] Half-precision for the RVC part.",
    "fsprvc_f0method": "[FSP+RVC][RVC] F0 method for the RVC part.",
    "fsprvc_rvc_pitch": "[FSP+RVC][RVC] Voice pitch for the RVC part.",
    "fsprvc_use_index_file": "[FSP+RVC][RVC] Use the .index file to improve the model's voice timbre matching. Disabling may be useful if the index file is low quality or causes artifacts.",
    "fsprvc_index_rate": "[FSP+RVC][RVC] Index rate for the RVC part.",
    "fsprvc_protect": "[FSP+RVC][RVC] Consonant protection for the RVC part.",
    "fsprvc_output_gain": "[FSP+RVC][RVC] Volume (gain) for the RVC part.",
    "fsprvc_filter_radius": "[FSP+RVC][RVC] F0 filter radius for the RVC part.",
    "fsprvc_rvc_rms_mix_rate": "[FSP+RVC][RVC] RMS mixing for the RVC part.",

    "speed": "[F5-TTS] Speed of the generated speech. 1.0 is normal speed, >1.0 is faster, <1.0 is slower.",
    "remove_silence": "[F5-TTS] Automatically remove silence from the beginning and end of the generated audio.",
    "nfe_step": "[F5-TTS] Number of diffusion steps. More = better quality, but slower. Less = faster, but may be worse. (Recommended: 3-10)",
    "cfg_strength": "[F5-TTS] Classifier-Free Guidance (CFG) strength. Controls how strongly the generation follows the reference audio. 0 - disabled. (Recommended: 0.7)",
    "sway_sampling_coef": "[F5-TTS] 'Sway' sampling coefficient. Adds variability to the generation. 0 - disabled. (Recommended: 0.0)",
    "target_rms": "[F5-TTS] Target loudness (RMS) for audio normalization. -1 disables normalization. (Recommended: -1)",
    "cross_fade_duration": "[F5-TTS] Crossfade duration (in seconds) between audio chunks. (Recommended: 0.015)",
    "fix_duration": "[F5-TTS] Fix phoneme duration. May improve stability but reduce naturalness. (Recommended: False)",

    "tmp_directory": "Folder for temporary files created during operation (e.g., intermediate audio files).",
    "verbose": "Enable detailed debug information output to the console for diagnosing problems.",
    "cuda_toolkit": "Presence of installed NVIDIA CUDA Toolkit. Required for some functions (e.g., torch.compile) and working with NVIDIA GPUs.",
    "windows_sdk": "Presence of installed Windows SDK. May be required for compiling some Python dependencies.",
}

default_description_text = "Наведите курсор на элемент интерфейса для получения описания."
default_description_text_en = "Hover over an interface element to get a description."

try:
    from utils.GpuUtils import check_gpu_provider, get_cuda_devices, get_gpu_name_by_id
except ImportError:
    logger.info(_("Предупреждение: Модуль GpuUtils не найден. Функции определения GPU не будут работать.", "Warning: GpuUtils module not found. GPU detection functions will not work."))
    def check_gpu_provider(): return None
    def get_cuda_devices(): return []

class Tooltip:
    """
    Creates a tooltip for a given widget.
    """
    def __init__(self, widget, text, delay=500, wraplength=250):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength 
        self.tipwindow = None
        self.id = None
        self.x = self.y = 0
        self._id_var = tk.StringVar() 

        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hidetip()

    def schedule(self):
        self.unschedule()
        self._id_var.set(self.widget.after(self.delay, self.showtip))

    def unschedule(self):
        scheduled_id = self._id_var.get()
        if scheduled_id:
            self.widget.after_cancel(scheduled_id)
            self._id_var.set('')

    def showtip(self, event=None):
        self.hidetip()
        if not self.widget.winfo_exists(): 
             return
        # Calculate position
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.wm_attributes("-topmost", True)

        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                       background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                       wraplength=self.wraplength, font=("Segoe UI", 8),
                       padx=4, pady=2)
        label.pack(ipadx=1)

    def hidetip(self):
        tw = self.tipwindow
        self.tipwindow = None
        if tw:
            try:
                if tw.winfo_exists():
                    tw.destroy()
            except tk.TclError:
                pass


class VoiceCollapsibleSection(ttk.Frame): # Используем ttk.Frame для стиля
    def __init__(self, parent, title, collapsed=False, update_scrollregion_func=None, clear_description_func=None, **kwargs):
        super().__init__(parent, **kwargs)

        self.configure(style='Collapsible.TFrame')
        self.update_scrollregion = update_scrollregion_func
        self.clear_description = clear_description_func or (lambda event=None: None)

        self.border_frame = tk.Frame(self, bg="#1e1e1e") 
        self.border_frame.pack(fill=tk.X, expand=True, pady=(0, 1))
        self.header_frame = tk.Frame(self.border_frame, bg="#252525")
        self.header_frame.pack(fill=tk.X, side=tk.TOP, anchor="nw", pady=(2, 1))
        self.arrow = tk.Label(self.header_frame, text=("▶" if collapsed else "▼"), bg="#252525", fg="white", width=2, font=("Segoe UI", 8)) # Шрифт для стрелки
        self.arrow.pack(side=tk.LEFT, padx=(5, 5))
        self.title_label = tk.Label(self.header_frame, text=title, bg="#252525", fg="white", font=("Segoe UI", 9, "bold")) # Жирный шрифт
        self.title_label.pack(side=tk.LEFT, pady=2)

        # Контентный фрейм - tk, т.к. внутри него grid
        self.content_frame = tk.Frame(self.border_frame, bg="#1e1e1e")
        self.content_frame.columnconfigure(0, weight=4, uniform="group1", minsize=150)
        self.content_frame.columnconfigure(1, weight=5, uniform="group1", minsize=150)

        for widget in [self.arrow, self.title_label, self.header_frame]:
            widget.bind("<Button-1>", self.toggle)
            widget.bind("<Leave>", self.clear_description)

        self.is_collapsed = collapsed
        self.row_count = 0
        self.widgets = {} # Словарь для хранения виджетов и их переменных

        if self.is_collapsed: self.collapse(update_scroll=False)
        else: self.expand(update_scroll=False)

    def toggle(self, event=None):
        if self.is_collapsed: self.expand()
        else: self.collapse()
        self.is_collapsed = not self.is_collapsed
        if self.update_scrollregion: self.after(10, self.update_scrollregion)

    def collapse(self, update_scroll=True):
        self.arrow.config(text="▶")
        self.content_frame.pack_forget()
        if update_scroll and self.update_scrollregion: self.after(10, self.update_scrollregion)

    def expand(self, update_scroll=True):
        self.arrow.config(text="▼")
        self.content_frame.pack(fill=tk.X, side=tk.TOP, padx=1, pady=(0, 1))
        if update_scroll and self.update_scrollregion: self.after(10, self.update_scrollregion)

    def add_row(self, key, label_text, widget_type, options, setting_info, show_setting_description=None):
        row_height = 28
        is_locked = setting_info.get("locked", False)
        label_fg_color = "#888888" if is_locked else "white"
        # Состояния для виджетов
        widget_state_tk = tk.DISABLED if is_locked else tk.NORMAL
        widget_state_ttk = "disabled" if is_locked else "normal"
        combobox_state_ttk = "disabled" if is_locked else "readonly"

        # Контейнеры и метка (tk)
        label_container = tk.Frame(self.content_frame, bg="#252525", height=row_height)
        label_container.grid(row=self.row_count, column=0, sticky="nsew", pady=(1, 0))
        label_container.pack_propagate(False)
        label = tk.Label(label_container, text=label_text, bg="#252525", fg=label_fg_color, anchor="w", font=("Segoe UI", 9))
        label.pack(fill=tk.BOTH, expand=True, padx=10, pady=3)

        widget_container = tk.Frame(self.content_frame, bg="#1e1e1e", height=row_height)
        widget_container.grid(row=self.row_count, column=1, sticky="nsew", pady=(1, 0))
        widget_container.pack_propagate(False)

        widget = None
        widget_var = None 
        container_padx = 5
        container_pady = 2
        entry_bg = "#3c3c3c"
        widget_fg = "white"
        disabled_fg = "#888888"
        disabled_bg = "#303030"

        current_value = options.get("default")

        if widget_type == "entry":
            entry_var = tk.StringVar()
            entry = tk.Entry(widget_container, textvariable=entry_var, bg=entry_bg, fg=widget_fg,
                           disabledbackground=disabled_bg, disabledforeground=disabled_fg,
                           insertbackground=widget_fg,
                           relief="solid", bd=1, highlightthickness=0, state=widget_state_tk, font=("Segoe UI", 9))
            entry.pack(fill=tk.X, expand=True, padx=container_padx, pady=container_pady, ipady=2)
            if current_value is not None:
                entry_var.set(str(current_value))
            widget = entry
            widget_var = entry_var

        elif widget_type == "combobox":
            combo_var = tk.StringVar()
            values_list = options.get("values", [])
            if not isinstance(values_list, (list, tuple)): values_list = []

            # Используем ttk.Combobox с кастомным стилем
            combo = ttk.Combobox(
                widget_container,
                textvariable=combo_var,
                values=values_list,
                state=combobox_state_ttk,
                style='CustomDark.TCombobox', # Применяем наш стиль
                font=("Segoe UI", 9)
            )
            combo.pack(fill=tk.X, expand=True, padx=container_padx, pady=container_pady, ipady=1)

            # Функция установки начального значения
            def set_initial_combo_value(target_widget, possible_values, value_to_set):
                if not target_widget.winfo_exists(): return
                if value_to_set is not None:
                    str_value_to_set = str(value_to_set)
                    str_possible_values = [str(v) for v in possible_values]
                    try:
                        value_index = str_possible_values.index(str_value_to_set)
                        target_widget.current(value_index)
                        return
                    except ValueError: pass
                    except tk.TclError: pass

                if possible_values:
                    try: target_widget.current(0)
                    except tk.TclError: pass

            combo.after_idle(lambda w=combo, v=values_list[:], cv=current_value: set_initial_combo_value(w, v, cv))

            widget = combo
            widget_var = combo_var

        elif widget_type == "checkbutton":
            var = tk.BooleanVar()
            bool_value = False
            if isinstance(current_value, str):
                bool_value = current_value.lower() == 'true'
            elif current_value is not None:
                bool_value = bool(current_value)
            var.set(bool_value)

            # Используем ttk.Checkbutton с кастомным стилем
            check = ttk.Checkbutton(
                widget_container, variable=var,
                style='CustomDark.TCheckbutton',
                state=widget_state_ttk,
                takefocus=False
            )
            check.pack(side=tk.RIGHT, padx=container_padx + 10, pady=container_pady)
            widget = check
            widget_var = var

        if widget:
            # Сохраняем виджет и его переменную
            self.widgets[key] = {'widget': widget, 'variable': widget_var}
            if show_setting_description:
                elements_to_bind = [label_container, label, widget_container, widget]
                for w in elements_to_bind:
                     if w:
                         w.bind("<Enter>", lambda event, k=key: show_setting_description(k), '+')
                         w.bind("<Leave>", self.clear_description, '+')

        self.row_count += 1
        return widget

    def get_values(self):
        values = {}
        for key, data in self.widgets.items():
            widget = data.get('widget')
            variable = data.get('variable')
            value = None
            try:
                if isinstance(widget, ttk.Combobox):
                    value = widget.get()
                elif isinstance(widget, tk.Entry) and variable:
                    value = variable.get()
                elif isinstance(widget, ttk.Checkbutton) and variable:
                    value = variable.get()
                elif variable:
                     value = variable.get()
                elif isinstance(widget, tk.Entry):
                     value = widget.get()
                values[key] = value
            except Exception as e:
                logger.info(f"{_('Ошибка получения значения для', 'Error getting value for')} {key}: {e}")
                values[key] = None
        return values

class VoiceModelSettingsWindow:
    _ttk_styles_initialized = False # Флаг для однократной инициализации стилей

    def __init__(self, master=None, config_dir=None, on_save_callback=None, local_voice=None, check_installed_func=None):
        self.master = master or tk.Tk()
        self.master.title(_("Настройки и Установка Локальных Моделей", "Settings and Installation of Local Models"))
        self.master.minsize(750, 500)
        self.master.geometry("875x800")
        self.master.configure(bg="#1e1e1e")

        self.local_voice = local_voice
        self.check_installed_func = check_installed_func
        self.config_dir = config_dir or os.path.dirname(os.path.abspath(__file__))
        self.settings_values_file = os.path.join(self.config_dir, "voice_model_settings.json")
        self.installed_models_file = os.path.join(self.config_dir, "installed_models.txt")
        self.on_save_callback = on_save_callback

        self.model_descriptions = model_descriptions_en if SettingsManager.get("LANGUAGE") == "EN" else model_descriptions
        self.setting_descriptions = setting_descriptions_en if SettingsManager.get("LANGUAGE") == "EN" else setting_descriptions
        self.default_description_text = default_description_text_en if SettingsManager.get("LANGUAGE") == "EN" else default_description_text

        self.detected_gpu_vendor = check_gpu_provider()
        self.detected_cuda_devices = []
        self.gpu_name = None # Инициализируем имя GPU

        if self.detected_gpu_vendor == "NVIDIA":
            self.detected_cuda_devices = get_cuda_devices()
            if self.detected_cuda_devices:
                # Пытаемся получить имя первой CUDA видеокарты
                try:
                    first_device_id = self.detected_cuda_devices[0]
                    self.gpu_name = get_gpu_name_by_id(first_device_id)
                    if self.gpu_name:
                        logger.info(f"{_('Обнаружена GPU:', 'Detected GPU:')} {self.gpu_name}")
                    else:
                        logger.info(f"{_('Не удалось получить имя для GPU', 'Could not get name for GPU')} {first_device_id}")
                except Exception as e:
                    logger.info(f"{_('Предупреждение: Не удалось получить имя GPU:', 'Warning: Could not get GPU name:')} {e}")

        self.description_label_widget = None
        self.settings_sections = {}
        self.model_action_buttons = {}
        self.installed_models = set()
        self.scrollable_frame_settings = None
        self.placeholder_label_settings = None
        self.top_frame_settings = None
        self.models_canvas = None
        self.settings_canvas = None
        self.models_scrollable_area = None
        self.local_voice_models = []

        self.load_installed_models_state()
        self.load_settings()
        
        self.docs_manager = DocsManager()
        self._check_system_dependencies()

        self._initialize_custom_ttk_styles()
        self._initialize_layout()
        self._create_model_panels()
        self.display_installed_models_settings()

        self.master.after(100, self._update_settings_scrollregion)
        self.master.after(100, self._update_models_scrollregion)

    def _initialize_custom_ttk_styles(self):
        if VoiceModelSettingsWindow._ttk_styles_initialized:
            return

        style = ttk.Style()

        # Цвета
        frame_bg = "#1e1e1e"
        widget_bg = "#3c3c3c"
        widget_fg = "white"
        border_color = "#6b6b6b"
        darker_border_color = "#444444"
        select_bg = "#005f87"
        disabled_fg = "#888888"
        disabled_bg = "#303030"
        arrow_color = widget_fg
        arrow_active_bg = "#4f4f4f"
        # Цвета для Scrollbar
        scrollbar_trough_color = frame_bg 
        scrollbar_thumb_color = "#555555"
        scrollbar_thumb_active_color = "#6a6a6a"
        scrollbar_border_color = darker_border_color 

        # --- Стиль Combobox (CustomDark.TCombobox) ---
        style.element_create("CustomDarkCombobox.field", "from", "default")
        style.element_create("CustomDarkCombobox.downarrow", "from", "default")
        style.layout("CustomDark.TCombobox", [(
            'CustomDarkCombobox.field', {'sticky': 'nswe', 'border': '1', 'children': [(
                    'CustomDarkCombobox.textarea', {'sticky': 'nswe'}
            )]}) , (
            'CustomDarkCombobox.downarrow', {'side': 'right', 'sticky': 'ns'}
        )])
        style.configure("CustomDark.TCombobox",
                        background=widget_bg, fieldbackground=widget_bg, foreground=widget_fg,
                        bordercolor=darker_border_color, arrowcolor=arrow_color, arrowsize=12,
                        borderwidth=1, padding=(5, 4), relief="solid", insertcolor=widget_fg)
        style.map("CustomDark.TCombobox",
                  foreground=[('disabled', disabled_fg)],
                  fieldbackground=[('disabled', disabled_bg)],
                  bordercolor=[('disabled', darker_border_color), ('focus', select_bg), ('hover', border_color)],
                  arrowcolor=[('disabled', disabled_fg), ('pressed', arrow_color), ('hover', arrow_color)])

        # --- Стиль Listbox внутри Combobox (через option_add) ---
        self.master.option_add('*TCombobox*Listbox.background', widget_bg)
        self.master.option_add('*TCombobox*Listbox.foreground', widget_fg)
        self.master.option_add('*TCombobox*Listbox.selectBackground', select_bg)
        self.master.option_add('*TCombobox*Listbox.selectForeground', widget_fg)
        self.master.option_add('*TCombobox*Listbox.font', ("Segoe UI", 9))
        self.master.option_add('*TCombobox*Listbox.borderWidth', 1)
        self.master.option_add('*TCombobox*Listbox.borderColor', darker_border_color)
        self.master.option_add('*TCombobox*Listbox.relief', 'solid')
        self.master.option_add('*TCombobox*Listbox.highlightThickness', 0)

        # --- Стиль Checkbutton (CustomDark.TCheckbutton) ---
        style.configure('CustomDark.TCheckbutton',
                        background=frame_bg, foreground=widget_fg, indicatorcolor=widget_bg,
                        indicatorrelief='solid', indicatormargin=2, indicatordiameter=12,
                        padding=5, relief='flat', font=("Segoe UI", 9))
        style.map('CustomDark.TCheckbutton',
                  indicatorcolor=[('selected', select_bg), ('active', '#555555')])


        style.configure('Collapsible.TFrame', background=frame_bg)

        style.element_create("CustomScrollbar.trough", "from", "default") 
        style.element_create("CustomScrollbar.thumb", "from", "default") 

        style.layout('CustomDark.Vertical.TScrollbar', [(
            'CustomScrollbar.trough', {'sticky': 'ns', 'children': [(
                'CustomScrollbar.thumb', {'expand': '1', 'sticky': 'nswe'}
            )]}
        )])
        # Убираем стрелки, если они есть в базовой теме
        style.layout('CustomDark.Horizontal.TScrollbar', [(
            'CustomScrollbar.trough', {'sticky': 'ew', 'children': [(
                'CustomScrollbar.thumb', {'expand': '1', 'sticky': 'nswe'}
            )]}
        )])


        style.configure('CustomDark.Vertical.TScrollbar',
                        relief='flat',
                        borderwidth=0,
                        background=scrollbar_trough_color,
                        troughrelief='flat',
                        troughborderwidth=0,
                        troughcolor=scrollbar_trough_color
                        )
        style.configure('CustomDark.Horizontal.TScrollbar', # На всякий случай, если понадобится
                        relief='flat',
                        borderwidth=0,
                        background=scrollbar_trough_color,
                        troughrelief='flat',
                        troughborderwidth=0,
                        troughcolor=scrollbar_trough_color
                        )

        # Настройка ручки (thumb)
        style.configure('CustomDark.Vertical.TScrollbar',   thumbrelief='flat', thumbborderwidth=0, background=scrollbar_thumb_color, bordercolor=scrollbar_border_color)
        style.configure('CustomDark.Horizontal.TScrollbar', thumbrelief='flat', thumbborderwidth=0, background=scrollbar_thumb_color, bordercolor=scrollbar_border_color)

        # Настройка ручки при наведении/нажатии
        style.map('CustomDark.Vertical.TScrollbar',
                  background=[('active', scrollbar_thumb_active_color), # Цвет ручки при наведении/нажатии
                              ('disabled', scrollbar_trough_color)], # Цвет ручки, если скроллбар неактивен
                  troughcolor=[('disabled', scrollbar_trough_color)]
                 )
        style.map('CustomDark.Horizontal.TScrollbar',
                  background=[('active', scrollbar_thumb_active_color),
                              ('disabled', scrollbar_trough_color)],
                  troughcolor=[('disabled', scrollbar_trough_color)]
                 )


        VoiceModelSettingsWindow._ttk_styles_initialized = True

    def get_default_model_structure(self):
        return [
             {
                "id": "low", "name": "Edge-TTS + RVC", "min_vram": 3, "rec_vram": 4,
                "gpu_vendor": ["NVIDIA", "AMD"], "size_gb": 3,
                "settings": [
                    {"key": "device", "label": _("Устройство RVC", "RVC Device"), "type": "combobox", "options": { "values_nvidia": ["dml", "cuda:0", "cpu"], "default_nvidia": "cuda:0", "values_amd": ["dml", "cpu"], "default_amd": "dml", "values_other": ["cpu", "mps:0"], "default_other": "cpu" }},
                     {"key": "is_half", "label": _("Half-precision RVC", "Half-precision RVC"), "type": "combobox", "options": {"values": ["True", "False"], "default_nvidia": "True", "default_amd": "False", "default_other": "False"}},
                    {"key": "f0method", "label": _("Метод F0 (RVC)", "F0 Method (RVC)"), "type": "combobox", "options": { "values_nvidia": ["pm", "rmvpe", "crepe", "harvest", "fcpe", "dio"], "default_nvidia": "rmvpe", "values_amd": ["rmvpe", "harvest", "pm", "dio"], "default_amd": "pm", "values_other": ["pm", "rmvpe", "crepe", "harvest", "fcpe", "dio"], "default_other": "pm" }},
                    {"key": "pitch", "label": _("Высота голоса RVC (пт)", "RVC Pitch (semitones)"), "type": "entry", "options": {"default": "6"}},
                    {"key": "use_index_file", "label": _("Исп. .index файл (RVC)", "Use .index file (RVC)"), "type": "checkbutton", "options": {"default": True}},
                    {"key": "index_rate", "label": _("Соотношение индекса RVC", "RVC Index Rate"), "type": "entry", "options": {"default": "0.75"}},
                    {"key": "protect", "label": _("Защита согласных (RVC)", "Consonant Protection (RVC)"), "type": "entry", "options": {"default": "0.33"}},
                    {"key": "tts_rate", "label": _("Скорость TTS (%)", "TTS Speed (%)"), "type": "entry", "options": {"default": "0"}},
                    # {"key": "output_gain", "label": _("Громкость RVC (gain)", "RVC Volume (gain)"), "type": "entry", "options": {"default": "0.75"}},
                    {"key": "filter_radius", "label": _("Радиус фильтра F0 (RVC)", "F0 Filter Radius (RVC)"), "type": "entry", "options": {"default": "3"}},
                    {"key": "rms_mix_rate", "label": _("Смешивание RMS (RVC)", "RMS Mixing (RVC)"), "type": "entry", "options": {"default": "0.5"}},
                ]
            },
            {
                "id": "low+", "name": "Silero + RVC", "min_vram": 3, "rec_vram": 4,
                "gpu_vendor": ["NVIDIA", "AMD"], "size_gb": 3,
                "settings": [
                    {"key": "silero_rvc_device", "label": _("Устройство RVC", "RVC Device"), "type": "combobox", "options": { "values_nvidia": ["dml", "cuda:0", "cpu"], "default_nvidia": "cuda:0", "values_amd": ["dml", "cpu"], "default_amd": "dml", "values_other": ["cpu", "dml"], "default_other": "cpu" }},
                    {"key": "silero_rvc_is_half", "label": _("Half-precision RVC", "Half-precision RVC"), "type": "combobox", "options": {"values": ["True", "False"], "default_nvidia": "True", "default_amd": "False", "default_other": "False"}},
                    {"key": "silero_rvc_f0method", "label": _("Метод F0 (RVC)", "F0 Method (RVC)"), "type": "combobox", "options": { "values_nvidia": ["pm", "rmvpe", "crepe", "harvest", "fcpe", "dio"], "default_nvidia": "rmvpe", "values_amd": ["rmvpe", "harvest", "pm", "dio"], "default_amd": "pm", "values_other": ["pm", "rmvpe", "harvest", "dio"], "default_other": "pm" }},
                    {"key": "silero_rvc_pitch", "label": _("Высота голоса RVC (пт)", "RVC Pitch (semitones)"), "type": "entry", "options": {"default": "6"}},
                    {"key": "silero_rvc_use_index_file", "label": _("Исп. .index файл (RVC)", "Use .index file (RVC)"), "type": "checkbutton", "options": {"default": True}},
                    {"key": "silero_rvc_index_rate", "label": _("Соотношение индекса RVC", "RVC Index Rate"), "type": "entry", "options": {"default": "0.75"}},
                    {"key": "silero_rvc_protect", "label": _("Защита согласных (RVC)", "Consonant Protection (RVC)"), "type": "entry", "options": {"default": "0.33"}},
                    {"key": "silero_rvc_filter_radius", "label": _("Радиус фильтра F0 (RVC)", "F0 Filter Radius (RVC)"), "type": "entry", "options": {"default": "3"}},
                    {"key": "silero_rvc_rms_mix_rate", "label": _("Смешивание RMS (RVC)", "RMS Mixing (RVC)"), "type": "entry", "options": {"default": "0.5"}},
                    
                    {"key": "silero_device", "label": _("Устройство Silero", "Silero Device"), "type": "combobox", "options": {"values_nvidia": ["cuda", "cpu"], "default_nvidia": "cuda", "values_amd": ["cpu"], "default_amd": "cpu", "values_other": ["cpu"], "default_other": "cpu"}},
                    {"key": "silero_sample_rate", "label": _("Частота Silero", "Silero Sample Rate"), "type": "combobox", "options": {"values": ["48000", "24000", "16000"], "default": "48000"}},
                    {"key": "silero_put_accent", "label": _("Акценты Silero", "Silero Accents"), "type": "checkbutton", "options": {"default": True}},
                    {"key": "silero_put_yo", "label": _("Буква Ё Silero", "Silero Letter Yo"), "type": "checkbutton", "options": {"default": True}}
                ]
            },
            {
                "id": "medium", "name": "Fish Speech", "min_vram": 3, "rec_vram": 6, "gpu_vendor": ["NVIDIA"], "size_gb": 5,
                 "settings": [
                    {"key": "device", "label": _("Устройство", "Device"), "type": "combobox", "options": {"values": ["cuda", "cpu", "mps"], "default": "cuda"}},
                    {"key": "half", "label": _("Half-precision", "Half-precision"), "type": "combobox", "options": {"values": ["False", "True"], "default": "False"}},
                    {"key": "temperature", "label": _("Температура", "Temperature"), "type": "entry", "options": {"default": "0.7"}},
                    {"key": "top_p", "label": _("Top-P", "Top-P"), "type": "entry", "options": {"default": "0.7"}},
                    {"key": "repetition_penalty", "label": _("Штраф повторений", "Repetition Penalty"), "type": "entry", "options": {"default": "1.2"}},
                    {"key": "chunk_length", "label": _("Размер чанка (~символов)", "Chunk Size (~chars)"), "type": "entry", "options": {"default": "200"}},
                    {"key": "max_new_tokens", "label": _("Макс. токены", "Max Tokens"), "type": "entry", "options": {"default": "1024"}},
                    { "key": "compile_model", "label": _("Компиляция модели", "Compile Model"), "type": "combobox", "options": {"values": ["False", "True"], "default": "False"}, "locked": True}
                ]
            },
            {
                "id": "medium+", "name": "Fish Speech+", "min_vram": 3, "rec_vram": 6, "gpu_vendor": ["NVIDIA"], "size_gb": 10,
                "rtx30plus": True,
                 "settings": [
                    {"key": "device", "label": _("Устройство", "Device"), "type": "combobox", "options": {"values": ["cuda", "cpu", "mps"], "default": "cuda"}},
                    {"key": "half", "label": _("Half-precision", "Half-precision"), "type": "combobox", "options": {"values": ["True", "False"], "default": "False"}, "locked": True},
                    {"key": "temperature", "label": _("Температура", "Temperature"), "type": "entry", "options": {"default": "0.7"}},
                    {"key": "top_p", "label": _("Top-P", "Top-P"), "type": "entry", "options": {"default": "0.8"}},
                    {"key": "repetition_penalty", "label": _("Штраф повторений", "Repetition Penalty"), "type": "entry", "options": {"default": "1.1"}},
                    {"key": "chunk_length", "label": _("Размер чанка (~символов)", "Chunk Size (~chars)"), "type": "entry", "options": {"default": "200"}},
                    {"key": "max_new_tokens", "label": _("Макс. токены", "Max Tokens"), "type": "entry", "options": {"default": "1024"}},
                    { "key": "compile_model", "label": _("Компиляция модели", "Compile Model"), "type": "combobox", "options": {"values": ["False", "True"], "default": "True"}, "locked": True}
                 ]
            },
            {
                "id": "medium+low", "name": "Fish Speech+ + RVC", "min_vram": 5, "rec_vram": 8, "gpu_vendor": ["NVIDIA"], "size_gb": 15,
                "rtx30plus": True,
                "settings": [
                    {"key": "fsprvc_fsp_device", "label": _("[FSP] Устройство", "[FSP] Device"), "type": "combobox", "options": {"values": ["cuda", "cpu", "mps"], "default": "cuda"}},
                    {"key": "fsprvc_fsp_half", "label": _("[FSP] Half-precision", "[FSP] Half-precision"), "type": "combobox", "options": {"values": ["True", "False"], "default": "False"}, "locked": True},
                    {"key": "fsprvc_fsp_temperature", "label": _("[FSP] Температура", "[FSP] Temperature"), "type": "entry", "options": {"default": "0.7"}},
                    {"key": "fsprvc_fsp_top_p", "label": _("[FSP] Top-P", "[FSP] Top-P"), "type": "entry", "options": {"default": "0.7"}},
                    {"key": "fsprvc_fsp_repetition_penalty", "label": _("[FSP] Штраф повторений", "[FSP] Repetition Penalty"), "type": "entry", "options": {"default": "1.2"}},
                    {"key": "fsprvc_fsp_chunk_length", "label": _("[FSP] Размер чанка (слов)", "[FSP] Chunk Size (words)"), "type": "entry", "options": {"default": "200"}},
                    {"key": "fsprvc_fsp_max_tokens", "label": _("[FSP] Макс. токены", "[FSP] Max Tokens"), "type": "entry", "options": {"default": "1024"}},
                    {"key": "fsprvc_rvc_device", "label": _("[RVC] Устройство", "[RVC] Device"), "type": "combobox", "options": {"values": ["cuda:0", "cpu", "mps:0", "dml"], "default_nvidia": "cuda:0", "default_amd": "dml"}},
                    {"key": "fsprvc_is_half", "label": _("[RVC] Half-precision", "[RVC] Half-precision"), "type": "combobox", "options": {"values": ["True", "False"], "default_nvidia": "True", "default_amd": "False"}},
                    {"key": "fsprvc_f0method", "label": _("[RVC] Метод F0", "[RVC] F0 Method"), "type": "combobox", "options": {"values": ["pm", "rmvpe", "crepe", "harvest", "fcpe", "dio"], "default_nvidia": "rmvpe", "default_amd": "dio"}},
                    {"key": "fsprvc_rvc_pitch", "label": _("[RVC] Высота голоса (пт)", "[RVC] Pitch (semitones)"), "type": "entry", "options": {"default": "0"}},
                    {"key": "fsprvc_use_index_file", "label": _("[RVC] Исп. .index файл", "[RVC] Use .index file"), "type": "checkbutton", "options": {"default": True}},
                    {"key": "fsprvc_index_rate", "label": _("[RVC] Соотн. индекса", "[RVC] Index Rate"), "type": "entry", "options": {"default": "0.75"}},
                    {"key": "fsprvc_protect", "label": _("[RVC] Защита согласных", "[RVC] Consonant Protection"), "type": "entry", "options": {"default": "0.33"}},
                    # {"key": "fsprvc_output_gain", "label": _("[RVC] Громкость (gain)", "[RVC] Volume (gain)"), "type": "entry", "options": {"default": "0.75"}},
                    {"key": "fsprvc_filter_radius", "label": _("[RVC] Радиус фильтра F0", "[RVC] F0 Filter Radius"), "type": "entry", "options": {"default": "3"}},
                    {"key": "fsprvc_rvc_rms_mix_rate", "label": _("[RVC] Смешивание RMS", "[RVC] RMS Mixing"), "type": "entry", "options": {"default": "0.5"}}
                ]
            },
            {
                "id": "f5_tts",
                "name": "F5-TTS",
                "min_vram": 6,
                "rec_vram": 8,
                "gpu_vendor": ["NVIDIA"],
                "size_gb": 4,
                "settings": [
                    {"key": "speed", "label": _("Скорость речи", "Speech Speed"), "type": "entry", "options": {"default": "1.0"}},
                    {"key": "nfe_step", "label": _("Шаги диффузии", "Diffusion Steps"), "type": "entry", "options": {"default": "32"}},
                    {"key": "remove_silence", "label": _("Удалять тишину", "Remove Silence"), "type": "checkbutton", "options": {"default": True}}
                ]
            }
        ]

    # def load_settings(self):
    #     self.installed_models = set()
    #     if self.local_voice and self.check_installed_func:
    #         for model_data in self.get_default_model_structure():
    #             model_id = model_data.get("id")
    #             if model_id:
    #                 if model_id == "low" and self.check_installed_func("tts_with_rvc"): self.installed_models.add(model_id)
    #                 elif model_id == "low+" and self.check_installed_func("tts_with_rvc"): self.installed_models.add(model_id)
    #                 elif model_id == "medium" and self.check_installed_func("fish_speech_lib"): self.installed_models.add(model_id)
    #                 elif model_id == "medium+" and self.check_installed_func("fish_speech_lib") and self.check_installed_func("triton"): self.installed_models.add(model_id)
    #                 elif model_id == "medium+low" and self.check_installed_func("tts_with_rvc") and self.check_installed_func("fish_speech_lib") and self.check_installed_func("triton"): self.installed_models.add(model_id)

    #     else:
    #         try:
    #             if os.path.exists(self.installed_models_file):
    #                 with open(self.installed_models_file, "r", encoding="utf-8") as f:
    #                     self.installed_models.update(line.strip() for line in f if line.strip())
    #         except Exception as e:
    #             logger.info(f"Ошибка загрузки состояния установленных моделей из {self.installed_models_file}: {e}")

    #     # 2. Получение базовой структуры по умолчанию
    #     default_model_structure = self.get_default_model_structure()

    #     # 3. Адаптация базовой структуры под окружение (GPU/OS) перед загрузкой сохраненных значений
    #     adapted_default_structure = self.finalize_model_settings(
    #         default_model_structure, self.detected_gpu_vendor, self.detected_cuda_devices
    #     )

    #     # 4. Загрузка сохраненных пользовательских значений из JSON
    #     saved_values = {}
    #     try:
    #         if os.path.exists(self.settings_values_file):
    #             with open(self.settings_values_file, "r", encoding="utf-8") as f:
    #                 saved_values = json.load(f)
    #     except Exception as e:
    #         logger.info(f"Ошибка загрузки сохраненных значений из {self.settings_values_file}: {e}")
    #         saved_values = {}

    #     # 5. Создание финальной структуры: начинаем с адаптированных дефолтов
    #     merged_model_structure = copy.deepcopy(adapted_default_structure)

    #     # 6. Наложение сохраненных значений поверх адаптированных дефолтов
    #     for model_data in merged_model_structure:
    #         model_id = model_data.get("id")
    #         if model_id in saved_values:
    #             model_saved_values = saved_values[model_id]
    #             if isinstance(model_saved_values, dict):
    #                 for setting in model_data.get("settings", []):
    #                     setting_key = setting.get("key")
    #                     if setting_key in model_saved_values:
    #                         setting.setdefault("options", {})["default"] = model_saved_values[setting_key]

    #     self.local_voice_models = merged_model_structure
    #     logger.info("Загрузка и адаптация настроек завершена.") 

    def load_settings(self):
        default_model_structure = self.get_default_model_structure()
        adapted_default_structure = self.finalize_model_settings(
            default_model_structure, self.detected_gpu_vendor, self.detected_cuda_devices
        )
        saved_values = {}
        try:
            if os.path.exists(self.settings_values_file):
                with open(self.settings_values_file, "r", encoding="utf-8") as f:
                    saved_values = json.load(f)
        except Exception as e:
            logger.info(f"{_('Ошибка загрузки сохраненных значений из', 'Error loading saved values from')} {self.settings_values_file}: {e}")
            saved_values = {}
        merged_model_structure = copy.deepcopy(adapted_default_structure)
        for model_data in merged_model_structure:
            model_id = model_data.get("id")
            if model_id in saved_values:
                model_saved_values = saved_values[model_id]
                if isinstance(model_saved_values, dict):
                    for setting in model_data.get("settings", []):
                        setting_key = setting.get("key")
                        if setting_key in model_saved_values:
                            setting.setdefault("options", {})["default"] = model_saved_values[setting_key]
        self.local_voice_models = merged_model_structure
        logger.info(_("Загрузка и адаптация настроек завершена.", "Loading and adaptation of settings completed."))

    def load_installed_models_state(self):
        """Загружает список установленных моделей из файла."""
        self.installed_models = set()
        # Загружаем из файла только для инициализации, если check_installed_func недоступен
        if not self.local_voice or not self.check_installed_func:
            try:
                if os.path.exists(self.installed_models_file):
                    with open(self.installed_models_file, "r", encoding="utf-8") as f:
                        self.installed_models.update(line.strip() for line in f if line.strip())
                    logger.info(f"{_('Загружен список установленных моделей из файла:', 'Loaded list of installed models from file:')} {self.installed_models}") 
            except Exception as e:
                logger.info(f"{_('Ошибка загрузки состояния из', 'Error loading state from')} {self.installed_models_file}: {e}")
        else:
            logger.info(_("Проверка установленных моделей через check_installed_func...", "Checking installed models via check_installed_func..."))
            for model_data in self.get_default_model_structure(): # Используем дефолтную структуру для перебора ID
                model_id = model_data.get("id")
                if model_id:
                    is_installed = False
                    if model_id == "low": is_installed = self.check_installed_func("tts_with_rvc")
                    elif model_id == "low+": is_installed = self.check_installed_func("tts_with_rvc")
                    elif model_id == "medium": is_installed = self.check_installed_func("fish_speech_lib")
                    elif model_id == "medium+": is_installed = self.check_installed_func("fish_speech_lib") and self.check_installed_func("triton")
                    elif model_id == "medium+low": is_installed = self.check_installed_func("tts_with_rvc") and self.check_installed_func("fish_speech_lib") and self.check_installed_func("triton")
                    elif model_id == "f5_tts": is_installed = self.check_installed_func("f5_tts")

                    if is_installed:
                        self.installed_models.add(model_id)
            logger.info(f"{_('Актуальный список установленных моделей:', 'Current list of installed models:')} {self.installed_models}")

    def save_settings(self):
        settings_to_save = {}
        for model_id, section in self.settings_sections.items():
            if model_id in self.installed_models and section.winfo_exists():
                try:
                    settings_to_save[model_id] = section.get_values()
                except Exception as e:
                    logger.info(f"{_('Ошибка при сборе значений из UI для модели', 'Error collecting UI values for model')} '{model_id}': {e}")
        if settings_to_save:
            try:
                with open(self.settings_values_file, "w", encoding="utf-8") as f:
                    json.dump(settings_to_save, f, indent=4, ensure_ascii=False)
            except Exception as e:
                logger.info(f"{_('Ошибка сохранения значений настроек в', 'Error saving settings values to')} {self.settings_values_file}: {e}")
        # Вызываем колбэк только если он есть
        if self.on_save_callback:
            callback_data = {
                 "installed_models": list(self.installed_models),
                 "models_data": self.local_voice_models
            }
            self.on_save_callback(callback_data)

    def finalize_model_settings(self, models_list, detected_vendor, cuda_devices):
        final_models = copy.deepcopy(models_list)

        gpu_name_upper = self.gpu_name.upper() if self.gpu_name else ""
        force_fp32 = False
        if detected_vendor == "NVIDIA" and gpu_name_upper:
            if (
                ("16" in gpu_name_upper and "V100" not in gpu_name_upper)
                or "P40" in gpu_name_upper
                or "P10" in gpu_name_upper
                or "1060" in gpu_name_upper
                or "1070" in gpu_name_upper
                or "1080" in gpu_name_upper
            ):
                logger.info(f"{_('Обнаружена GPU', 'Detected GPU')} {self.gpu_name}, {_('принудительно используется FP32 для совместимых настроек.', 'forcing FP32 for compatible settings.')}")
                force_fp32 = True
        elif detected_vendor == "AMD":
            force_fp32 = True


        for model in final_models:
            model_vendors = model.get("gpu_vendor", [])
            vendor_to_adapt_for = None
            if detected_vendor == "NVIDIA" and "NVIDIA" in model_vendors: vendor_to_adapt_for = "NVIDIA"
            elif detected_vendor == "AMD" and "AMD" in model_vendors: vendor_to_adapt_for = "AMD"
            elif not detected_vendor or detected_vendor not in model_vendors: vendor_to_adapt_for = "OTHER"
            elif detected_vendor in model_vendors: vendor_to_adapt_for = detected_vendor

            for setting in model.get("settings", []):
                options = setting.get("options", {})
                setting_key = setting.get("key")
                widget_type = setting.get("type")
                is_device_setting = "device" in str(setting_key).lower()
                is_half_setting = setting_key in ["is_half", "fsprvc_is_half", "half", "fsprvc_fsp_half"] # Включаем все варианты half

                final_values_list = None
                adapt_key_suffix = ""
                if vendor_to_adapt_for == "NVIDIA": adapt_key_suffix = "_nvidia"
                elif vendor_to_adapt_for == "AMD": adapt_key_suffix = "_amd"
                elif vendor_to_adapt_for == "OTHER": adapt_key_suffix = "_other"

                values_key = f"values{adapt_key_suffix}"
                default_key = f"default{adapt_key_suffix}"

                if values_key in options: final_values_list = options[values_key]
                elif "values" in options: final_values_list = options["values"]

                if default_key in options: options["default"] = options[default_key]

                if vendor_to_adapt_for == "NVIDIA" and is_device_setting:
                    base_nvidia_values = options.get("values_nvidia", [])
                    base_other_values = options.get("values_other", ["cpu"])
                    base_non_cuda_provider = base_nvidia_values if base_nvidia_values else base_other_values
                    non_cuda_options = [v for v in base_non_cuda_provider if not str(v).startswith("cuda")]
                    if cuda_devices: final_values_list = cuda_devices + non_cuda_options
                    else: final_values_list = [v for v in base_other_values if v in ["cpu", "mps"]] or ["cpu"]

                if final_values_list is not None and widget_type == "combobox":
                    options["values"] = final_values_list

                keys_to_remove = [k for k in options if k.startswith("values_") or k.startswith("default_")]
                for key_to_remove in keys_to_remove: options.pop(key_to_remove, None)

                # Применяем принудительное FP32 и блокировку
                if force_fp32 and is_half_setting:
                    options["default"] = "False" # Принудительно ставим False
                    setting["locked"] = True     # Блокируем настройку
                    logger.info(f"  - {_('Принудительно', 'Forcing')} '{setting_key}' = False {_('и заблокировано.', 'and locked.')}")
                elif is_half_setting:
                    logger.info(f"  - '{setting_key}' = True - Доступен.")

                if widget_type == "combobox" and "default" in options and "values" in options:
                    current_values = options["values"]
                    if isinstance(current_values, list):
                        current_default = options["default"]
                        str_values = [str(v) for v in current_values]
                        str_default = str(current_default)
                        if str_default not in str_values:
                            options["default"] = str_values[0] if str_values else ""
                    else:
                         options["default"] = ""
        return final_models

    def get_model_parameters(self, model_id):
        parameters = {}
        settings_file = self.settings_values_file
        if not os.path.exists(settings_file): return parameters
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                all_saved_data = json.load(f)
            if isinstance(all_saved_data, dict):
                parameters = all_saved_data.get(model_id, {})
        except Exception as e:
            logger.info(f"{_('Ошибка чтения файла настроек', 'Error reading settings file')} {settings_file}: {e}")
        return parameters

    # --- ИСПРАВЛЕННЫЙ МЕТОД ИНИЦИАЛИЗАЦИИ ---
    def _initialize_layout(self):
        main_app_frame = tk.Frame(self.master, bg="#1e1e1e")
        main_app_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # --- Левая панель ---
        left_panel_frame = tk.Frame(main_app_frame, bg="#1e1e1e", width=280)
        left_panel_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 5), pady=10)
        left_panel_frame.pack_propagate(False)
        # ... (код описания и списка моделей остается прежним) ...
        description_frame = tk.Frame(left_panel_frame, bg="#252525", bd=1, relief=tk.SOLID, height=135, highlightbackground="#444", highlightthickness=1)
        description_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))
        description_frame.pack_propagate(False)
        description_title = tk.Label(description_frame, text=_("Описание:","Description"), font=("Segoe UI", 9, "bold"), anchor="nw", bg="#252525", fg="white")
        description_title.pack(padx=10, pady=(5,2), anchor="nw")
        self.description_label_widget = tk.Label(description_frame, text=self.default_description_text, font=("Segoe UI", 9), anchor="nw", justify="left", wraplength=250, bg="#252525", fg="#cccccc")
        self.description_label_widget.pack(padx=10, pady=(0, 10), fill=tk.BOTH, expand=True)

        models_title = tk.Label(left_panel_frame, text=_("Доступные Модели:","Available models"), font=("Segoe UI", 10, "bold"), anchor="nw", bg="#1e1e1e", fg="white")
        models_title.pack(fill=tk.X, pady=(0, 5))
        
        models_canvas_frame = tk.Frame(left_panel_frame, bg="#1e1e1e")
        models_canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.models_canvas = tk.Canvas(models_canvas_frame, bg="#1e1e1e", highlightthickness=0)
        models_scrollbar = ttk.Scrollbar(models_canvas_frame, orient="vertical", command=self.models_canvas.yview, style='CustomDark.Vertical.TScrollbar')
        self.models_canvas.configure(yscrollcommand=models_scrollbar.set)
        models_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.models_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.models_scrollable_area = tk.Frame(self.models_canvas, bg="#1e1e1e")
        models_canvas_window_id = self.models_canvas.create_window((0, 0), window=self.models_scrollable_area, anchor="nw")
        
        self.models_scrollable_area.bind("<Configure>", self._update_models_scrollregion)
        self.models_canvas.bind("<Configure>", lambda e, cw=models_canvas_window_id: self.models_canvas.itemconfig(cw, width=e.width))
        
        self._bind_mousewheel(self.models_canvas, lambda e: self._handle_mousewheel(self.models_canvas, e))
        self._bind_mousewheel(self.models_scrollable_area, lambda e: self._handle_mousewheel(self.models_canvas, e))

        # --- Правая панель ---
        right_settings_frame = tk.Frame(main_app_frame, bg="#1e1e1e")
        right_settings_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 10), pady=10)
        
        self.settings_canvas = tk.Canvas(right_settings_frame, bg="#1e1e1e", highlightthickness=0)
        settings_scrollbar = ttk.Scrollbar(right_settings_frame, orient=tk.VERTICAL, command=self.settings_canvas.yview, style='CustomDark.Vertical.TScrollbar')
        self.settings_canvas.configure(yscrollcommand=settings_scrollbar.set)
        settings_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.scrollable_frame_settings = tk.Frame(self.settings_canvas, bg="#1e1e1e")
        settings_canvas_window_id = self.settings_canvas.create_window((0, 0), window=self.scrollable_frame_settings, anchor="nw")
        
        self.scrollable_frame_settings.bind("<Configure>", self._update_settings_scrollregion)
        self.settings_canvas.bind("<Configure>", lambda e, cw=settings_canvas_window_id: self.settings_canvas.itemconfig(cw, width=e.width))
        
        self._bind_mousewheel(self.settings_canvas, lambda e: self._handle_mousewheel(self.settings_canvas, e))
        self._bind_mousewheel(self.scrollable_frame_settings, lambda e: self._handle_mousewheel(self.settings_canvas, e))


        # --- Отображение статуса зависимостей (Внутри правой панели) ---
        self.top_frame_settings = tk.Frame(self.scrollable_frame_settings, bg="#1e1e1e")
        self.top_frame_settings.pack(fill=tk.X, padx=10, pady=(10, 5), anchor='nw')

        status_font = ("Segoe UI", 9)
        warning_font = ("Segoe UI", 9, "bold")
        status_label_color = "white"
        status_found_color = "lightgreen"
        status_notfound_color = "#FF6A6A" 
        link_color = "#81d4fa" 
        warning_color = "orange"
        bg_color = "#1e1e1e"

        # Фрейм для ГОРИЗОНТАЛЬНОЙ строки статусов компонентов
        status_items_display_frame = tk.Frame(self.top_frame_settings, bg=bg_color)
        status_items_display_frame.pack(anchor='w', fill=tk.X) # Заполняет ширину

        # Фрейм для строки предупреждения и ссылки (под статусами)
        warning_link_frame = None 

        if platform.system() == "Windows":
            if self.triton_installed:
                if self.triton_checks_performed:
                    items = [
                        ("CUDA Toolkit:", self.cuda_found),
                        ("Windows SDK:", self.winsdk_found),
                        ("MSVC:", self.msvc_found)
                    ]
                    
                    for text, found in items:
                        item_frame = tk.Frame(status_items_display_frame, bg=bg_color)
                        item_frame.pack(side=tk.LEFT, padx=(0, 15)) 

                        label = tk.Label(item_frame, text=text, font=status_font, bg=bg_color, fg=status_label_color)
                        label.pack(side=tk.LEFT) 

                        status_text = _("Найден", "Found") if found else _("Не найден", "Not Found")
                        status_color = status_found_color if found else status_notfound_color
                        status_label = tk.Label(item_frame, text=status_text, font=status_font, bg=bg_color, fg=status_color)
                        status_label.pack(side=tk.LEFT, padx=(3, 0)) # Небольшой отступ слева от статуса

                    # Проверка необходимости предупреждения (ПОСЛЕ статусов)
                    if not (self.cuda_found and self.winsdk_found and self.msvc_found):
                        # Создаем и пакуем фрейм для предупреждения/ссылки под статусами
                        warning_link_frame = tk.Frame(self.top_frame_settings, bg=bg_color)
                        warning_link_frame.pack(side=tk.TOP, fill=tk.X, pady=(5, 0), anchor='w') 

                        warning_text = _("⚠️ Для моделей Fish Speech+ / +RVC могут потребоваться все компоненты.", "⚠️ Fish Speech+ / +RVC models may require all components.")
                        warning_label = tk.Label(warning_link_frame, text=warning_text, bg=bg_color, fg=warning_color, font=warning_font)
                        warning_label.pack(side=tk.LEFT, padx=(0, 5)) 

                        doc_link_label = tk.Label(warning_link_frame, text=_("[Документация]", "[Documentation]"), bg=bg_color, fg=link_color, font=warning_font, cursor="hand2")
                        doc_link_label.pack(side=tk.LEFT) 
                        doc_link_label.bind("<Button-1>", lambda event: self.docs_manager.open_doc("installation_guide.html"))

                else: # Ошибка проверки
                    tk.Label(status_items_display_frame, text=_("⚠️ Ошибка проверки зависимостей Triton.", "⚠️ Error checking Triton dependencies."), font=status_font, bg=bg_color, fg=warning_color).pack(anchor='w')

            else: # Triton не установлен
                warning_link_frame = tk.Frame(self.top_frame_settings, bg=bg_color)
                warning_link_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 0), anchor='w') 

                tk.Label(warning_link_frame, text=_("Triton не установлен (необходим для Fish Speech+ / +RVC).", "Triton not installed (required for Fish Speech+ / +RVC)."), font=status_font, bg=bg_color, fg=warning_color).pack(side=tk.LEFT, padx=(0, 5))

                #  doc_link_label_triton = tk.Label(warning_link_frame, text="[Инструкция]", bg=bg_color, fg=link_color, font=status_font, cursor="hand2")
                #  doc_link_label_triton.pack(side=tk.LEFT)
                #  doc_link_label_triton.bind("<Button-1>", lambda event: self.docs_manager.open_doc("installation_guide.html"))

        else: # Не Windows
            tk.Label(status_items_display_frame, text=_("Проверка зависимостей Triton доступна только в Windows.", "Triton dependency check is only available on Windows."), font=status_font, bg=bg_color, fg="#aaaaaa").pack(anchor='w')

        bottom_frame = tk.Frame(self.master, bg="#1e1e1e", height=50)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 10), padx=10)
        bottom_frame.pack_propagate(False) 
        
        save_button = tk.Button(bottom_frame, text=_("Сохранить", "Save"), command=self.save_and_continue, bg="#3c3cac", fg="white", activebackground="#4a4acb", activeforeground="white", relief="flat", bd=0, padx=20, pady=5, font=("Segoe UI", 9))
        save_button.pack(side=tk.RIGHT, pady=5, padx=(5, 0))
        
        close_button = tk.Button(bottom_frame, text=_("Закрыть", "Close"), command=self.save_and_quit, bg="#3c3c3c", fg="white", activebackground="#555555", activeforeground="white", relief="flat", bd=0, padx=20, pady=5, font=("Segoe UI", 9))
        close_button.pack(side=tk.RIGHT, pady=5, padx=(0, 0)) 

    def _bind_mousewheel(self, widget, command):
         widget.bind("<MouseWheel>", command, '+')
         if platform.system() == "Linux":
             widget.bind("<Button-4>", command, '+')
             widget.bind("<Button-5>", command, '+')

    def _handle_mousewheel(self, canvas, event):
        if not canvas or not canvas.winfo_exists(): return
        canvas.update_idletasks()
        bbox = canvas.bbox("all")
        if not bbox or (bbox[3] - bbox[1]) <= canvas.winfo_height(): return
        delta = 0
        system = platform.system()
        if system == "Windows": delta = -1 * (event.delta // 120)
        elif system == "Darwin": delta = -1 * event.delta
        else: delta = -1 if event.num == 4 else (1 if event.num == 5 else 0)
        if delta != 0: canvas.yview_scroll(delta, "units")

    def _create_model_panels(self):
        if not self.models_scrollable_area: return
        for widget in self.models_scrollable_area.winfo_children(): widget.destroy()
        self.download_buttons = {}
        for model_info in self.local_voice_models:
            panel = self.create_model_panel(self.models_scrollable_area, model_info)
            panel.pack(pady=4, padx=2, fill=tk.X)
        self.master.after(50, self._update_models_scrollregion)

    def display_installed_models_settings(self):
        """Отображает настройки для установленных моделей БЕЗ дополнительной плашки RTX в настройках."""
        if not self.scrollable_frame_settings or not self.scrollable_frame_settings.winfo_exists():
            return

        widgets_to_manage = [w for w in self.scrollable_frame_settings.winfo_children() if w != self.top_frame_settings]
        for widget in widgets_to_manage:
            widget.destroy()

        self.settings_sections.clear()

        if self.placeholder_label_settings and self.placeholder_label_settings.winfo_exists():
            self.placeholder_label_settings.pack_forget()

        if not self.installed_models:
            if self.placeholder_label_settings is None or not self.placeholder_label_settings.winfo_exists():
                self.placeholder_label_settings = tk.Label(self.scrollable_frame_settings, text=_("Модели не установлены.\n\nНажмите 'Установить' слева для установки модели,\nее настройки появятся здесь.", "Models not installed.\n\nClick 'Install' on the left to install a model,\nits settings will appear here."), font=("Segoe UI", 10), bg="#1e1e1e", fg="#aaa", justify="center", wraplength=350)
            self.placeholder_label_settings.pack(pady=30, padx=10, fill=tk.BOTH, expand=True, after=self.top_frame_settings)
        else:
            any_settings_shown = False
            last_packed_widget = self.top_frame_settings

            for model_data in self.local_voice_models:
                model_id = model_data.get("id")
                if not model_id or model_id not in self.installed_models:
                    continue

                any_settings_shown = True
                model_name = model_data.get('name', model_id)

                section_title = f"{_('Настройки:', 'Settings:')} {model_name}"
                start_collapsed = len(self.installed_models) > 2
                section = VoiceCollapsibleSection(
                    self.scrollable_frame_settings,
                    section_title,
                    collapsed=start_collapsed,
                    update_scrollregion_func=self._update_settings_scrollregion,
                    clear_description_func=self.clear_description
                )
                self.settings_sections[model_id] = section

                # Добавление строк настроек
                model_settings = model_data.get("settings", [])
                current_row_index = 0 # Начинаем с 0 строки внутри секции
                if model_settings:
                    for setting_info in model_settings:
                        key = setting_info.get("key")
                        label = setting_info.get("label", key)
                        widget_type = setting_info.get("type")
                        options = setting_info.get("options", {})
                        if key and widget_type:
                            section.add_row(
                                key, label, widget_type, options, setting_info,
                                show_setting_description=self.show_setting_description
                            )
                else:
                    no_settings_label = tk.Label(section.content_frame, text=_("Специфические настройки отсутствуют.", "Specific settings are missing."), bg="#1e1e1e", fg="#ccc", font=("Segoe UI", 9))

                    no_settings_label.grid(row=0, column=0, columnspan=2, pady=10, padx=10)
                    section.row_count = 1


                section.pack(fill=tk.X, padx=10, pady=(5,0), anchor='nw', after=last_packed_widget)
                last_packed_widget = section

            if self.installed_models and not any_settings_shown:
                if self.placeholder_label_settings is None or not self.placeholder_label_settings.winfo_exists():
                    self.placeholder_label_settings = tk.Label(self.scrollable_frame_settings, text=_("Не удалось отобразить настройки для установленных моделей.", "Could not display settings for installed models."), font=("Segoe UI", 10), bg="#1e1e1e", fg="#aaa", justify="center", wraplength=350)
                self.placeholder_label_settings.pack(pady=30, padx=10, fill=tk.BOTH, expand=True, after=self.top_frame_settings)


        self.master.after(50, self._update_settings_scrollregion)

        
    def _check_system_dependencies(self):
        """Проверяет наличие CUDA, Windows SDK и MSVC с помощью triton (исправлено)."""
        self.cuda_found = False
        self.winsdk_found = False
        self.msvc_found = False
        self.triton_installed = False
        self.triton_checks_performed = False

        if platform.system() != "Windows":
            logger.info(_("Проверка зависимостей Triton актуальна только для Windows.", "Triton dependency check is relevant only for Windows."))
            return

        try:
            from triton.windows_utils import find_cuda, find_winsdk, find_msvc
            self.triton_installed = True

            # --- Проверка CUDA ---
            cuda_result = find_cuda()
            logger.info(f"CUDA find_cuda() result: {cuda_result}")
            if isinstance(cuda_result, (tuple, list)) and len(cuda_result) >= 1:
                cuda_path = cuda_result[0]
                self.cuda_found = cuda_path is not None and os.path.exists(str(cuda_path)) 
            else:
                self.cuda_found = False
            logger.info(f"CUDA Check: Found={self.cuda_found}")

            # --- Проверка WinSDK ---
            winsdk_result = find_winsdk(False)
            logger.info(f"WinSDK find_winsdk() result: {winsdk_result}") 
            if isinstance(winsdk_result, (tuple, list)) and len(winsdk_result) >= 1:
                winsdk_paths = winsdk_result[0]
                self.winsdk_found = isinstance(winsdk_paths, list) and bool(winsdk_paths)
            else:
                self.winsdk_found = False
            logger.info(f"WinSDK Check: Found={self.winsdk_found}")

            # --- Проверка MSVC ---
            msvc_result = find_msvc(False)
            logger.info(f"MSVC find_msvc() result: {msvc_result}")
            if isinstance(msvc_result, (tuple, list)) and len(msvc_result) >= 1:
                msvc_paths = msvc_result[0]
                self.msvc_found = isinstance(msvc_paths, list) and bool(msvc_paths)
            else:
                self.msvc_found = False
            logger.info(f"MSVC Check: Found={self.msvc_found}")

            self.triton_checks_performed = True

        except ImportError:
            logger.info(_("Triton не установлен. Невозможно проверить зависимости CUDA/WinSDK/MSVC.", "Triton not installed. Cannot check CUDA/WinSDK/MSVC dependencies."))
            self.triton_installed = False
        except Exception as e:
            logger.info(f"{_('Ошибка при проверке зависимостей Triton:', 'Error checking Triton dependencies:')} {e}")

    # Адаптированный метод create_model_panel
    def create_model_panel(self, parent, model_data):
        panel_bg = "#2a2a2e"; text_color = "#b0b0b0"; title_color = "#ffffff"
        border_color = "#444444"; button_fg = "white"
        install_button_bg = "#555555"; install_button_active_bg = "#666666"
        uninstall_button_bg = "#ac3939"; uninstall_button_active_bg = "#bf4a4a" # Красный для удаления
        button_disabled_fg = "#999999"
        warning_color_amd = "#FF6A6A"; rtx_warning_color = "orange"; rtx_ok_color = "lightgreen"
        medium_warning_color = "orange" # Цвет для иконки предупреждения medium

        model_id = model_data["id"]
        model_name = model_data["name"]
        supported_vendors = model_data.get('gpu_vendor', [])
        requires_rtx30plus = model_data.get("rtx30plus", False)

        panel = tk.Frame(parent, bg=panel_bg, bd=1, relief=tk.SOLID, highlightbackground=border_color, highlightthickness=1)
        panel.bind("<Enter>", lambda e, k=model_id: self.show_model_description(k))
        panel.bind("<Leave>", self.clear_description)

        # --- Title Frame ---
        title_frame = tk.Frame(panel, bg=panel_bg)
        title_frame.pack(pady=(5, 2), padx=10, fill=tk.X)
        title_label = tk.Label(title_frame, text=model_name, font=("Segoe UI", 10, "bold"), bg=panel_bg, fg=title_color, anchor='w')
        title_label.pack(side=tk.LEFT, anchor='w')
        title_label.bind("<Enter>", lambda e, k=model_id: self.show_model_description(k)) # Bind title too
        title_label.bind("<Leave>", self.clear_description)

        # --- Warning Icon for "medium" model with Tooltip ---
        if model_id == "medium":
            warning_icon_medium = tk.Label(
                title_frame, text="⚠️",
                font=("Segoe UI", 9), # Slightly smaller than title
                bg=panel_bg, fg=medium_warning_color, anchor='w',
                cursor="question_arrow" # Indicate interactivity
            )
            warning_icon_medium.pack(side=tk.LEFT, padx=(3, 0), anchor='w')
            medium_tooltip_text = _(
                "Модель 'Fish Speech' не рекомендуется для большинства пользователей.\n\n"
                "Для стабильной скорости генерации требуется мощная видеокарта, "
                "минимальные \"играбельные\" GPU: GeForce RTX 2080 Ti / RTX 2070 Super / GTX 1080 Ti и подобные, "
                "использование на более слабых GPU может привести к очень медленной работе.\n\n"
                "Владельцам RTX30+ рекомендуется использовать модели \"Fish Speech+\", "
                "остальным рекомендуется использовать модель \"Silero + RVC\"",
                "The 'Fish Speech' model is not recommended for most users.\n\n"
                "A powerful graphics card is required for stable generation speed, "
                "minimum \"playable\" GPUs: GeForce RTX 2080 Ti / RTX 2070 Super / GTX 1080 Ti and similar, "
                "using it on weaker GPUs can lead to very slow performance.\n\n"
                "RTX30+ owners are recommended to use \"Fish Speech+\" models, "
                "others are recommended to use the \"Silero + RVC\" model"
            )
            Tooltip(warning_icon_medium, medium_tooltip_text, wraplength=300) # Create tooltip for the icon

        # --- RTX 30+ Icon (if needed) ---
        if requires_rtx30plus:
            gpu_meets_requirement = self.is_gpu_rtx30_or_40()
            icon_color = rtx_ok_color if gpu_meets_requirement else rtx_warning_color
            rtx_icon_label = tk.Label(title_frame, text="RTX 30+", font=("Segoe UI", 7, "bold"), bg=panel_bg, fg=icon_color, anchor='w')
            rtx_icon_label.pack(side=tk.LEFT, padx=(5, 0), anchor='w')
            # Optional: Add tooltip for RTX icon too
            rtx_tooltip_text = _("Требуется GPU NVIDIA RTX 30xx/40xx для оптимальной производительности.", "Requires NVIDIA RTX 30xx/40xx GPU for optimal performance.") if not gpu_meets_requirement else _("Ваша GPU подходит для этой модели.", "Your GPU is suitable for this model.")
            Tooltip(rtx_icon_label, rtx_tooltip_text)

        # --- Info Label (VRAM, GPU Support) ---
        vram_text = f"VRAM: {model_data.get('min_vram', '?')}GB - {model_data.get('rec_vram', '?')}GB"
        gpu_req_text = f"GPU: {', '.join(supported_vendors)}" if supported_vendors else "GPU: Any"
        info_label = tk.Label(panel, text=f"{vram_text} | {gpu_req_text}", font=("Segoe UI", 8), bg=panel_bg, fg=text_color, anchor='w')
        info_label.pack(pady=(0, 5), padx=10, fill=tk.X)
        # Bind info label to general model description as well
        info_label.bind("<Enter>", lambda e, k=model_id: self.show_model_description(k))
        info_label.bind("<Leave>", self.clear_description)

        # --- AMD Warning (if needed) ---
        allow_unsupported_gpu = os.environ.get("ALLOW_UNSUPPORTED_GPU", "0") == "1"
        is_amd_user = self.detected_gpu_vendor == "AMD"
        is_amd_supported = "AMD" in supported_vendors
        is_gpu_unsupported_amd = is_amd_user and not is_amd_supported
        show_warning_amd = allow_unsupported_gpu and is_gpu_unsupported_amd

        if show_warning_amd:
            warning_label_amd = tk.Label(panel, text=_("Может не работать на AMD!", "May not work on AMD!"), font=("Segoe UI", 8, "bold"), bg=panel_bg, fg=warning_color_amd, anchor='w')
            warning_label_amd.pack(pady=(0, 5), padx=10, fill=tk.X)

        # --- Install/Uninstall Button ---
        button_frame = tk.Frame(panel, bg=panel_bg)
        button_frame.pack(pady=(2, 6), padx=10, fill=tk.X)
        button_frame.columnconfigure(0, weight=1)

        is_installed = model_id in self.installed_models
        action_button = None

        if is_installed:
            action_button = tk.Button(
                button_frame, text=_("Удалить", "Uninstall"),
                command=lambda mid=model_id, mname=model_name: self.confirm_and_start_uninstall(mid, mname),
                bg=uninstall_button_bg, fg=button_fg,
                activebackground=uninstall_button_active_bg, activeforeground=button_fg,
                relief="flat", bd=0,
                font=("Segoe UI", 8, "bold"),
                padx=5, pady=5, state=tk.NORMAL
            )
        else:
            install_text = _("Установить", "Install")
            can_install = True
            if is_gpu_unsupported_amd and not allow_unsupported_gpu:
                can_install = False
                install_text = _("Несовместимо с AMD", "Incompatible with AMD")

            install_state_tk = tk.NORMAL if can_install else tk.DISABLED
            action_button = tk.Button(
                button_frame, text=install_text,
                state=install_state_tk,
                bg=install_button_bg, fg=button_fg,
                activebackground=install_button_active_bg, activeforeground=button_fg,
                disabledforeground=button_disabled_fg,
                relief="flat", bd=0,
                font=("Segoe UI", 8, "bold"),
                padx=5, pady=5
            )
            if can_install:
                action_button.configure(command=lambda mid=model_id, btn=action_button, mdata=model_data: self.confirm_and_start_download(mid, btn, mdata))

        if action_button:
            self.model_action_buttons[model_id] = action_button
            action_button.grid(row=0, column=0, sticky="ew")

        return panel

    def is_gpu_rtx30_or_40(self):
        """
        Проверяет, является ли обнаруженная GPU NVIDIA RTX 30xx или 40xx,
        учитывая флаг окружения RTX_FORCE_UNSUPPORTED.
        """

        # Проверяем флаг принудительного неподдерживаемого статуса
        force_unsupported_str = os.environ.get("RTX_FORCE_UNSUPPORTED", "0")
        force_unsupported = force_unsupported_str.lower() in ['true', '1', 't', 'y', 'yes']

        if force_unsupported:
            logger.info(_("INFO: RTX_FORCE_UNSUPPORTED=1 - Имитация неподходящей GPU для RTX 30+.", "INFO: RTX_FORCE_UNSUPPORTED=1 - Simulating unsuitable GPU for RTX 30+."))
            return False

        if self.detected_gpu_vendor != "NVIDIA" or not self.gpu_name:
            return False

        name_upper = self.gpu_name.upper()
        # Проверяем наличие "RTX" и цифр "30" или "40" в начале серии
        if "RTX" in name_upper:
            if any(f" {gen}" in name_upper or name_upper.endswith(gen) or f"-{gen}" in name_upper for gen in ["3050", "3060", "3070", "3080", "3090"]):
                return True
            if any(f" {gen}" in name_upper or name_upper.endswith(gen) or f"-{gen}" in name_upper for gen in ["4050", "4060", "4070", "4080", "4090"]):
                return True
        return False

    def confirm_and_start_download(self, model_id, button_widget, model_data):
        """
        Показывает предупреждение для моделей rtx30plus, если GPU не соответствует,
        и затем запускает загрузку, если пользователь согласен.
        """
        requires_rtx30plus = model_data.get("rtx30plus", False)
        proceed_to_download = True # По умолчанию продолжаем

        if requires_rtx30plus:
            if not self.is_gpu_rtx30_or_40():
                gpu_info = self.gpu_name if self.gpu_name else "не определена"
                if self.detected_gpu_vendor and self.detected_gpu_vendor != "NVIDIA":
                    gpu_info = f"{self.detected_gpu_vendor} GPU"

                model_name = model_data.get("name", model_id)
                title = f"Предупреждение для модели '{model_name}'"
                message = _(
                    f"Эта модель ('{model_name}') оптимизирована для видеокарт NVIDIA RTX 30xx/40xx.\n\n"
                    f"Ваша видеокарта ({gpu_info}) может не обеспечить достаточной производительности, "
                    "что может привести к медленной работе или нестабильности.\n\n"
                    "Продолжить установку?",
                    f"This model ('{model_name}') is optimized for NVIDIA RTX 30xx/40xx graphics cards.\n\n"
                    f"Your graphics card ({gpu_info}) may not provide sufficient performance, "
                    "which could lead to slow operation or instability.\n\n"
                    "Continue installation?"
                )
                # Спрашиваем пользователя
                proceed_to_download = tkinter.messagebox.askokcancel(title, message, icon='warning', parent=self.master)

        if proceed_to_download:
            self.start_download(model_id, button_widget)

    def confirm_and_start_uninstall(self, model_id, model_name):
        """Запрашивает подтверждение и проверяет инициализацию перед удалением."""
        if not self.local_voice:
            logger.error(_("LocalVoice не инициализирован, удаление невозможно.", "LocalVoice not initialized, uninstallation impossible."))
            tkinter.messagebox.showerror(_("Ошибка", "Error"), _("Компонент LocalVoice не доступен.", "LocalVoice component is not available."), parent=self.master)
            return

        # Проверка, инициализирована ли модель
        try:
            if hasattr(self.local_voice, 'is_model_initialized') and self.local_voice.is_model_initialized(model_id):
                logger.warning(f"Попытка удаления инициализированной модели: {model_id}")
                tkinter.messagebox.showerror(
                    _("Модель Активна", "Model Active"),
                    _(f"Модель '{model_name}' сейчас используется или инициализирована.\n\n"
                      "Пожалуйста, перезапустите приложение полностью, чтобы освободить ресурсы, "
                      "прежде чем удалять эту модель.",
                      f"Model '{model_name}' is currently in use or initialized.\n\n"
                      "Please restart the application completely to free up resources "
                      "before uninstalling this model."),
                    parent=self.master
                )
                return 
        except Exception as e:
            logger.error(f"{_('Ошибка при проверке инициализации модели', 'Error checking model initialization')} {model_id}: {e}")
            tkinter.messagebox.showerror(_("Ошибка Проверки", "Check Error"), _(f"Не удалось проверить статус модели '{model_name}'. Удаление отменено.", f"Could not check status of model '{model_name}'. Uninstallation cancelled."), parent=self.master)
            return

        # Запрос подтверждения
        confirm = tkinter.messagebox.askyesno(
            _("Подтверждение Удаления", "Confirm Uninstallation"),
            _(f"Вы уверены, что хотите удалить модель '{model_name}'?\n\n"
              "Будут удалены основной пакет модели и все зависимости, которые больше не используются другими установленными моделями (кроме g4f).\n\n"
              "Это действие необратимо!",
              f"Are you sure you want to uninstall the model '{model_name}'?\n\n"
              "The main model package and all dependencies no longer used by other installed models (except g4f) will be removed.\n\n"
              "This action is irreversible!"),
            icon='warning', parent=self.master
        )

        if confirm:
            self.start_uninstall(model_id)

    def start_download(self, model_id, button_widget):
        if button_widget and button_widget.winfo_exists():
            # Используем состояние tk.DISABLED
            button_widget.config(text=_("Загрузка...", "Downloading..."), state=tk.DISABLED)

        if self.local_voice and hasattr(self.local_voice, 'download_model'):
            def install_thread_func():
                success = False
                try:
                    success = self.local_voice.download_model(model_id)
                except Exception as e:
                    logger.info(f"{_('Ошибка в потоке загрузки для', 'Error in download thread for')} {model_id}: {e}")
                finally:
                    if self.master.winfo_exists():
                        self.master.after(0, lambda: self.handle_download_result(success, model_id))

            install_thread = threading.Thread(target=install_thread_func, daemon=True)
            install_thread.start()
        else:
            logger.info(_("Внимание: LocalVoice не доступен, используется имитация установки", "Warning: LocalVoice not available, simulating installation"))
            self.master.after(2000 + hash(model_id)%1000, lambda: self.handle_download_result(True, model_id))

    def start_uninstall(self, model_id):
        button_widget = self.model_action_buttons.get(model_id)
        if button_widget and button_widget.winfo_exists():
            button_widget.config(text=_("Удаление...", "Uninstalling..."), state=tk.DISABLED)

        if not self.local_voice:
            logger.error(f"{_('Неизвестный model_id для удаления:', 'Unknown model_id for uninstallation:')} {model_id}")
            if button_widget and button_widget.winfo_exists(): button_widget.config(text=_("Ошибка", "Error"), state=tk.NORMAL)
            return

        target_uninstall_func = None
        if model_id in ["low", "low+"]:
            target_uninstall_func = self.local_voice.uninstall_edge_tts_rvc
        elif model_id == "medium":
            target_uninstall_func = self.local_voice.uninstall_fish_speech
        elif model_id in ["medium+", "medium+low"]:
            target_uninstall_func = self.local_voice.uninstall_triton_component
        elif model_id == "f5_tts":
            target_uninstall_func = self.local_voice.uninstall_f5_tts
        else:
            logger.error(f"Неизвестный model_id для удаления: {model_id}")
            if button_widget and button_widget.winfo_exists(): button_widget.config(text="Ошибка", state=tk.NORMAL)
            return

        if not hasattr(self.local_voice, target_uninstall_func.__name__):
            logger.error(f"{_('Метод', 'Method')} {target_uninstall_func.__name__} {_('не найден в LocalVoice.', 'not found in LocalVoice.')}")
            if button_widget and button_widget.winfo_exists(): button_widget.config(text=_("Ошибка", "Error"), state=tk.NORMAL)
            return

        # Запускаем выбранную функцию удаления в потоке
        def uninstall_thread_func():
            success = False
            try:
                success = target_uninstall_func() # Вызываем нужную функцию
            except Exception as e:
                logger.error(f"{_('Ошибка в потоке удаления для', 'Error in uninstall thread for')} {model_id}: {e}")
                logger.error(traceback.format_exc())
            finally:
                if self.master.winfo_exists():
                    self.master.after(0, lambda: self.handle_uninstall_result(success, model_id))

        uninstall_thread = threading.Thread(target=uninstall_thread_func, daemon=True)
        uninstall_thread.start()

    def handle_download_result(self, success, model_id):
        button_widget = self.download_buttons.get(model_id)
        if success:
            self.installed_models.add(model_id)
            logger.info(f"{_('Модель', 'Model')} {model_id} {_('установлена. Перезагрузка и адаптация настроек...', 'installed. Reloading and adapting settings...')}")
            self.load_settings()
            logger.info(_("Настройки перезагружены.", "Settings reloaded."))

            # Обновляем кнопку уже после перезагрузки настроек
            button_widget = self.download_buttons.get(model_id)
            if button_widget and button_widget.winfo_exists():
                button_widget.config(text="Установлено", state=tk.DISABLED)

            self.display_installed_models_settings()
            self.save_installed_models_list() 

            if self.on_save_callback:
                 callback_data = {
                    "installed_models": list(self.installed_models),
                    "models_data": self.local_voice_models 
                 }
                 self.on_save_callback(callback_data)
            logger.info(f"{_('Обработка установки', 'Handling installation of')} {model_id} {_('завершена.', 'completed.')}")
        else:
            logger.info(f"{_('Ошибка установки модели', 'Error installing model')} {model_id}.")
            # ?????
            self._create_model_panels()
            button_widget = self.model_action_buttons.get(model_id)
            if button_widget and button_widget.winfo_exists():
                button_widget.config(text=_("Ошибка", "Error"), state=tk.NORMAL) 

    def handle_uninstall_result(self, success, model_id):
        """Обновляет интерфейс после завершения удаления."""
        button_widget = self.model_action_buttons.get(model_id)
        model_data = next((m for m in self.local_voice_models if m["id"] == model_id), None)

        if success:
            logger.info(f"{_('Удаление модели', 'Uninstallation of model')} {model_id} {_('завершено успешно.', 'completed successfully.')}")
            if model_id in self.installed_models:
                self.installed_models.remove(model_id)

            if button_widget and button_widget.winfo_exists() and model_data:
                install_text = _("Установить", "Install")
                can_install = True

                supported_vendors = model_data.get('gpu_vendor', [])
                allow_unsupported_gpu = os.environ.get("ALLOW_UNSUPPORTED_GPU", "0") == "1"
                is_amd_user = self.detected_gpu_vendor == "AMD"
                is_amd_supported = "AMD" in supported_vendors
                is_gpu_unsupported_amd = is_amd_user and not is_amd_supported
                if is_gpu_unsupported_amd and not allow_unsupported_gpu:
                    can_install = False
                    install_text = _("Несовместимо с AMD", "Incompatible with AMD")

                install_state_tk = tk.NORMAL if can_install else tk.DISABLED
                button_widget.config(
                    text=install_text,
                    state=install_state_tk,
                    command=lambda mid=model_id, btn=button_widget, mdata=model_data: self.confirm_and_start_download(mid, btn, mdata),
                    bg="#555555", # Цвет кнопки установки
                    activebackground="#666666"
                )
            else:
                logger.warning(_(f"Не удалось найти кнопку для модели {model_id} после удаления.", f"Couldn't find the button for model {model_id} after uninstall."))

            if model_id in self.settings_sections:
                section = self.settings_sections.pop(model_id)
                if section and section.winfo_exists():
                    section.destroy()

            if not self.installed_models:
                 self.display_installed_models_settings() 

            self.save_installed_models_list() 
            if self.on_save_callback:
                 callback_data = {"installed_models": list(self.installed_models), "models_data": self.local_voice_models}
                 self.on_save_callback(callback_data)
            self._update_settings_scrollregion() 

        else:
            logger.error(f"{_('Ошибка при удалении модели', 'Error uninstalling model')} {model_id}.")
            tkinter.messagebox.showerror(_("Ошибка Удаления", "Uninstallation Error"), _(f"Не удалось удалить модель '{model_id}'.\nСм. лог для подробностей.", f"Could not uninstall model '{model_id}'.\nSee log for details."), parent=self.master)
            # Восстанавливаем кнопку "Удалить"
            if button_widget and button_widget.winfo_exists():
                button_widget.config(text="Удалить", state=tk.NORMAL)

    def save_installed_models_list(self):
        try:
            with open(self.installed_models_file, "w", encoding="utf-8") as f:
                for model_id in sorted(list(self.installed_models)):
                    f.write(f"{model_id}\n")
        except Exception as e:
            logger.info(f"{_('Ошибка сохранения списка установленных моделей в', 'Error saving list of installed models to')} {self.installed_models_file}: {e}")

    def show_setting_description(self, key):
        if self.description_label_widget and self.description_label_widget.winfo_exists():
            description = self.setting_descriptions.get(key, "")
            self.description_label_widget.config(text=description if description else self.default_description_text)

    def show_model_description(self, key):
        if self.description_label_widget and self.description_label_widget.winfo_exists():
            description = self.model_descriptions.get(key, "")
            self.description_label_widget.config(text=description if description else self.default_description_text)

    def clear_description(self, event=None):
        if self.description_label_widget and self.description_label_widget.winfo_exists():
            self.description_label_widget.config(text=self.default_description_text)

    def _update_scrollregion(self, canvas, scrollbar_widget):
        # Общий метод для обновления области прокрутки и показа/скрытия скроллбара
        if not canvas or not canvas.winfo_exists(): return
        canvas.update_idletasks()
        bbox = canvas.bbox("all")
        if bbox:
            scroll_region = (bbox[0], bbox[1], bbox[2], bbox[3])
            canvas.configure(scrollregion=scroll_region)
            scroll_height = scroll_region[3] - scroll_region[1]
            canvas_height = canvas.winfo_height()

            if scrollbar_widget and scrollbar_widget.winfo_exists():
                if scroll_height > canvas_height:
                    if not scrollbar_widget.winfo_ismapped():
                        # Пакуем относительно родительского фрейма канваса
                        scrollbar_widget.pack(side=tk.RIGHT, fill=tk.Y, in_=canvas.master)
                else:
                    if scrollbar_widget.winfo_ismapped():
                        scrollbar_widget.pack_forget()
                        canvas.yview_moveto(0)

    def _update_settings_scrollregion(self, event=None):
        # Находим скроллбар в родительском фрейме канваса настроек
        scrollbar = next((w for w in self.settings_canvas.master.winfo_children() if isinstance(w, ttk.Scrollbar)), None)
        self._update_scrollregion(self.settings_canvas, scrollbar)

    def _update_models_scrollregion(self, event=None):
        # Находим скроллбар в родительском фрейме канваса моделей
        scrollbar = next((w for w in self.models_canvas.master.winfo_children() if isinstance(w, ttk.Scrollbar)), None)
        self._update_scrollregion(self.models_canvas, scrollbar)

    def save_and_continue(self):
        self.save_settings()

    def save_and_quit(self):
        self.save_settings()
        if self.master:
            self.master.destroy()

    def run(self):
        self.master.mainloop()
