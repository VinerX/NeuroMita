from __future__ import annotations

import os
import hashlib
from datetime import datetime
import asyncio
from typing import Optional, Any, List, Dict

from .base_model import IVoiceModel
from main_logger import logger
from utils import getTranslationVariant as _, get_character_voice_paths

from core.install_types import InstallPlan, InstallAction
from core.install_requirements import InstallRequirement, check_requirements
from handlers.voice_models.install_plan_helpers import torch_install_action, pip_uninstall_action, remove_paths_action

class F5TTSInstallSpec:
    @classmethod
    def supported_model_ids(cls) -> list[str]:
        return ["high", "high+low"]

    @classmethod
    def title(cls, model_id: str) -> str:
        return _("Установка локальной модели: ", "Installing local model: ") + str(model_id)

    @classmethod
    def requirements(cls, model_id: str, ctx: dict) -> list[InstallRequirement]:
        model_dir = os.path.join("checkpoints", "F5-TTS")
        ckpt = os.path.join(model_dir, "model.safetensors")
        vocab = os.path.join(model_dir, "vocab.txt")

        req = [
            InstallRequirement(id="f5_tts", kind="python_dist", spec="f5-tts", required=True),
            InstallRequirement(id="ckpt", kind="file", path=ckpt, required=True),
            InstallRequirement(id="vocab", kind="file", path=vocab, required=True),
        ]

        if str(model_id) == "high+low":
            req.append(InstallRequirement(id="tts_with_rvc", kind="python_dist", spec="tts-with-rvc", required=True))

        return req

    @classmethod
    def is_installed(cls, model_id: str, ctx: dict) -> bool:
        st = check_requirements(cls.requirements(model_id, ctx), ctx=ctx)
        return bool(st.get("ok"))

    @classmethod
    def build_install_plan(cls, model_id: str, ctx: dict) -> InstallPlan:
        mid = str(model_id)
        if cls.is_installed(mid, ctx):
            return InstallPlan(actions=[], already_installed=True, already_installed_status=_("Уже установлено", "Already installed"))

        model_dir = os.path.join("checkpoints", "F5-TTS")
        ckpt_dest = os.path.join(model_dir, "model.safetensors")
        vocab_dest = os.path.join(model_dir, "vocab.txt")

        actions: list[InstallAction] = []
        actions.append(torch_install_action(ctx, progress=10))

        actions.append(
            InstallAction(
                type="pip",
                description=_("Установка F5-TTS...", "Installing F5-TTS..."),
                progress=30,
                packages=["f5-tts", "cached_path", "google-api-core", "numpy==1.26.0", "librosa==0.9.1", "numba==0.60.0"],
            )
        )

        actions.append(
            InstallAction(
                type="pip",
                description=_("Установка RUAccent (опционально)...", "Installing RUAccent (optional)..."),
                progress=40,
                packages=["ruaccent"],
            )
        )

        actions.append(
            InstallAction(
                type="call",
                description=_("Подготовка папок...", "Preparing folders..."),
                progress=50,
                fn=lambda **_k: (os.makedirs(model_dir, exist_ok=True) or True),
            )
        )

        actions.append(
            InstallAction(
                type="download_http",
                description=_("Загрузка весов F5-TTS...", "Downloading F5-TTS weights..."),
                progress=60,
                progress_to=90,
                files=[
                    {
                        "url": "https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN/resolve/main/"
                               "F5TTS_v1_Base/model_240000_inference.safetensors?download=true",
                        "dest": ckpt_dest,
                    },
                    {
                        "url": "https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN/resolve/main/"
                               "F5TTS_v1_Base/vocab.txt?download=true",
                        "dest": vocab_dest,
                    },
                ],
            )
        )

        if mid == "high+low":
            actions.append(
                InstallAction(
                    type="pip",
                    description=_("Установка Edge/RVC компонента...", "Installing Edge/RVC component..."),
                    progress=92,
                    packages=["tts-with-rvc"],
                )
            )

        actions.append(
            InstallAction(
                type="call",
                description=_("Проверка установки...", "Final check..."),
                progress=99,
                fn=lambda **_k: cls.is_installed(mid, ctx),
            )
        )

        return InstallPlan(actions=actions, ok_status=_("Готово", "Done"))

    @classmethod
    def build_uninstall_plan(cls, model_id: str, ctx: dict) -> InstallPlan:
        mid = str(model_id)
        pkgs = ["f5-tts", "ruaccent"]
        if mid == "high+low":
            pkgs = ["tts-with-rvc"] + pkgs

        return InstallPlan(
            actions=[
                pip_uninstall_action(pkgs, description=_("Удаление компонентов...", "Uninstalling components...")),
                remove_paths_action([os.path.join("checkpoints", "F5-TTS")], description=_("Удаление файлов модели...", "Removing model files..."), progress=85),
            ],
            ok_status=_("Удалено", "Uninstalled"),
        )

