from __future__ import annotations

import os
import hashlib
from datetime import datetime
import asyncio
from typing import Optional, Any, List, Dict

from .base_model import IVoiceModel
from main_logger import logger
from utils import getTranslationVariant as _, get_character_voice_paths

from core.backends import BackendKind, get_backend_service
from core.install_types import InstallPlan, InstallAction
from core.install_requirements import InstallRequirement, check_requirements
from handlers.voice_models.install_plan_helpers import (
    pip_uninstall_action,
    remove_paths_action,
    rvc_python_compat_error,
    warning_action,
)
from installables.compatibility_specs import (
    F5_CPU_FALLBACK_COMPATIBILITY,
    F5_RVC_FALLBACK_COMPATIBILITY,
)
from handlers.voice_models.context import VoiceRuntimeContext

class F5TTSInstallSpec:
    @classmethod
    def _log_final_check_failure(cls, result: dict, callbacks=None) -> None:
        log = getattr(callbacks, "log", None) if callbacks is not None else None
        if not callable(log):
            def log(*_args):
                return None

        missing_required = list(result.get("missing_required") or [])
        details = list(result.get("details") or [])
        log("ОШИБКА: Финальная проверка установки не пройдена.")
        if missing_required:
            log("ОШИБКА: Не выполнены обязательные требования: " + ", ".join(missing_required))

        for item in details:
            if item.get("ok"):
                continue
            req_id = str(item.get("id") or "?")
            kind = str(item.get("kind") or "?")
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}

            if kind == "python_dist":
                spec = str(extra.get("spec") or extra.get("dist") or req_id)
                version = extra.get("version")
                if version:
                    log(f"ОШИБКА: Требование {req_id}: пакет {spec} не удовлетворён, обнаружена версия {version}.")
                else:
                    log(f"ОШИБКА: Требование {req_id}: пакет {spec} не найден или не удовлетворяет версии.")
            elif kind == "file":
                path = str(extra.get("path") or "")
                log(f"ОШИБКА: Требование {req_id}: отсутствует файл {path}.")
            elif kind == "backend":
                reason = str(extra.get("reason") or "").strip()
                action = str(extra.get("action") or "").strip()
                backend_kind = str(extra.get("backend_kind") or req_id)
                msg = f"ОШИБКА: Требование {req_id}: backend {backend_kind} не готов"
                if action:
                    msg += f" (action={action})"
                if reason:
                    msg += f": {reason}"
                log(msg + ".")
            elif kind == "python_module":
                module = str(extra.get("module") or req_id)
                log(f"ОШИБКА: Требование {req_id}: Python-модуль {module} не найден.")
            else:
                log(f"ОШИБКА: Требование {req_id}: проверка kind={kind} не пройдена.")

    @classmethod
    def _final_check(cls, model_id: str, ctx: dict, callbacks=None) -> bool:
        result = check_requirements(cls.requirements(model_id, ctx), ctx=ctx)
        ok = bool(result.get("ok"))
        if not ok:
            cls._log_final_check_failure(result, callbacks=callbacks)
        return ok

    @classmethod
    def _rvc_package_spec(cls, ctx: dict) -> str:
        gpu_vendor = str((ctx or {}).get("gpu_vendor") or "CPU").upper()
        if gpu_vendor == "NVIDIA":
            return "tts-with-rvc"
        return "tts-with-rvc-onnx[dml]"

    @classmethod
    def _rvc_uninstall_package(cls, ctx: dict) -> str:
        spec = cls._rvc_package_spec(ctx)
        return spec.split("[", 1)[0]

    # --- Языковые веса F5 -------------------------------------------------
    # Раньше веса были захардкожены на русскую модель (F5-TTS_RUSSIAN), хотя
    # карточка обещала «RUSSIAN / ENGLISH». Теперь набор весов выбирается по
    # настройке VOICE_LANGUAGE: en → мультиязычная Cross-Lingual F5-TTS
    # (репозиторий подсказал Артём).
    _RU_CKPT_URL = (
        "https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN/resolve/main/"
        "F5TTS_v1_Base/model_240000_inference.safetensors?download=true"
    )
    _RU_VOCAB_URL = (
        "https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN/resolve/main/"
        "F5TTS_v1_Base/vocab.txt?download=true"
    )
    _EN_CKPT_URL = (
        "https://huggingface.co/QingyuLiu1/Cross-Lingual_F5-TTS/resolve/main/"
        "clf5_950000.safetensors?download=true"
    )
    _EN_VOCAB_URL = (
        "https://huggingface.co/QingyuLiu1/Cross-Lingual_F5-TTS/resolve/main/"
        "vocab.txt?download=true"
    )

    @classmethod
    def resolve_language(cls, ctx: dict) -> str:
        """Язык весов F5: ctx['voice_language'] → настройка VOICE_LANGUAGE → 'ru'."""
        raw = str((ctx or {}).get("voice_language") or "").strip().lower()
        if raw in ("ru", "en"):
            return raw
        try:
            from managers.settings_manager import SettingsManager
            v = str(SettingsManager.get("VOICE_LANGUAGE", "ru") or "ru").strip().lower()
        except Exception:
            v = "ru"
        return "en" if v == "en" else "ru"

    @classmethod
    def model_dir_for_lang(cls, lang: str) -> str:
        """Папка весов для языка. RU остаётся в корне checkpoints/F5-TTS
        (обратная совместимость с уже скачанными весами), EN/мультиязычные —
        в подпапке, чтобы наборы весов не перетирали друг друга."""
        base = os.path.join("checkpoints", "F5-TTS")
        return base if lang == "ru" else os.path.join(base, lang)

    @classmethod
    def _weight_files(cls, lang: str, ckpt_dest: str, vocab_dest: str) -> list[dict]:
        if lang == "en":
            return [
                {"url": cls._EN_CKPT_URL, "dest": ckpt_dest},
                {"url": cls._EN_VOCAB_URL, "dest": vocab_dest},
            ]
        return [
            {"url": cls._RU_CKPT_URL, "dest": ckpt_dest},
            {"url": cls._RU_VOCAB_URL, "dest": vocab_dest},
        ]

    @classmethod
    def supported_model_ids(cls) -> list[str]:
        return ["high", "high+low"]

    @classmethod
    def title(cls, model_id: str) -> str:
        return _("Установка локальной модели: ", "Installing local model: ") + str(model_id)

    @classmethod
    def requirements(cls, model_id: str, ctx: dict) -> list[InstallRequirement]:
        backend_kind = cls.required_backend(model_id, ctx)
        model_dir = cls.model_dir_for_lang(cls.resolve_language(ctx))
        ckpt = os.path.join(model_dir, "model.safetensors")
        vocab = os.path.join(model_dir, "vocab.txt")

        req = [
            InstallRequirement(id=f"backend_{backend_kind.value}", kind="backend", backend_kind=backend_kind, required=True),
            InstallRequirement(id="f5_tts", kind="python_dist", spec="f5-tts", required=True),
            InstallRequirement(id="pyarrow", kind="python_dist", spec="pyarrow<21.0.0", required=True),
            InstallRequirement(id="ckpt", kind="file", path=ckpt, required=True),
            InstallRequirement(id="vocab", kind="file", path=vocab, required=True),
        ]

        if str(model_id) == "high+low":
            req.append(
                InstallRequirement(
                    id="tts_with_rvc",
                    kind="python_dist",
                    spec=cls._rvc_package_spec(ctx),
                    required=True,
                )
            )

        return req

    @classmethod
    def is_installed(cls, model_id: str, ctx: dict) -> bool:
        st = check_requirements(cls.requirements(model_id, ctx), ctx=ctx)
        return bool(st.get("ok"))

    @classmethod
    def required_backend(cls, model_id: str, ctx: dict) -> BackendKind:
        return get_backend_service().preferred_torch_kind(ctx)

    @classmethod
    def build_install_plan(cls, model_id: str, ctx: dict) -> InstallPlan:
        mid = str(model_id)
        backend_kind = cls.required_backend(mid, ctx)
        lang = cls.resolve_language(ctx)
        compat_warning = rvc_python_compat_error(cls._rvc_package_spec(ctx)) if mid == "high+low" else None
        if cls.is_installed(mid, ctx):
            return InstallPlan(
                required_backend=backend_kind,
                backend_context=dict(ctx),
                actions=[],
                already_installed=True,
                already_installed_status=_("Уже установлено", "Already installed")
            )

        model_dir = cls.model_dir_for_lang(lang)
        ckpt_dest = os.path.join(model_dir, "model.safetensors")
        vocab_dest = os.path.join(model_dir, "vocab.txt")

        actions: list[InstallAction] = []

        pkgs = [
            "f5-tts",
            "pyarrow<21.0.0",
            "cached_path",
            "google-api-core",
            "librosa==0.9.1",
            "numba==0.60.0",
            # Keep the whole stack on numpy 1.x. Without an upper bound pip drags
            # scipy up to a numpy-2.0 build (>=1.13 uses np.long, removed in
            # numpy 1.26), and `from transformers import pipeline` then explodes
            # with AttributeError: module 'numpy' has no attribute 'long'.
            "numpy<2.0",
            "scipy<1.13",
            "ruaccent",
        ]
        if mid == "high+low":
            pkgs.insert(0, cls._rvc_package_spec(ctx))

        actions.append(
            InstallAction(
                type="pip",
                description=_("Установка зависимостей F5-TTS...", "Installing F5-TTS dependencies..."),
                progress=35,
                packages=pkgs,
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

        weights_desc = (
            _("Загрузка весов F5-TTS (RU)...", "Downloading F5-TTS weights (RU)...")
            if lang == "ru"
            else _("Загрузка весов F5-TTS (мультиязычные/EN)...", "Downloading F5-TTS weights (multilingual/EN)...")
        )
        actions.append(
            InstallAction(
                type="download_http",
                description=weights_desc,
                progress=60,
                progress_to=90,
                files=cls._weight_files(lang, ckpt_dest, vocab_dest),
            )
        )

        ctx_outer = dict(ctx or {})

        def _verify_install(*, callbacks=None, ctx=None, **_kwargs) -> bool:
            verify_ctx = dict(ctx_outer)
            verify_ctx.update(dict(ctx or {}))
            return cls._final_check(mid, verify_ctx, callbacks=callbacks)

        actions.append(
            InstallAction(
                type="call",
                description=_("Проверка установки...", "Final check..."),
                progress=99,
                fn=_verify_install,
            )
        )

        if compat_warning:
            actions.insert(0, warning_action(compat_warning))

        return InstallPlan(
            actions=actions,
            ok_status=_("Готово", "Done"),
            required_backend=backend_kind,
            backend_context=dict(ctx),
        )


    @classmethod
    def build_uninstall_plan(cls, model_id: str, ctx: dict) -> InstallPlan:
        mid = str(model_id)
        pkgs = ["f5-tts", "ruaccent"]
        if mid == "high+low":
            pkgs = [cls._rvc_uninstall_package(ctx)] + pkgs

        return InstallPlan(
            actions=[
                pip_uninstall_action(pkgs, description=_("Удаление компонентов...", "Uninstalling components...")),
                remove_paths_action([os.path.join("checkpoints", "F5-TTS")], description=_("Удаление файлов модели...", "Removing model files..."), progress=85),
            ],
            ok_status=_("Удалено", "Uninstalled"),
        )

class F5TTSModel(IVoiceModel):
    def __init__(self, parent: VoiceRuntimeContext, model_id: str, rvc_handler: Optional[IVoiceModel] = None):
        super().__init__(parent, model_id)
        self.f5_pipeline_module = None
        self.current_f5_pipeline = None
        self.rvc_handler = rvc_handler
        self.ruaccent_instance = None
        self._import_attempted = False
        self._initialized_lang = None

    MODEL_CONFIGS = [
        {
            "id": "high",
            "name": "F5-TTS",
            "min_vram": 4, "rec_vram": 8,
            "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"],
            "size_gb": 4,
            "backend": "cpu",
            "compatibility": F5_CPU_FALLBACK_COMPATIBILITY,
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
            "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"],
            "size_gb": 7,
            "backend": "cpu",
            "compatibility": F5_RVC_FALLBACK_COMPATIBILITY,
            "languages": ["Russian", "English"],
            "intents": [_("Эмоции", "Emotion"), _("Конверсия голоса", "Voice conversion")],
            "description": _(
                "F5‑TTS с последующей конверсией тембра через RVC.",
                "F5‑TTS followed by timbre conversion via RVC."
            ),
            "settings": [
                {"key": "f5rvc_f5_device", "label": _("[F5] Устройство", "[F5] Device"), "type": "combobox",
                 "options": {"values_nvidia": ["cuda", "cpu"], "default_nvidia": "cuda",
                             "values_amd": ["cpu"], "default_amd": "cpu",
                             "values_intel": ["cpu"], "default_intel": "cpu",
                             "values_other": ["cpu"], "default_other": "cpu"},
                 "help": _("Устройство для части F5‑TTS.", "Device for F5‑TTS part.")},
                {"key": "f5rvc_rvc_device", "label": _("[RVC] Устройство RVC", "[RVC] RVC Device"), "type": "combobox",
                 "options": {"values_nvidia": ["dml", "cuda:0", "cpu"], "default_nvidia": "cuda:0",
                             "values_amd": ["dml", "cpu"], "default_amd": "dml",
                             "values_intel": ["dml", "cpu"], "default_intel": "dml",
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

    @classmethod
    def required_backend_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> BackendKind:
        return F5TTSInstallSpec.required_backend(model_id, ctx)

    @classmethod
    def is_model_installed(cls, model_id: str, ctx: Dict[str, Any]) -> bool:
        return F5TTSInstallSpec.is_installed(model_id, ctx)

    @classmethod
    def build_install_plan_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> InstallPlan:
        return F5TTSInstallSpec.build_install_plan(model_id, ctx)

    @classmethod
    def build_uninstall_plan_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> InstallPlan:
        return F5TTSInstallSpec.build_uninstall_plan(model_id, ctx)

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

    def initialize(self, init: bool = False) -> bool:
        mode = self._mode()
        # Веса выбираем по языку озвучки (VOICE_LANGUAGE): RU лежат в корне
        # checkpoints/F5-TTS, мультиязычные/EN — в подпапке. Это тот же выбор,
        # что и при установке (F5TTSInstallSpec), поэтому пути совпадают.
        lang = str(getattr(self.parent, "voice_language", "ru") or "ru").strip().lower()
        lang = "en" if lang == "en" else "ru"
        # initialized_for оставляем равным mode (его сравнивают с model_id в
        # is_model_initialized), а язык держим отдельно: при смене ru↔en без
        # смены mode пайплайн надо пересобрать под другие веса.
        if self.initialized and self.initialized_for == mode and getattr(self, "_initialized_lang", None) == lang:
            return True

        self._load_module()
        if self.f5_pipeline_module is None:
            logger.error("F5 pipeline not available. Install dependencies first.")
            self.initialized = False
            self.initialized_for = None
            return False

        model_dir = F5TTSInstallSpec.model_dir_for_lang(lang)
        ckpt_path = os.path.join(model_dir, "model.safetensors")
        vocab_path = os.path.join(model_dir, "vocab.txt")

        if not all(os.path.exists(p) for p in [ckpt_path, vocab_path]):
            logger.error(
                f"Missing F5-TTS model files in {model_dir} (language '{lang}'). "
                f"Install the '{lang}' weights via AI Hub."
            )
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
        self._initialized_lang = lang
        return True

    def cleanup_state(self):
        super().cleanup_state()
        self.current_f5_pipeline = None
        self.f5_pipeline_module = None
        self.ruaccent_instance = None
        self._import_attempted = False
        self._initialized_lang = None
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
            logger.info(
                f"F5-TTS: voice asset for '{voice_paths.get('character_name') or '?'}' is not "
                f"installed — falling back to the default reference voice."
            )
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
            name = voice_paths.get("character_name") or "?"
            logger.warning(
                f"F5-TTS: no reference audio for '{name}' (voice asset not installed) and no "
                f"default available — skipping voiceover; no audio for this character."
            )
            return None

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
