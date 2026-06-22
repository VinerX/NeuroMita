from __future__ import annotations

import gc
import os
import re
import sys
import tempfile
import traceback
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from .base_model import IVoiceModel
from core.backends import BackendKind
from core.install_requirements import InstallRequirement, check_requirements
from core.install_types import InstallAction, InstallPlan
from handlers.voice_models.install_plan_helpers import (
    pip_uninstall_action,
    rvc_python_compat_error,
    unsupported_runtime_plan,
)
from main_logger import logger
from utils import getTranslationVariant as _, get_character_voice_paths


EDGE_TTS_RVC_CUDA_ID = "edge_tts_rvc_cuda"
EDGE_TTS_RVC_ONNX_ID = "edge_tts_rvc_onnx"
SILERO_RVC_CUDA_ID = "silero_rvc_cuda"
SILERO_RVC_ONNX_ID = "silero_rvc_onnx"


# Full F0-extractor set. The previous refactor narrowed CUDA to (crepe, fcpe)
# and ONNX to (pm,), which broke parity with how the older single-source
# config exposed methods. Restore the full set for both branches and keep
# rmvpe as the main default — it's the best speed/quality tradeoff on
# both NVIDIA and AMD/Intel paths.
_RVC_F0_METHODS = ("pm", "dio", "crepe", "rmvpe", "harvest", "fcpe")
_RVC_F0_DEFAULT = "rmvpe"
_RVC_F0_HELP_RU = (
    "Алгоритм извлечения F0 (высоты тона): rmvpe/crepe — точнее, "
    "pm/harvest/dio — быстрее, fcpe — компромисс."
)
_RVC_F0_HELP_EN = (
    "F0 extraction algorithm: rmvpe/crepe — more accurate, "
    "pm/harvest/dio — faster, fcpe — middle ground."
)


def _setting_entry(key: str, label_ru: str, label_en: str, default: str, help_ru: str, help_en: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": _(label_ru, label_en),
        "type": "entry",
        "options": {"default": default},
        "help": _(help_ru, help_en),
    }


def _setting_check(key: str, label_ru: str, label_en: str, default: bool, help_ru: str, help_en: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": _(label_ru, label_en),
        "type": "checkbutton",
        "options": {"default": bool(default)},
        "help": _(help_ru, help_en),
    }


def _setting_combo(
    key: str,
    label_ru: str,
    label_en: str,
    values: list[str],
    default: str,
    help_ru: str,
    help_en: str,
    *,
    locked: bool = False,
) -> dict[str, Any]:
    item = {
        "key": key,
        "label": _(label_ru, label_en),
        "type": "combobox",
        "options": {"values": list(values), "default": default},
        "help": _(help_ru, help_en),
    }
    if locked:
        item["locked"] = True
    return item


def _cuda_edge_settings() -> list[dict[str, Any]]:
    return [
        _setting_combo(
            "device",
            "Устройство RVC",
            "RVC Device",
            ["cuda:0", "cpu"],
            "cuda:0",
            "CUDA-устройство для PyTorch/RVC. CPU оставлен как аварийный режим.",
            "CUDA device for PyTorch/RVC. CPU is kept as a fallback.",
        ),
        _setting_combo(
            "is_half",
            "Half-precision RVC",
            "Half-precision RVC",
            ["True", "False"],
            "True",
            "FP16 для NVIDIA: быстрее и экономнее по VRAM на совместимых видеокартах.",
            "FP16 on NVIDIA: faster and lighter on VRAM for compatible GPUs.",
        ),
        _setting_combo(
            "f0method",
            "Метод F0 (RVC)",
            "F0 Method (RVC)",
            list(_RVC_F0_METHODS),
            _RVC_F0_DEFAULT,
            _RVC_F0_HELP_RU,
            _RVC_F0_HELP_EN,
        ),
        _setting_entry("pitch", "Высота голоса RVC (пт)", "RVC Pitch (semitones)", "6", "Смещение высоты в полутонах.", "Pitch shift in semitones."),
        _setting_check("use_index_file", "Исп. .index файл (RVC)", "Use .index file (RVC)", True, "Использовать .index для лучшего совпадения тембра.", "Use .index to better match voice timbre."),
        _setting_entry("index_rate", "Соотношение индекса RVC", "RVC Index Rate", "0.75", "Степень влияния .index (0..1).", "How much .index affects result (0..1)."),
        _setting_entry("protect", "Защита согласных (RVC)", "Consonant Protection (RVC)", "0.33", "Защищает глухие согласные от искажения тоном.", "Protect voiceless consonants from pitch distortion."),
        _setting_entry("tts_rate", "Скорость TTS (%)", "TTS Speed (%)", "0", "Скорость базового Edge-TTS в процентах.", "Base Edge-TTS speed in percent."),
        _setting_entry("filter_radius", "Радиус фильтра F0 (RVC)", "F0 Filter Radius (RVC)", "3", "Сглаживание кривой F0.", "Smooth F0 curve."),
        _setting_entry("rms_mix_rate", "Смешивание RMS (RVC)", "RMS Mixing (RVC)", "0.5", "Смешивание громкости исходника и RVC.", "Mix source loudness and RVC result."),
        _setting_entry("volume", "Громкость (volume)", "Volume", "1.0", "Итоговая громкость.", "Final loudness."),
    ]


