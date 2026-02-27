import os
import sys
import importlib
import traceback
import hashlib
from datetime import datetime
import asyncio
import subprocess
from typing import Optional, Any, List, Dict

from .base_model import IVoiceModel
from main_logger import logger

from core.events import Events
from utils import getTranslationVariant as _, get_character_voice_paths

from core.install_types import InstallPlan, InstallAction
from core.install_requirements import InstallRequirement, check_requirements

from handlers.voice_models.install_plan_helpers import torch_install_action, pip_uninstall_action


class FishSpeechInstallSpec:
    @classmethod
    def supported_model_ids(cls) -> list[str]:
        return ["medium", "medium+", "medium+low"]

    @classmethod
    def title(cls, model_id: str) -> str:
        return _("Установка локальной модели: ", "Installing local model: ") + str(model_id)

    @classmethod
    def requirements(cls, model_id: str, ctx: dict) -> list[InstallRequirement]:
        mid = str(model_id)
        req: list[InstallRequirement] = [
            InstallRequirement(id="fish_speech_lib", kind="python_dist", spec="fish-speech-lib", required=True),
        ]
        if mid in ("medium+", "medium+low"):
            req.append(InstallRequirement(id="triton", kind="python_dist", spec="triton-windows<3.4", required=True))
        if mid == "medium+low":
            req.append(InstallRequirement(id="tts_with_rvc", kind="python_dist", spec="tts-with-rvc", required=True))
        return req
    
    @classmethod
    def is_installed(cls, model_id: str, ctx: dict) -> bool:
        st = check_requirements(cls.requirements(model_id, ctx), ctx=ctx)
        return bool(st.get("ok"))

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

    @classmethod
    def _ensure_sys_path(cls, libs_path_abs: str) -> None:
        if libs_path_abs and libs_path_abs not in sys.path:
            sys.path.insert(0, libs_path_abs)

    @classmethod
    def _apply_triton_patches(cls, libs_path_abs: str, log_cb) -> None:
        def _safe_write(path: str, new_text: str) -> None:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_text)
            except Exception as e:
                log_cb(_(f"Ошибка записи {path}: {e}", f"Write error {path}: {e}"))

        build_py_path = os.path.join(libs_path_abs, "triton", "runtime", "build.py")
        if os.path.exists(build_py_path):
            try:
                with open(build_py_path, "r", encoding="utf-8") as f:
                    source = f.read()

                new_line_tcc = 'cc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tcc", "tcc.exe")'
                source2 = source

                # patch tcc path (a bit tolerant)
                if "tcc.exe" in source2 and "sysconfig.get_paths()" in source2 and "platlib" in source2:
                    import re as _re
                    source2 = _re.sub(
                        r'cc\s*=\s*os\.path\.join\(\s*sysconfig\.get_paths\(\)\s*\[\s*"platlib"\s*\]\s*,\s*"triton"\s*,\s*"runtime"\s*,\s*"tcc"\s*,\s*"tcc\.exe"\s*\)',
                        new_line_tcc,
                        source2
                    )

                # remove -fPIC
                source2 = source2.replace(
                    'cc_cmd = [cc, src, "-O3", "-shared", "-fPIC", "-Wno-psabi", "-o", out]',
                    'cc_cmd = [cc, src, "-O3", "-shared", "-Wno-psabi", "-o", out]'
                )

                if source2 != source:
                    _safe_write(build_py_path, source2)
                    log_cb(_("Патчи применены к triton/runtime/build.py", "Patched triton/runtime/build.py"))
            except Exception as e:
                log_cb(_(f"Ошибка патча build.py: {e}", f"Error patching build.py: {e}"))
                log_cb(traceback.format_exc())
        else:
            log_cb(_("build.py не найден, патч пропущен", "build.py not found, patch skipped"))

        windows_utils_path = os.path.join(libs_path_abs, "triton", "windows_utils.py")
        if os.path.exists(windows_utils_path):
            try:
                with open(windows_utils_path, "r", encoding="utf-8") as f:
                    source = f.read()
                old_code = "output = subprocess.check_output(command, text=True).strip()"
                new_code = (
                    "output = subprocess.check_output(\n"
                    "            command, text=True, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True, "
                    "stdin=subprocess.DEVNULL, stderr=subprocess.PIPE\n"
                    "        ).strip()"
                )
                if old_code in source:
                    _safe_write(windows_utils_path, source.replace(old_code, new_code))
                    log_cb(_("Патч применён к triton/windows_utils.py", "Patched triton/windows_utils.py"))
            except Exception as e:
                log_cb(_(f"Ошибка патча windows_utils.py: {e}", f"Error patching windows_utils.py: {e}"))
                log_cb(traceback.format_exc())

        compiler_path = os.path.join(libs_path_abs, "triton", "backends", "nvidia", "compiler.py")
        if os.path.exists(compiler_path):
            try:
                with open(compiler_path, "r", encoding="utf-8") as f:
                    source = f.read()
                old_line = 'version = subprocess.check_output([_path_to_binary("ptxas")[0], "--version"]).decode("utf-8")'
                new_line = 'version = subprocess.check_output([_path_to_binary("ptxas")[0], "--version"], creationflags=subprocess.CREATE_NO_WINDOW, stderr=subprocess.PIPE, close_fds=True, stdin=subprocess.DEVNULL).decode("utf-8")'
                if old_line in source:
                    _safe_write(compiler_path, source.replace(old_line, new_line))
                    log_cb(_("Патч применён к triton/backends/nvidia/compiler.py", "Patched triton/backends/nvidia/compiler.py"))
            except Exception as e:
                log_cb(_(f"Ошибка патча compiler.py: {e}", f"Error patching compiler.py: {e}"))
                log_cb(traceback.format_exc())

        cache_py_path = os.path.join(libs_path_abs, "triton", "runtime", "cache.py")
        if os.path.exists(cache_py_path):
            try:
                with open(cache_py_path, "r", encoding="utf-8") as f:
                    source = f.read()
                old_line = 'temp_dir = os.path.join(self.cache_dir, f"tmp.pid_{pid}_{rnd_id}")'
                new_line = 'temp_dir = os.path.join(self.cache_dir, f"tmp.pid_{str(pid)[:5]}_{str(rnd_id)[:5]}")'
                if old_line in source:
                    _safe_write(cache_py_path, source.replace(old_line, new_line))
                    log_cb(_("Патч применён к triton/runtime/cache.py", "Patched triton/runtime/cache.py"))
            except Exception as e:
                log_cb(_(f"Ошибка патча cache.py: {e}", f"Error patching cache.py: {e}"))
                log_cb(traceback.format_exc())

    @classmethod
    def _probe_triton_deps(cls, libs_path_abs: str) -> dict:
        deps = {"cuda_found": False, "winsdk_found": False, "msvc_found": False}
        if os.name != "nt":
            return deps

        cls._ensure_sys_path(libs_path_abs)
        import importlib as _importlib
        _importlib.invalidate_caches()

        import triton  # noqa: F401
        from triton.windows_utils import find_cuda, find_winsdk, find_msvc

        try:
            cuda_result = find_cuda()
            if isinstance(cuda_result, (tuple, list)) and len(cuda_result) >= 1:
                cuda_path = cuda_result[0]
                deps["cuda_found"] = bool(cuda_path and os.path.exists(str(cuda_path)))
        except Exception:
            deps["cuda_found"] = False

        try:
            winsdk_result = find_winsdk(False)
            if isinstance(winsdk_result, (tuple, list)) and len(winsdk_result) >= 1:
                winsdk_paths = winsdk_result[0]
                deps["winsdk_found"] = isinstance(winsdk_paths, list) and bool(winsdk_paths)
        except Exception:
            deps["winsdk_found"] = False

        try:
            msvc_result = find_msvc(False)
            cl_path = None
            inc_paths, lib_paths = [], []
            if isinstance(msvc_result, (tuple, list)):
                if len(msvc_result) >= 1:
                    cl_path = msvc_result[0]
                if len(msvc_result) >= 2:
                    inc_paths = msvc_result[1] or []
                if len(msvc_result) >= 3:
                    lib_paths = msvc_result[2] or []
            deps["msvc_found"] = bool((cl_path and os.path.exists(str(cl_path))) or inc_paths or lib_paths)
        except Exception:
            deps["msvc_found"] = False

        return deps

    @classmethod
    def _ensure_triton_ready_call(cls, mode: str):
        def _fn(*, pip_installer=None, callbacks=None, ctx=None, **_kwargs) -> bool:
            cb = callbacks
            ctx = ctx or {}
            eb = ctx.get("event_bus")

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

            libs_path_abs = cls._libs_path_abs(pip_installer)
            cls._ensure_sys_path(libs_path_abs)

            status(_("Применение патчей Triton...", "Applying Triton patches..."))
            cls._apply_triton_patches(libs_path_abs, log)

            # Import check with VC redist retry dialog
            import importlib as _importlib
            for attempt in range(2):
                try:
                    _importlib.invalidate_caches()
                    if "triton" in sys.modules:
                        try:
                            del sys.modules["triton"]
                        except Exception:
                            pass
                    import triton  # noqa: F401
                    break
                except ImportError as e:
                    msg = str(e)
                    log(f"Triton import error: {msg}")
                    if "DLL load failed while importing libtriton" in msg:
                        status(_("Ошибка загрузки Triton! Проверьте VC++ Redistributable.", "Triton load error! Check VC++ Redistributable."))
                        if callable(getattr(eb, "emit_and_wait", None)):
                            res = eb.emit_and_wait(Events.Audio.SHOW_VC_REDIST_DIALOG, timeout=6000.0)
                            choice = res[0] if res else "close"
                            if choice == "retry" and attempt == 0:
                                continue
                        return False
                    return False
                except Exception as e:
                    log(traceback.format_exc())
                    return False

            # Dependencies dialog + optional init.py
            if os.name == "nt" and callable(getattr(eb, "emit_and_wait", None)):
                status(_("Проверка зависимостей Triton...", "Checking Triton dependencies..."))
                deps = cls._probe_triton_deps(libs_path_abs)
                res = eb.emit_and_wait(Events.Audio.SHOW_TRITON_DIALOG, deps, timeout=6000.0)
                choice = res[0] if res else "continue"
                if choice == "skip":
                    status(_("Инициализация ядра пропущена", "Kernel initialization skipped"))
                    return True

            status(_("Инициализация ядра Triton...", "Initializing Triton kernel..."))
            script_path = cls._script_path(pip_installer)

            try:
                temp_dir = "temp"
                os.makedirs(temp_dir, exist_ok=True)

                init_cmd = [script_path, "init.py"]
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                result = subprocess.run(
                    init_cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    check=False,
                    creationflags=creationflags,
                )

                if result.stdout:
                    for line in result.stdout.splitlines():
                        log(line)
                if result.stderr:
                    for line in result.stderr.splitlines():
                        log(f"STDERR: {line}")

                ok = (result.returncode == 0 and os.path.exists(os.path.join(temp_dir, "inited.wav")))
                if ok:
                    status(_("Инициализация ядра успешно завершена!", "Kernel initialization completed successfully!"))
                    return True

                status(_("Ошибка при инициализации ядра", "Error during kernel initialization"))
                return False

            except Exception as e:
                log(_(f"Непредвиденная ошибка init.py: {e}", f"Unexpected init.py error: {e}"))
                log(traceback.format_exc())
                status(_("Ошибка инициализации ядра", "Kernel initialization error"))
                return False

        return _fn

    @classmethod
    def build_install_plan(cls, model_id: str, ctx: dict) -> InstallPlan:
        mid = str(model_id)
        if cls.is_installed(mid, ctx):
            return InstallPlan(
                actions=[],
                already_installed=True,
                already_installed_status=_("Уже установлено", "Already installed")
            )

        allow_unsupported = os.environ.get("ALLOW_UNSUPPORTED_GPU", "0") == "1"
        gpu = str((ctx or {}).get("gpu_vendor") or "")

        if gpu != "NVIDIA" and not allow_unsupported:
            return InstallPlan(
                actions=[
                    InstallAction(
                        type="call",
                        description=_("Требуется NVIDIA GPU", "NVIDIA GPU required"),
                        progress=5,
                        fn=lambda **_k: False
                    )
                ],
                already_installed=False,
            )

        actions: list[InstallAction] = []

        actions.append(torch_install_action(ctx, progress=10))

        pkgs = [
            "fish-speech-lib",
            "numpy==1.26.0",
            "librosa==0.9.1",
            "numba==0.60.0",
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

        # Triton оставляем отдельным шагом (и окно/патчи — отдельно)
        if mid in ("medium+", "medium+low"):
            actions.append(
                InstallAction(
                    type="pip",
                    description=_("Установка Triton...", "Installing Triton..."),
                    progress=65,
                    packages=["triton-windows<3.4"],
                    extra_args=["--upgrade"],
                )
            )
            actions.append(
                InstallAction(
                    type="call",
                    description=_("Патчи/инициализация Triton...", "Patching/initializing Triton..."),
                    progress=80,
                    fn=cls._ensure_triton_ready_call(mid),
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

        if mid == "medium":
            return InstallPlan(
                actions=[
                    pip_uninstall_action(["fish-speech-lib"], description=_("Удаление fish-speech-lib...", "Uninstalling fish-speech-lib..."), progress=20)
                ],
                ok_status=_("Удалено", "Uninstalled"),
            )

        if mid in ("medium+", "medium+low"):
            return InstallPlan(
                actions=[
                    pip_uninstall_action(["triton-windows"], description=_("Удаление Triton...", "Uninstalling Triton..."), progress=20)
                ],
                ok_status=_("Удалено", "Uninstalled"),
            )

        return InstallPlan(actions=[InstallAction(type="call", description="Failed", progress=1, fn=lambda **_k: False)])


class FishSpeechModel(IVoiceModel):
    def __init__(self, parent: 'LocalVoice', model_id: str, rvc_handler: Optional[IVoiceModel] = None):
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

            self.current_fish_speech = self.fish_speech_module(device=device, half=half, compile_model=compile_model)

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