class F5TTSModel(IVoiceModel):
    def __init__(self, parent: "LocalVoice", model_id: str, rvc_handler: Optional[IVoiceModel] = None):
        super().__init__(parent, model_id)
        self.f5_pipeline_module = None
        self.current_f5_pipeline = None
        self.rvc_handler = rvc_handler
        self.ruaccent_instance = None
        self._import_attempted = False

    MODEL_CONFIGS = [
        {
            "id": "high",
            "name": "F5-TTS",
            "min_vram": 4, "rec_vram": 8,
            "gpu_vendor": ["NVIDIA"],
            "size_gb": 4,
            "languages": ["Russian", "English"],
            "intents": [_("Эмоции", "Emotion"), _("Качество", "Quality")],
            "description": _(
                "Эмоциональная диффузионная модель с высоким качеством. Самая требовательная к GPU.",
                "Emotional diffusion model with high quality. Most GPU‑demanding."
            ),
            "settings": [
                {"key": "speed", "label": _("Скорость речи", "Speech Speed"), "type": "entry", "options": {"default": "1.0"},
                 "help": _("Множитель скорости: 1.0 — нормальная.", "Speed multiplier: 1.0 is normal.")},
                {"key": "nfe_step", "label": _("Шаги диффузии", "Diffusion Steps"), "type": "entry", "options": {"default": "32"},
                 "help": _("Больше шагов — лучше качество, медленнее.", "More steps — better quality, slower.")},
                {"key": "remove_silence", "label": _("Удалять тишину", "Remove Silence"), "type": "checkbutton", "options": {"default": True},
                 "help": _("Обрезать тишину в начале/конце.", "Trim silence at head/tail.")},
                {"key": "seed", "label": _("Seed", "Seed"), "type": "entry", "options": {"default": "0"},
                 "help": _("Инициализация генератора случайности.", "Random seed.")},
                {"key": "volume", "label": _("Громкость (volume)", "Volume"), "type": "entry", "options": {"default": "1.0"},
                 "help": _("Итоговая громкость.", "Final loudness.")},
                {"key": "use_ruaccent", "label": _("Использовать RUAccent", "Use RUAccent"), "type": "checkbutton", "options": {"default": False},
                 "help": _("Улучшение ударений для русского.", "Better Russian stress handling.")}
            ]
        },
        {
            "id": "high+low",
            "name": "F5-TTS + RVC",
            "min_vram": 6, "rec_vram": 8,
            "gpu_vendor": ["NVIDIA"],
            "size_gb": 7,
            "languages": ["Russian", "English"],
            "intents": [_("Эмоции", "Emotion"), _("Конверсия голоса", "Voice conversion")],
            "description": _(
                "F5‑TTS с последующей конверсией тембра через RVC.",
                "F5‑TTS followed by timbre conversion via RVC."
            ),
            "settings": [
                {"key": "f5rvc_f5_device", "label": _("[F5] Устройство", "[F5] Device"), "type": "combobox",
                 "options": {"values": ["cuda", "cpu"], "default": "cuda"},
                 "help": _("Устройство для части F5‑TTS.", "Device for F5‑TTS part.")},
                {"key": "f5rvc_rvc_device", "label": _("[RVC] Устройство RVC", "[RVC] RVC Device"), "type": "combobox",
                 "options": {"values_nvidia": ["dml", "cuda:0", "cpu"], "default_nvidia": "cuda:0",
                             "values_amd": ["dml", "cpu"], "default_amd": "dml",
                             "values_other": ["cpu", "dml"], "default_other": "cpu"},
                 "help": _("Устройство для части RVC.", "Device for RVC part.")},

                {"key": "f5rvc_f5_speed", "label": _("[F5] Скорость речи", "[F5] Speech Speed"), "type": "entry", "options": {"default": "1.0"},
                 "help": _("Множитель скорости F5‑TTS.", "F5‑TTS speed multiplier.")},
                {"key": "f5rvc_f5_nfe_step", "label": _("[F5] Шаги диффузии", "[F5] Diffusion Steps"), "type": "entry", "options": {"default": "32"},
                 "help": _("Больше шагов — лучше качество, медленнее.", "More steps — better quality, slower.")},
                {"key": "f5rvc_f5_seed", "label": _("[F5] Seed", "[F5] Seed"), "type": "entry", "options": {"default": "0"},
                 "help": _("Сид генерации F5‑TTS.", "Seed value for F5‑TTS.")},
                {"key": "f5rvc_f5_remove_silence", "label": _("[F5] Удалять тишину", "[F5] Remove Silence"), "type": "checkbutton", "options": {"default": True},
                 "help": _("Обрезать тишину в начале/конце.", "Trim silence at head/tail.")},

                {"key": "f5rvc_rvc_pitch", "label": _("[RVC] Высота голоса (пт)", "[RVC] Pitch (semitones)"), "type": "entry", "options": {"default": "0"},
                 "help": _("Смещение высоты в полутонах.", "Pitch shift in semitones.")},
                {"key": "f5rvc_index_rate", "label": _("[RVC] Соотн. индекса", "[RVC] Index Rate"), "type": "entry", "options": {"default": "0.75"},
                 "help": _("Степень влияния .index (0..1).", "How much .index affects result (0..1).")},
                {"key": "f5rvc_protect", "label": _("[RVC] Защита согласных", "[RVC] Consonant Protection"), "type": "entry", "options": {"default": "0.33"},
                 "help": _("Защита глухих согласных (0..0.5).", "Protect voiceless consonants (0..0.5).")},
                {"key": "f5rvc_filter_radius", "label": _("[RVC] Радиус фильтра F0", "[RVC] F0 Filter Radius"), "type": "entry", "options": {"default": "3"},
                 "help": _("Сглаживание кривой F0 (рекоменд. ≥3).", "Smooth F0 curve (recommended ≥3).")},
                {"key": "f5rvc_rvc_rms_mix_rate", "label": _("[RVC] Смешивание RMS", "[RVC] RMS Mixing"), "type": "entry", "options": {"default": "0.5"},
                 "help": _("Смешивание громкости исходника и RVC (0..1).", "Mix source loudness and RVC result (0..1).")},
                {"key": "f5rvc_is_half", "label": _("[RVC] Half-precision", "[RVC] Half-precision"), "type": "combobox",
                 "options": {"values": ["True", "False"], "default": "True"},
                 "help": _("FP16 для RVC на совместимых GPU.", "FP16 for RVC on compatible GPUs.")},
                {"key": "f5rvc_f0method", "label": _("[RVC] Метод F0", "[RVC] F0 Method"), "type": "combobox",
                 "options": {"values": ["pm", "rmvpe", "crepe", "harvest", "fcpe", "dio"], "default": "rmvpe"},
                 "help": _("Алгоритм извлечения высоты тона.", "Pitch extraction algorithm.")},
                {"key": "f5rvc_use_index_file", "label": _("[RVC] Исп. .index файл", "[RVC] Use .index file"), "type": "checkbutton", "options": {"default": True},
                 "help": _("Улучшает совпадение тембра.", "Improves timbre matching.")},

                {"key": "volume", "label": _("Громкость (volume)", "Volume"), "type": "entry", "options": {"default": "1.0"},
                 "help": _("Итоговая громкость.", "Final loudness.")},
                {"key": "f5rvc_use_ruaccent", "label": _("Использовать RUAccent", "Use RUAccent"), "type": "checkbutton", "options": {"default": False},
                 "help": _("Улучшение ударений для русского.", "Better Russian stress handling.")}
            ]
        }
    ]

    def get_model_configs(self) -> List[Dict[str, Any]]:
        return self.MODEL_CONFIGS

    def get_display_name(self) -> str:
        mode = self._mode()
        return "F5-TTS + RVC" if mode == "high+low" else "F5-TTS"

    def _load_module(self):
        if self.f5_pipeline_module is not None:
            return
        if self._import_attempted:
            return
        self._import_attempted = True
        try:
            from handlers.voice_models.pipelines.f5_pipeline import F5TTSPipeline
            self.f5_pipeline_module = F5TTSPipeline
        except Exception as ex:
            logger.info(f"F5_TTS import failed: {ex}")
            self.f5_pipeline_module = None

    def is_installed(self, model_id) -> bool:
        self._load_module()
        model_dir = os.path.join("checkpoints", "F5-TTS")
        ckpt_path = os.path.join(model_dir, "model.safetensors")
        vocab_path = os.path.join(model_dir, "vocab.txt")

        if self.f5_pipeline_module is None:
            return False
        if not (os.path.exists(ckpt_path) and os.path.exists(vocab_path)):
            return False

        if str(model_id) == "high+low":
            if self.rvc_handler is None or not self.rvc_handler.is_installed("low"):
                return False

        return True

    def initialize(self, init: bool = False) -> bool:
        mode = self._mode()
        if self.initialized and self.initialized_for == mode:
            return True

        self._load_module()
        if self.f5_pipeline_module is None:
            logger.error("F5 pipeline not available. Install dependencies first.")
            self.initialized = False
            self.initialized_for = None
            return False

        model_dir = os.path.join("checkpoints", "F5-TTS")
        ckpt_path = os.path.join(model_dir, "model.safetensors")
        vocab_path = os.path.join(model_dir, "vocab.txt")

        if not all(os.path.exists(p) for p in [ckpt_path, vocab_path]):
            logger.error(f"Missing F5-TTS model files in {model_dir}.")
            self.initialized = False
            self.initialized_for = None
            return False

        settings = self.parent.load_model_settings(mode)
        device_key = "f5rvc_f5_device" if mode == "high+low" else "device"
        device = settings.get(device_key, "cuda" if self.parent.provider == "NVIDIA" else "cpu")

        self.current_f5_pipeline = self.f5_pipeline_module(
            model="F5TTS_v1_Base",
            ckpt_file=ckpt_path,
            vocab_file=vocab_path,
            device=device,
        )

        if mode == "high+low":
            if self.rvc_handler and not self.rvc_handler.initialized:
                ok = self.rvc_handler.initialize(init=False)
                if not ok:
                    logger.error("Failed to init RVC component for high+low.")
                    self.initialized = False
                    self.initialized_for = None
                    return False

        self.initialized = True
        self.initialized_for = mode
        return True

    def cleanup_state(self):
        super().cleanup_state()
        self.current_f5_pipeline = None
        self.f5_pipeline_module = None
        self.ruaccent_instance = None
        self._import_attempted = False
        try:
            if self.rvc_handler and self.rvc_handler.initialized:
                self.rvc_handler.cleanup_state()
        except Exception:
            pass

    def _load_ruaccent_if_needed(self, settings: dict):
        mode = self._mode()
        use_ruaccent_key = "f5rvc_use_ruaccent" if mode == "high+low" else "use_ruaccent"
        if not settings.get(use_ruaccent_key, False) or self.ruaccent_instance is not None:
            return
        try:
            from ruaccent import RUAccent
            self.ruaccent_instance = RUAccent()
            device = "CUDA" if self.parent.provider == "NVIDIA" else "CPU"
            workdir = os.path.join("checkpoints", "ruaccent_models")
            os.makedirs(workdir, exist_ok=True)
            self.ruaccent_instance.load(
                omograph_model_size='turbo3.1',
                use_dictionary=True,
                device=device,
                workdir=workdir,
                tiny_mode=False
            )
        except Exception as e:
            logger.warning(f"RUAccent init failed: {e}")
            self.ruaccent_instance = None

    def _apply_ruaccent(self, text: str) -> str:
        if self.ruaccent_instance is None:
            return text
        try:
            return self.ruaccent_instance.process_all(text)
        except Exception:
            return text

    async def voiceover(self, text: str, character: Optional[Any] = None, **kwargs) -> Optional[str]:
        if not self.initialized or self.current_f5_pipeline is None:
            raise RuntimeError(f"Model {self.model_id} is not initialized.")

        mode = self._mode()
        settings = self.parent.load_model_settings(mode)
        is_combined_model = mode == "high+low"

        output_file = kwargs.get("output_file")
        if not output_file:
            hash_object = hashlib.sha1(f"{text[:20]}_{datetime.now().timestamp()}".encode())
            output_file = os.path.join("temp", f"f5_out_{hash_object.hexdigest()[:10]}.wav")
        output_file = os.path.abspath(str(output_file))
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

        self._load_ruaccent_if_needed(settings)

        speed_key = "f5rvc_f5_speed" if is_combined_model else "speed"
        remove_silence_key = "f5rvc_f5_remove_silence" if is_combined_model else "remove_silence"
        nfe_step_key = "f5rvc_f5_nfe_step" if is_combined_model else "nfe_step"
        seed_key = "f5rvc_f5_seed" if is_combined_model else "seed"

        voice_paths = get_character_voice_paths(character, self.parent.provider)

        ref_audio_path = None
        ref_text_content = ""

        if os.path.exists(voice_paths.get("f5_voice_filename", "")):
            ref_audio_path = voice_paths["f5_voice_filename"]
            if os.path.exists(voice_paths.get("f5_voice_text", "")):
                with open(voice_paths["f5_voice_text"], "r", encoding="utf-8") as f:
                    ref_text_content = f.read().strip()
        elif os.path.exists(voice_paths.get("clone_voice_filename", "")):
            ref_audio_path = voice_paths["clone_voice_filename"]
            if os.path.exists(voice_paths.get("clone_voice_text", "")):
                with open(voice_paths["clone_voice_text"], "r", encoding="utf-8") as f:
                    ref_text_content = f.read().strip()

        if not ref_audio_path:
            default_paths = get_character_voice_paths(None, self.parent.provider)
            if os.path.exists(default_paths.get("f5_voice_filename", "")):
                ref_audio_path = default_paths["f5_voice_filename"]
                if os.path.exists(default_paths.get("f5_voice_text", "")):
                    with open(default_paths["f5_voice_text"], "r", encoding="utf-8") as f:
                        ref_text_content = f.read().strip()
            elif os.path.exists(default_paths.get("clone_voice_filename", "")):
                ref_audio_path = default_paths["clone_voice_filename"]
                if os.path.exists(default_paths.get("clone_voice_text", "")):
                    with open(default_paths["clone_voice_text"], "r", encoding="utf-8") as f:
                        ref_text_content = f.read().strip()

        if not ref_audio_path:
            raise FileNotFoundError("F5-TTS requires reference audio, but none found.")

        if self.ruaccent_instance is not None:
            text = self._apply_ruaccent(text)
            if ref_text_content:
                ref_text_content = self._apply_ruaccent(ref_text_content)

        seed_processed = int(settings.get(seed_key, 0) or 0)
        if seed_processed <= 0 or seed_processed > 2**31 - 1:
            seed_processed = 42

        vol = str(settings.get("volume", "1.0") or "1.0")

        raw_tmp = os.path.join("temp", f"f5_raw_{hashlib.sha1(output_file.encode()).hexdigest()[:10]}.wav")
        os.makedirs("temp", exist_ok=True)

        await asyncio.to_thread(
            self.current_f5_pipeline.generate,
            text_to_generate=text,
            output_path=raw_tmp,
            ref_audio=ref_audio_path,
            ref_text=ref_text_content,
            speed=float(settings.get(speed_key, 1.0)),
            remove_silence=bool(settings.get(remove_silence_key, True)),
            nfe_step=int(settings.get(nfe_step_key, 32)),
            seed=seed_processed
        )

        if not os.path.exists(raw_tmp) or os.path.getsize(raw_tmp) == 0:
            return None

        stereo_tmp = raw_tmp.replace("_raw_", "_stereo_")
        converted = self.parent.convert_wav_to_stereo(raw_tmp, stereo_tmp, volume=vol)
        produced = stereo_tmp if converted and os.path.exists(converted) else raw_tmp

        # Move result into requested output_file
        try:
            if os.path.abspath(produced) != os.path.abspath(output_file):
                if os.path.exists(output_file):
                    try:
                        os.remove(output_file)
                    except Exception:
                        pass
                os.replace(produced, output_file)
                produced = output_file
        except Exception:
            produced = produced

        # Cleanup leftover temp
        for p in [raw_tmp, stereo_tmp]:
            try:
                if os.path.exists(p) and os.path.abspath(p) != os.path.abspath(produced):
                    os.remove(p)
            except Exception:
                pass

        if mode == "high+low" and self.rvc_handler:
            # If your RVC handler supports apply_rvc_to_file, keep using it as runtime post-process.
            # Installation is handled by InstallController.
            try:
                rvc_output_path = await self.rvc_handler.apply_rvc_to_file(
                    filepath=produced,
                    character=character,
                    pitch=float(settings.get("f5rvc_rvc_pitch", 0)),
                    index_rate=float(settings.get("f5rvc_index_rate", 0.75)),
                    protect=float(settings.get("f5rvc_protect", 0.33)),
                    filter_radius=int(settings.get("f5rvc_filter_radius", 3)),
                    rms_mix_rate=float(settings.get("f5rvc_rvc_rms_mix_rate", 0.5)),
                    is_half=str(settings.get("f5rvc_is_half", "True")).lower() == "true",
                    f0method=settings.get("f5rvc_f0method", None),
                    use_index_file=bool(settings.get("f5rvc_use_index_file", True)),
                    volume=vol
                )
                if rvc_output_path and os.path.exists(rvc_output_path):
                    if os.path.abspath(rvc_output_path) != os.path.abspath(produced):
                        try:
                            os.remove(produced)
                        except Exception:
                            pass
                    produced = rvc_output_path
            except Exception as e:
                logger.warning(f"RVC post-process failed: {e}")

        return produced

    def _mode(self) -> str:
        return self.parent.current_model_id or "high"