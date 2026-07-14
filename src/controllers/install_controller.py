# src/controllers/install_controller.py
from __future__ import annotations

from typing import Callable, Optional, Any, Iterable, Sequence
import importlib
import inspect
import json
import os
import subprocess
import sys
import time
import threading
import urllib.request
import urllib.error

from main_logger import logger
from core.backends import BackendKind, get_backend_service
from core.events import get_event_bus, Events, Event
from utils.pip_installer import PipInstaller
from core.install_types import (
    DEFAULT_INSTALL_TIMEOUT_SEC,
    InstallAction,
    InstallCallbacks,
    InstallPlan,
)
from core.runtime_environments import EnvironmentTransaction, runtime_environments
from core.services import services
from core.install_requirements import missing_pip_specs
from core.task_supervisor import task_supervisor
from utils import getTranslationVariant as _
from services.contracts import AIEngineService, InstallService


from packaging.utils import canonicalize_name
from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

# Пакеты, версии которых мы защищаем от изменения при установке новых компонентов.
# Раньше через uv --overrides пинились ВООБЩЕ ВСЕ установленные пакеты (==version),
# и это ломало резолв: например, установка f5-tts падала с кодом 2, потому что uv
# не мог удовлетворить её зависимости под жёстко зафиксированное окружение
# (фидбэк Артёма: «f5 всё также еррорит при установке», pip exit code 2).
# Теперь фиксируем только хрупкое ядро (torch/onnx/triton/numpy) — то, ради чего
# оверрайды и вводились (чтобы не сломать CUDA/ONNX-стек), а всё остальное даём
# uv резолвить свободно.
_PROTECTED_CONSTRAINT_NAMES = {
    canonicalize_name(n)
    for n in (
        "torch", "torchaudio", "torchvision", "torchcrepe",
        "triton", "triton-windows",
        "onnxruntime", "onnxruntime-gpu", "onnxruntime-directml",
        "numpy",
    )
}


class InstallCancelled(RuntimeError):
    pass


def _get_installed_constraints(target_dir: str, exclude_specs: list[str]) -> list[str]:
    """
    Сканирует target_dir на наличие установленных пакетов (.dist-info)
    и возвращает список ограничений "package==version" — но ТОЛЬКО для защищённого
    ядра (_PROTECTED_CONSTRAINT_NAMES) и кроме тех, что устанавливаются сейчас
    (exclude_specs). Массовый пин всего окружения намеренно убран: он делал резолв
    новых пакетов неразрешимым (см. комментарий к _PROTECTED_CONSTRAINT_NAMES).
    """
    if not target_dir or not os.path.isdir(target_dir):
        return []

    # Шаг 1. Парсим каноничные имена пакетов, которые устанавливаем сейчас,
    # чтобы не заблокировать их обновление.
    excluded_names = set()
    for spec in exclude_specs:
        try:
            req = Requirement(spec)
            excluded_names.add(canonicalize_name(req.name))
        except Exception:
            # Фолбэк на случай сырой строки без сложного синтаксиса
            name = spec.split(";", 1)[0].split("==")[0].split(">=")[0].split("<=")[0].strip()
            excluded_names.add(canonicalize_name(name))

    candidates: dict[str, tuple[str, str]] = {}
    
    # Шаг 2. Быстро сканируем папки .dist-info
    try:
        for item in os.listdir(target_dir):
            if not item.endswith(".dist-info"):
                continue

            metadata_path = os.path.join(target_dir, item, "METADATA")
            name: Optional[str] = None
            version: Optional[str] = None

            # Пробуем прочесть метаданные напрямую
            if os.path.isfile(metadata_path):
                try:
                    with open(metadata_path, "r", encoding="utf-8", errors="ignore") as fh:
                        for line in fh:
                            lower = line.lower()
                            if lower.startswith("name:"):
                                name = line.split(":", 1)[1].strip()
                            elif lower.startswith("version:"):
                                version = line.split(":", 1)[1].strip()
                            if name and version:
                                break
                except Exception:
                    pass

            # Если файл METADATA не прочитался, парсим имя папки
            if name is None:
                stem = item.rsplit(".dist-info", 1)[0]
                parts = stem.split("-")
                if len(parts) >= 2:
                    name = parts[0]
                    version = parts[-1]
                else:
                    name = stem
                    version = ""

            if name and version:
                canon_name = canonicalize_name(name)
                # Пиним только защищённое ядро и только если пакет не ставится
                # прямо сейчас (иначе заблокировали бы его же обновление).
                if canon_name in excluded_names:
                    continue
                if canon_name not in _PROTECTED_CONSTRAINT_NAMES:
                    continue
                current = candidates.get(canon_name)
                if current is None or _prefer_distribution_version(version, current[1]):
                    candidates[canon_name] = (name, version)
                    
    except Exception as e:
        logger.warning(f"[InstallController] Ошибка сканирования установленных пакетов: {e}")

    return [
        f"{candidates[key][0]}=={candidates[key][1]}"
        for key in sorted(candidates)
    ]


def _prefer_distribution_version(candidate: str, current: str) -> bool:
    """Choose one deterministic version when stale *.dist-info directories coexist.

    ``pip --target`` and interrupted upgrades can leave metadata for several
    versions of the same distribution. Emitting every one of them as an uv
    override produces an inherently unsatisfiable resolver input. Prefer the
    highest valid PEP 440 version and fall back to a stable lexical comparison
    for malformed third-party metadata.
    """
    try:
        return Version(candidate) > Version(current)
    except InvalidVersion:
        return str(candidate) > str(current)


def _merge_requirement_specs(*groups: Iterable[str]) -> list[str]:
    """Merge constraints by canonical distribution name, preserving priority.

    Earlier groups are authoritative. In particular, the backend install plan
    must win over metadata discovered in ``Lib``; otherwise stale dist-info can
    replace the selected torch/torchaudio pair with an older version.
    """
    merged: dict[str, str] = {}
    unparsed: set[str] = set()
    result: list[str] = []

    for group in groups:
        for raw in group or ():
            spec = str(raw or "").strip()
            if not spec:
                continue
            try:
                name = canonicalize_name(Requirement(spec).name)
            except Exception:
                key = spec.lower()
                if key in unparsed:
                    continue
                unparsed.add(key)
                result.append(spec)
                continue
            if name in merged:
                continue
            merged[name] = spec
            result.append(spec)
    return result

