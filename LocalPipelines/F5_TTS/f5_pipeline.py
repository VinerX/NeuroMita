import codecs
import os
import re
from datetime import datetime
from importlib.resources import files
from pathlib import Path

import numpy as np
import soundfile as sf
import tomli
from cached_path import cached_path
from hydra.utils import get_class
from omegaconf import OmegaConf

# Все импорты из f5_tts.infer.utils_infer остаются такими же
from f5_tts.infer.utils_infer import (
    cfg_strength as default_cfg_strength,
    cross_fade_duration as default_cross_fade_duration,
    device as default_device,
    fix_duration as default_fix_duration,
    infer_process,
    load_model,
    load_vocoder,
    mel_spec_type as default_mel_spec_type,
    nfe_step as default_nfe_step,
    preprocess_ref_audio_text,
    remove_silence_for_generated_wav,
    speed as default_speed,
    sway_sampling_coef as default_sway_sampling_coef,
    target_rms as default_target_rms,
)


class F5TTSPipeline:
    """
    Класс-пайплайн для инкапсуляции логики Text-to-Speech F5-TTS.
    Инициализирует модели один раз и позволяет многократно генерировать речь.
    """

    def __init__(self, config_path=None, **kwargs):
        """
        Инициализирует пайплайн, загружает модели и конфигурацию.

        Args:
            config_path (str, optional): Путь к TOML-файлу конфигурации.
            **kwargs: Аргументы для переопределения параметров из файла конфигурации.
        """
        print("Initializing F5-TTS Pipeline...")
        # 1. Загрузка и объединение конфигураций
        config = self._load_config(config_path, **kwargs)
        self.config = config

        # 2. Исправление путей для pip-пакета
        self._patch_paths()
        
        # 3. Загрузка вокодера
        print("Loading vocoder...")
        self.vocoder = self._load_vocoder()
        
        # 4. Загрузка основной TTS модели
        print("Loading TTS model...")
        self.model = self._load_tts_model()

        print("F5-TTS Pipeline initialized successfully.")

    def _load_config(self, config_path, **kwargs):
        """Загружает конфигурацию из файла и объединяет с kwargs."""
        # Путь к конфигу по умолчанию, если не предоставлен
        if config_path is None:
            config_path = os.path.join(files("f5_tts").joinpath("infer/examples/basic"), "basic.toml")

        # Загрузка из TOML файла
        file_config = tomli.load(open(config_path, "rb"))

        # Значения по умолчанию из оригинального скрипта
        defaults = {
            "model": "F5TTS_v1_Base",
            "ckpt_file": "",
            "vocab_file": "",
            "ref_audio": str(files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav")),
            "ref_text": "Some call me nature, others call me mother nature.",
            "gen_text": "Here we generate something just for test.",
            "gen_file": "",
            "output_dir": "tests",
            "output_file": f"infer_cli_{datetime.now().strftime(r'%Y%m%d_%H%M%S')}.wav",
            "save_chunk": False,
            "remove_silence": False,
            "load_vocoder_from_local": False,
            "vocoder_name": default_mel_spec_type,
            "target_rms": default_target_rms,
            "cross_fade_duration": default_cross_fade_duration,
            "nfe_step": default_nfe_step,
            "cfg_strength": default_cfg_strength,
            "sway_sampling_coef": default_sway_sampling_coef,
            "speed": default_speed,
            "fix_duration": default_fix_duration,
            "device": default_device,
        }
        
        # Объединение: сначала дефолты, потом из файла, потом из kwargs
        config = defaults
        config.update(file_config)
        config.update(kwargs)

        return config

    def _patch_paths(self):
        """Исправляет пути в конфигурации для пользователей pip пакета."""
        ref_audio = self.config.get("ref_audio", "")
        if "infer/examples/" in ref_audio:
            self.config["ref_audio"] = str(files("f5_tts").joinpath(ref_audio))
        
        gen_file = self.config.get("gen_file", "")
        if "infer/examples/" in gen_file:
            self.config["gen_file"] = str(files("f5_tts").joinpath(gen_file))

        if "voices" in self.config:
            for voice in self.config["voices"]:
                voice_ref_audio = self.config["voices"][voice]["ref_audio"]
                if "infer/examples/" in voice_ref_audio:
                    self.config["voices"][voice]["ref_audio"] = str(files("f5_tts").joinpath(voice_ref_audio))

    def _load_vocoder(self):
        """Загружает вокодер на основе конфигурации."""
        vocoder_name = self.config["vocoder_name"]
        if vocoder_name == "vocos":
            vocoder_local_path = "../checkpoints/vocos-mel-24khz"
        elif vocoder_name == "bigvgan":
            vocoder_local_path = "../checkpoints/bigvgan_v2_24khz_100band_256x"
        
        return load_vocoder(
            vocoder_name=vocoder_name,
            is_local=self.config["load_vocoder_from_local"],
            local_path=vocoder_local_path,
            device=self.config["device"]
        )

    def _load_tts_model(self):
        """Загружает TTS модель на основе конфигурации."""
        model_name = self.config["model"]
        model_cfg_path = self.config.get("model_cfg")
        if not model_cfg_path:
             model_cfg_path = str(files("f5_tts").joinpath(f"configs/{model_name}.yaml"))
        
        model_cfg = OmegaConf.load(model_cfg_path)
        model_cls = get_class(f"f5_tts.model.{model_cfg.model.backbone}")
        model_arc = model_cfg.model.arch

        repo_name, ckpt_step, ckpt_type = "F5-TTS", 1250000, "safetensors"

        if model_name != "F5TTS_Base":
            assert self.config["vocoder_name"] == model_cfg.model.mel_spec.mel_spec_type, \
                f"Vocoder mismatch! Model '{model_name}' requires '{model_cfg.model.mel_spec.mel_spec_type}' but '{self.config['vocoder_name']}' is configured."

        if model_name == "F5TTS_Base":
            if self.config["vocoder_name"] == "vocos":
                ckpt_step = 1200000
            elif self.config["vocoder_name"] == "bigvgan":
                model_name = "F5TTS_Base_bigvgan"
                ckpt_type = "pt"
        elif model_name == "E2TTS_Base":
            repo_name = "E2-TTS"
            ckpt_step = 1200000

        ckpt_file = self.config.get("ckpt_file")
        if not ckpt_file:
            ckpt_file = str(cached_path(f"hf://SWivid/{repo_name}/{model_name}/model_{ckpt_step}.{ckpt_type}"))

        print(f"Using model: {model_name} from {ckpt_file}")
        return load_model(
            model_cls,
            model_arc,
            ckpt_file,
            mel_spec_type=self.config["vocoder_name"],
            vocab_file=self.config["vocab_file"],
            device=self.config["device"]
        )

    def generate(self, text_to_generate, output_path, **kwargs):
        """
        Генерирует аудио из текста и сохраняет его в файл.

        Args:
            text_to_generate (str): Текст для озвучивания. Может быть строкой или путем к файлу.
            output_path (str): Путь для сохранения итогового WAV файла.
            **kwargs: Параметры для переопределения настроек генерации (например, ref_audio, ref_text, speed).
        
        Returns:
            str: Абсолютный путь к сгенерированному аудиофайлу.
        """
        # Создаем локальную копию конфига для этого запуска, чтобы не менять состояние объекта
        run_config = self.config.copy()
        run_config.update(kwargs)

        # Проверяем, является ли text_to_generate путем к файлу
        if os.path.isfile(text_to_generate):
            print(f"Reading text from file: {text_to_generate}")
            gen_text = codecs.open(text_to_generate, "r", "utf-8").read()
        else:
            gen_text = text_to_generate

        # Подготовка голосов
        main_voice = {"ref_audio": run_config["ref_audio"], "ref_text": run_config["ref_text"]}
        voices = run_config.get("voices", {})
        voices["main"] = main_voice # 'main' используется по умолчанию

        print("Preprocessing reference voices...")
        for voice_name, voice_data in voices.items():
            print(f"  - Voice: {voice_name}")
            voices[voice_name]["ref_audio"], voices[voice_name]["ref_text"] = preprocess_ref_audio_text(
                voice_data["ref_audio"], voice_data["ref_text"]
            )

        # Основной процесс генерации
        generated_audio_segments = []
        reg1 = r"(?=\[\w+\])"
        chunks = re.split(reg1, gen_text)
        reg2 = r"\[(\w+)\]"

        output_dir = Path(output_path).parent
        output_filename = Path(output_path).name

        if run_config.get("save_chunk"):
            output_chunk_dir = output_dir / f"{Path(output_filename).stem}_chunks"
            output_chunk_dir.mkdir(parents=True, exist_ok=True)

        for i, text_chunk in enumerate(chunks):
            if not text_chunk.strip():
                continue

            match = re.match(reg2, text_chunk)
            voice_name = "main" # по умолчанию
            if match:
                voice_name = match[1]
                if voice_name not in voices:
                    print(f"Warning: Voice '{voice_name}' not found in config, using 'main'.")
                    voice_name = "main"
            
            clean_text = re.sub(reg2, "", text_chunk).strip()
            print(f"Generating chunk {i+1} with voice '{voice_name}': '{clean_text[:80]}...'")

            ref_audio_ = voices[voice_name]["ref_audio"]
            ref_text_ = voices[voice_name]["ref_text"]
            
            audio_segment, final_sample_rate, _ = infer_process(
                ref_audio_,
                ref_text_,
                clean_text,
                self.model,
                self.vocoder,
                mel_spec_type=run_config["vocoder_name"],
                target_rms=run_config["target_rms"],
                cross_fade_duration=run_config["cross_fade_duration"],
                nfe_step=run_config["nfe_step"],
                cfg_strength=run_config["cfg_strength"],
                sway_sampling_coef=run_config["sway_sampling_coef"],
                speed=run_config["speed"],
                fix_duration=run_config["fix_duration"],
                device=run_config["device"],
            )
            generated_audio_segments.append(audio_segment)

            if run_config.get("save_chunk"):
                chunk_filename = f"{i}_{voice_name}_{clean_text[:50].replace(' ', '_')}.wav"
                sf.write(output_chunk_dir / chunk_filename, audio_segment, final_sample_rate)

        if not generated_audio_segments:
            print("No audio was generated.")
            return None

        # Сохранение итогового файла
        final_wave = np.concatenate(generated_audio_segments)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        sf.write(output_path, final_wave, final_sample_rate)

        if run_config.get("remove_silence"):
            print(f"Removing silence from {output_path}...")
            remove_silence_for_generated_wav(output_path)
            
        print(f"\n✅ Audio generated successfully and saved to: {os.path.abspath(output_path)}")
        return os.path.abspath(output_path)
