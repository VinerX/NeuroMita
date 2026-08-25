from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from core.app_paths import checkpoints_dir
from core.backends import BackendKind, get_backend_service
from core.install_requirements import InstallRequirement, check_requirements
from core.install_types import InstallAction, InstallPlan
from handlers.voice_models.base_model import IVoiceModel
from handlers.voice_models.context import VoiceRuntimeContext
from handlers.voice_models.install_plan_helpers import remove_paths_action
from installables.compatibility_specs import OMNIVOICE_CPU_FALLBACK_COMPATIBILITY
from main_logger import logger
from utils import get_character_voice_paths
from utils import getTranslationVariant as _


def _device_options() -> dict[str, Any]:
    return {
        "values": ["cuda", "cpu"],
        "default": "cuda",
        "values_nvidia": ["cuda", "cpu"],
        "default_nvidia": "cuda",
        "values_amd": ["cpu"],
        "default_amd": "cpu",
        "values_intel": ["cpu"],
        "default_intel": "cpu",
        "values_other": ["cpu"],
        "default_other": "cpu",
    }


class OmniVoiceInstallSpec:
    MODEL_ID = "omnivoice"
    PACKAGE_SPEC = "omnivoice==0.2.1"
    TRANSFORMERS_SPEC = "transformers==5.3.0"
    SCIPY_SPEC = "scipy==1.12.0"
    MODEL_REPO = "k2-fsa/OmniVoice"
    MODEL_REVISION = "c5fdb5ccb189668d56333f77ba2629f4cd7535f4"
    REQUIRED_MODEL_FILES = (
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "chat_template.jinja",
        "audio_tokenizer/config.json",
        "audio_tokenizer/model.safetensors",
        "audio_tokenizer/preprocessor_config.json",
    )

    @classmethod
    def model_dir(cls) -> Path:
        return checkpoints_dir() / "OmniVoice"

    @classmethod
    def supported_model_ids(cls) -> list[str]:
        return [cls.MODEL_ID]

    @classmethod
    def title(cls, model_id: str) -> str:
        return _("Установка локальной модели: OmniVoice", "Installing local model: OmniVoice")

    @classmethod
    def required_backend(cls, model_id: str, ctx: dict) -> BackendKind:
        return get_backend_service().preferred_torch_kind(ctx)

    @classmethod
    def requirements(cls, model_id: str, ctx: dict) -> list[InstallRequirement]:
        backend_kind = cls.required_backend(model_id, ctx)
        requirements = [
            InstallRequirement(
                id=f"backend_{backend_kind.value}",
                kind="backend",
                backend_kind=backend_kind,
                required=True,
            ),
            InstallRequirement(
                id="omnivoice",
                kind="python_dist",
                spec=cls.PACKAGE_SPEC,
                required=True,
            ),
            InstallRequirement(
                id="omnivoice_transformers",
                kind="python_dist",
                spec=cls.TRANSFORMERS_SPEC,
                required=True,
            ),
            InstallRequirement(
                id="omnivoice_scipy",
                kind="python_dist",
                spec=cls.SCIPY_SPEC,
                required=True,
            ),
        ]
        requirements.extend(
            InstallRequirement(
                id=f"omnivoice_model_{index}",
                kind="file",
                path=str(cls.model_dir() / relative_path),
                required=True,
            )
            for index, relative_path in enumerate(cls.REQUIRED_MODEL_FILES)
        )
        return requirements

    @classmethod
    def is_installed(cls, model_id: str, ctx: dict) -> bool:
        if str(model_id or "").strip() != cls.MODEL_ID:
            return False
        return bool(check_requirements(cls.requirements(model_id, ctx), ctx=ctx).get("ok"))

    @classmethod
    def _download_snapshot(cls, *, callbacks=None, ctx=None, cancel_event=None, **_kwargs) -> bool:
        if cancel_event is not None and cancel_event.is_set():
            return False

        from huggingface_hub import snapshot_download

        model_dir = cls.model_dir()
        model_dir.mkdir(parents=True, exist_ok=True)
        log = getattr(callbacks, "log", None)
        if callable(log):
            log(
                f"Hugging Face: {cls.MODEL_REPO}@{cls.MODEL_REVISION[:8]} -> {model_dir}"
            )

        clean = bool(((ctx or {}).get("meta") or {}).get("clean"))
        snapshot_download(
            repo_id=cls.MODEL_REPO,
            revision=cls.MODEL_REVISION,
            local_dir=str(model_dir),
            force_download=clean,
        )

        if cancel_event is not None and cancel_event.is_set():
            return False
        return all((model_dir / relative_path).is_file() for relative_path in cls.REQUIRED_MODEL_FILES)

    @classmethod
    def _final_check(cls, model_id: str, ctx: dict, callbacks=None) -> bool:
        result = check_requirements(cls.requirements(model_id, ctx), ctx=ctx)
        if result.get("ok"):
            return True

        log = getattr(callbacks, "log", None)
        if callable(log):
            missing = ", ".join(str(item) for item in result.get("missing_required") or ())
            log(_("OmniVoice установлена не полностью: ", "OmniVoice installation is incomplete: ") + missing)
        return False

    @classmethod
    def build_install_plan(cls, model_id: str, ctx: dict) -> InstallPlan:
        mid = str(model_id or "").strip()
        backend_kind = cls.required_backend(mid, ctx)
        if cls.is_installed(mid, ctx):
            return InstallPlan(
                actions=[],
                already_installed=True,
                already_installed_status=_("Уже установлено", "Already installed"),
                required_backend=backend_kind,
                backend_context=dict(ctx),
            )

        outer_ctx = dict(ctx or {})

        def verify(*, callbacks=None, ctx=None, **_kwargs) -> bool:
            verify_ctx = dict(outer_ctx)
            verify_ctx.update(dict(ctx or {}))
            return cls._final_check(mid, verify_ctx, callbacks=callbacks)

        return InstallPlan(
            actions=[
                InstallAction(
                    type="pip",
                    description=_(
                        "Установка зависимостей OmniVoice...",
                        "Installing OmniVoice dependencies...",
                    ),
                    progress=30,
                    packages=[
                        cls.PACKAGE_SPEC,
                        cls.TRANSFORMERS_SPEC,
                        cls.SCIPY_SPEC,
                    ],
                ),
                InstallAction(
                    type="call",
                    description=_(
                        "Загрузка OmniVoice с Hugging Face...",
                        "Downloading OmniVoice from Hugging Face...",
                    ),
                    progress=55,
                    fn=cls._download_snapshot,
                ),
                InstallAction(
                    type="call",
                    description=_("Проверка установки...", "Final check..."),
                    progress=99,
                    fn=verify,
                ),
            ],
            ok_status=_("Готово", "Done"),
            required_backend=backend_kind,
            backend_context=dict(ctx),
        )

    @classmethod
    def build_uninstall_plan(cls, model_id: str, ctx: dict) -> InstallPlan:
        return InstallPlan(
            actions=[
                remove_paths_action(
                    [str(cls.model_dir())],
                    description=_(
                        "Удаление файлов OmniVoice...",
                        "Removing OmniVoice files...",
                    ),
                    progress=85,
                )
            ],
            ok_status=_("Удалено", "Uninstalled"),
        )