def _onnx_edge_settings() -> list[dict[str, Any]]:
    return [
        _setting_combo(
            "device",
            "Устройство RVC",
            "RVC Device",
            ["dml", "cpu"],
            "dml",
            "DirectML для AMD/Intel или CPU fallback.",
            "DirectML for AMD/Intel or CPU fallback.",
        ),
        _setting_combo(
            "f0method",
            "Метод F0 (RVC)",
            "F0 Method (RVC)",
            list(_RVC_F0_METHODS),
            _RVC_F0_DEFAULT,
            _RVC_F0_HELP_RU,
            _RVC_F0_HELP_EN,
        ),
        _setting_entry("pitch", "Высота голоса RVC (пт)", "RVC Pitch (semitones)", "6", "Смещение высоты в полутонах.", "Pitch shift in semitones."),
        _setting_check("use_index_file", "Исп. .index файл (RVC)", "Use .index file (RVC)", True, "Использовать .index для лучшего совпадения тембра.", "Use .index to better match voice timbre."),
        _setting_entry("index_rate", "Соотношение индекса RVC", "RVC Index Rate", "0.75", "Степень влияния .index (0..1).", "How much .index affects result (0..1)."),
        _setting_entry("protect", "Защита согласных (RVC)", "Consonant Protection (RVC)", "0.33", "Защита глухих согласных (0..0.5).", "Protect voiceless consonants (0..0.5)."),
        _setting_entry("tts_rate", "Скорость TTS (%)", "TTS Speed (%)", "0", "Скорость базового Edge-TTS в процентах.", "Base Edge-TTS speed in percent."),
        _setting_entry("volume", "Громкость (volume)", "Volume", "1.0", "Итоговая громкость.", "Final loudness."),
    ]


def _cuda_silero_settings() -> list[dict[str, Any]]:
    return [
        _setting_combo("silero_rvc_device", "Устройство RVC", "RVC Device", ["cuda:0", "cpu"], "cuda:0", "CUDA-устройство для RVC.", "CUDA device for RVC."),
        _setting_combo("silero_device", "Устройство Silero", "Silero Device", ["cuda", "cpu"], "cuda", "Устройство для Silero.", "Device for Silero."),
        _setting_combo("silero_rvc_is_half", "Half-precision RVC", "Half-precision RVC", ["True", "False"], "True", "FP16 для RVC на NVIDIA.", "FP16 for RVC on NVIDIA."),
        _setting_combo(
            "silero_rvc_f0method",
            "Метод F0 (RVC)",
            "F0 Method (RVC)",
            list(_RVC_F0_METHODS),
            _RVC_F0_DEFAULT,
            _RVC_F0_HELP_RU,
            _RVC_F0_HELP_EN,
        ),
        _setting_entry("silero_rvc_pitch", "Высота голоса RVC (пт)", "RVC Pitch (semitones)", "6", "Смещение высоты в полутонах.", "Pitch shift in semitones."),
        _setting_check("silero_rvc_use_index_file", "Исп. .index файл (RVC)", "Use .index file (RVC)", True, "Улучшает совпадение тембра.", "Improves timbre matching."),
        _setting_entry("silero_rvc_index_rate", "Соотношение индекса RVC", "RVC Index Rate", "0.75", "Степень влияния .index (0..1).", "How much .index affects result (0..1)."),
        _setting_entry("silero_rvc_protect", "Защита согласных (RVC)", "Consonant Protection (RVC)", "0.33", "Защита глухих согласных (0..0.5).", "Protect voiceless consonants (0..0.5)."),
        _setting_entry("silero_rvc_filter_radius", "Радиус фильтра F0 (RVC)", "F0 Filter Radius (RVC)", "3", "Сглаживание кривой F0.", "Smooth F0 curve."),
        _setting_entry("silero_rvc_rms_mix_rate", "Смешивание RMS (RVC)", "RMS Mixing (RVC)", "0.5", "Смешивание громкости исходника и RVC.", "Mix source loudness and RVC result."),
        _setting_combo("silero_sample_rate", "Частота Silero", "Silero Sample Rate", ["48000", "24000", "16000"], "48000", "Частота дискретизации синтеза Silero.", "Silero synthesis sample rate."),
        _setting_check("silero_put_accent", "Акценты Silero", "Silero Accents", True, "Авторасстановка ударений.", "Automatic stress placement."),
        _setting_check("silero_put_yo", "Буква Ё Silero", "Silero Letter Yo", True, "Автозамена е на ё по словарю.", "Auto replace e with yo."),
        _setting_entry("volume", "Громкость (volume)", "Volume", "1.0", "Итоговая громкость.", "Final loudness."),
    ]


