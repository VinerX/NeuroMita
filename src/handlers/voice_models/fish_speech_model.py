from __future__ import annotations

import os
import sys
import traceback
import hashlib
from datetime import datetime
import subprocess
from typing import Optional, Any, List, Dict

from .base_model import IVoiceModel
from main_logger import logger

from core.services import services
from services.contracts import AIEngineAdministrationService, GuiInteractionService
from utils import getTranslationVariant as _, get_character_voice_paths

from core.backends import BackendKind
from core.install_types import InstallPlan, InstallAction
from core.install_requirements import InstallRequirement, check_requirements
from handlers.voice_models.context import VoiceRuntimeContext

from handlers.voice_models.install_plan_helpers import (
    patch_tts_with_rvc_audio,
    pip_uninstall_action,
    remove_paths_action,
    rvc_python_compat_error,
    warning_action,
)
from handlers.voice_models.rvc_runtime_assets import (
    CUDA_RVC_RUNTIME_ASSETS,
    application_root,
    runtime_asset_download_action,
    runtime_asset_requirements,
)
from installables.compatibility_specs import (
    FISH_CUDA_COMPATIBILITY,
    FISH_SPEECH_BACKEND,
    FISH_TRITON_COMPATIBILITY,
)


class FishSpeechInstallSpec:
    _MODEL_REPO_URL = "https://huggingface.co/fishaudio/fish-speech-1.5/resolve/main"
    _MODEL_ASSETS = (
        ("model.pth", f"{_MODEL_REPO_URL}/model.pth"),
        ("tokenizer.tiktoken", f"{_MODEL_REPO_URL}/tokenizer.tiktoken"),
        ("config.json", f"{_MODEL_REPO_URL}/config.json"),
        (
            "firefly-gan-vq-fsq-8x1024-21hz-generator.pth",
            f"{_MODEL_REPO_URL}/firefly-gan-vq-fsq-8x1024-21hz-generator.pth",
        ),
    )

    @classmethod
    def checkpoint_dir(cls) -> str:
        return os.path.join(application_root(), "checkpoints", "fish-speech-1.5")

    @classmethod
    def _model_asset_path(cls, filename: str) -> str:
        return os.path.join(cls.checkpoint_dir(), filename)

    @classmethod
    def supported_model_ids(cls) -> list[str]:
        return ["medium", "medium+", "medium+low"]

    @classmethod
    def title(cls, model_id: str) -> str:
        return _("Установка локальной модели: ", "Installing local model: ") + str(model_id)

    @classmethod
    def requirements(cls, model_id: str, ctx: dict) -> list[InstallRequirement]:
        mid = str(model_id)
        backend_kind = cls.required_backend(model_id, ctx)
        req: list[InstallRequirement] = [
            InstallRequirement(id=f"backend_{backend_kind.value}", kind="backend", backend_kind=backend_kind, required=True),
            InstallRequirement(id="fish_speech_lib", kind="python_dist", spec="fish-speech-lib", required=True),
        ]
        if mid in ("medium+", "medium+low"):
            req.append(InstallRequirement(id="triton", kind="python_dist", spec="triton-windows<3.4", required=True))
        if mid == "medium+low":
            req.append(InstallRequirement(id="tts_with_rvc", kind="python_dist", spec="tts-with-rvc", required=True))
        req.extend(
            InstallRequirement(
                id=f"fish_asset_{filename}",
                kind="file",
                path_fn=lambda _ctx, name=filename: cls._model_asset_path(name),
                required=True,
            )
            for filename, _url in cls._MODEL_ASSETS
        )
        if mid == "medium+low":
            req.extend(runtime_asset_requirements(CUDA_RVC_RUNTIME_ASSETS))
        return req
    
    @classmethod
    def is_installed(cls, model_id: str, ctx: dict) -> bool:
        st = check_requirements(cls.requirements(model_id, ctx), ctx=ctx)
        return bool(st.get("ok"))

    @classmethod
    def required_backend(cls, model_id: str, ctx: dict) -> BackendKind:
        return BackendKind(FISH_SPEECH_BACKEND)

    @classmethod
    def _libs_path_abs(cls, pip_installer) -> str:
        lp = getattr(pip_installer, "libs_path_abs", None)
        if lp:
            return str(lp)
        return os.environ.get("NEUROMITA_LIB_DIR", os.path.abspath("Lib"))

    @classmethod
    def _script_path(cls, pip_installer) -> str:
        sp = getattr(pip_installer, "script_path", None)
        if sp:
            return str(sp)
        return os.environ.get("NEUROMITA_PYTHON", sys.executable)

    @staticmethod
    def _runtime_subprocess_env(python_paths: list[str]) -> dict[str, str]:
        from core.torch_compile_runtime import configure_compile_environment

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(python_paths)
        env["NEUROMITA_RUNTIME_PYTHON_PATHS"] = os.pathsep.join(python_paths)
        dll_paths: list[str] = []
        for root in python_paths:
            for candidate in (
                root,
                os.path.join(root, "torch", "lib"),
                os.path.join(root, "onnxruntime", "capi"),
            ):
                if os.path.isdir(candidate):
                    dll_paths.append(candidate)
        if dll_paths:
            env["PATH"] = os.pathsep.join(dll_paths + [env.get("PATH", "")])
        configure_compile_environment(python_paths, env)
        return env

    @staticmethod
    def _compile_entry_command(
        python_executable: str,
        python_paths: list[str],
    ) -> list[str]:
        candidates = [
            str(path)
            for path in python_paths
            if str(path).lower().endswith(".pyz") and os.path.isfile(str(path))
        ]
        packaged_archive = os.path.join(
            os.environ.get("NEUROMITA_BASE_DIR") or os.getcwd(),
            "NeuroMita.pyz",
        )
        if os.path.isfile(packaged_archive) and packaged_archive not in candidates:
            candidates.append(packaged_archive)
        if candidates:
            return [
                python_executable,
                os.path.abspath(candidates[0]),
                "--internal-compile-fish-speech",
            ]
        return [
            python_executable,
            "-m",
            "handlers.voice_models.compile_fish_speech",
        ]

    @staticmethod
    def _track_subprocess(pip_installer, process) -> None:
        register = getattr(pip_installer, "_set_active_process", None)
        terminate = getattr(pip_installer, "_terminate_process", None)
        if callable(register) and callable(terminate):
            register(
                process,
                lambda: terminate(process, "Installation subprocess cancelled."),
            )

    @staticmethod
    def _untrack_subprocess(pip_installer, process) -> None:
        clear = getattr(pip_installer, "_clear_active_process", None)
        if callable(clear):
            clear(process)

    @classmethod
    def _compile_call(
        cls,
        *,
        optional: bool = False,
        clear_only: bool = False,
        clear_cache: bool = False,
    ):
        def _fn(*, pip_installer=None, callbacks=None, ctx=None, **_kwargs) -> bool:
            cb = callbacks
            ctx = ctx or {}

            def log(m: str):
                try:
                    if cb:
                        cb.log(str(m))
                except Exception:
                    pass

            def status(s: str):
                try:
                    if cb:
                        cb.status(str(s))
                except Exception:
                    pass

            if pip_installer is None:
                return False

            python_paths = [
                os.path.abspath(str(path))
                for path in (ctx.get("python_paths") or [cls._libs_path_abs(pip_installer)])
                if str(path).strip()
            ]
            python_paths.extend(
                str(path) for path in sys.path
                if (
                    str(path).lower().endswith(".pyz")
                    or os.path.isfile(os.path.join(str(path), "handlers", "voice_models", "compile_fish_speech.py"))
                )
                and str(path) not in python_paths
            )
            script_path = cls._script_path(pip_installer)
            from core.torch_compile_runtime import clear_compile_cache, compile_cache_status

            if optional:
                gui = services().get_optional(GuiInteractionService)
                if gui is None or not gui.confirm("triton", compile_cache_status()):
                    status(_("Компиляция отложена", "Compilation postponed"))
                    return True

            engine = services().get_optional(AIEngineAdministrationService)
            suspended = False
            if engine is not None:
                suspended = engine.suspend_for_maintenance(timeout=15.0)
                if not suspended:
                    raise RuntimeError("AI workers could not be suspended")
            if clear_only or clear_cache:
                status(_("Удаление кеша компиляции...", "Deleting compilation cache..."))
                try:
                    clear_compile_cache()
                except Exception:
                    if suspended and engine is not None:
                        engine.resume_after_maintenance()
                    raise
            if clear_only:
                if suspended and engine is not None:
                    engine.resume_after_maintenance()
                return True

            base_dir = os.environ.get("NEUROMITA_BASE_DIR") or os.getcwd()
            ref_wav = os.path.join(base_dir, "Models", "Mila.wav")
            if not os.path.exists(ref_wav):
                message = _(
                    "Для компиляции нужен Models/Mila.wav. Сначала установите голоса Мит.",
                    "Models/Mila.wav is required for compilation. Install Mita voices first.",
                )
                log(message)
                if suspended and engine is not None:
                    engine.resume_after_maintenance()
                return bool(optional)

            status(_("Компиляция Fish Speech+...", "Compiling Fish Speech+..."))
            try:
                init_cmd = [
                    *cls._compile_entry_command(script_path, python_paths),
                    "--reference-audio",
                    ref_wav,
                ]
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                child_env = cls._runtime_subprocess_env(python_paths)
                proc = subprocess.Popen(
                    init_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    bufsize=1,
                    creationflags=creationflags,
                    env=child_env,
                    cwd=base_dir,
                )
                cls._track_subprocess(pip_installer, proc)
                try:
                    if proc.stdout is not None:
                        for line in proc.stdout:
                            line = line.rstrip()
                            if line:
                                log(line)
                        try:
                            proc.stdout.close()
                        except Exception:
                            pass
                    proc.wait()
                finally:
                    cls._untrack_subprocess(pip_installer, proc)

                ok = proc.returncode == 0
                if ok:
                    status(_("Компиляция успешно завершена", "Compilation completed successfully"))
                    if suspended and engine is not None:
                        engine.resume_after_maintenance()
                    return True

                status(_("Ошибка компиляции Fish Speech+", "Fish Speech+ compilation failed"))
                if suspended and engine is not None:
                    engine.resume_after_maintenance()
                return False

            except Exception as e:
                log(_(f"Ошибка компиляции: {e}", f"Compilation error: {e}"))
                log(traceback.format_exc())
                status(_("Ошибка компиляции", "Compilation error"))
                if suspended and engine is not None:
                    engine.resume_after_maintenance()
                return False

        return _fn

    @classmethod
    def build_install_plan(cls, model_id: str, ctx: dict) -> InstallPlan:
        mid = str(model_id)
        backend_kind = cls.required_backend(mid, ctx)
        compat_warning = rvc_python_compat_error("tts-with-rvc") if mid == "medium+low" else None
        if cls.is_installed(mid, ctx):
            return InstallPlan(
                actions=[],
                already_installed=True,
                required_backend=backend_kind,
                backend_context=dict(ctx),
                already_installed_status=_("Уже установлено", "Already installed")
            )

        actions: list[InstallAction] = []

        pkgs = [
            "fish-speech-lib",
            "librosa==0.9.1",
            "numba==0.60.0",
            # Держим scipy на numpy-1.x-совместимой ветке: fish-speech-lib тянет
            # pytorch_lightning -> torchmetrics -> scipy, и без верхней границы
            # ставится scipy>=1.13 (использует np.long, удалён в numpy 1.26) →
            # "module 'numpy' has no attribute 'long'". Зеркалит пин F5.
            "scipy<1.13",
        ]
        if mid == "medium+low":
            pkgs.append("tts-with-rvc")

        actions.append(
            InstallAction(
                type="pip",
                description=_("Установка зависимостей Fish Speech...", "Installing Fish Speech dependencies..."),
                progress=45,
                packages=pkgs,
            )
        )

        actions.append(
            InstallAction(
                type="download_http",
                description=_(
                    "Загрузка весов Fish Speech...",
                    "Downloading Fish Speech weights...",
                ),
                progress=50,
                progress_to=64,
                files=[
                    {"url": url, "dest": cls._model_asset_path(filename)}
                    for filename, url in cls._MODEL_ASSETS
                ],
            )
        )

        if mid == "medium+low":
            actions.append(
                runtime_asset_download_action(
                    CUDA_RVC_RUNTIME_ASSETS,
                    description=_(
                        "Загрузка моделей RVC...",
                        "Downloading RVC model assets...",
                    ),
                    progress=65,
                    progress_to=76,
                )
            )

        if mid in ("medium+", "medium+low"):
            actions.append(
                InstallAction(
                    type="pip",
                    description=_("Установка Triton...", "Installing Triton..."),
                    progress=78,
                    packages=["triton-windows<3.4"],
                    extra_args=["--upgrade"],
                )
            )
            actions.append(
                InstallAction(
                    type="call",
                    description=_("Настройка компиляции Fish Speech+...", "Configuring Fish Speech+ compilation..."),
                    progress=88,
                    fn=cls._compile_call(optional=True),
                )
            )

        if mid == "medium+low":
            actions.append(
                InstallAction(
                    type="call",
                    description=_(
                        "Применение совместимости TTS/RVC...",
                        "Applying TTS/RVC compatibility patch...",
                    ),
                    progress=90,
                    fn=patch_tts_with_rvc_audio,
                )
            )

        actions.append(
            InstallAction(
                type="call",
                description=_("Проверка установки...", "Final check..."),
                progress=99,
                fn=lambda ctx=None, **_k: cls.is_installed(mid, dict(ctx or {})),
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

        if mid == "medium":
            return InstallPlan(
                actions=[
                    pip_uninstall_action(["fish-speech-lib"], description=_("Удаление fish-speech-lib...", "Uninstalling fish-speech-lib..."), progress=20),
                    remove_paths_action(
                        [cls.checkpoint_dir()],
                        description=_("Удаление весов Fish Speech...", "Removing Fish Speech weights..."),
                        progress=85,
                    ),
                ],
                ok_status=_("Удалено", "Uninstalled"),
            )

        if mid in ("medium+", "medium+low"):
            packages = ["fish-speech-lib", "triton-windows"]
            if mid == "medium+low":
                packages.append("tts-with-rvc")
            return InstallPlan(
                actions=[
                    pip_uninstall_action(
                        packages,
                        description=_("Удаление компонентов Fish Speech...", "Uninstalling Fish Speech components..."),
                        progress=20,
                    ),
                    remove_paths_action(
                        [cls.checkpoint_dir()],
                        description=_("Удаление весов Fish Speech...", "Removing Fish Speech weights..."),
                        progress=85,
                    ),
                ],
                ok_status=_("Удалено", "Uninstalled"),
            )

        return InstallPlan(actions=[InstallAction(type="call", description="Failed", progress=1, fn=lambda **_k: False)])


class FishSpeechModel(IVoiceModel):
    def __init__(self, parent: VoiceRuntimeContext, model_id: str, rvc_handler: Optional[IVoiceModel] = None):
        super().__init__(parent, model_id)
        self.fish_speech_module = None
        self.current_fish_speech = None
        self.rvc_handler = rvc_handler

    MODEL_CONFIGS = [
        {
            "id": "medium",
            "name": "Fish Speech",
            "min_vram": 3, "rec_vram": 6,
            "gpu_vendor": ["NVIDIA"],
            "size_gb": 5,
            "compatibility": FISH_CUDA_COMPATIBILITY,
            "languages": ["Russian", "English", "Chinese", "German", "Japanese", "French", "Korean", "Arabic", "Dutch", "Italian", "Polish", "Portuguese"],
            "intents": [_("Качество", "Quality"), _("Сбалансировано", "Balanced")],
            "description": _(
                "Генерация речи хорошего качества. Требует больше ресурсов, чем быстрые модели.",
                "Speech generation with good quality. Requires more resources than fast models."
            ),
            "settings": [
                {"key": "device", "label": _("Устройство", "Device"), "type": "combobox",
                 "options": {"values": ["cuda"], "default": "cuda"},
                 "locked": True,
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
            "compatibility": FISH_TRITON_COMPATIBILITY,
            "languages": ["Russian", "English", "Chinese", "German", "Japanese", "French", "Korean", "Arabic", "Dutch", "Italian", "Polish", "Portuguese"],
            "intents": [_("Качество", "Quality"), "Triton"],
            "description": _(
                "Версия Fish Speech, скомпилированная под GPU. Требует больше места и современную NVIDIA.",
                "Fish Speech version compiled for GPU. Needs more disk space and a modern NVIDIA GPU."
            ),
            "settings": [
                {"key": "device", "label": _("Устройство", "Device"), "type": "combobox",
                 "options": {"values": ["cuda"], "default": "cuda"},
                 "locked": True,
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
            "compatibility": FISH_TRITON_COMPATIBILITY,
            "languages": ["Russian", "English", "Chinese", "German", "Japanese", "French", "Korean", "Arabic", "Dutch", "Italian", "Polish", "Portuguese"],
            "intents": [_("Качество", "Quality"), _("Конверсия голоса", "Voice conversion")],
            "description": _(
                "Комбинация Fish Speech+ и RVC для высококачественного изменения тембра.",
                "Combination of Fish Speech+ and RVC for high‑quality timbre conversion."
            ),
            "settings": [
                {"key": "fsprvc_fsp_device", "label": _("[FSP] Устройство", "[FSP] Device"), "type": "combobox",
                 "options": {"values": ["cuda"], "default": "cuda"},
                 "locked": True,
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

    @classmethod
    def required_backend_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> BackendKind:
        return FishSpeechInstallSpec.required_backend(model_id, ctx)

    @classmethod
    def is_model_installed(cls, model_id: str, ctx: Dict[str, Any]) -> bool:
        return FishSpeechInstallSpec.is_installed(model_id, ctx)

    @classmethod
    def build_install_plan_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> InstallPlan:
        return FishSpeechInstallSpec.build_install_plan(model_id, ctx)

    @classmethod
    def build_uninstall_plan_for_model(cls, model_id: str, ctx: Dict[str, Any]) -> InstallPlan:
        return FishSpeechInstallSpec.build_uninstall_plan(model_id, ctx)

    def build_initialize_plan(self, ctx: Dict[str, Any] | None = None) -> InstallPlan | None:
        run_ctx = dict(ctx or {})
        if self.model_id not in ("medium+", "medium+low"):
            return None
        mode = str(run_ctx.get("initialize_mode") or "compile")
        clear_only = mode == "clear_cache"
        return InstallPlan(
            actions=[
                InstallAction(
                    type="call",
                    description=(
                        _("Удаление кеша компиляции...", "Deleting compilation cache...")
                        if clear_only
                        else _("Компиляция Fish Speech+...", "Compiling Fish Speech+...")
                    ),
                    progress=20 if clear_only else 10,
                    fn=FishSpeechInstallSpec._compile_call(
                        clear_only=clear_only,
                        clear_cache=not clear_only,
                    ),
                )
            ],
            ok_status=(
                _("Кеш компиляции удалён", "Compilation cache deleted")
                if clear_only
                else _("Компиляция завершена", "Compilation completed")
            ),
        )

    def _load_module(self):
        if self.fish_speech_module is not None:
            return
        if getattr(self, "_import_attempted", False):
            return

        self._import_attempted = True
        try:
            import fish_speech_lib
            # fish_speech_lib импортирует свои подмодули через
            # pyrootutils.setup_root(..., indicator=".project-root"), который ищет
            # маркер ВВЕРХ от файла пакета. Когда библиотека лежит в отдельном
            # Venv (а не в Lib игры), маркер из NEUROMITA_BASE_DIR не находится и
            # инициализация падает с FileNotFoundError. Чекпоинты резолвятся
            # относительно cwd (cwd setup_root не меняет), поэтому достаточно
            # положить маркер рядом с самим пакетом — он попадёт в путь поиска.
            self._ensure_fish_speech_project_root(fish_speech_lib)

            from fish_speech_lib.inference import FishSpeech
            self.fish_speech_module = FishSpeech
        except ImportError as ex:
            logger.info(ex)
            self.fish_speech_module = None

    def _ensure_fish_speech_project_root(self, fish_speech_lib) -> None:
        try:
            pkg_file = getattr(fish_speech_lib, "__file__", None)
            if not pkg_file:
                return
            marker = os.path.join(os.path.dirname(os.path.abspath(pkg_file)), ".project-root")
            if not os.path.exists(marker):
                open(marker, "w").close()
                logger.info(f"Создан маркер .project-root для fish_speech_lib: {marker}")
        except Exception as ex:
            logger.warning(f"Не удалось создать .project-root для fish_speech_lib: {ex}")

    def get_display_name(self) -> str:
        mode = self._mode()
        if mode == "medium":
            return "Fish Speech"
        if mode == "medium+":
            return "Fish Speech+"
        if mode == "medium+low":
            return "Fish Speech+ + RVC"
        return "Fish Speech"

    
    def cleanup_state(self):
        super().cleanup_state()
        self.current_fish_speech = None
        self.fish_speech_module = None
        self._import_attempted = False

        if self.rvc_handler and self.rvc_handler.initialized:
            self.rvc_handler.cleanup_state()

        logger.info(f"Состояние для модели {self.model_id} сброшено.")

    def initialize(self, init: bool = False) -> bool:
        mode = self._mode()
        if self.initialized and self.initialized_for == mode:
            return True

        self._load_module()
        if self.fish_speech_module is None:
            logger.error("fish_speech_lib не установлен")
            self.initialized = False
            self.initialized_for = None
            return False

        compile_model = mode in ("medium+", "medium+low")

        prev = getattr(self.parent, "first_compiled", None)
        if prev is not None and prev != compile_model:
            logger.error("КОНФЛИКТ: нельзя переключиться между compile=True/False без перезапуска")
            self.initialized = False
            self.initialized_for = None
            return False

        if self.current_fish_speech is None:
            settings = self.parent.load_model_settings(mode)
            device = settings.get("fsprvc_fsp_device" if mode == "medium+low" else "device", "cuda")
            half = settings.get("fsprvc_fsp_half" if mode == "medium+low" else "half", "True" if compile_model else "False").lower() == "true"

            checkpoint_dir = FishSpeechInstallSpec.checkpoint_dir()
            self.current_fish_speech = self.fish_speech_module(
                device=device,
                half=half,
                compile_model=compile_model,
                llama_checkpoint_path=checkpoint_dir,
                decoder_checkpoint_path=os.path.join(
                    checkpoint_dir,
                    "firefly-gan-vq-fsq-8x1024-21hz-generator.pth",
                ),
            )

            self.parent.first_compiled = compile_model
            logger.info(f"FishSpeech инициализирован (compile={compile_model})")

        if mode == "medium+low":
            if self.rvc_handler and not self.rvc_handler.initialized:
                rvc_success = self.rvc_handler.initialize(init=False)
                if not rvc_success:
                    logger.error("Не удалось инициализировать RVC компонент для 'medium+low'.")
                    self.initialized = False
                    self.initialized_for = None
                    return False

        self.initialized = True
        self.initialized_for = mode
        return True

    async def voiceover(self, text: str, character: Optional[Any] = None, **kwargs) -> Optional[str]:
        mode = self._mode()
        if not self.initialized or self.initialized_for != mode:
            raise Exception(f"Модель {self.model_id} не инициализирована.")
        if self.fish_speech_module is None:
            raise ImportError("Модуль fish_speech_lib не установлен.")

        try:
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
            if os.path.exists(voice_paths["clone_voice_filename"]):
                reference_audio_path = voice_paths["clone_voice_filename"]
                if os.path.exists(voice_paths["clone_voice_text"]):
                    with open(voice_paths["clone_voice_text"], "r", encoding="utf-8") as file:
                        reference_text = file.read().strip()

            seed_processed = int(settings.get(seed_key, 0))
            if seed_processed <= 0 or seed_processed > 2**31 - 1:
                seed_processed = 42

            vol = str(settings.get("volume", "1.0"))
            output_file = kwargs.get("output_file")
            output_file_abs = os.path.abspath(str(output_file)) if output_file else None
            if output_file_abs:
                os.makedirs(os.path.dirname(output_file_abs) or ".", exist_ok=True)

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
                    volume=vol,
                )
                if rvc_output_path and os.path.exists(rvc_output_path):
                    if final_output_path != rvc_output_path:
                        try:
                            os.remove(final_output_path)
                        except OSError:
                            pass
                    final_output_path = rvc_output_path

            if output_file_abs and final_output_path and os.path.exists(final_output_path):
                try:
                    if os.path.abspath(final_output_path) != output_file_abs:
                        if os.path.exists(output_file_abs):
                            try:
                                os.remove(output_file_abs)
                            except Exception:
                                pass
                        os.replace(final_output_path, output_file_abs)
                        final_output_path = output_file_abs
                except Exception:
                    pass

            return final_output_path

        except Exception as error:
            traceback.print_exc()
            logger.info(f"Ошибка при создании озвучки с Fish Speech ({self.model_id}): {error}")
            return None

    def _mode(self) -> str:
        return (self.parent.current_model_id or "medium")