class OmniVoiceModel(IVoiceModel):
    MODEL_CONFIGS: ClassVar[list[dict[str, Any]]] = [
        {
            "id": OmniVoiceInstallSpec.MODEL_ID,
            "name": "OmniVoice",
            "min_vram": 4,
            "rec_vram": 6,
            "gpu_vendor": ["NVIDIA", "AMD", "INTEL", "CPU"],
            "size_gb": 3.3,
            "backend": "cpu",
            "compatibility": OMNIVOICE_CPU_FALLBACK_COMPATIBILITY,
            "languages": ["Multilingual"],
            "intents": [_("Клонирование голоса", "Voice cloning"), _("Доступность", "Accessibility")],
            "description": _(
                "Более доступная мультиязычная альтернатива Fish Speech: работает на тех же voice cuts, требует меньше места, но уступает Fish Speech по качеству и стабильности.",
                "A more accessible multilingual alternative to Fish Speech: it uses the same voice cuts and needs less disk space, but trails Fish Speech in quality and stability.",
            ),
            "settings": [
                {
                    "key": "device",
                    "label": _("Устройство", "Device"),
                    "type": "combobox",
                    "options": _device_options(),
                    "help": _("Устройство для OmniVoice.", "Device used by OmniVoice."),
                },
                {
                    "key": "speed",
                    "label": _("Скорость речи", "Speech Speed"),
                    "type": "entry",
                    "options": {"default": "1.0"},
                    "help": _("Множитель скорости: 1.0 — нормальная.", "Speed multiplier: 1.0 is normal."),
                },
                {
                    "key": "num_step",
                    "label": _("Шаги диффузии", "Diffusion Steps"),
                    "type": "entry",
                    "options": {"default": "16"},
                    "help": _("16 — быстрее; 32 — качественнее.", "16 is faster; 32 offers better quality."),
                },
                {
                    "key": "postprocess_output",
                    "label": _("Обработка аудио", "Audio Post-processing"),
                    "type": "checkbutton",
                    "options": {"default": True},
                    "help": _("Убирать тишину и сглаживать края аудио.", "Remove silence and smooth audio edges."),
                },
                {
                    "key": "volume",
                    "label": _("Громкость (volume)", "Volume"),
                    "type": "entry",
                    "options": {"default": "1.0"},
                    "help": _("Итоговая громкость.", "Final loudness."),
                },
            ],
        }
    ]

    def __init__(self, parent: VoiceRuntimeContext, model_id: str):
        super().__init__(parent, model_id)
        self.current_model = None
        self._voice_prompt = None
        self._voice_prompt_key: tuple[str, int, str] | None = None

    @classmethod
    def required_backend_for_model(cls, model_id: str, ctx: dict[str, Any]) -> BackendKind:
        return OmniVoiceInstallSpec.required_backend(model_id, ctx)

    @classmethod
    def is_model_installed(cls, model_id: str, ctx: dict[str, Any]) -> bool:
        return OmniVoiceInstallSpec.is_installed(model_id, ctx)

    @classmethod
    def build_install_plan_for_model(cls, model_id: str, ctx: dict[str, Any]) -> InstallPlan:
        return OmniVoiceInstallSpec.build_install_plan(model_id, ctx)

    @classmethod
    def build_uninstall_plan_for_model(cls, model_id: str, ctx: dict[str, Any]) -> InstallPlan:
        return OmniVoiceInstallSpec.build_uninstall_plan(model_id, ctx)

    def get_model_configs(self) -> list[dict[str, Any]]:
        return self.MODEL_CONFIGS

    def get_display_name(self) -> str:
        return "OmniVoice"

    def initialize(self, init: bool = False) -> bool:
        mode = self._mode()
        if self.initialized and self.initialized_for == mode and self.current_model is not None:
            return True

        try:
            import torch
            from omnivoice import OmniVoice

            settings = self.parent.load_model_settings(mode)
            requested_device = str(
                settings.get(
                    "device",
                    "cuda" if self.parent.provider == "NVIDIA" else "cpu",
                )
                or "cpu"
            ).lower()
            use_cuda = requested_device.startswith("cuda") and torch.cuda.is_available()
            if requested_device.startswith("cuda") and not use_cuda:
                logger.warning("OmniVoice: CUDA requested but unavailable; falling back to CPU.")

            device = "cuda:0" if use_cuda else "cpu"
            dtype = torch.float16 if use_cuda else torch.float32
            self.current_model = OmniVoice.from_pretrained(
                str(OmniVoiceInstallSpec.model_dir()),
                device_map=device,
                dtype=dtype,
            )
            self._voice_prompt = None
            self._voice_prompt_key = None
            self.initialized = True
            self.initialized_for = mode
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(f"OmniVoice initialization failed: {exc}", exc_info=True)
            self.current_model = None
            self.initialized = False
            self.initialized_for = None
            return False

    @staticmethod
    def _reference_from_paths(paths: dict[str, Any]) -> tuple[str, str] | None:
        candidates = (
            (paths.get("f5_voice_filename"), paths.get("f5_voice_text")),
            (paths.get("clone_voice_filename"), paths.get("clone_voice_text")),
        )
        for audio_path, text_path in candidates:
            audio = str(audio_path or "").strip()
            transcript = str(text_path or "").strip()
            if not audio or not transcript or not os.path.isfile(audio) or not os.path.isfile(transcript):
                continue
            try:
                text = Path(transcript).read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if text:
                return audio, text
        return None

    def _resolve_reference(self, character: Any | None) -> tuple[str, str] | None:
        paths = get_character_voice_paths(character, self.parent.provider)
        reference = self._reference_from_paths(paths)
        if reference is not None:
            return reference

        logger.info(
            "OmniVoice: complete voice cut for '%s' is unavailable; using the default voice cut.",
            paths.get("character_name") or "?",
        )
        default_paths = get_character_voice_paths(None, self.parent.provider)
        return self._reference_from_paths(default_paths)

    def _prompt_for(self, audio_path: str, ref_text: str):
        mtime_ns = os.stat(audio_path).st_mtime_ns
        key = (
            os.path.abspath(audio_path),
            mtime_ns,
            hashlib.sha1(ref_text.encode("utf-8")).hexdigest(),
        )
        if self._voice_prompt is None or self._voice_prompt_key != key:
            self._voice_prompt = self.current_model.create_voice_clone_prompt(
                ref_audio=audio_path,
                ref_text=ref_text,
            )
            self._voice_prompt_key = key
        return self._voice_prompt

    async def voiceover(self, text: str, character: Any | None = None, **kwargs) -> str | None:
        if not self.initialized or self.current_model is None:
            raise RuntimeError("OmniVoice is not initialized.")

        reference = self._resolve_reference(character)
        if reference is None:
            logger.warning("OmniVoice: no reference audio with transcript is installed; skipping voiceover.")
            return None

        output_file = kwargs.get("output_file")
        if not output_file:
            timestamp = datetime.now(timezone.utc).timestamp()
            digest = hashlib.sha1(f"{text[:20]}_{timestamp}".encode()).hexdigest()[:10]
            output_file = os.path.join("temp", f"omnivoice_out_{digest}.wav")
        output_file = os.path.abspath(str(output_file))
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
        os.makedirs("temp", exist_ok=True)

        settings = self.parent.load_model_settings(self._mode())
        speed = max(0.1, float(settings.get("speed", 1.0) or 1.0))
        num_step = max(1, min(64, int(settings.get("num_step", 16) or 16)))
        postprocess_output = bool(settings.get("postprocess_output", True))
        volume = str(settings.get("volume", "1.0") or "1.0")
        raw_tmp = os.path.abspath(
            os.path.join("temp", f"omnivoice_raw_{hashlib.sha1(output_file.encode()).hexdigest()[:10]}.wav")
        )
        stereo_tmp = raw_tmp.replace("_raw_", "_stereo_")

        def generate_raw() -> None:
            import soundfile as sf

            audio_path, ref_text = reference
            prompt = self._prompt_for(audio_path, ref_text)
            generated = self.current_model.generate(
                text=text,
                voice_clone_prompt=prompt,
                speed=speed,
                num_step=num_step,
                postprocess_output=postprocess_output,
            )
            if not generated:
                raise RuntimeError("OmniVoice returned no audio")
            sf.write(raw_tmp, generated[0], int(self.current_model.sampling_rate), subtype="PCM_16")

        produced: str | None = None
        try:
            await asyncio.to_thread(generate_raw)
            if not os.path.isfile(raw_tmp) or os.path.getsize(raw_tmp) <= 0:
                return None

            converted = self.parent.convert_wav_to_stereo(raw_tmp, stereo_tmp, volume=volume)
            produced = stereo_tmp if converted and os.path.isfile(converted) else raw_tmp
            if os.path.abspath(produced) != output_file:
                if os.path.exists(output_file):
                    os.remove(output_file)
                shutil.move(produced, output_file)
                produced = output_file
            return produced
        finally:
            for path in (raw_tmp, stereo_tmp):
                try:
                    if os.path.exists(path) and os.path.abspath(path) != os.path.abspath(produced or ""):
                        os.remove(path)
                except OSError:
                    pass

    def cleanup_state(self) -> None:
        super().cleanup_state()
        self.current_model = None
        self._voice_prompt = None
        self._voice_prompt_key = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except (ImportError, RuntimeError):
            pass

    def _mode(self) -> str:
        return self.parent.current_model_id or OmniVoiceInstallSpec.MODEL_ID