def _onnx_silero_settings() -> list[dict[str, Any]]:
    return [
        _setting_combo("silero_rvc_device", "Устройство RVC", "RVC Device", ["dml", "cpu"], "dml", "DirectML для RVC или CPU fallback.", "DirectML for RVC or CPU fallback."),
        _setting_combo("silero_device", "Устройство Silero", "Silero Device", ["cpu"], "cpu", "Silero в ONNX-сборке запускается на CPU для стабильности.", "Silero runs on CPU in the ONNX build for stability.", locked=True),
        _setting_combo(
            "silero_rvc_f0method",
            "Метод F0 (RVC)",
            "F0 Method (RVC)",
            list(_RVC_F0_METHODS),
            _RVC_F0_DEFAULT,
            _RVC_F0_HELP_RU,
            _RVC_F0_HELP_EN,
        ),
        _setting_entry("silero_rvc_pitch", "Высота голоса RVC (пт)", "RVC Pitch (semitones)", "6", "Смещение высоты в полутонах.", "Pitch shift in semitones."),
        _setting_check("silero_rvc_use_index_file", "Исп. .index файл (RVC)", "Use .index file (RVC)", True, "Улучшает совпадение тембра.", "Improves timbre matching."),
        _setting_entry("silero_rvc_index_rate", "Соотношение индекса RVC", "RVC Index Rate", "0.75", "Степень влияния .index (0..1).", "How much .index affects result (0..1)."),
        _setting_entry("silero_rvc_protect", "Защита согласных (RVC)", "Consonant Protection (RVC)", "0.33", "Защита глухих согласных (0..0.5).", "Protect voiceless consonants (0..0.5)."),
        _setting_combo("silero_sample_rate", "Частота Silero", "Silero Sample Rate", ["48000", "24000", "16000"], "48000", "Частота дискретизации синтеза Silero.", "Silero synthesis sample rate."),
        _setting_check("silero_put_accent", "Акценты Silero", "Silero Accents", True, "Авторасстановка ударений.", "Automatic stress placement."),
        _setting_check("silero_put_yo", "Буква Ё Silero", "Silero Letter Yo", True, "Автозамена е на ё по словарю.", "Auto replace e with yo."),
        _setting_entry("volume", "Громкость (volume)", "Volume", "1.0", "Итоговая громкость.", "Final loudness."),
    ]


def _ensure_lib_path() -> None:
    libs_path_abs = os.environ.get("NEUROMITA_LIB_DIR", os.path.abspath("Lib"))
    if libs_path_abs not in sys.path:
        sys.path.insert(0, libs_path_abs)


