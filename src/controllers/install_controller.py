# src/controllers/install_controller.py
from __future__ import annotations

from typing import Callable, Optional, Any, Iterable
import os
import sys
import time
import urllib.request
import urllib.error

from main_logger import logger
from core.backends import BackendKind, get_backend_service
from core.events import get_event_bus, Events, Event
from utils.pip_installer import PipInstaller
from core.install_types import InstallCallbacks, InstallAction, InstallPlan


from packaging.utils import canonicalize_name
from packaging.requirements import Requirement

def _get_installed_constraints(target_dir: str, exclude_specs: list[str]) -> list[str]:
    """
    Сканирует target_dir на наличие установленных пакетов (.dist-info)
    и возвращает список ограничений "package==version" для всех пакетов,
    кроме тех, которые переданы в exclude_specs (устанавливаемые сейчас).
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

    constraints = []
    
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
                # Добавляем в оверрайды только если пакет не обновляется прямо сейчас
                if canon_name not in excluded_names:
                    constraints.append(f"{name}=={version}")
                    
    except Exception as e:
        logger.warning(f"[InstallController] Ошибка сканирования установленных пакетов: {e}")

    return constraints

class InstallController:
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
        self._subscribe_to_events()

    def _subscribe_to_events(self) -> None:
        self.event_bus.subscribe(Events.Install.RUN_BLOCKING, self._on_run_blocking, weak=False)

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

        timeout_sec = float(data.get("timeout_sec", 3600.0) or 3600.0)

        return bool(self.run_task(
            task_id=str(task_id),
            runner=runner,
            callbacks=None,
            meta=meta,
            timeout_sec=timeout_sec,
        ))

    def _make_pip_installer(self, cb: InstallCallbacks) -> PipInstaller:
        return PipInstaller(
            # script_path=self.script_path,
            # libs_path=self.libs_path,
            update_status=cb.status,
            update_log=cb.log,
            update_progress=cb.progress,
            progress_window=None,
        )

    def _emit(self, event_name: str, payload: dict) -> None:
        try:
            self.event_bus.emit(event_name, payload)
        except Exception:
            pass

    def _call_flex(self, fn: Callable[..., Any], **kwargs) -> Any:
        try:
            return fn(**kwargs)
        except TypeError:
            return fn()

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

    def _backend_actions(self, plan: InstallPlan, ctx: dict) -> list[InstallAction]:
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
        files: list[dict],
        *,
        cb: InstallCallbacks,
        start_progress: int,
        end_progress: int,
        headers: Optional[dict[str, str]] = None,
    ) -> bool:
        start_progress = max(0, min(99, int(start_progress)))
        end_progress = max(start_progress, min(99, int(end_progress)))

        filtered: list[dict] = []
        for it in files or []:
            url = str(it.get("url") or "").strip()
            dest = str(it.get("dest") or "").strip()
            if not url or not dest:
                continue
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                continue
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

    def _execute_plan(
        self,
        plan: InstallPlan,
        *,
        pip_installer: PipInstaller,
        callbacks: InstallCallbacks,
        ctx: dict,
    ) -> bool:
        cb = callbacks
        backend_ctx = dict(ctx or {})
        backend_ctx.update(getattr(plan, "backend_context", {}) or {})
        backend_actions = self._backend_actions(plan, backend_ctx)
        backend_requirement = getattr(plan, "required_backend", None)
        if backend_requirement is not None:
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
        for act in actions:
            atype = (act.type or "").strip().lower()

            desc = str(act.description or "")
            pr = int(act.progress or 0)
            pr = max(0, min(99, pr))

            if desc:
                cb.status(desc)
            if pr > 0:
                cb.progress(pr)

            if atype == "pip":
                pkgs = act.packages or []
                if hasattr(pip_installer, "missing_specs"):
                    to_install = pip_installer.missing_specs(pkgs)
                else:
                    to_install = self._missing_pip_specs(pkgs)
                if not to_install:
                    if pkgs:
                        cb.log(f"Skip pip step (already satisfied): {', '.join(pkgs)}")
                    continue

                cb.log(f"Installing: {', '.join(to_install)}")
                extra_args = list(act.extra_args or [])
                
                # --- ДИНАМИЧЕСКИЙ СБОР СУЩЕСТВУЮЩИХ ПАКЕТОВ ---
                target_dir = os.environ.get("NEUROMITA_LIB_DIR", self.libs_path)
                
                # Сканируем папку Lib на наличие установленных пакетов и версий,
                # исключая те, что мы устанавливаем прямо сейчас (to_install)
                detected_constraints = _get_installed_constraints(target_dir, to_install)
                
                # Объединяем специфичные оверрайды бэкенда с обнаруженными в системе
                local_overrides = list(act.uv_overrides or [])
                combined_overrides = list(set(local_overrides + detected_constraints))
                # ----------------------------------------------

                install_with_overrides = getattr(pip_installer, "install_package_with_overrides", None)
                if callable(install_with_overrides):
                    ok = install_with_overrides(
                        to_install,
                        description=desc or "Installing...",
                        extra_args=extra_args or None,
                        uv_overrides=combined_overrides, # <-- Передаем дополненный список
                    )
                else:
                    # Фолбэк на случай если метод оверрайдов недоступен
                    ok = pip_installer.install_package(
                        to_install,
                        description=desc or "Installing...",
                        extra_args=extra_args or None,
                    )
                if not ok:
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
                )
                if not ok:
                    return False

            elif atype == "call":
                if not callable(act.fn):
                    cb.status("Failed")
                    cb.log("Invalid plan action: call without fn")
                    return False
                try:
                    res = self._call_flex(act.fn, pip_installer=pip_installer, callbacks=cb, ctx=ctx)
                    if res is False:
                        cb.status("Failed")
                        cb.log(f"call step returned False: {desc or atype}")
                        return False
                except Exception as e:
                    cb.status("Failed")
                    cb.log(str(e))
                    return False

            elif atype == "call_async":
                if not callable(act.fn):
                    cb.status("Failed")
                    cb.log("Invalid plan action: call_async without fn")
                    return False
                try:
                    import asyncio

                    timeout = float(act.timeout_sec or ctx.get("timeout_sec", 3600.0) or 3600.0)
                    coro = self._call_flex(act.fn, pip_installer=pip_installer, callbacks=cb, ctx=ctx)
                    ok = bool(asyncio.run(asyncio.wait_for(coro, timeout=timeout)))
                    if not ok:
                        cb.status("Failed")
                        cb.log("async step returned False")
                        return False
                except Exception as e:
                    cb.status("Failed")
                    cb.log(str(e))
                    return False

            else:
                cb.log(f"Unknown plan action type: {atype}")
                cb.status("Failed")
                return False

        cb.progress(100)
        cb.status(plan.ok_status or "Done")
        return True

    def run_task(
        self,
        *,
        task_id: str,
        runner: Callable[..., Any],
        callbacks: Optional[InstallCallbacks] = None,
        meta: Optional[dict] = None,
        timeout_sec: float = 3600.0,
    ) -> bool:
        meta = meta or {}

        user_cb = callbacks or InstallCallbacks(
            progress=lambda *_: None,
            status=lambda *_: None,
            log=lambda m: logger.info(m),
        )

        state = {"progress": 0, "status": ""}

        def base_payload(extra: Optional[dict] = None) -> dict:
            p = {
                "task_id": str(task_id),
                "meta": meta,
                "kind": meta.get("kind"),
                "item_id": meta.get("item_id"),
            }
            if extra:
                p.update(extra)
            return p

        def cb_progress(v: int) -> None:
            try:
                v = int(v)
            except Exception:
                v = 0
            v = max(0, min(100, v))
            state["progress"] = v
            try:
                user_cb.progress(v)
            except Exception:
                pass
            self._emit(Events.Install.TASK_PROGRESS, base_payload({"progress": v, "status": state.get("status", "")}))

        def cb_status(s: str) -> None:
            s = "" if s is None else str(s)
            state["status"] = s
            try:
                user_cb.status(s)
            except Exception:
                pass
            self._emit(Events.Install.TASK_PROGRESS, base_payload({"progress": state.get("progress", 0), "status": s}))

        def cb_log(m: str) -> None:
            m = "" if m is None else str(m)
            try:
                user_cb.log(m)
            except Exception:
                pass
            self._emit(Events.Install.TASK_LOG, base_payload({"message": m}))

        cb = InstallCallbacks(progress=cb_progress, status=cb_status, log=cb_log)
        pip_installer = self._make_pip_installer(cb)

        self._emit(Events.Install.TASK_STARTED, base_payload({"progress": 0, "status": "Preparing..."}))
        cb.status("Preparing...")
        cb.progress(1)

        ctx = {
            "task_id": str(task_id),
            "meta": meta,
            "timeout_sec": float(timeout_sec),
            "event_bus": self.event_bus,
        }

        try:
            result: Any
            try:
                result = runner(pip_installer=pip_installer, callbacks=cb, ctx=ctx)
            except TypeError:
                result = runner(pip_installer, cb, ctx)

            if isinstance(result, InstallPlan):
                ok = self._execute_plan(result, pip_installer=pip_installer, callbacks=cb, ctx=ctx)
            elif isinstance(result, dict) and "actions" in result:
                actions = result.get("actions") or []
                plan = InstallPlan(
                    actions=[InstallAction(**a) if isinstance(a, dict) else a for a in actions],
                    already_installed=bool(result.get("already_installed", False)),
                    ok_status=str(result.get("ok_status", "Done") or "Done"),
                    already_installed_status=str(result.get("already_installed_status", "Already installed") or "Already installed"),
                )
                ok = self._execute_plan(plan, pip_installer=pip_installer, callbacks=cb, ctx=ctx)
            else:
                ok = bool(result)
                if ok:
                    cb.progress(100)
                    cb.status("Done")

            if ok:
                self._emit(Events.Install.TASK_FINISHED, base_payload({"ok": True}))
                return True

            cb.status("Failed")
            self._emit(Events.Install.TASK_FAILED, base_payload({"ok": False, "error": "Task failed"}))
            return False

        except Exception as e:
            err = str(e) or repr(e)
            cb.status("Failed")
            cb.log(err)
            self._emit(Events.Install.TASK_FAILED, base_payload({"ok": False, "error": err}))
            return False
