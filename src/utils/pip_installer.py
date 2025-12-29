"""
PipInstaller 3.1 — упрощённый PTY/Pipes-раннер без снапшотов.
"""

from __future__ import annotations
import subprocess, sys, os, queue, threading, time, json, shutil, gc, importlib.util, re
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, NormalizedName
from packaging.version import parse as parse_version
from main_logger import logger
from PyQt6.QtWidgets import QApplication
from typing import Set, List, Tuple, Optional, Deque
from PyQt6.QtCore import QThread, QCoreApplication
from collections import deque


class DependencyResolver:
    def __init__(self, libs_path_abs, update_log_func):
        self.libs_path = libs_path_abs
        self.update_log = update_log_func
        self.cache_file_path = os.path.join(self.libs_path, "dependency_cache.json")
        self._dist_info_cache: dict[NormalizedName, str | None] = {}
        self._dep_cache: dict[NormalizedName, set[NormalizedName]] = {}
        self._tree_cache = self._load_tree_cache()

    def _load_tree_cache(self):
        if os.path.exists(self.cache_file_path):
            try:
                with open(self.cache_file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as ex:
                logger.error("Ошибка при _load_tree_cache: " + str(ex))
        return {}

    def _save_tree_cache(self):
        try:
            with open(self.cache_file_path, "w", encoding="utf-8") as f:
                json.dump(self._tree_cache, f, indent=4)
        except Exception as ex:
            logger.error("Ошибка при _save_tree_cache: " + str(ex))

    def _find_dist_info_path(self, package_name_canon: NormalizedName):
        cached = self._dist_info_cache.get(package_name_canon)
        if cached is not None:
            return cached
        if not os.path.exists(self.libs_path):
            logger.warning(f"Директория {self.libs_path} не существует для поиска dist-info.")
            self._dist_info_cache[package_name_canon] = None
            return None
        logger.debug(f"Сканирование {self.libs_path} для {package_name_canon}")
        for item in os.listdir(self.libs_path):
            if item.endswith(".dist-info"):
                try:
                    dist_name = item.split("-")[0]
                    if canonicalize_name(dist_name) == package_name_canon:
                        p = os.path.join(self.libs_path, item)
                        self._dist_info_cache[package_name_canon] = p
                        logger.debug(f"Найден dist-info для {package_name_canon}: {p}")
                        return p
                except Exception as ex:
                    logger.debug(f"Пропуск повреждённого dist-info {item}: {ex}")
                    continue
        self._dist_info_cache[package_name_canon] = None
        return None

    def _get_package_version(self, package_name_canon: NormalizedName):
        dist_path = self._find_dist_info_path(package_name_canon)
        if not dist_path:
            return None
        try:
            parts = os.path.basename(dist_path).split("-")
            if len(parts) >= 2 and parts[-1] == "dist-info":
                v = parts[-2]
                if v and v[0].isdigit():
                    return str(parse_version(v))
        except Exception as ex:
            logger.error("Ошибка при _get_package_version: " + str(ex))
        meta = os.path.join(dist_path, "METADATA")
        if os.path.exists(meta):
            try:
                with open(meta, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.lower().startswith("version:"):
                            return line.split(":", 1)[1].strip()
            except Exception as ex:
                logger.error("Ошибка при _get_package_version (METADATA): " + str(ex))
        return None

    def _get_direct_dependencies(self, package_name_canon: NormalizedName):
        cached = self._dep_cache.get(package_name_canon)
        if cached is not None:
            return cached
        deps: set[NormalizedName] = set()
        dist_path = self._find_dist_info_path(package_name_canon)
        if dist_path:
            meta = os.path.join(dist_path, "METADATA")
            if os.path.exists(meta):
                try:
                    with open(meta, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.lower().startswith("requires-dist:"):
                                req_str = line.split(":", 1)[1].strip()
                                try:
                                    req_part = req_str.split(";")[0].strip()
                                    if req_part:
                                        deps.add(canonicalize_name(Requirement(req_part).name))
                                except Exception as ex:
                                    logger.error("Ошибка парсинга requires-dist: " + str(ex))
                except Exception as ex:
                    logger.error("Ошибка чтения METADATA: " + str(ex))
        self._dep_cache[package_name_canon] = deps
        logger.debug(f"Direct deps for {package_name_canon}: {deps}")
        return deps

    def get_dependency_tree(self, root_package_name: str):
        root_canon = canonicalize_name(root_package_name)
        ver = self._get_package_version(root_canon)
        if not ver:
            if root_canon in self._tree_cache:
                del self._tree_cache[root_canon]
                self._save_tree_cache()
            return set()
        cached = self._tree_cache.get(root_canon)
        if cached and cached.get("version") == ver:
            return set(cached.get("dependencies", []))
        required: set[NormalizedName] = {root_canon}
        q: list[NormalizedName] = [root_canon]
        processed: set[NormalizedName] = set()
        self._dist_info_cache.clear()
        self._dep_cache.clear()
        while q:
            cur = q.pop(0)
            if cur in processed:
                continue
            processed.add(cur)
            for dep in self._get_direct_dependencies(cur):
                if dep not in required:
                    required.add(dep)
                    if dep not in processed:
                        q.append(dep)
        self._tree_cache[root_canon] = {"version": ver, "dependencies": sorted(required)}
        self._save_tree_cache()
        logger.debug(f"Dependency tree for {root_package_name}: {required}")
        return required

    def get_all_installed_packages(self):
        pkgs = set()
        if os.path.exists(self.libs_path):
            logger.debug(f"Сканирование всех пакетов в {self.libs_path}")
            for item in os.listdir(self.libs_path):
                if item.endswith(".dist-info"):
                    try:
                        pkg_name = canonicalize_name(item.split("-")[0])
                        pkgs.add(pkg_name)
                        logger.debug(f"Найден пакет: {pkg_name}")
                    except Exception as ex:
                        logger.error("Ошибка при get_all_installed_packages: " + str(ex))
        else:
            logger.warning(f"Директория {self.libs_path} не существует для get_all_installed_packages.")
        logger.debug(f"Все установленные пакеты: {pkgs}")
        return pkgs


class PipInstaller:
    def __init__(
        self,
        script_path: str,
        libs_path: str = "Lib",
        update_status=None,
        update_log=None,
        progress_window=None,
        update_progress=None,
        protected_packages: Optional[List[str]] = None
    ):
        self.script_path = script_path
        self.libs_path = libs_path
        self.python_root = Path(script_path).resolve().parent
        self.libs_path_abs = os.path.abspath(self.libs_path)
        self.update_status = update_status or (lambda m: logger.info(f"STATUS: {m}"))
        self.update_log = update_log or (lambda m: logger.info(f"LOG: {m}"))
        self.update_progress = update_progress or (lambda *_: None)
        self.progress_window = progress_window
        # Защищенные пакеты по умолчанию
        self.protected_packages = protected_packages or ["g4f", "gigaam", "pillow", "silero-vad"]
        self._ensure_libs_path()

    def install_package(self, package_spec, description="Установка пакета...", extra_args=None) -> bool:
        cmd = [
            self.script_path, "-m", "uv", "pip", "install",
            "--target", str(self.libs_path_abs),
            "--no-cache-dir"
        ]
        if extra_args:
            cmd.extend(extra_args)
        if isinstance(package_spec, list):
            cmd.extend(package_spec)
        else:
            cmd.append(package_spec)
        return self._run_pip_process(cmd, description)

    def _unload_module_from_sys(self, module_name: str):
        """Выгружает модуль и все его подмодули из sys.modules"""
        to_remove = []
        for loaded_name in list(sys.modules.keys()):
            if loaded_name == module_name or loaded_name.startswith(module_name + "."):
                to_remove.append(loaded_name)
        alt_name = module_name.replace("-", "_") if "-" in module_name else module_name.replace("_", "-")
        if alt_name != module_name:
            for loaded_name in list(sys.modules.keys()):
                if loaded_name == alt_name or loaded_name.startswith(alt_name + "."):
                    to_remove.append(loaded_name)
        for mod_name in to_remove:
            try:
                if mod_name in sys.modules:
                    self.update_log(f"Выгружаем модуль из памяти: {mod_name}")
                    del sys.modules[mod_name]
            except Exception as e:
                logger.warning(f"Не удалось выгрузить модуль {mod_name}: {e}")
        gc.collect()

    def _is_protected_dependency(self, package_canon: NormalizedName, protected_deps: Set[NormalizedName]) -> bool:
        """Проверяет, является ли пакет защищенной зависимостью"""
        return package_canon in protected_deps

    def uninstall_packages(self, packages: List[str], description="Удаление пакетов...") -> bool:
        if not packages:
            self.update_log("Список пакетов для удаления пуст.")
            return True

        resolver = DependencyResolver(self.libs_path_abs, self.update_log)
        requested: Set[NormalizedName] = {canonicalize_name(p) for p in packages}
        
        main_packages_to_remove = packages.copy()
        self.update_log(f"Запрошено удаление пакетов: {main_packages_to_remove}")

        protected_canon = {canonicalize_name(p) for p in self.protected_packages}
        protected_deps: Set[NormalizedName] = set()
        
        all_installed = resolver.get_all_installed_packages()
        
        for prot_pkg in self.protected_packages:
            prot_canon = canonicalize_name(prot_pkg)
            if prot_canon in all_installed:
                deps = resolver.get_dependency_tree(prot_pkg) or {prot_canon}
                protected_deps.update(deps)
                self.update_log(f"Защищенный пакет {prot_pkg} и его зависимости: {deps}")

        candidates: Set[NormalizedName] = set()
        for pkg in requested:
            candidates.update(resolver.get_dependency_tree(str(pkg)))
        candidates.update(requested)
        
        final_remove = sorted(candidates - protected_deps)
        
        self.update_log(f"Кандидаты на удаление (исключая защищенные): {final_remove}")

        if not final_remove:
            self.update_log("Нечего удалять: все пакеты либо защищены, либо не найдены.")
            return True

        main_packages_removed = []
        dependencies_failed = []
        
        self.update_log("Выгружаем модули из памяти...")
        for pkg in final_remove:
            if not self._is_protected_dependency(canonicalize_name(pkg), protected_deps):
                self._unload_module_from_sys(str(pkg))

        for pkg in final_remove:
            canon = canonicalize_name(pkg)
            is_main_package = str(pkg) in main_packages_to_remove or canon in requested
            dist_path = self._find_dist_info_path(canon)
            if dist_path:
                cmd = [
                    self.script_path, "-m", "uv", "pip", "uninstall",
                    "--target", str(self.libs_path_abs), str(pkg)
                ]
                success = self._run_pip_process(cmd, f"Удаление {pkg}")
                if not success:
                    self.update_log(f"uv pip не смог удалить {pkg}, пробуем ручное удаление...")
                    success = self._manual_remove(dist_path, str(pkg))
                if success and is_main_package:
                    main_packages_removed.append(str(pkg))
                elif not success and not is_main_package:
                    dependencies_failed.append(str(pkg))
                elif not success and is_main_package:
                    self.update_log(f"ОШИБКА: Не удалось удалить основной пакет {pkg}")
                    return False
            else:
                self.update_log(f"{pkg}: dist-info не найден, считаем удалённым.")
                if is_main_package:
                    main_packages_removed.append(str(pkg))

        if main_packages_removed:
            self.update_log(f"Успешно удалены основные пакеты: {main_packages_removed}")
            if dependencies_failed:
                self.update_log(f"Некоторые зависимости не удалились (это нормально): {dependencies_failed}")
            self.update_log("Удаление завершено успешно.")
            return True
        else:
            self.update_log("ОШИБКА: Не удалось удалить ни одного основного пакета.")
            return False

    def _manual_remove(self, path: str, pkg_name: str) -> bool:
        if not os.path.exists(path):
            return True

        retries = 5
        wait = [0.5, 1, 2, 3, 5]
        for attempt in range(retries):
            try:
                shutil.rmtree(path, ignore_errors=False)
                if not os.path.exists(path):
                    logger.info(f"{pkg_name}: каталог {path} удалён.")
                    return True
            except Exception as ex:
                logger.warning(
                    f"{pkg_name}: не удалось удалить (попытка {attempt+1}/{retries}): {ex}"
                )
                self._unload_module_from_sys(pkg_name)
                gc.collect()
                time.sleep(wait[attempt])
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass
        if os.path.exists(path):
            logger.error(f"{pkg_name}: не удалось удалить каталог {path} после всех попыток.")
            return False
        logger.info(f"{pkg_name}: каталог {path} удалён после нескольких попыток.")
        return True

    def _find_dist_info_path(self, package_name_canon: NormalizedName) -> str | None:
        if not os.path.exists(self.libs_path_abs):
            return None
        for item in os.listdir(self.libs_path_abs):
            if item.endswith(".dist-info"):
                try:
                    dist_name = item.split("-")[0]
                    if canonicalize_name(dist_name) == package_name_canon:
                        return os.path.join(self.libs_path_abs, item)
                except Exception:
                    continue
        return None

    def _ensure_libs_path(self):
        os.makedirs(self.libs_path_abs, exist_ok=True)
        if self.libs_path_abs not in sys.path:
            sys.path.insert(0, self.libs_path_abs)

    # ------------------------ Новый, разбитый раннер UV/PIP ------------------------

    class _RunState:
        def __init__(self, description: str, cmd: List[str]):
            self.description = description
            self.cmd = cmd
            self.cmd_str_low = " ".join(cmd).lower()
            self.start = time.time()
            self.last_activity = self.start
            self.last_status_emit = self.start
            self.last_status_message: Optional[str] = None
            self.percent: int = 0
            self.history: Deque[tuple[float, int]] = deque(maxlen=180)
            self.history.append((self.start, 0))
            self.error_seen: bool = False
            self.is_pytorch_install: bool = (
                ("download.pytorch.org" in self.cmd_str_low)
                or ("torch" in self.cmd_str_low and "install" in self.cmd_str_low)
            )
            self.torch_hint_logged: bool = False

    # Настройки времени/таймаутов
    STALL_INFO_SEC = 10
    STALL_HINT_SEC = 60
    TIMEOUT_SEC = 7200000   # как было ранее (очень большой общий таймаут)
    NO_ACTIVITY_SEC = 3600000

    _RE_PCT = re.compile(r'(\d{1,3})\s?%')
    _RE_PAIR = re.compile(
        r'(?P<done>\d+(?:\.\d+)?)\s*(?P<dunit>[KMGTP]?i?B|B)\s*/\s*'
        r'(?P<total>\d+(?:\.\d+)?)\s*(?P<tunit>[KMGTP]?i?B|B)',
        re.IGNORECASE
    )
    _ANSI_RE = re.compile(r'\x1b(?:\[.*?[@-~]|\].*?(?:\x1b\\|\x07))')

    @staticmethod
    def _unit_mul(unit: str) -> int:
        u = unit.upper()
        dec = {"B":1,"KB":1000,"MB":1000**2,"GB":1000**3,"TB":1000**4,"PB":1000**5}
        bin_ = {"KIB":1024,"MIB":1024**2,"GIB":1024**3,"TIB":1024**4,"PIB":1024**5}
        return bin_.get(u, dec.get(u, 1))

    @staticmethod
    def _fmt_hms(seconds: float) -> str:
        seconds = int(max(0, seconds))
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    @classmethod
    def _clean_line(cls, s: str) -> str:
        if not s:
            return ""
        return cls._ANSI_RE.sub('', s).replace("\x1b", "")

    def _prepare_env(self) -> dict:
        env = os.environ.copy()
        env.setdefault("PIP_PROGRESS_BAR", "on")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("NO_COLOR", "1")
        env.setdefault("CLICOLOR", "0")
        env.setdefault("FORCE_COLOR", "0")
        env.setdefault("PY_COLORS", "0")
        env.setdefault("TERM", "dumb")
        return env

    def _detect_pty(self) -> Tuple[bool, Optional[object]]:
        # Упрощённо: используем PTY только на Windows (если есть pywinpty/winpty)
        is_windows = os.name == "nt"
        uv_tty_env = os.environ.get("UV_TTY")
        if uv_tty_env == "0":
            return False, None

        PtyProcess = None
        if is_windows:
            try:
                from pywinpty import PtyProcess as _PtyProcess
                PtyProcess = _PtyProcess
            except Exception:
                try:
                    import winpty  # type: ignore
                    PtyProcess = winpty.PtyProcess  # type: ignore
                except Exception:
                    PtyProcess = None

        if uv_tty_env == "1":
            return PtyProcess is not None, PtyProcess

        # По умолчанию — PTY только если реально доступен на Windows
        return PtyProcess is not None, PtyProcess

    def _process_line(self, state: _RunState, line: str):
        if not line:
            return
        clean = self._clean_line(line.rstrip())
        if not clean:
            return

        low = clean.lower()
        if any(k in low for k in ("error", "ошибка", "failed", "traceback", "exception", "critical")):
            logger.error(clean)
            self.update_log(clean)
            state.error_seen = True
        else:
            # Попробуем вытащить проценты
            m = self._RE_PCT.search(clean)
            if m:
                try:
                    pct = max(0, min(100, int(m.group(1))))
                    if pct > state.percent:
                        state.percent = min(99, pct)  # не прыгать на 100 до конца
                        self.update_progress(state.percent)
                        state.history.append((time.time(), state.percent))
                except Exception:
                    pass

            # Попробуем вытащить отношение done/total
            m2 = self._RE_PAIR.search(clean)
            if m2:
                try:
                    d = float(m2.group("done"))  * self._unit_mul(m2.group("dunit"))
                    T = float(m2.group("total")) * self._unit_mul(m2.group("tunit"))
                    if T > 0:
                        pct2 = int(round(d / T * 100))
                        if pct2 > state.percent:
                            state.percent = min(99, max(0, pct2))
                            self.update_progress(state.percent)
                            state.history.append((time.time(), state.percent))
                except Exception:
                    pass

            self.update_log(clean)

        state.last_activity = time.time()

    def _update_status_if_needed(self, state: _RunState):
        now = time.time()
        if now - state.last_status_emit < 0.5:
            return

        eta_txt = ""
        if len(state.history) >= 2 and state.percent >= 3:
            t0, p0 = state.history[0]
            dt = now - t0
            dp = state.percent - p0
            if dt > 0 and dp > 0:
                eta_sec = int(max(0.0, (100.0 - state.percent)) / (dp / dt))
                eta_txt = f" (ETA {self._fmt_hms(eta_sec)})"

        stalled_sec = int(now - state.last_activity)
        msg = f"{state.description} — {state.percent}%"
        if eta_txt:
            msg += eta_txt
        elif stalled_sec >= self.STALL_INFO_SEC:
            msg += f" (нет вывода {stalled_sec} с, процесс работает)"

        if msg != state.last_status_message:
            self.update_status(msg)
            state.last_status_message = msg

        # Подсказка для больших бинарей PyTorch
        if state.is_pytorch_install and (stalled_sec >= self.STALL_HINT_SEC) and not state.torch_hint_logged:
            self.update_log("Похоже, идёт загрузка больших бинарников PyTorch. Это может занимать длительное время без вывода.")
            state.torch_hint_logged = True

        state.last_status_emit = now

    def _pump_events(self):
        app = QCoreApplication.instance()
        if app and QThread.currentThread() == app.thread():
            QApplication.processEvents()

    def _terminate_process(self, proc, reason: str):
        try:
            self.update_log(reason)
            proc.terminate()
            time.sleep(0.5)
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass

    def _run_with_pipes(self, cmd: List[str], env: dict, state: _RunState) -> Tuple[bool, int]:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env=env
            )
        except FileNotFoundError:
            self.update_log("ОШИБКА: не найден интерпретатор Python.")
            self.update_status(state.description + " — ошибка.")
            return False, -1
        except Exception as e:
            self.update_log(f"ОШИБКА запуска subprocess: {e}")
            self.update_status(state.description + " — ошибка.")
            return False, -1

        q_out, q_err = queue.Queue(), queue.Queue()

        def _reader(pipe, q):
            try:
                for line in iter(pipe.readline, ""):
                    q.put(line.rstrip())
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        threading.Thread(target=_reader, args=(proc.stdout, q_out), daemon=True).start()
        threading.Thread(target=_reader, args=(proc.stderr, q_err), daemon=True).start()

        while proc.poll() is None:
            processed_any = False
            while not q_out.empty():
                line = q_out.get_nowait()
                self._process_line(state, line)
                processed_any = True
            while not q_err.empty():
                line = q_err.get_nowait()
                self._process_line(state, line)
                processed_any = True

            if processed_any:
                # Плавное движение прогресса, если ничто не пишет проценты
                if state.percent < 95:
                    # Не дергаем часто — история сама обновится при _process_line
                    pass

            # Обновим статус по таймеру
            self._update_status_if_needed(state)

            now = time.time()
            if now - state.last_activity > self.NO_ACTIVITY_SEC:
                self._terminate_process(proc, "Процесс неактивен слишком долго, прерываем.")
                self.update_status(state.description + " — прервано по таймауту неактивности.")
                return False, -1

            if now - state.start > self.TIMEOUT_SEC:
                self._terminate_process(proc, "Таймаут процесса истёк, прерываем.")
                self.update_status(state.description + " — прервано по общему таймауту.")
                return False, -1

            self._pump_events()
            time.sleep(0.03)

        # Дочистим очереди
        while not q_out.empty():
            self._process_line(state, q_out.get_nowait())
        while not q_err.empty():
            self._process_line(state, q_err.get_nowait())

        return True, (proc.returncode or 0)

    def _run_with_winpty(self, cmd: List[str], env: dict, state: _RunState, PtyProcess) -> Tuple[bool, int]:
        # На Windows запускаем команду через winpty/pywinpty и читаем как текстовый поток
        try:
            try:
                cmdline = subprocess.list2cmdline(cmd)
            except Exception:
                import shlex
                cmdline = " ".join(shlex.quote(c) if " " in c else c for c in cmd)

            # В PtyProcess.spawn нельзя напрямую передать env, поэтому используем cmdline
            pty = PtyProcess.spawn(cmdline)
        except Exception as e:
            logger.warning(f"PTY-режим недоступен или ошибка запуска PTY: {e}")
            return False, -1

        buffer = ""
        while pty.isalive():
            try:
                chunk = pty.read(4096)
            except Exception:
                chunk = ""

            if chunk:
                if isinstance(chunk, bytes):
                    try:
                        chunk = chunk.decode("utf-8", errors="ignore")
                    except Exception:
                        chunk = chunk.decode("cp1251", errors="ignore")
                buffer += chunk
                parts = re.split(r'(\r|\n)', buffer)
                buffer = ""
                acc = ""
                i = 0
                while i < len(parts):
                    tok = parts[i]
                    if tok in ("\r", "\n"):
                        line = acc.strip()
                        if line:
                            self._process_line(state, line)
                        acc = ""
                    else:
                        acc += tok
                    i += 1
                buffer = acc

            # Обновим статус
            self._update_status_if_needed(state)

            now = time.time()
            if now - state.last_activity > self.NO_ACTIVITY_SEC:
                try:
                    pty.close(force=True)
                except Exception:
                    pass
                self.update_log("Процесс неактивен слишком долго, прерываем.")
                self.update_status(state.description + " — прервано по таймауту неактивности.")
                return False, -1

            if now - state.start > self.TIMEOUT_SEC:
                try:
                    pty.close(force=True)
                except Exception:
                    pass
                self.update_log("Таймаут процесса истёк, прерываем.")
                self.update_status(state.description + " — прервано по общему таймауту.")
                return False, -1

            self._pump_events()
            time.sleep(0.03)

        ret = pty.exitstatus or 0
        return True, ret

    def _run_pip_process(self, cmd: List[str], description: str) -> bool:
        """
        Упрощённый запуск UV/PIP:
        - Без снапшотов и специальных маркеров.
        - Поддержка PTY только на Windows (если доступен winpty/pywinpty), иначе — стандартные пайпы.
        - Прогресс/ETA извлекаются из процентов или done/total; при их отсутствии — оценка по тренду.
        """
        state = self._RunState(description, cmd)
        env = self._prepare_env()

        self.update_status(description)
        self.update_log("Выполняем: " + " ".join(cmd))

        use_pty, PtyProcess = self._detect_pty()
        ok, ret = False, -1

        if use_pty and PtyProcess is not None and os.name == "nt":
            ok, ret = self._run_with_winpty(cmd, env, state, PtyProcess)
            if not ok:
                # Фоллбэк на пайпы
                ok, ret = self._run_with_pipes(cmd, env, state)
        else:
            ok, ret = self._run_with_pipes(cmd, env, state)

        # Завершение
        elapsed = time.time() - state.start
        self.update_status(f"{description} — завершено за {self._fmt_hms(elapsed)}")

        is_uninstall = any("uninstall" == x for x in cmd) or "uninstall" in " ".join(cmd).lower()
        if is_uninstall and ret in (1, 2):
            logger.info(f"UV вернул код {ret} при удалении - возможно пакет не был установлен")
            self.update_progress(100)
            return True
            
        if not ok or ret != 0:
            err_msg = f"ОШИБКА: Процесс завершился с кодом {ret}. Проверьте лог выше."
            if not state.error_seen:
                self.update_log(err_msg)
            # Принудительно пишем в основной логгер
            logger.error(f"pip завершился с ошибкой, код {ret}. Команда: {cmd}")
            return False
        
        self.update_progress(100)
        self.update_log(f"pip завершился успешно (код {ret})")
        return True