class InstallController(InstallService):
    """
    Generic install orchestrator.

    - Creates PipInstaller wired to callbacks
    - Runs a runner(pip_installer, callbacks, ctx) which may:
        a) return bool (legacy mode), or
        b) return InstallPlan (preferred mode)
    - Executes InstallPlan with built-in skip for pip specs (generic).
    - Emits generic install events: Events.Install.TASK_*
    - NEW: supports blocking event-driven installs via Events.Install.RUN_BLOCKING
    """

    def __init__(self):
        self.script_path = os.environ.get("NEUROMITA_PYTHON", sys.executable)
        self.libs_path = os.environ.get("NEUROMITA_LIB_DIR", "Lib")
        self.event_bus = get_event_bus()
        self.environment_manager = runtime_environments()
        self._active_installers_lock = threading.RLock()
        self._active_installers: set[PipInstaller] = set()
        self._subscribe_to_events()

    def _subscribe_to_events(self) -> None:
        self.event_bus.subscribe(Events.Install.RUN_BLOCKING, self._on_run_blocking, weak=False)

    def run_blocking(self, payload: dict[str, Any]) -> bool:
        return bool(self._on_run_blocking(Event(Events.Install.RUN_BLOCKING, payload)))

    def _on_run_blocking(self, event: Event) -> bool:
        data = event.data if isinstance(event.data, dict) else {}

        runner = data.get("runner")
        if not callable(runner):
            logger.error("InstallController: missing callable 'runner' in RUN_BLOCKING payload")
            return False

        kind = data.get("kind") or (data.get("meta") or {}).get("kind") or "install"
        item_id = data.get("item_id") or data.get("engine") or (data.get("meta") or {}).get("item_id") or "task"
        task_id = data.get("task_id") or f"{kind}:{item_id}"
        meta = data.get("meta") or {"kind": kind, "item_id": item_id}

        timeout_sec = float(data.get("timeout_sec", DEFAULT_INSTALL_TIMEOUT_SEC) or DEFAULT_INSTALL_TIMEOUT_SEC)

        return bool(self.run_task(
            task_id=str(task_id),
            runner=runner,
            callbacks=None,
            meta=meta,
            timeout_sec=timeout_sec,
        ))

    def _make_pip_installer(
        self,
        cb: InstallCallbacks,
        *,
        target_path: str | os.PathLike[str] | None = None,
    ) -> PipInstaller:
        installer = PipInstaller(
            update_status=cb.status,
            update_log=cb.log,
            update_raw_log=cb.raw_log,
            update_progress=cb.progress,
            progress_window=None,
            target_path=target_path,
        )
        with self._active_installers_lock:
            self._active_installers.add(installer)
        return installer

    def _release_pip_installer(self, installer: PipInstaller | None) -> None:
        if installer is None:
            return
        lock = getattr(self, "_active_installers_lock", None)
        active = getattr(self, "_active_installers", None)
        if lock is None or active is None:
            return
        with lock:
            active.discard(installer)

    def shutdown(self) -> None:
        with self._active_installers_lock:
            installers = list(self._active_installers)
            self._active_installers.clear()
        for installer in installers:
            try:
                installer.cancel()
            except Exception:
                pass
        try:
            self.event_bus.unsubscribe_owner(self)
        except Exception:
            pass

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        try:
            self.event_bus.emit(event_name, payload)
        except Exception:
            pass

    def _call_flex(self, fn: Callable[..., Any], **kwargs) -> Any:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            return fn(**kwargs)
        if any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ):
            return fn(**kwargs)
        accepted = {
            name: value
            for name, value in kwargs.items()
            if name in signature.parameters
        }
        return fn(**accepted)

    @staticmethod
    def _invoke_runner(
        runner: Callable[..., Any],
        *,
        pip_installer: Any,
        callbacks: InstallCallbacks,
        ctx: dict[str, Any],
    ) -> Any:
        try:
            signature = inspect.signature(runner)
        except (TypeError, ValueError):
            return runner(pip_installer=pip_installer, callbacks=callbacks, ctx=ctx)

        try:
            signature.bind(
                pip_installer=pip_installer,
                callbacks=callbacks,
                ctx=ctx,
            )
        except TypeError as keyword_error:
            try:
                signature.bind(pip_installer, callbacks, ctx)
            except TypeError:
                raise keyword_error
            return runner(pip_installer, callbacks, ctx)
        return runner(pip_installer=pip_installer, callbacks=callbacks, ctx=ctx)

    @staticmethod
    def _raise_if_cancelled(ctx: dict[str, Any]) -> None:
        cancel_event = ctx.get("cancel_event")
        if isinstance(cancel_event, threading.Event) and cancel_event.is_set():
            raise InstallCancelled("Installation cancelled")

    def _dist_exists_and_version(self, dist_name: str) -> tuple[bool, Optional[str]]:
        try:
            import importlib.metadata as md
        except Exception:
            return False, None

        names_to_try = [dist_name]
        n = (dist_name or "").strip()
        if n:
            names_to_try.append(n.replace("_", "-"))
            names_to_try.append(n.replace("-", "_"))

        for name in names_to_try:
            if not name:
                continue
            try:
                ver = md.version(name)
                return True, ver
            except Exception:
                continue
        return False, None

    def _is_pip_spec_satisfied(self, spec: str) -> bool:
        spec = (spec or "").strip()
        if not spec:
            return True

        try:
            from packaging.requirements import Requirement
        except Exception:
            ok, _ver = self._dist_exists_and_version(spec)
            return bool(ok)

        try:
            req = Requirement(spec)
        except Exception:
            return False

        try:
            if req.marker is not None and not req.marker.evaluate():
                return True
        except Exception:
            pass

        ok, ver = self._dist_exists_and_version(req.name)
        if not ok:
            return False

        if not req.specifier:
            return True

        if not ver:
            return False

        try:
            return bool(req.specifier.contains(ver, prereleases=True))
        except Exception:
            return False

    def _missing_pip_specs(self, specs: Iterable[str]) -> list[str]:
        missing: list[str] = []
        for s in specs or []:
            s = (s or "").strip()
            if not s:
                continue
            if not self._is_pip_spec_satisfied(s):
                missing.append(s)
        return missing

    def _backend_actions(self, plan: InstallPlan, ctx: dict[str, Any]) -> list[InstallAction]:
        required_backend = getattr(plan, "required_backend", None)
        if required_backend is None:
            return []

        backend_service = get_backend_service()
        backend_requirement = backend_service.build_requirement(required_backend)
        if backend_requirement.kind == BackendKind.NONE:
            return []

        backend_ctx = dict(ctx or {})
        backend_ctx.update(getattr(plan, "backend_context", {}) or {})

        def _install_backend(*, pip_installer=None, callbacks=None, ctx=None, **_kwargs) -> bool:
            if pip_installer is None:
                return False
            status = backend_service.install_backend(
                backend_requirement,
                pip_installer=pip_installer,
                callbacks=callbacks,
                ctx=backend_ctx,
            )
            return bool(status.ok)

        def _validate_backend(*, callbacks=None, ctx=None, **_kwargs) -> bool:
            status = backend_service.get_status(backend_requirement, ctx=backend_ctx)
            if status.ok:
                return True
            if callbacks is not None:
                try:
                    callbacks.log(
                        "Backend validation failed: "
                        + ", ".join(
                            value for value in (
                                f"kind={status.requested_kind.value}",
                                f"variant={status.variant}",
                                f"provider={status.provider}",
                                status.reason,
                            )
                            if value
                        )
                    )
                except Exception:
                    pass
            return False

        install_status = backend_service.get_status(backend_requirement, ctx=backend_ctx)
        actions: list[InstallAction] = []
        if not install_status.ok and install_status.action != "skip":
            actions.append(
                InstallAction(
                    type="call",
                    description=install_status.reason,
                    progress=10,
                    fn=_install_backend,
                )
            )
        actions.append(
            InstallAction(
                type="call",
                description="Validating backend runtime...",
                progress=25,
                fn=_validate_backend,
            )
        )
        return actions

    def _download_http_files(
        self,
        files: list[dict[str, Any]],
        *,
        cb: InstallCallbacks,
        start_progress: int,
        end_progress: int,
        headers: Optional[dict[str, str]] = None,
        force: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        start_progress = max(0, min(99, int(start_progress)))
        end_progress = max(start_progress, min(99, int(end_progress)))

        filtered: list[dict[str, Any]] = []
        for it in files or []:
            url = str(it.get("url") or "").strip()
            dest = str(it.get("dest") or "").strip()
            if not url or not dest:
                continue
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                if not force:
                    continue
                # Clean reinstall: drop the existing (possibly corrupt) file so
                # it is downloaded again instead of being skipped.
                try:
                    os.remove(dest)
                except OSError:
                    pass
            filtered.append({"url": url, "dest": dest})

        if not filtered:
            return True

        req_headers = dict(headers or {})
        if "User-Agent" not in req_headers:
            req_headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python-urllib"
        if "Accept" not in req_headers:
            req_headers["Accept"] = "*/*"

        totals: list[Optional[int]] = []
        for it in filtered:
            try:
                r = urllib.request.Request(it["url"], headers=req_headers, method="HEAD")
                with urllib.request.urlopen(r, timeout=30) as resp:
                    cl = resp.headers.get("Content-Length")
                    totals.append(int(cl) if cl else None)
            except Exception:
                totals.append(None)

        known_total = sum([t for t in totals if isinstance(t, int) and t > 0])
        have_known_total = known_total > 0 and all(isinstance(t, int) and t > 0 for t in totals)

        done_overall = 0
        file_done: list[int] = [0 for _ in filtered]
        last_emit = 0.0

        def emit_progress(status: str):
            nonlocal last_emit
            now = time.time()
            if now - last_emit < 0.25:
                return
            last_emit = now

            if have_known_total:
                pct = (done_overall * 1.0 / known_total) if known_total else 0.0
            else:
                completed = 0
                for i, t in enumerate(totals):
                    if os.path.exists(filtered[i]["dest"]) and os.path.getsize(filtered[i]["dest"]) > 0:
                        completed += 1
                    elif isinstance(t, int) and t > 0 and file_done[i] >= t:
                        completed += 1
                pct = completed / max(1, len(filtered))

            prog = start_progress + int((end_progress - start_progress) * pct)
            cb.status(status)
            cb.progress(int(max(start_progress, min(end_progress, prog))))

        for idx, it in enumerate(filtered):
            if cancel_event is not None and cancel_event.is_set():
                raise InstallCancelled("Installation cancelled")
            url = it["url"]
            dest = it["dest"]
            tmp = dest + ".part"

            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

            try:
                emit_progress(f"Downloading: {os.path.basename(dest)}")
                req = urllib.request.Request(url, headers=req_headers, method="GET")
                with urllib.request.urlopen(req, timeout=60) as resp:
                    cl = resp.headers.get("Content-Length")
                    total = int(cl) if cl else None
                    totals[idx] = total

                    with open(tmp, "wb") as f:
                        while True:
                            if cancel_event is not None and cancel_event.is_set():
                                raise InstallCancelled("Installation cancelled")
                            chunk = resp.read(1024 * 1024 * 4)
                            if not chunk:
                                break
                            f.write(chunk)

                            file_done[idx] += len(chunk)
                            if have_known_total:
                                done_overall += len(chunk)

                            if total and total > 0:
                                pct_file = (file_done[idx] * 100.0 / total)
                                emit_progress(f"Downloading: {os.path.basename(dest)} ({pct_file:.1f}%)")
                            else:
                                emit_progress(f"Downloading: {os.path.basename(dest)}")

                if os.path.exists(dest):
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
                os.replace(tmp, dest)

            except InstallCancelled:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            except urllib.error.HTTPError as e:
                cb.log(f"HTTP error {e.code} {e.reason} for {url}")
                cb.status("Failed")
                return False
            except Exception as e:
                cb.log(f"Download failed for {url}: {e}")
                cb.status("Failed")
                return False

        cb.progress(end_progress)
        return True

    def _run_with_heartbeat(self, cb: InstallCallbacks, desc: str, run: Callable[[], Any]) -> Any:
        """Выполняет непрозрачный длительный шаг (call/call_async — напр. докачка
        весов модели с HuggingFace, которая не стримит прогресс) с «пульсом»:
        раз в пару секунд обновляет статус живым таймером, чтобы фаза не выглядела
        зависшей. Пульс молчит, если сам шаг активно шлёт статус (чтобы не перебивать
        стримящие шаги вроде прогрева F5). Устаревшие pip-метрики в шапке сбрасываем."""
        import threading

        # Сбросить стухшие метрики предыдущей (pip) фазы — иначе шапка держит
        # «Готово»/«Пакеты 3/3» и весь экран кажется завершённым.
        try:
            cb.log("__STATS__{}")
        except Exception:
            pass
        # Инфо-строку про долгую фоновую загрузку пишем только для шагов, которые
        # реально что-то КАЧАЮТ (по описанию) — чтобы не мусорить на быстром
        # «Finalizing…» и не путать на удалении («Удаление файлов модели…», где тоже
        # есть слово «модель»). Сброс метрик и пульс работают для любого шага.
        low_desc = (desc or "").lower()
        is_download = any(k in low_desc for k in ("download", "скач", "докач", "загруз", "fetch"))
        if is_download:
            try:
                cb.log(_(
                    "Загрузка данных модели — прогресс не потоковый, идёт в фоне; "
                    "это может занять несколько минут, дождитесь завершения.",
                    "Downloading model data — progress is not streamed, running in "
                    "the background; this can take a few minutes, please wait.",
                ))
            except Exception:
                pass

        last = {"t": time.time()}
        orig_status = cb.status

        def wrapped_status(s):
            last["t"] = time.time()
            orig_status(s)

        stop = threading.Event()
        start = time.time()
        base = desc or _("Скачивание модели…", "Downloading model…")

        def _tick():
            while not stop.wait(2.0):
                # Шаг сам обновлял статус недавно — не мешаем ему.
                if time.time() - last["t"] < 4.0:
                    continue
                el = int(time.time() - start)
                m, s = divmod(el, 60)
                h, m = divmod(m, 60)
                clock = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
                orig_status(f"{base} — {clock}")

        th = task_supervisor().start_thread(
            cb,
            "install-elapsed-timer",
            _tick,
        )
        cb.status = wrapped_status
        try:
            return run()
        finally:
            stop.set()
            th.join(timeout=1.0)
            cb.status = orig_status

    @staticmethod
    def _is_main_environment_category(category: str) -> bool:
        return str(category or "").strip().lower() == "dependency"

    @staticmethod
    def _validate_main_environment(
        record,
        *,
        timeout: float,
    ) -> bool:
        modules = tuple(
            dict.fromkeys(
                str(module).strip()
                for module in getattr(record, "probe_modules", ())
                if str(module).strip()
            )
        )
        if not modules:
            return True

        python_executable = os.environ.get("NEUROMITA_PYTHON", sys.executable)
        core_root = os.environ.get("NEUROMITA_CORE_DIR") or os.environ.get("NEUROMITA_LIB_DIR", "")
        python_paths = [str(record.site_packages)]
        if core_root:
            python_paths.append(os.path.abspath(core_root))
        script = (
            "import importlib,json; "
            "mods=json.loads(" + repr(json.dumps(list(modules))) + "); "
            "[importlib.import_module(name) for name in mods]"
        )
        env = os.environ.copy()
        env.pop("PYTHONHOME", None)
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONSAFEPATH"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(python_paths)
        try:
            completed = subprocess.run(
                [python_executable, "-S", "-c", script],
                cwd=os.environ.get("NEUROMITA_BASE_DIR") or None,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max(3.0, float(timeout)),
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt"
                    else 0
                ),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.error("Main dependency validation failed: %s", exc)
            return False
        if completed.returncode == 0:
            return True
        detail = (completed.stderr or completed.stdout or "").strip()
        logger.error(
            "Main dependency validation failed for %s: %s",
            getattr(record, "logical_id", "dependency"),
            detail or f"exit code {completed.returncode}",
        )
        return False

    @staticmethod
    def _activate_main_environment(record) -> None:
        path = os.path.abspath(str(record.site_packages))
        if path not in sys.path:
            sys.path.append(path)
        importlib.invalidate_caches()
        existing = [
            item
            for item in os.environ.get("NEUROMITA_MAIN_ENVIRONMENT_PATHS", "").split(os.pathsep)
            if item
        ]
        if path not in existing:
            existing.append(path)
        os.environ["NEUROMITA_MAIN_ENVIRONMENT_PATHS"] = os.pathsep.join(existing)

    @staticmethod
    def _deactivate_main_environment(record) -> None:
        target = os.path.normcase(os.path.abspath(str(record.site_packages)))
        sys.path[:] = [
            item
            for item in sys.path
            if os.path.normcase(os.path.abspath(item or "")) != target
        ]
        existing = [
            item
            for item in os.environ.get("NEUROMITA_MAIN_ENVIRONMENT_PATHS", "").split(os.pathsep)
            if item and os.path.normcase(os.path.abspath(item)) != target
        ]
        os.environ["NEUROMITA_MAIN_ENVIRONMENT_PATHS"] = os.pathsep.join(existing)
        importlib.invalidate_caches()

    @staticmethod
    def _environment_service_name(category: str) -> str | None:
        mapping = {
            "tts": "tts",
            "voice": "tts",
            "asr": "asr",
            "rag": "rag",
            "embedding": "rag",
            "beats": "beats",
        }
        return mapping.get(str(category or "").strip().lower())

    def _quiesce_environment_worker(
        self,
        *,
        category: str,
        item_id: str,
        timeout: float,
    ) -> bool:
        service_name = self._environment_service_name(category)
        if service_name is None:
            return True
        engine_service = services().get_optional(AIEngineService)
        if engine_service is None:
            return True
        engine = engine_service.get_engine()
        deactivate = getattr(engine, "deactivate_environment", None)
        if not callable(deactivate):
            raise RuntimeError("AI engine does not support managed environment deactivation")
        return bool(
            deactivate(
                service_name,
                item_id,
                category=category,
                timeout=timeout,
                persist=False,
            )
        )

    @staticmethod
    def _forget_environment_runtime(
        *,
        category: str,
        item_id: str,
    ) -> None:
        service_name = InstallController._environment_service_name(category)
        if service_name is None:
            return
        engine_service = services().get_optional(AIEngineService)
        if engine_service is None:
            return
        engine = engine_service.get_engine()
        forget = getattr(engine, "forget_environment", None)
        if callable(forget):
            forget(service_name, item_id, category=category)

    @staticmethod
    def _refresh_ai_runtime(
        *,
        timeout: float,
        preferred_core_layer_ids: Sequence[str] = (),
    ) -> bool:
        engine_service = services().get_optional(AIEngineService)
        if engine_service is None:
            return True
        engine = engine_service.get_engine()
        refresh = getattr(engine, "refresh_runtime", None)
        if not callable(refresh):
            raise RuntimeError("AI engine does not support managed runtime refresh")
        return bool(
            refresh(
                timeout=timeout,
                preferred_core_layer_ids=tuple(preferred_core_layer_ids),
            )
        )

    @staticmethod
    def _artifact_cleanup_plan(plan: InstallPlan) -> InstallPlan:
        actions = [
            action
            for action in (plan.actions or [])
            if str(action.type or "").strip().lower() != "pip"
            and not bool(action.environment_mutation)
        ]
        return InstallPlan(
            actions=actions,
            already_installed=False,
            ok_status=plan.ok_status,
            already_installed_status=plan.already_installed_status,
            required_backend=None,
            backend_context={},
            environment_id=plan.environment_id,
            environment_managed=plan.environment_managed,
        )

    @staticmethod
    def _collect_pip_specs(plan: InstallPlan) -> list[str]:
        specs: list[str] = []
        for action in plan.actions or []:
            if str(action.type or "").strip().lower() != "pip":
                continue
            specs.extend(str(item) for item in (action.packages or []) if str(item).strip())
        return specs

    @staticmethod
    def _apply_environment_ctx(
        ctx: dict[str, Any],
        *,
        target_dir: str,
        python_paths: Iterable[str],
        transaction: EnvironmentTransaction | None = None,
    ) -> None:
        paths = [str(path) for path in python_paths if str(path).strip()]
        ctx.update({
            "libs_dir": str(target_dir),
            "lib_dir": str(target_dir),
            "target_dir": str(target_dir),
            "python_paths": paths,
            "strict_target": True,
        })
        if transaction is not None:
            ctx["environment_transaction"] = transaction
            ctx["environment_id"] = transaction.logical_id

    def _execute_plan(
        self,
        plan: InstallPlan,
        *,
        pip_installer: PipInstaller,
        callbacks: InstallCallbacks,
        ctx: dict[str, Any],
        environment_transaction: EnvironmentTransaction | None = None,
    ) -> bool:
        cb = callbacks
        clean = bool((ctx.get("meta") or {}).get("clean")) if isinstance(ctx, dict) else False
        backend_ctx = dict(ctx or {})
        backend_ctx.update(getattr(plan, "backend_context", {}) or {})
        backend_actions = [] if environment_transaction is not None else self._backend_actions(plan, backend_ctx)
        backend_requirement = getattr(plan, "required_backend", None)
        if backend_requirement is not None and environment_transaction is None:
            backend_service = get_backend_service()
            backend_requirement = backend_service.build_requirement(backend_requirement)
            if backend_requirement.kind != BackendKind.NONE:
                for act in (plan.actions or []):
                    if (act.type or "").strip().lower() != "pip":
                        continue
                    if act.uv_overrides:
                        continue
                    act.uv_overrides = list(
                        backend_service.build_uv_overrides(
                            backend_requirement,
                            requested_specs=act.packages or [],
                        )
                    )

        if plan.already_installed and not backend_actions:
            cb.status(plan.already_installed_status or "Already installed")
            cb.progress(100)
            return True

        actions = backend_actions + (plan.actions or [])
        overlay_prepared = False

        def prepare_overlay() -> None:
            nonlocal overlay_prepared
            if overlay_prepared or environment_transaction is None:
                return
            environment_transaction.strip_core_packages()
            self._apply_environment_ctx(
                ctx,
                target_dir=str(environment_transaction.site_packages),
                python_paths=environment_transaction.validation_paths,
                transaction=environment_transaction,
            )
            overlay_prepared = True

        for act in actions:
            self._raise_if_cancelled(ctx)
            atype = (act.type or "").strip().lower()

            desc = str(act.description or "")
            pr = int(act.progress or 0)
            pr = max(0, min(99, pr))

            if desc:
                cb.status(desc)
            if pr > 0:
                cb.progress(pr)

            if atype != "pip":
                prepare_overlay()

            if atype == "pip":
                pkgs = act.packages or []
                if environment_transaction is not None and ctx.get("environment_overlay_resolved"):
                    if pkgs:
                        cb.log(f"Resolved environment package set: {', '.join(pkgs)}")
                    continue
                if clean:
                    # Clean reinstall: don't skip satisfied packages, force-reinstall.
                    to_install = list(pkgs)
                else:
                    if environment_transaction is not None:
                        to_install = missing_pip_specs(pkgs, ctx=ctx)
                    elif hasattr(pip_installer, "missing_specs"):
                        to_install = pip_installer.missing_specs(pkgs)
                    else:
                        to_install = self._missing_pip_specs(pkgs)
                    if not to_install:
                        if pkgs:
                            cb.log(f"Skip pip step (already satisfied): {', '.join(pkgs)}")
                        continue

                cb.log(f"Installing: {', '.join(to_install)}")
                extra_args = list(act.extra_args or [])
                if clean and "--reinstall" not in extra_args and "--force-reinstall" not in extra_args:
                    # PipInstaller translates --reinstall -> --force-reinstall for pip.
                    extra_args.append("--reinstall")
                
                # --- ДИНАМИЧЕСКИЙ СБОР СУЩЕСТВУЮЩИХ ПАКЕТОВ ---
                target_dir = str(ctx.get("target_dir") or os.environ.get("NEUROMITA_LIB_DIR", self.libs_path))

                if environment_transaction is not None:
                    detected_constraints = []
                    local_overrides = list(environment_transaction.core_overrides)
                    local_overrides.extend(list(act.uv_overrides or []))
                else:
                    detected_constraints = _get_installed_constraints(target_dir, to_install)
                    local_overrides = list(act.uv_overrides or [])
                combined_overrides = _merge_requirement_specs(
                    local_overrides,
                    detected_constraints,
                )
                # ----------------------------------------------

                install_with_overrides = getattr(pip_installer, "install_package_with_overrides", None)
                if not callable(install_with_overrides):
                    raise RuntimeError("PipInstaller does not support the required uv override contract")
                ok = install_with_overrides(
                    to_install,
                    description=desc or "Installing...",
                    extra_args=extra_args or None,
                    uv_overrides=combined_overrides,
                )
                if not ok:
                    self._raise_if_cancelled(ctx)
                    cb.status("Failed")
                    cb.log("pip step failed")
                    return False

            elif atype == "download_http":
                files = act.files or []
                end_pr = act.progress_to if act.progress_to is not None else 99
                ok = self._download_http_files(
                    files,
                    cb=cb,
                    start_progress=pr,
                    end_progress=int(end_pr),
                    headers=act.headers,
                    force=clean,
                    cancel_event=ctx.get("cancel_event"),
                )
                if not ok:
                    return False

            elif atype == "call":
                if not callable(act.fn):
                    cb.status("Failed")
                    cb.log("Invalid plan action: call without fn")
                    return False
                action_fn = act.fn
                try:
                    res = self._run_with_heartbeat(
                        cb, desc,
                        lambda: self._call_flex(
                            action_fn,
                            pip_installer=pip_installer,
                            callbacks=cb,
                            ctx=ctx,
                            cancel_event=ctx.get("cancel_event"),
                        ),
                    )
                    if res is False:
                        self._raise_if_cancelled(ctx)
                        cb.status("Failed")
                        cb.log(f"call step returned False: {desc or atype}")
                        # Иначе причина падения шага (напр. «Downloading model
                        # files…») жила только в GUI-логе, а в NeuroMitaLogs.log
                        # было пусто — пользователю нечего смотреть.
                        logger.error(f"Install call step '{desc or atype}' returned False")
                        return False
                except InstallCancelled:
                    raise
                except Exception as e:
                    cb.status("Failed")
                    cb.log(str(e))
                    logger.error(f"Install call step '{desc or atype}' failed: {e}", exc_info=True)
                    return False

            elif atype == "call_async":
                if not callable(act.fn):
                    cb.status("Failed")
                    cb.log("Invalid plan action: call_async without fn")
                    return False
                action_fn = act.fn
                try:
                    import asyncio

                    timeout = float(act.timeout_sec or ctx.get("timeout_sec", DEFAULT_INSTALL_TIMEOUT_SEC) or DEFAULT_INSTALL_TIMEOUT_SEC)

                    async def _await_action():
                        coro = self._call_flex(
                            action_fn,
                            pip_installer=pip_installer,
                            callbacks=cb,
                            ctx=ctx,
                            cancel_event=ctx.get("cancel_event"),
                        )
                        task = asyncio.create_task(coro)
                        deadline = time.monotonic() + timeout
                        try:
                            while not task.done():
                                self._raise_if_cancelled(ctx)
                                remaining = deadline - time.monotonic()
                                if remaining <= 0:
                                    raise TimeoutError(
                                        f"Install action timed out after {timeout:.1f}s"
                                    )
                                await asyncio.sleep(min(0.1, remaining))
                            return bool(await task)
                        finally:
                            if not task.done():
                                task.cancel()
                                await asyncio.gather(task, return_exceptions=True)

                    def _run_async():
                        return asyncio.run(_await_action())

                    ok = self._run_with_heartbeat(cb, desc, _run_async)
                    if not ok:
                        self._raise_if_cancelled(ctx)
                        cb.status("Failed")
                        cb.log("async step returned False")
                        logger.error(f"Install async step '{desc or atype}' returned False")
                        return False
                except InstallCancelled:
                    raise
                except Exception as e:
                    cb.status("Failed")
                    cb.log(str(e))
                    logger.error(f"Install async step '{desc or atype}' failed: {e}", exc_info=True)
                    return False

            else:
                cb.log(f"Unknown plan action type: {atype}")
                cb.status("Failed")
                return False

        prepare_overlay()
        cb.progress(100)
        cb.status(plan.ok_status or "Done")
        return True

    def run_task(
        self,
        *,
        task_id: str,
        runner: Callable[..., Any],
        callbacks: Optional[InstallCallbacks] = None,
        meta: dict[str, Any] | None = None,
        timeout_sec: float = DEFAULT_INSTALL_TIMEOUT_SEC,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        meta = dict(meta or {})

        user_cb = callbacks or InstallCallbacks(
            progress=lambda *_: None,
            status=lambda *_: None,
            log=lambda m: logger.info(m),
        )

        state = {"progress": 0, "status": ""}

        def base_payload(extra: dict[str, Any] | None = None) -> dict[str, Any]:
            payload = {
                "task_id": str(task_id),
                "meta": meta,
                "kind": meta.get("kind"),
                "item_id": meta.get("item_id"),
            }
            if extra:
                payload.update(extra)
            return payload

        def cb_progress(value: int) -> None:
            try:
                value = int(value)
            except Exception:
                value = 0
            value = max(0, min(100, value))
            state["progress"] = value
            try:
                user_cb.progress(value)
            except Exception:
                pass
            self._emit(
                Events.Install.TASK_PROGRESS,
                base_payload({"progress": value, "status": state.get("status", "")}),
            )

        def cb_status(message: str) -> None:
            message = "" if message is None else str(message)
            state["status"] = message
            try:
                user_cb.status(message)
            except Exception:
                pass
            self._emit(
                Events.Install.TASK_PROGRESS,
                base_payload({"progress": state.get("progress", 0), "status": message}),
            )

        def cb_log(message: str) -> None:
            message = "" if message is None else str(message)
            try:
                user_cb.log(message)
            except Exception:
                pass
            self._emit(Events.Install.TASK_LOG, base_payload({"message": message}))

        def cb_raw_log(chunk: str) -> None:
            raw_cb = user_cb.raw_log
            if raw_cb is None:
                return
            try:
                raw_cb("" if chunk is None else str(chunk))
            except Exception:
                pass

        cb = InstallCallbacks(
            progress=cb_progress,
            status=cb_status,
            log=cb_log,
            raw_log=cb_raw_log,
        )
        created_installers: list[PipInstaller] = []
        created_installers_lock = threading.Lock()
        cancellation = cancel_event or threading.Event()
        task_finished = threading.Event()

        def create_installer(target_path: str | os.PathLike[str] | None) -> PipInstaller:
            try:
                installer = self._make_pip_installer(cb, target_path=target_path)
            except TypeError:
                installer = self._make_pip_installer(cb)
            with created_installers_lock:
                created_installers.append(installer)
            return installer

        environment_manager = getattr(self, "environment_manager", None) or runtime_environments()
        environment_candidate = environment_manager.should_manage(meta)
        logical_id, _category, _item_id = environment_manager.logical_id_from_meta(meta)
        active_environment = environment_manager.active(logical_id) if environment_candidate else None

        if active_environment is not None:
            initial_target = str(active_environment.site_packages)
            initial_paths = environment_manager.runtime_paths(active_environment)
        elif environment_candidate:
            empty_target = environment_manager.staging_root / "probe-empty" / logical_id
            empty_target.mkdir(parents=True, exist_ok=True)
            initial_target = str(empty_target)
            initial_paths = (initial_target,)
        else:
            initial_target = getattr(self, "libs_path", os.environ.get("NEUROMITA_LIB_DIR", "Lib"))
            initial_paths = (str(initial_target),)

        pip_installer = create_installer(initial_target)
        if not environment_candidate:
            actual_target = str(getattr(pip_installer, "libs_path_abs", initial_target))
            initial_target = actual_target
            initial_paths = (actual_target,)

        self._emit(
            Events.Install.TASK_STARTED,
            base_payload({"progress": 0, "status": "Preparing..."}),
        )
        cb.status("Preparing...")
        cb.progress(1)

        ctx = {
            "task_id": str(task_id),
            "meta": meta,
            "timeout_sec": float(timeout_sec),
            "event_bus": self.event_bus,
            "libs_dir": initial_target,
            "lib_dir": initial_target,
            "target_dir": initial_target,
            "python_paths": list(initial_paths),
            "strict_target": bool(environment_candidate),
            "python_executable": pip_installer.script_path,
            "cancel_event": cancellation,
        }

        def watch_cancellation() -> None:
            while not task_finished.is_set():
                if not cancellation.wait(0.1):
                    continue
                with created_installers_lock:
                    installers = tuple(created_installers)
                for installer in installers:
                    try:
                        installer.cancel()
                    except Exception:
                        pass
                return

        cancellation_watcher = task_supervisor().start_thread(
            ctx,
            f"install-cancel:{task_id}",
            watch_cancellation,
        )

        transaction: EnvironmentTransaction | None = None
        quiesced_environment = False
        try:
            self._raise_if_cancelled(ctx)
            result = self._invoke_runner(
                runner,
                pip_installer=pip_installer,
                callbacks=cb,
                ctx=ctx,
            )

            if isinstance(result, dict) and "actions" in result:
                actions = result.get("actions") or []
                result = InstallPlan(
                    actions=[InstallAction(**action) if isinstance(action, dict) else action for action in actions],
                    already_installed=bool(result.get("already_installed", False)),
                    ok_status=str(result.get("ok_status", "Done") or "Done"),
                    already_installed_status=str(
                        result.get("already_installed_status", "Already installed") or "Already installed"
                    ),
                    required_backend=result.get("required_backend"),
                    backend_context=dict(result.get("backend_context") or {}),
                    environment_id=result.get("environment_id"),
                    environment_managed=bool(result.get("environment_managed", True)),
                )

            if isinstance(result, InstallPlan):
                op = str(meta.get("op") or "install").strip().lower()
                managed = bool(environment_candidate and result.environment_managed)

                if managed and result.already_installed and active_environment is not None and op != "uninstall":
                    cb.status(result.already_installed_status or "Already installed")
                    cb.progress(100)
                    ok = True
                elif managed and op == "install":
                    requested_specs = self._collect_pip_specs(result)
                    candidate_transaction = environment_manager.begin(
                        meta={**meta, **({"environment_id": result.environment_id} if result.environment_id else {})},
                        requested_specs=requested_specs,
                        required_backend=result.required_backend,
                        backend_context={**ctx, **dict(result.backend_context or {})},
                    )
                    transaction = candidate_transaction
                    if not candidate_transaction.ensure_core_layers(create_installer, log=cb.log):
                        self._raise_if_cancelled(ctx)
                        raise RuntimeError("Failed to prepare shared AI backend layer")

                    pip_installer = create_installer(str(candidate_transaction.site_packages))
                    self._apply_environment_ctx(
                        ctx,
                        target_dir=str(candidate_transaction.site_packages),
                        python_paths=candidate_transaction.validation_paths,
                        transaction=candidate_transaction,
                    )
                    package_actions = [
                        action
                        for action in (result.actions or [])
                        if str(action.type or "").strip().lower() == "pip"
                    ]
                    resolver_args: list[str] = list(candidate_transaction.core_resolver_args)
                    for action in package_actions:
                        resolver_args.extend(list(action.extra_args or []))
                    if requested_specs:
                        resolve_environment = getattr(
                            pip_installer, "install_environment_lock", None
                        )
                        if not callable(resolve_environment):
                            raise RuntimeError(
                                "PipInstaller does not support transactional environment locks"
                            )
                        if not resolve_environment(
                            requested_specs,
                            core_overrides=list(candidate_transaction.core_overrides),
                            core_packages=list(candidate_transaction.core_package_names),
                            extra_args=resolver_args,
                        ):
                            self._raise_if_cancelled(ctx)
                            raise RuntimeError("Failed to resolve and install environment overlay")
                        ctx["environment_overlay_resolved"] = True
                    ok = self._execute_plan(
                        result,
                        pip_installer=pip_installer,
                        callbacks=cb,
                        ctx=ctx,
                        environment_transaction=candidate_transaction,
                    )
                    if ok:
                        if candidate_transaction.category == "backend":
                            environment_manager.register_backend_candidates(
                                layer.layer_id
                                for layer in candidate_transaction.core_layers
                            )
                            candidate_transaction.abort()
                            cb.log(
                                "Installed AI backend. It will be validated and activated "
                                "when a model is initialized."
                            )
                        else:
                            record = candidate_transaction.commit(meta)
                            if self._is_main_environment_category(record.category):
                                if not self._validate_main_environment(
                                    record,
                                    timeout=min(30.0, max(3.0, float(timeout_sec))),
                                ):
                                    candidate_transaction.rollback_commit()
                                    raise RuntimeError(
                                        "Installed main-process dependency failed import validation; "
                                        "the previous runtime was preserved"
                                    )
                                self._activate_main_environment(record)
                            candidate_transaction.finalize()
                            cb.log(
                                f"Installed environment '{record.logical_id}' revision "
                                f"{record.revision_id}. It will be attached to the AI worker "
                                "when the model is initialized."
                            )
                    else:
                        candidate_transaction.abort()
                elif managed and op == "uninstall" and active_environment is not None:
                    main_environment = self._is_main_environment_category(
                        active_environment.category
                    )
                    if not main_environment:
                        if not self._quiesce_environment_worker(
                            category=active_environment.category,
                            item_id=active_environment.item_id,
                            timeout=min(30.0, max(1.0, float(timeout_sec))),
                        ):
                            raise RuntimeError(
                                f"Failed to stop active worker for environment "
                                f"'{active_environment.logical_id}'"
                            )
                        quiesced_environment = True

                    pip_installer = create_installer(str(active_environment.site_packages))
                    self._apply_environment_ctx(
                        ctx,
                        target_dir=str(active_environment.site_packages),
                        python_paths=environment_manager.runtime_paths(active_environment),
                    )
                    cleanup_plan = self._artifact_cleanup_plan(result)
                    ok = self._execute_plan(
                        cleanup_plan,
                        pip_installer=pip_installer,
                        callbacks=cb,
                        ctx=ctx,
                    )
                    if ok:
                        if main_environment:
                            self._deactivate_main_environment(active_environment)
                        if not environment_manager.remove_installed(
                            active_environment.logical_id,
                            delete=True,
                        ):
                            if main_environment:
                                self._activate_main_environment(active_environment)
                            raise RuntimeError(
                                f"Failed to deactivate environment "
                                f"'{active_environment.logical_id}'"
                            )
                        if not main_environment:
                            self._forget_environment_runtime(
                                category=active_environment.category,
                                item_id=active_environment.item_id,
                            )
                        quiesced_environment = False
                        environment_manager.cleanup_unreferenced_core_layers()
                        cb.log(
                            f"Removed environment '{active_environment.logical_id}'."
                        )
                    elif main_environment:
                        self._activate_main_environment(active_environment)
                    elif not self._refresh_ai_runtime(
                        timeout=min(30.0, max(3.0, float(timeout_sec))),
                    ):
                        raise RuntimeError(
                            "Environment artifact cleanup failed and the previous shared AI "
                            "runtime could not be restored"
                        )
                    else:
                        quiesced_environment = False
                else:
                    ok = self._execute_plan(
                        result,
                        pip_installer=pip_installer,
                        callbacks=cb,
                        ctx=ctx,
                    )
            else:
                ok = bool(result)
                if ok:
                    cb.progress(100)
                    cb.status("Done")

            if ok:
                self._emit(Events.Install.TASK_FINISHED, base_payload({"ok": True}))
                return True

            if transaction is not None:
                transaction.abort()
            cb.status("Failed")
            self._emit(
                Events.Install.TASK_FAILED,
                base_payload({"ok": False, "error": "Task failed"}),
            )
            return False

        except InstallCancelled as exc:
            if transaction is not None:
                transaction.abort()
            error = str(exc) or "Installation cancelled"
            cb.status("Cancelled")
            cb.log(error)
            self._emit(
                Events.Install.TASK_FAILED,
                base_payload({"ok": False, "cancelled": True, "error": error}),
            )
            return False
        except Exception as exc:
            if transaction is not None:
                transaction.abort()
            if quiesced_environment:
                try:
                    restored = self._refresh_ai_runtime(
                        timeout=min(30.0, max(3.0, float(timeout_sec))),
                    )
                    if restored:
                        quiesced_environment = False
                    else:
                        cb.log(
                            "Failed to restore the previous shared AI runtime after an "
                            "uninstall error"
                        )
                except Exception as restore_exc:
                    cb.log(
                        "Failed to restore the previous shared AI runtime after an "
                        f"uninstall error: {restore_exc}"
                    )
            error = str(exc) or repr(exc)
            cb.status("Failed")
            cb.log(error)
            self._emit(
                Events.Install.TASK_FAILED,
                base_payload({"ok": False, "error": error}),
            )
            return False
        finally:
            task_finished.set()
            cancellation_watcher.join(timeout=0.5)
            release = getattr(self, "_release_pip_installer", None)
            if callable(release):
                with created_installers_lock:
                    installers = tuple(created_installers)
                for installer in installers:
                    release(installer)