class EdgeTTSRVCBaseModel(IVoiceModel):
    BACKEND_KIND = BackendKind.NONE
    RVC_PACKAGE = ""
    RVC_UNINSTALL_PACKAGES: tuple[str, ...] = ()
    MODEL_EXTENSION = "pth"
    VOICE_PATH_PROVIDER = "NVIDIA"
    RVC_DEFAULT_DEVICE = "cpu"
    RVC_DEFAULT_F0_METHOD = "pm"
    RVC_F0_METHODS: tuple[str, ...] = ()
    RVC_HELPER_MODEL_ID = ""
    SUPPORTS_HALF = False
    SUPPORTS_RUNTIME_F0 = False
    PATCH_FAIRSEQ_CONFIGS = False

    EDGE_MODEL_ID = ""
    SILERO_MODEL_ID = ""

    def __init__(self, parent: "LocalVoice", model_id: str):
        super().__init__(parent, model_id)
        self.tts_rvc_module = None
        self.current_tts_rvc = None
        self.current_silero_model = None
        self.current_silero_sample_rate = 48000

    @classmethod
    def _pipeline_for_model(cls, model_id: str) -> str:
        return str(cls._find_model_config(model_id).get("pipeline") or "").strip()

    @classmethod
    def _is_silero_model(cls, model_id: str) -> bool:
        return cls._pipeline_for_model(model_id) == "silero"

    @classmethod
    def required_backend_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> BackendKind:
        return cls.BACKEND_KIND

    @classmethod
    def requirements(cls, model_id: str, ctx: dict) -> list[InstallRequirement]:
        req: list[InstallRequirement] = [
            InstallRequirement(id=f"backend_{cls.BACKEND_KIND.value}", kind="backend", backend_kind=cls.BACKEND_KIND, required=True),
            InstallRequirement(id="omegaconf", kind="python_dist", spec="omegaconf", required=True),
            InstallRequirement(id="tts_rvc_pkg", kind="python_dist", spec=cls.RVC_PACKAGE, required=True),
        ]
        if cls._is_silero_model(model_id):
            req.append(InstallRequirement(id="silero", kind="python_dist", spec="silero", required=True))
        return req

    @classmethod
    def is_model_installed(cls, model_id: str, ctx: Dict[str, Any]) -> bool:
        st = check_requirements(cls.requirements(model_id, ctx), ctx=ctx)
        return bool(st.get("ok"))

    @classmethod
    def _patch_fairseq_configs_call(cls):
        def _fn(*, pip_installer=None, callbacks=None, ctx=None, **_kwargs) -> bool:
            libs_path_abs = getattr(pip_installer, "libs_path_abs", None) if pip_installer else None
            libs_path_abs = str(libs_path_abs or os.environ.get("NEUROMITA_LIB_DIR", os.path.abspath("Lib")))
            config_path = os.path.join(libs_path_abs, "fairseq", "dataclass", "configs.py")

            def log(message: str) -> None:
                try:
                    if callbacks:
                        callbacks.log(str(message))
                except Exception:
                    pass

            if not os.path.exists(config_path):
                log(_("fairseq/dataclass/configs.py не найден, патч пропущен", "fairseq/dataclass/configs.py not found, patch skipped"))
                return True

            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    source = f.read()
                patched = re.sub(r"metadata=\{(.*?)help:", r'metadata={\1"help":', source)
                if patched != source:
                    with open(config_path, "w", encoding="utf-8") as f:
                        f.write(patched)
                    log(_("Патч fairseq/dataclass/configs.py применён", "fairseq/dataclass/configs.py patched"))
                return True
            except Exception as exc:
                log(str(exc))
                log(traceback.format_exc())
                return False

        return _fn

    @classmethod
    def build_install_plan_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> InstallPlan:
        mid = str(model_id)
        compat_error = rvc_python_compat_error(cls.RVC_PACKAGE)
        if compat_error:
            return unsupported_runtime_plan(compat_error)
        if cls.is_model_installed(mid, ctx):
            return InstallPlan(
                actions=[],
                already_installed=True,
                required_backend=cls.BACKEND_KIND,
                backend_context=dict(ctx),
                already_installed_status=_("Уже установлено", "Already installed"),
            )

        pkgs = ["omegaconf", cls.RVC_PACKAGE]
        if cls._is_silero_model(mid):
            pkgs.append("silero")

        actions: list[InstallAction] = [
            InstallAction(
                type="pip",
                description=_("Установка зависимостей TTS/RVC...", "Installing TTS/RVC dependencies..."),
                progress=60,
                packages=pkgs,
            )
        ]
        if cls.PATCH_FAIRSEQ_CONFIGS:
            actions.append(
                InstallAction(
                    type="call",
                    description=_("Применение совместимости fairseq...", "Applying fairseq compatibility patch..."),
                    progress=90,
                    fn=cls._patch_fairseq_configs_call(),
                )
            )
        actions.append(
            InstallAction(
                type="call",
                description=_("Проверка установки...", "Final check..."),
                progress=99,
                fn=lambda **_k: cls.is_model_installed(mid, ctx),
            )
        )
        return InstallPlan(actions=actions, ok_status=_("Готово", "Done"), required_backend=cls.BACKEND_KIND, backend_context=dict(ctx))

    @classmethod
    def build_uninstall_plan_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> InstallPlan:
        return InstallPlan(
            actions=[
                pip_uninstall_action(
                    list(cls.RVC_UNINSTALL_PACKAGES),
                    description=_("Удаление компонентов RVC...", "Uninstalling RVC components..."),
                    progress=20,
                )
            ],
            ok_status=_("Удалено", "Uninstalled"),
        )

    def _load_rvc_class(self):
        raise NotImplementedError

    def _set_rvc_model_path(self, model_path: str) -> None:
        self.current_tts_rvc.current_model = model_path

    def _apply_backend_sampling_policy(self) -> None:
        return

    def get_display_name(self) -> str:
        return "Edge-TTS/Silero + RVC"

    def get_model_configs(self) -> List[Dict[str, Any]]:
        return self.MODEL_CONFIGS

    def cleanup_state(self):
        super().cleanup_state()
        self.current_tts_rvc = None
        self.current_silero_model = None
        self.tts_rvc_module = None
        logger.info(f"State reset for {self.__class__.__name__}.")

    def _runtime_model_id(self, mode: str) -> str:
        if mode in self.supported_model_ids():
            return mode
        return self.RVC_HELPER_MODEL_ID

    def _runtime_pipeline(self, mode: str) -> str:
        return self._pipeline_for_model(self._runtime_model_id(mode))

    def _settings_keys(self, mode: str) -> tuple[str, str]:
        if mode == "medium+low":
            return "fsprvc_rvc_device", "fsprvc_f0method"
        if mode == "high+low":
            return "f5rvc_rvc_device", "f5rvc_f0method"
        if self._runtime_pipeline(mode) == "silero":
            return "silero_rvc_device", "silero_rvc_f0method"
        return "device", "f0method"

    def _load_settings_for(self, model_id: str) -> dict[str, Any]:
        settings = self.parent.load_model_settings(model_id)
        if settings:
            return settings
        legacy = {"edge": "low", "silero": "low+"}.get(self._runtime_pipeline(model_id))
        if legacy:
            return self.parent.load_model_settings(legacy)
        return {}

    def _normalize_f0_method(self, value: Optional[str]) -> str:
        method = str(value or self.RVC_DEFAULT_F0_METHOD).strip() or self.RVC_DEFAULT_F0_METHOD
        if self.RVC_F0_METHODS and method not in self.RVC_F0_METHODS:
            return self.RVC_DEFAULT_F0_METHOD
        return method

    def initialize(self, init: bool = False) -> bool:
        current_mode = str(self.parent.current_model_id or "").strip()
        runtime_mode = self._runtime_model_id(current_mode)
        if self.initialized and self.initialized_for == current_mode:
            return True

        logger.info(f"Initializing {self.__class__.__name__} for mode='{current_mode}', runtime='{runtime_mode}'")

        try:
            if self.tts_rvc_module is None:
                self.tts_rvc_module = self._load_rvc_class()

            if self.current_tts_rvc is not None and self.initialized_for != current_mode:
                self.current_tts_rvc = None

            if self.current_tts_rvc is None:
                settings = self._load_settings_for(current_mode)
                device_key, f0_key = self._settings_keys(current_mode)
                device = str(settings.get(device_key, self.RVC_DEFAULT_DEVICE) or self.RVC_DEFAULT_DEVICE)
                f0_method = self._normalize_f0_method(settings.get(f0_key, self.RVC_DEFAULT_F0_METHOD))
                model_path_to_use = self._default_model_path()

                parent_model_path = getattr(self.parent, "pth_path", None)
                parent_ext = os.path.splitext(str(parent_model_path or ""))[1].lower().lstrip(".")
                if parent_model_path and parent_ext == self.MODEL_EXTENSION and os.path.exists(parent_model_path):
                    model_path_to_use = parent_model_path

                if not os.path.exists(model_path_to_use):
                    logger.error(f"RVC model file not found: {model_path_to_use}")
                    self.initialized = False
                    self.initialized_for = None
                    return False

                self.current_tts_rvc = self.tts_rvc_module(model_path=model_path_to_use, device=device, f0_method=f0_method)
                self._apply_backend_sampling_policy()
                logger.info(f"RVC initialized with device={device}, f0_method={f0_method}")

            self._set_edge_voice()

            if self._runtime_pipeline(current_mode) == "silero":
                self._ensure_silero_model(current_mode)
            elif self.current_silero_model is not None:
                self.current_silero_model = None
                gc.collect()

            self.initialized = True
            self.initialized_for = current_mode
            return True
        except Exception as exc:
            logger.error(f"Failed to initialize {self.__class__.__name__}: {exc}", exc_info=True)
            self.initialized = False
            self.initialized_for = None
            return False

    def _default_model_path(self) -> str:
        # Base model for RVC init when the character's own model isn't available.
        # Pick any installed voice (preferring Mila) instead of hard-requiring
        # Mila, which may not be installed under per-voice downloads.
        from utils import default_installed_voice

        models_dir = os.environ.get("NEUROMITA_MODELS_DIR", os.path.abspath("Models"))
        name = default_installed_voice(models_dir, ext=self.MODEL_EXTENSION)
        return os.path.join(models_dir, f"{name}.{self.MODEL_EXTENSION}")

    def _set_edge_voice(self) -> None:
        if self.parent.voice_language == "ru":
            self.current_tts_rvc.set_voice("ru-RU-SvetlanaNeural")
        else:
            self.current_tts_rvc.set_voice("en-US-MichelleNeural")

    def _ensure_silero_model(self, mode: str) -> None:
        if self.current_silero_model is not None:
            return
        _ensure_lib_path()
        from silero import silero_tts

        settings = self._load_settings_for(mode)
        silero_device = str(settings.get("silero_device", "cpu") or "cpu")
        self.current_silero_sample_rate = int(settings.get("silero_sample_rate", 48000))
        language = "en" if self.parent.voice_language == "en" else "ru"
        model_id_silero = "v3_en" if language == "en" else "v5_ru"
        model, _ = silero_tts(language=language, speaker=model_id_silero)
        model.to(silero_device)
        self.current_silero_model = model
        logger.info(f"Silero initialized on {silero_device}.")

    def _maybe_move_to_output(self, produced_path: Optional[str], output_file: Optional[str]) -> Optional[str]:
        if not produced_path or not os.path.exists(produced_path) or not output_file:
            return produced_path
        out = os.path.abspath(str(output_file))
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        try:
            if os.path.abspath(produced_path) == out:
                return produced_path
            if os.path.exists(out):
                try:
                    os.remove(out)
                except Exception:
                    pass
            os.replace(produced_path, out)
            return out
        except Exception:
            return produced_path

    def _update_parent_paths(self, character=None):
        voice_paths = get_character_voice_paths(character, self.VOICE_PATH_PROVIDER)
        self.parent.pth_path = voice_paths["pth_path"]
        self.parent.index_path = voice_paths["index_path"]
        self.parent.clone_voice_filename = voice_paths["clone_voice_filename"]
        self.parent.clone_voice_text = voice_paths["clone_voice_text"]
        self.parent.current_character_name = voice_paths["character_name"]
        return voice_paths

    def _preprocess_text_to_ssml(self, text: str, character_name: str):
        lang = self.parent.voice_language
        defaults = {"en": {"pitch": 6, "speaker": "en_88"}, "ru": {"pitch": 2, "speaker": "kseniya"}}
        lang_defaults = defaults.get(lang, defaults["en"])
        char_params = {
            "en": {
                "CappieMita": (6, "en_26"), "CrazyMita": (6, "en_60"), "GhostMita": (6, "en_33"),
                "Mila": (6, "en_88"), "MitaKind": (3, "en_33"), "ShorthairMita": (6, "en_60"),
                "SleepyMita": (6, "en_33"), "TinyMita": (2, "en_60"), "Player": (0, "en_27"),
            },
            "ru": {
                "CappieMita": (6, "kseniya"), "MitaKind": (1, "kseniya"), "ShorthairMita": (2, "kseniya"),
                "CrazyMita": (2, "kseniya"), "Mila": (2, "kseniya"), "TinyMita": (-3, "baya"),
                "SleepyMita": (2, "baya"), "GhostMita": (1, "baya"), "Player": (0, "aidar"),
            },
        }
        character_rvc_pitch, character_speaker = lang_defaults["pitch"], lang_defaults["speaker"]
        current_lang_params = char_params.get(lang, char_params["en"])
        if specific_params := current_lang_params.get(character_name):
            character_rvc_pitch, character_speaker = specific_params

        text = escape(re.sub(r"<[^>]*>", "", text))
        pattern = re.compile(r"\b([MmМм])([IiИи])([A-Za-zА-Яа-я]{2,3})\b", re.IGNORECASE)
        text = pattern.sub(lambda match: f"{match.group(1)}+{match.group(2)}{match.group(3)}", text)

        parts = re.split(r"([.!?]+[^A-Za-zА-Яа-я0-9_]*)(\s+)", text.strip())
        processed_text = ""
        i = 0
        while i < len(parts):
            if text_part := parts[i]:
                processed_text += text_part
            if i + 2 < len(parts):
                if punctuation_part := parts[i + 1]:
                    processed_text += punctuation_part
                if (whitespace_part := parts[i + 2]) and i + 3 < len(parts) and parts[i + 3]:
                    processed_text += ' <break time="300ms"/> '
                elif whitespace_part:
                    processed_text += whitespace_part
            i += 3

        ssml_content = processed_text.strip()
        ssml_output = f"<speak><p>{ssml_content}</p></speak>" if ssml_content else "<speak></speak>"
        return ssml_output, character_rvc_pitch, character_speaker

    def _rvc_params(
        self,
        *,
        pitch: float,
        index_rate: float,
        protect: float,
        filter_radius: int,
        rms_mix_rate: float,
        is_half: bool,
        f0method: Optional[str],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "pitch": pitch,
            "index_rate": index_rate,
            "protect": protect,
            "filter_radius": filter_radius,
            "rms_mix_rate": rms_mix_rate,
        }
        if self.SUPPORTS_HALF:
            params["is_half"] = bool(is_half)
        if self.SUPPORTS_RUNTIME_F0 and f0method:
            params["f0method"] = self._normalize_f0_method(f0method)
        return params

    def _convert_to_stereo(self, output_file_rvc: str, volume: str) -> str:
        stereo_output_file = output_file_rvc.replace(".wav", "_stereo.wav")
        converted_file = self.parent.convert_wav_to_stereo(output_file_rvc, stereo_output_file, atempo=1.0, volume=volume)
        if converted_file and os.path.exists(converted_file):
            try:
                os.remove(output_file_rvc)
            except OSError:
                pass
            return stereo_output_file
        return output_file_rvc

    def _prepare_rvc_target(self, character: Optional[Any], use_index_file: bool) -> None:
        voice_paths = self._update_parent_paths(character)
        model_path = voice_paths["pth_path"]
        index_path = voice_paths["index_path"]

        if use_index_file and index_path and os.path.exists(index_path):
            self.current_tts_rvc.set_index_path(index_path)
        else:
            self.current_tts_rvc.set_index_path("")

        self._apply_backend_sampling_policy()

        current_model = str(getattr(self.current_tts_rvc, "current_model", "") or "")
        if os.path.abspath(model_path) != os.path.abspath(current_model):
            self._set_rvc_model_path(model_path)
            logger.info(f"RVC model switched to: {model_path}")

    async def voiceover(self, text: str, character: Optional[Any] = None, **kwargs) -> Optional[str]:
        current_mode = str(self.parent.current_model_id or "").strip()
        if current_mode not in self.supported_model_ids():
            raise ValueError(f"Unsupported mode for {self.__class__.__name__}: {current_mode}")
        if not self.initialized or self.initialized_for != current_mode:
            raise Exception(f"Handler is not initialized for mode '{current_mode}'.")

        voice_paths = self._update_parent_paths(character)
        # Voice asset gate: RVC needs this character's trained model. If the
        # bundle isn't installed, skip cleanly (no audio for this Mita) instead
        # of wasting a TTS synthesis and then blowing up inside RVC.
        pth = voice_paths.get("pth_path")
        if not pth or not os.path.exists(pth):
            name = voice_paths.get("character_name") or "?"
            logger.warning(
                f"Voice asset for '{name}' is not installed ({pth}) — "
                f"skipping voiceover; this character will have no audio."
            )
            return None
        if self._pipeline_for_model(current_mode) == "edge":
            return await self._voiceover_edge_tts_rvc(
                text,
                character,
                output_file=kwargs.get("output_file"),
                settings_model_id=kwargs.get("settings_model_id"),
                TEST_WITH_DONE_AUDIO=kwargs.get("TEST_WITH_DONE_AUDIO"),
            )
        return await self._voiceover_silero_rvc(text, character, output_file=kwargs.get("output_file"))

    async def apply_rvc_to_file(
        self,
        filepath: str,
        character: Optional[Any] = None,
        pitch: float = 0,
        index_rate: float = 0.75,
        protect: float = 0.33,
        filter_radius: int = 3,
        rms_mix_rate: float = 0.5,
        is_half: bool = True,
        f0method: Optional[str] = None,
        use_index_file: bool = True,
        volume: str = "1.0",
        original_model_id: Optional[str] = None,
    ) -> Optional[str]:
        current_mode = str(getattr(self.parent, "current_model_id", "") or "").strip()
        if not self.initialized or self.initialized_for != current_mode:
            if self.initialized:
                self.cleanup_state()
            if not self.initialize(init=False):
                return None

        try:
            self._prepare_rvc_target(character, use_index_file)
            inference_params = self._rvc_params(
                pitch=pitch,
                index_rate=index_rate,
                protect=protect,
                filter_radius=filter_radius,
                rms_mix_rate=rms_mix_rate,
                is_half=is_half,
                f0method=f0method,
            )
            output_file_rvc = self.current_tts_rvc.voiceover_file(input_path=filepath, **inference_params)
            if not output_file_rvc or not os.path.exists(output_file_rvc) or os.path.getsize(output_file_rvc) == 0:
                return None
            return self._convert_to_stereo(output_file_rvc, volume)
        except Exception as error:
            traceback.print_exc()
            logger.info(f"RVC file conversion failed: {error}")
            return None

    async def _voiceover_edge_tts_rvc(
        self,
        text,
        character=None,
        TEST_WITH_DONE_AUDIO: str = None,
        settings_model_id: Optional[str] = None,
        output_file: Optional[str] = None,
    ):
        if self.current_tts_rvc is None:
            raise Exception("RVC component is not initialized.")
        try:
            config_id = settings_model_id if settings_model_id else self.parent.current_model_id
            settings = self._load_settings_for(str(config_id))
            voice_paths = self._update_parent_paths(character)
            character_name = voice_paths["character_name"]

            pitch = float(settings.get("pitch", 0))
            if character_name == "Player" and config_id != "medium+low":
                pitch = -12

            use_index_file = settings.get("use_index_file", True)
            self._prepare_rvc_target(character, use_index_file)

            inference_params = self._rvc_params(
                pitch=pitch,
                index_rate=float(settings.get("index_rate", 0.75)),
                protect=float(settings.get("protect", 0.33)),
                filter_radius=int(settings.get("filter_radius", 3)),
                rms_mix_rate=float(settings.get("rms_mix_rate", 0.5)),
                is_half=str(settings.get("is_half", "True")).lower() == "true",
                f0method=settings.get("f0method", None),
            )

            if not TEST_WITH_DONE_AUDIO:
                inference_params["tts_rate"] = int(settings.get("tts_rate", 0)) if config_id != "medium+low" else 0
                output_file_rvc = self.current_tts_rvc(text=text, **inference_params)
            else:
                output_file_rvc = self.current_tts_rvc.voiceover_file(input_path=TEST_WITH_DONE_AUDIO, **inference_params)

            if not output_file_rvc or not os.path.exists(output_file_rvc) or os.path.getsize(output_file_rvc) == 0:
                return None
            final_output_path = self._convert_to_stereo(output_file_rvc, str(settings.get("volume", "1.0")))
            return self._maybe_move_to_output(final_output_path, output_file)
        except Exception as error:
            traceback.print_exc()
            logger.info(f"Edge-TTS + RVC voiceover failed: {error}")
            return None

    async def _voiceover_silero_rvc(self, text, character=None, output_file: Optional[str] = None):
        if self.current_silero_model is None or self.current_tts_rvc is None:
            raise Exception("Silero or RVC component is not initialized.")

        self.parent.current_character = character if character is not None else getattr(self.parent, "current_character", None)
        temp_wav = None
        try:
            voice_paths = self._update_parent_paths(character)
            character_name = voice_paths["character_name"]
            ssml_text, character_base_rvc_pitch, character_speaker = self._preprocess_text_to_ssml(text, character_name)
            settings = self._load_settings_for(str(self.parent.current_model_id))

            audio_tensor = self.current_silero_model.apply_tts(
                ssml_text=ssml_text,
                speaker=character_speaker,
                sample_rate=self.current_silero_sample_rate,
                put_accent=settings.get("silero_put_accent", True),
                put_yo=settings.get("silero_put_yo", True),
                put_stress_homo=settings.get("silero_put_accent", True),
                put_yo_homo=settings.get("silero_put_yo", True),
            )

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav_file:
                temp_wav = temp_wav_file.name
            import soundfile as sf

            sf.write(temp_wav, audio_tensor.cpu().numpy(), self.current_silero_sample_rate)
            if not os.path.exists(temp_wav) or os.path.getsize(temp_wav) == 0:
                return None

            base_rvc_pitch_from_settings = float(settings.get("silero_rvc_pitch", 6))
            final_rvc_pitch = base_rvc_pitch_from_settings - (6 - character_base_rvc_pitch)
            final_output_path = await self.apply_rvc_to_file(
                filepath=temp_wav,
                character=character,
                pitch=final_rvc_pitch,
                index_rate=float(settings.get("silero_rvc_index_rate", 0.75)),
                protect=float(settings.get("silero_rvc_protect", 0.33)),
                filter_radius=int(settings.get("silero_rvc_filter_radius", 3)),
                rms_mix_rate=float(settings.get("silero_rvc_rms_mix_rate", 0.5)),
                is_half=str(settings.get("silero_rvc_is_half", "True")).lower() == "true",
                f0method=settings.get("silero_rvc_f0method", None),
                use_index_file=settings.get("silero_rvc_use_index_file", True),
                volume=str(settings.get("volume", "1.0")),
            )
            return self._maybe_move_to_output(final_output_path, output_file)
        except Exception as error:
            traceback.print_exc()
            logger.info(f"Silero + RVC voiceover failed: {error}")
            return None
        finally:
            if temp_wav and os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except OSError:
                    pass


