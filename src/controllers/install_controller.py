import asyncio
from dataclasses import dataclass
from typing import Callable, Optional

from main_logger import logger
from core.events import get_event_bus, Events
from utils.pip_installer import PipInstaller
from utils.gpu_utils import check_gpu_provider


@dataclass
class InstallCallbacks:
    progress: Callable[[int], None]
    status: Callable[[str], None]
    log: Callable[[str], None]


class InstallController:
    """
    MVP install controller (ASR only):
    - создаёт PipInstaller с UI callbacks
    - строит ctx (gpu_vendor/device)
    - выполняет recognizer.pip_install_steps(ctx)
    - проверяет recognizer.is_installed()/requirements
    - вызывает recognizer.install() (только веса/артефакты)
    """

    def __init__(self, script_path: str = r"libs\python\python.exe", libs_path: str = "Lib"):
        self.script_path = script_path
        self.libs_path = libs_path
        self.event_bus = get_event_bus()

    def _make_pip_installer(self, cb: InstallCallbacks) -> PipInstaller:
        return PipInstaller(
            script_path=self.script_path,
            libs_path=self.libs_path,
            update_status=cb.status,
            update_log=cb.log,
            update_progress=cb.progress,
            progress_window=None
        )

    def install_asr_engine(
        self,
        engine: str,
        *,
        engine_settings: Optional[dict] = None,
        callbacks: Optional[InstallCallbacks] = None,
        timeout_sec: float = 3600.0
    ) -> bool:
        import asyncio
        import importlib

        from handlers.asr_models.requirements import check_requirements, missing_pip_specs

        engine_settings = engine_settings or {}
        cb = callbacks or InstallCallbacks(
            progress=lambda *_: None,
            status=lambda *_: None,
            log=lambda m: logger.info(m)
        )

        def emit_progress(progress: int, status: str = ""):
            try:
                self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_PROGRESS, {
                    "model": engine,
                    "progress": int(progress),
                    "status": status
                })
            except Exception:
                pass

        try:
            self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_STARTED, {"model": engine})
        except Exception:
            pass

        cb.status("Preparing...")
        cb.progress(1)
        emit_progress(1, "Preparing...")

        # ctx (gpu/device)
        try:
            gpu_vendor = check_gpu_provider() or "CPU"
        except Exception:
            gpu_vendor = "CPU"

        ctx = {
            "gpu_vendor": gpu_vendor,
            "device": engine_settings.get("device"),
        }

        pip_installer = self._make_pip_installer(cb)

        # create recognizer
        try:
            from handlers.asr_handler import SpeechRecognition
        except Exception as e:
            msg = f"ASR handler import failed: {e}"
            cb.log(msg)
            try:
                self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {"model": engine, "error": msg})
            except Exception:
                pass
            return False

        reg = getattr(SpeechRecognition, "_registry", {}) or {}
        cls = reg.get(engine)
        if not cls:
            msg = f"Unknown ASR engine: {engine}"
            cb.log(msg)
            try:
                self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {"model": engine, "error": msg})
            except Exception:
                pass
            return False

        try:
            recognizer = cls(pip_installer, logger)
        except Exception as e:
            msg = f"Failed to create recognizer '{engine}': {e}"
            cb.log(msg)
            try:
                self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {"model": engine, "error": msg})
            except Exception:
                pass
            return False

        try:
            if hasattr(recognizer, "apply_settings"):
                recognizer.apply_settings(engine_settings)
        except Exception:
            pass

        # pip steps (dependencies)
        try:
            steps = recognizer.pip_install_steps(ctx) if hasattr(recognizer, "pip_install_steps") else []
            steps = steps or []
        except Exception as e:
            steps = []
            cb.log(f"pip_install_steps error: {e}")

        # Если уже полностью установлен (deps+файлы) — выходим
        try:
            if recognizer.is_installed():
                cb.status("Already installed")
                cb.progress(100)
                emit_progress(100, "Already installed")
                self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FINISHED, {"model": engine})
                return True
        except Exception:
            pass

        # 1) Выполняем pip шаги (скипаем уже удовлетворённые по checkers из requirements.py)
        for step in steps:
            try:
                pr = int(step.get("progress", 10) or 10)
                desc = str(step.get("description", "Installing...") or "Installing...")
                pkgs = step.get("packages")
                extra = step.get("extra_args")

                cb.status(desc)
                emit_progress(pr, desc)
                cb.progress(min(99, pr))

                if not pkgs:
                    continue

                if isinstance(pkgs, str):
                    pkgs_list = [pkgs]
                else:
                    pkgs_list = list(pkgs)

                to_install = missing_pip_specs(pkgs_list, ctx=ctx)
                if not to_install:
                    cb.log(f"Skip pip step (already satisfied): {', '.join(pkgs_list)}")
                    continue

                cb.log(f"Installing: {', '.join(to_install)}")
                ok = pip_installer.install_package(to_install, description=desc, extra_args=extra)
                if not ok:
                    raise RuntimeError(f"pip step failed: {desc}")

                importlib.invalidate_caches()

            except Exception as e:
                msg = str(e)
                cb.status("Failed")
                cb.log(msg)
                try:
                    self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {"model": engine, "error": msg})
                except Exception:
                    pass
                return False

        try:
            reqs = recognizer.requirements() if hasattr(recognizer, "requirements") else []
            py_reqs = [r for r in (reqs or []) if getattr(r, "kind", None) == "python_module"]
            st = check_requirements(py_reqs, ctx=ctx) if py_reqs else {"ok": True, "missing_required": []}

            missing = st.get("missing_required", []) or []
            if missing:
                details = st.get("details", []) or []
                miss_details = []
                for d in details:
                    if d.get("id") in missing:
                        extra = d.get("extra") or {}
                        mod = extra.get("module")
                        path = extra.get("path")
                        if mod:
                            miss_details.append(f"{d.get('id')} (module={mod})")
                        elif path:
                            miss_details.append(f"{d.get('id')} (path={path})")
                        else:
                            miss_details.append(str(d.get("id")))
                msg = "Missing python deps after pip: " + ", ".join(miss_details or missing)

                cb.status("Failed")
                cb.log(msg)
                try:
                    self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {"model": engine, "error": msg})
                except Exception:
                    pass
                return False
        except Exception:
            pass

        # 3) Скачивание артефактов/весов
        try:
            cb.status("Downloading model files...")
            emit_progress(90, "Downloading model files...")
            cb.progress(90)

            ok = bool(asyncio.run(asyncio.wait_for(recognizer.install(), timeout=timeout_sec)))
            if not ok:
                msg = "Artifacts install returned False"
                cb.status("Failed")
                cb.log(msg)
                try:
                    self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {"model": engine, "error": msg})
                except Exception:
                    pass
                return False

        except Exception as e:
            msg = str(e)
            cb.status("Failed")
            cb.log(msg)
            try:
                self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {"model": engine, "error": msg})
            except Exception:
                pass
            return False

        # 4) Финальная проверка уже должна учитывать файлы
        try:
            if hasattr(recognizer, "is_installed") and not recognizer.is_installed():
                msg = "Artifacts downloaded, but requirements still not satisfied"
                cb.status("Failed")
                cb.log(msg)
                try:
                    self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {"model": engine, "error": msg})
                except Exception:
                    pass
                return False
        except Exception:
            pass

        cb.progress(100)
        cb.status("Done")
        emit_progress(100, "Done")
        try:
            self.event_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FINISHED, {"model": engine})
        except Exception:
            pass
        return True