class EdgeTTSRVCCudaModel(EdgeTTSRVCBaseModel):
    BACKEND_KIND = BackendKind.CUDA
    RVC_PACKAGE = "tts-with-rvc"
    RVC_UNINSTALL_PACKAGES = ("tts-with-rvc",)
    MODEL_EXTENSION = "pth"
    VOICE_PATH_PROVIDER = "NVIDIA"
    RVC_DEFAULT_DEVICE = "cuda:0"
    RVC_DEFAULT_F0_METHOD = _RVC_F0_DEFAULT
    RVC_F0_METHODS = _RVC_F0_METHODS
    RVC_HELPER_MODEL_ID = EDGE_TTS_RVC_CUDA_ID
    SUPPORTS_HALF = True
    SUPPORTS_RUNTIME_F0 = True
    PATCH_FAIRSEQ_CONFIGS = True

    EDGE_MODEL_ID = EDGE_TTS_RVC_CUDA_ID
    SILERO_MODEL_ID = SILERO_RVC_CUDA_ID

    MODEL_CONFIGS = [
        {
            "id": EDGE_TTS_RVC_CUDA_ID,
            "pipeline": "edge",
            "name": "Edge-TTS + RVC (CUDA)",
            "min_vram": 3,
            "rec_vram": 4,
            "gpu_vendor": ["NVIDIA"],
            "size_gb": 3,
            "languages": ["Russian", "English"],
            "intents": [_("CUDA", "CUDA"), _("Быстро", "Fast"), _("FP16", "FP16")],
            "description": _("Edge-TTS с RVC через PyTorch/CUDA. Подходит для NVIDIA и поддерживает fp16.", "Edge-TTS with RVC via PyTorch/CUDA. Built for NVIDIA and supports fp16."),
            "settings": _cuda_edge_settings(),
        },
        {
            "id": SILERO_RVC_CUDA_ID,
            "pipeline": "silero",
            "name": "Silero + RVC (CUDA)",
            "min_vram": 3,
            "rec_vram": 4,
            "gpu_vendor": ["NVIDIA"],
            "size_gb": 3,
            "languages": ["Russian", "English"],
            "intents": [_("CUDA", "CUDA"), _("Локальный синтез", "Offline synth"), _("FP16", "FP16")],
            "description": _("Silero генерирует речь локально, RVC работает через PyTorch/CUDA.", "Silero generates speech locally, RVC runs through PyTorch/CUDA."),
            "settings": _cuda_silero_settings(),
        },
    ]

    def _load_rvc_class(self):
        _ensure_lib_path()
        from tts_with_rvc import TTS_RVC

        return TTS_RVC


class EdgeTTSRVCOnnxModel(EdgeTTSRVCBaseModel):
    BACKEND_KIND = BackendKind.ONNX
    RVC_PACKAGE = "tts-with-rvc-onnx[dml]"
    RVC_UNINSTALL_PACKAGES = ("tts-with-rvc-onnx",)
    MODEL_EXTENSION = "onnx"
    VOICE_PATH_PROVIDER = "AMD"
    RVC_DEFAULT_DEVICE = "dml"
    RVC_DEFAULT_F0_METHOD = _RVC_F0_DEFAULT
    RVC_F0_METHODS = _RVC_F0_METHODS
    RVC_HELPER_MODEL_ID = EDGE_TTS_RVC_ONNX_ID
    SUPPORTS_HALF = False
    SUPPORTS_RUNTIME_F0 = True
    PATCH_FAIRSEQ_CONFIGS = False

    EDGE_MODEL_ID = EDGE_TTS_RVC_ONNX_ID
    SILERO_MODEL_ID = SILERO_RVC_ONNX_ID

    MODEL_CONFIGS = [
        {
            "id": EDGE_TTS_RVC_ONNX_ID,
            "pipeline": "edge",
            "name": "Edge-TTS + RVC (ONNX)",
            "min_vram": 3,
            "rec_vram": 4,
            "gpu_vendor": ["AMD", "CPU"],
            "size_gb": 3,
            "languages": ["Russian", "English"],
            "intents": [_("ONNX", "ONNX"), _("Стабильно", "Stable")],
            "description": _("Edge-TTS с RVC через ONNX (DirectML / CPU). Ветка для AMD, Intel и CPU без fp16.", "Edge-TTS with RVC via ONNX (DirectML / CPU). Variant for AMD, Intel and CPU without fp16."),
            "settings": _onnx_edge_settings(),
        },
        {
            "id": SILERO_RVC_ONNX_ID,
            "pipeline": "silero",
            "name": "Silero + RVC (ONNX)",
            "min_vram": 3,
            "rec_vram": 4,
            "gpu_vendor": ["AMD", "CPU"],
            "size_gb": 3,
            "languages": ["Russian", "English"],
            "intents": [_("ONNX", "ONNX"), _("Локальный синтез", "Offline synth")],
            "description": _("Silero + RVC через ONNX с ограниченными стабильными параметрами.", "Silero + RVC through ONNX with a limited stable parameter set."),
            "settings": _onnx_silero_settings(),
        },
    ]

    def _load_rvc_class(self):
        _ensure_lib_path()
        from tts_with_rvc_onnx import TTS_RVC

        return TTS_RVC

    def _set_rvc_model_path(self, model_path: str) -> None:
        self.current_tts_rvc.set_model(model_path)

    def _apply_backend_sampling_policy(self) -> None:
        char = getattr(self.parent, "current_character_name", "Mila")
        sr, hop = (48000, 512) if char == "ShorthairMita" else (40000, 512)
        self.current_tts_rvc.set_sampling_params(sr, hop)
        self.current_tts_rvc.sampling_rate = sr
        logger.info(f"[ONNX] Sampling parameters set for '{char}': {sr}/{hop}")


# Backward-compatible name for older imports. New code should use the explicit backend classes.
EdgeTTS_RVC_Model = EdgeTTSRVCCudaModel
