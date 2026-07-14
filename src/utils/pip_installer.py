"""
PipInstaller 3.1 — упрощённый PTY/Pipes-раннер без снапшотов.
"""

from __future__ import annotations

import gc
import json
import locale
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, NormalizedName
from packaging.version import parse as parse_version
from main_logger import logger
from typing import Set, List, Tuple, Optional, Deque
from collections import deque
from core.app_paths import base_dir
from core.task_supervisor import task_supervisor
from core.install_types import DEFAULT_INSTALL_NO_ACTIVITY_SEC, DEFAULT_INSTALL_TIMEOUT_SEC


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
    DIST_MODULE_ALIASES = {
        "beat-this": ("beat_this",),
        "rotary-embedding-torch": ("rotary_embedding_torch",),
        "scikit-learn": ("sklearn",),
        "charset-normalizer": ("charset_normalizer",),
        "typing-extensions": ("typing_extensions",),
        "pillow": ("PIL",),
        "pyyaml": ("yaml",),
        "opencv-python": ("cv2",),
        "tts-with-rvc": ("tts_with_rvc",),
        "tts-with-rvc-onnx": ("tts_with_rvc_onnx", "tts_with_rvc"),
    }


    def __init__(
        self,
        update_status=None,
        update_log=None,
        progress_window=None,
        update_progress=None,
        update_raw_log=None,
        protected_packages: Optional[List[str]] = None,
        target_path: str | os.PathLike[str] | None = None,
    ):
        self.script_path = os.environ.get("NEUROMITA_PYTHON", sys.executable)
        self.libs_path = os.fspath(target_path) if target_path is not None else os.environ.get("NEUROMITA_LIB_DIR", "Lib")
        self.python_root = Path(self.script_path).resolve().parent
        self.libs_path_abs = os.path.abspath(self.libs_path)
        self.update_status = update_status or (lambda m: logger.info(f"STATUS: {m}"))
        self.update_log = update_log or (lambda m: logger.info(f"LOG: {m}"))
        self.update_raw_log = update_raw_log or (lambda *_: None)
        self.update_progress = update_progress or (lambda *_: None)
        self.progress_window = progress_window
        # Защищенные пакеты по умолчанию
        self.protected_packages = protected_packages or ["g4f", "gigaam", "pillow", "silero-vad"]
        self._preferred_installer_cmd: Optional[List[str]] = None
        self._uv_probe_complete: bool = False
        self._uv_available: bool = False
        self._last_run_uv_cache_access_denied: bool = False
        self._last_run_returncode: int = 0
        self._last_run_recent_lines: List[str] = []
        self._cancel_event = threading.Event()
        self._active_process_lock = threading.RLock()
        self._active_process = None
        self._active_process_killer = None
        # Однократная проверка доступности pywinpty для живого PTY-вывода.
        self._pty_bootstrap_attempted: bool = False
        self._ensure_libs_path()

    def install_package(self, package_spec, description="Установка пакета...", extra_args=None) -> bool:
        self._maybe_warn_fragile_location()
        self.repair_broken_target_metadata()
        return self._install_package_attempt(
            package_spec,
            description=description,
            extra_args=extra_args,
        )

    def _build_dependency_overrides(self, package_spec) -> List[str]:
        return []

    def _adapt_extra_args(self, extra_args, is_uv: bool) -> List[str]:
        """Translate installer-specific flags so a uv-targeted extra_args list
        still works when we fall back to the built-in pip (and vice versa).

        The backend passes uv's `--reinstall`; pip only understands
        `--force-reinstall`. Without this translation the CPU->CUDA reinstall
        crashed with `no such option: --reinstall` whenever uv was missing."""
        if not extra_args:
            return []
        result: List[str] = []
        for arg in extra_args:
            a = str(arg)
            if not is_uv and a == "--reinstall":
                result.append("--force-reinstall")
            elif is_uv and a == "--force-reinstall":
                result.append("--reinstall")
            else:
                result.append(a)
        return result

    def install_package_with_overrides(
        self,
        package_spec,
        description="Installing package...",
        extra_args=None,
        uv_overrides: Optional[List[str]] = None,
    ) -> bool:
        self._maybe_warn_fragile_location()
        self.repair_broken_target_metadata()
        # Runtime packages are installed by one resolver only. The embedded
        # pip is reserved for bootstrapping the private uv executable and is
        # never a fallback for a failed dependency resolution.
        return self._install_package_attempt(
            package_spec,
            description=description,
            extra_args=extra_args,
            uv_overrides=uv_overrides,
        )

    def _install_package_attempt(
        self,
        package_spec,
        *,
        description: str,
        extra_args=None,
        uv_overrides: Optional[List[str]] = None,
    ) -> bool:
        cmd = self._build_install_command()
        is_uv = self._is_uv_command(cmd)
        requirement_file_path: str | None = None
        try:
            if extra_args:
                cmd.extend(self._adapt_extra_args(extra_args, is_uv))

            if uv_overrides is None:
                effective_overrides = self._build_dependency_overrides(package_spec) if is_uv else []
            else:
                effective_overrides = self._dedupe_overrides(list(uv_overrides or []))
            if effective_overrides:
                requirement_file_path = self._write_requirement_file(
                    effective_overrides,
                    prefix="neuromita_uv_overrides_" if is_uv else "neuromita_pip_constraints_",
                )
                cmd.extend([
                    "--overrides" if is_uv else "--constraint",
                    requirement_file_path,
                ])

            if isinstance(package_spec, list):
                cmd.extend(package_spec)
            else:
                cmd.append(package_spec)
            return self._run_pip_process(cmd, description)
        finally:
            if requirement_file_path:
                try:
                    os.unlink(requirement_file_path)
                except OSError:
                    pass

    def install_environment_lock(
        self,
        direct_specs: List[str],
        *,
        core_overrides: Optional[List[str]] = None,
        core_packages: Optional[List[str]] = None,
        extra_args: Optional[List[str]] = None,
        description: str = "Resolving environment dependencies...",
    ) -> bool:
        """Resolve once, omit shared core packages, then materialize the overlay.

        The lock contains every non-core transitive dependency with an exact
        version. Shared torch/ONNX distributions are used only as resolver
        overrides and are omitted from the overlay output, so large runtimes are
        neither downloaded nor copied into every feature environment.
        """
        specs = [str(item).strip() for item in direct_specs or [] if str(item).strip()]
        if not specs:
            return True

        input_path = self._write_requirement_file(specs, prefix="neuromita_environment_in_")
        lock_fd, lock_path = tempfile.mkstemp(
            prefix="neuromita_environment_lock_", suffix=".txt", text=True
        )
        os.close(lock_fd)
        override_path: str | None = None
        try:
            uv_base = self._resolve_installer_base_cmd()
            uv_root = list(uv_base[:-1]) if uv_base and uv_base[-1] == "pip" else list(uv_base)
            compile_cmd = uv_root + [
                "pip",
                "compile",
                input_path,
                "--output-file",
                lock_path,
                "--python",
                str(self.script_path),
                "--no-header",
                "--no-annotate",
            ]
            overrides = self._dedupe_overrides(list(core_overrides or []))
            if overrides:
                override_path = self._write_requirement_file(
                    overrides, prefix="neuromita_environment_overrides_"
                )
                compile_cmd.extend(["--overrides", override_path])

            for package_name in sorted(
                {canonicalize_name(str(name)) for name in (core_packages or []) if str(name).strip()}
            ):
                compile_cmd.extend(["--no-emit-package", package_name])

            # Only resolver/index options are meaningful during compile. Runtime
            # flags such as --upgrade are intentionally ignored for immutable
            # staging environments.
            allowed_prefixes = (
                "--index-url",
                "--extra-index-url",
                "--find-links",
                "--no-index",
                "--prerelease",
                "--index-strategy",
            )
            raw_extra = list(extra_args or [])
            index = 0
            while index < len(raw_extra):
                value = str(raw_extra[index])
                if value.startswith(allowed_prefixes):
                    compile_cmd.append(value)
                    if "=" not in value and value not in {"--no-index"} and index + 1 < len(raw_extra):
                        index += 1
                        compile_cmd.append(str(raw_extra[index]))
                index += 1

            if not self._run_pip_process(compile_cmd, description):
                return False

            install_cmd = self._build_install_command()
            install_cmd.extend(["--no-deps", "-r", lock_path])
            return self._run_pip_process(install_cmd, "Installing resolved environment...")
        finally:
            for path in (input_path, lock_path, override_path):
                if not path:
                    continue
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def _requested_dist_names(self, package_spec) -> Set[NormalizedName]:
        specs = package_spec if isinstance(package_spec, list) else [package_spec]
        names: Set[NormalizedName] = set()
        for spec in specs:
            value = str(spec or "").strip()
            if not value:
                continue
            try:
                req = Requirement(value)
                names.add(canonicalize_name(req.name))
            except Exception:
                names.add(canonicalize_name(value.split(";", 1)[0].strip()))
        return names

    def _dedupe_overrides(self, overrides: List[str]) -> List[str]:
        seen_names: set[str] = set()
        seen_raw: set[str] = set()
        result: List[str] = []
        for item in overrides:
            value = str(item or "").strip()
            if not value:
                continue
            try:
                key = canonicalize_name(Requirement(value).name)
            except Exception:
                raw_key = value.lower()
                if raw_key in seen_raw:
                    continue
                seen_raw.add(raw_key)
                result.append(value)
                continue
            if key in seen_names:
                continue
            seen_names.add(key)
            result.append(value)
        return result


    def _is_uv_command(self, cmd: List[str]) -> bool:
        parts = [str(p).lower() for p in cmd]
        if not parts:
            return False
        # Module form: python -m uv ...
        for i, p in enumerate(parts):
            if p == "-m" and i + 1 < len(parts) and parts[i + 1] == "uv":
                return True
        # Executable form: .../uv.exe pip ... or uv pip ...
        exe = os.path.basename(parts[0])
        return exe in ("uv", "uv.exe")

    def _write_requirement_file(self, requirements: List[str], *, prefix: str) -> str:
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=".txt", text=True)
        lines = [str(item).strip() for item in requirements or [] if str(item).strip()]
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines))
            fh.write("\n")
        return path

    def _write_uv_overrides(self, overrides: List[str]) -> str:
        path = self._write_requirement_file(overrides, prefix="neuromita_uv_overrides_")
        self.update_log(f"Using uv dependency overrides: {path}")
        return path

    def missing_specs(self, specs: List[str]) -> List[str]:
        missing: List[str] = []
        for spec in specs or []:
            value = str(spec or "").strip()
            if not value:
                continue
            if not self.is_spec_satisfied_in_target(value):
                missing.append(value)
        return missing

    def is_spec_satisfied_in_target(self, spec: str) -> bool:
        try:
            req = Requirement(spec)
        except Exception:
            req = None

        try:
            if req is not None and req.marker is not None and not req.marker.evaluate():
                return True
        except Exception:
            pass

        dist_name = req.name if req is not None else spec.split(";", 1)[0].strip()
        version = self._target_dist_version(dist_name)
        if version is None:
            return False
        if req is not None and req.specifier:
            try:
                if not bool(req.specifier.contains(version, prereleases=True)):
                    return False
            except Exception:
                return False
        return self._target_module_exists_for_dist(dist_name)

    def _target_module_exists_for_dist(self, dist_name: str) -> bool:
        base = canonicalize_name(dist_name)
        if base == "sentencepiece":
            package_dir = os.path.join(self.libs_path_abs, "sentencepiece")
            if not os.path.isfile(os.path.join(package_dir, "__init__.py")):
                return False
            try:
                return any(
                    name.startswith("_sentencepiece") and name.endswith((".pyd", ".so", ".dll"))
                    for name in os.listdir(package_dir)
                )
            except OSError:
                return False

        candidates: list[str] = []
        dist_info = self._target_dist_info_path(dist_name)
        if dist_info is not None:
            top_level = dist_info / "top_level.txt"
            if top_level.is_file():
                try:
                    candidates.extend(
                        line.strip()
                        for line in top_level.read_text(encoding="utf-8", errors="ignore").splitlines()
                        if line.strip() and not line.lstrip().startswith("#")
                    )
                except OSError:
                    pass
            if not candidates:
                record = dist_info / "RECORD"
                if record.is_file():
                    try:
                        for line in record.read_text(encoding="utf-8", errors="ignore").splitlines():
                            rel = line.split(",", 1)[0].replace("\\", "/").lstrip("./")
                            if not rel or ".dist-info/" in rel or ".data/" in rel:
                                continue
                            first = rel.split("/", 1)[0]
                            if first.endswith(".py"):
                                first = first[:-3]
                            if first and first not in candidates:
                                candidates.append(first)
                    except OSError:
                        pass
        candidates.extend(self.DIST_MODULE_ALIASES.get(base, (base.replace("-", "_"),)))
        if not os.path.isdir(self.libs_path_abs):
            return False
        for module_name in candidates:
            value = str(module_name or "").strip()
            if not value:
                continue
            parts = value.split(".")
            first = parts[0]
            if os.path.isdir(os.path.join(self.libs_path_abs, first)):
                return True
            if os.path.isfile(os.path.join(self.libs_path_abs, first + ".py")):
                return True
        return False

    def _target_dist_info_path(self, dist_name: str) -> Optional[Path]:
        if not dist_name or not os.path.isdir(self.libs_path_abs):
            return None
        wanted = canonicalize_name(dist_name)
        for item in os.listdir(self.libs_path_abs):
            if not item.endswith(".dist-info"):
                continue
            path = Path(self.libs_path_abs) / item
            metadata_path = path / "METADATA"
            name: Optional[str] = None
            if metadata_path.is_file():
                try:
                    for line in metadata_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.lower().startswith("name:"):
                            name = line.split(":", 1)[1].strip()
                            break
                except OSError:
                    pass
            if name is None:
                name = item.rsplit(".dist-info", 1)[0].split("-", 1)[0]
            if canonicalize_name(name) == wanted:
                return path
        return None

    def _target_dist_version(self, dist_name: str) -> Optional[str]:
        if not dist_name or not os.path.isdir(self.libs_path_abs):
            return None

        wanted = canonicalize_name(dist_name)
        for item in os.listdir(self.libs_path_abs):
            if not item.endswith(".dist-info"):
                continue
            metadata_path = os.path.join(self.libs_path_abs, item, "METADATA")
            name: Optional[str] = None
            version: Optional[str] = None

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
                    name = None
                    version = None

            if name is None:
                name = item.rsplit(".dist-info", 1)[0].split("-", 1)[0]
            if canonicalize_name(name) != wanted:
                continue
            if version:
                return version
            logger.warning(
                f"Broken dist-info detected for '{dist_name}' in target Lib: "
                f"missing/unreadable METADATA at {metadata_path}"
            )
            return None
        return None

    def _build_install_command(self) -> List[str]:
        base = list(self._resolve_installer_base_cmd())
        base.extend(
            [
                "install",
                "--target",
                str(self.libs_path_abs),
                "--python",
                str(self.script_path),
            ]
        )
        # Кэш включён по умолчанию: после обрыва (диск/VPN) повторная попытка
        # переиспользует уже скачанное и докачивает, а не качает всё заново.
        # Отключается настройкой INSTALL_USE_CACHE (кэш чистится кнопкой в AI Hub).
        if not self._use_cache():
            base.append("--no-cache-dir")
        return base

    def _use_cache(self) -> bool:
        try:
            from managers.settings_manager import SettingsManager
            return bool(SettingsManager.get("INSTALL_USE_CACHE", True))
        except Exception:
            return True

    def _uv_base_cmd(self) -> List[str]:
        # БЕЗ --verbose: в verbose-режиме uv переключается на DEBUG-логирование и
        # глушит свои живые прогресс-бары (indicatif) → в вывод не идут байтовые
        # пары done/total и скорость, все бары в AI Hub остаются пустыми и висит
        # «Ожидание данных о размере пакетов…». Без verbose uv под PTY рисует
        # живой прогресс, а строки-вехи (Resolved/Prepared/Installed) и ошибки
        # разрешения печатаются в обоих режимах — диагностика при падении не теряется.
        return [str(self._uv_executable_path()), "pip"]

    def _pip_base_cmd(self) -> List[str]:
        return [self.script_path, "-m", "pip", "--isolated"]

    def _uv_executable_path(self) -> Path:
        return (
            base_dir()
            / ".bootstrap"
            / "uv"
            / "bin"
            / ("uv.exe" if os.name == "nt" else "uv")
        )

    def _uv_target_path(self) -> Path:
        return base_dir() / ".bootstrap" / "uv"

    def _ensure_pip_available(self) -> bool:
        pip_cmd = self._pip_base_cmd()
        if self._check_installer_command(pip_cmd + ["--version"]):
            return True

        self.update_log("pip не найден во встроенном Python, запускаем ensurepip...")
        bootstrap_cmd = [self.script_path, "-m", "ensurepip", "--upgrade"]
        if not self._run_pip_process(bootstrap_cmd, "Восстановление pip..."):
            self.update_log("ОШИБКА: Не удалось восстановить pip через ensurepip.")
            return False
        return self._check_installer_command(pip_cmd + ["--version"])

    def _ensure_uv_available(self) -> bool:
        if self._uv_probe_complete:
            return self._uv_available

        self._uv_probe_complete = True
        uv_exe = self._uv_executable_path()
        if uv_exe.is_file() and self._check_installer_command([str(uv_exe), "--version"]):
            self._uv_available = True
            return True

        if not self._ensure_pip_available():
            self.update_log("uv недоступен: встроенный pip тоже не удалось подготовить.")
            return False

        target = self._uv_target_path()
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as exc:
                self.update_log(
                    f"Повреждённый приватный uv не удалось очистить ({exc}). "
                    "Установка остановлена: fallback на другой installer запрещён."
                )
                return False

        target.mkdir(parents=True, exist_ok=True)
        self.update_log(f"Устанавливаем приватный uv в {target}...")
        install_cmd = self._pip_base_cmd() + [
            "install",
            "--target",
            str(target),
            "--upgrade",
            "--force-reinstall",
            "--no-warn-script-location",
            "uv",
        ]
        if not self._run_pip_process(install_cmd, "Установка uv..."):
            self.update_log("Не удалось подготовить приватный uv. Установка остановлена.")
            return False
        if not uv_exe.is_file() or not self._check_installer_command([str(uv_exe), "--version"]):
            self.update_log("Приватный uv установился некорректно: исполняемый файл недоступен.")
            return False

        self._uv_available = True
        self.update_log("Приватный uv установлен и готов к работе.")
        return True

    def purge_cache(self, description: str = "Очистка кэша установщика...") -> bool:
        """Clear the pip/uv download cache (frees disk; resets resumable state)."""
        self.update_status(description)
        base = self._resolve_installer_base_cmd()
        if self._is_uv_command(base):
            root = [p for p in base if str(p).lower() != "pip"]
            cmd = root + ["cache", "clean"]
        else:
            cmd = list(base) + ["cache", "purge"]
        try:
            return bool(self._run_pip_process(cmd, description))
        except Exception as exc:
            self.update_log(f"Не удалось очистить кэш: {exc}")
            return False

        
    def _resolve_installer_base_cmd(self) -> List[str]:
        if self._preferred_installer_cmd is not None:
            return list(self._preferred_installer_cmd)

        uv_cmd = self._uv_base_cmd()
        if self._ensure_uv_available():
            self._preferred_installer_cmd = uv_cmd
            self.update_log("Для установки зависимостей выбран uv pip.")
            return list(self._preferred_installer_cmd)

        raise RuntimeError(
            "uv is unavailable and automatic installer fallback is disabled. "
            "Repair the private .bootstrap/uv installation and retry."
        )

    def _check_installer_command(self, cmd: List[str]) -> bool:
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
            )
            if proc.returncode == 0:
                return True

            details = (proc.stderr or proc.stdout or "").strip()
            if details:
                logger.warning(f"[installer] Probe command exited with code {proc.returncode}: {details}")
            return False
        except Exception as ex:
            logger.warning(f"[installer] Failed to probe installer command {cmd}: {ex}")
            return False

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

    def uninstall_packages(self, packages: List[str], description="Удаление пакетов...",
                           include_dependencies: bool = True) -> bool:
        # include_dependencies=False — удалять ТОЛЬКО перечисленные пакеты, без
        # раскрытия их дерева зависимостей. Нужно, когда пакеты делят общие зависимости
        # с другими компонентами (напр. faster-whisper тянет tokenizers/huggingface-hub/
        # onnxruntime/pyyaml, общие с transformers/RAG/onnx-движками): каскадное
        # удаление снесло бы их и сломало соседей. Вызывающий сам гарантирует, что
        # перечисленные пакеты эксклюзивны для его компонента.
        if not packages:
            self.update_log("Список пакетов для удаления пуст.")
            return True

        resolver = DependencyResolver(self.libs_path_abs, self.update_log)
        requested: Set[NormalizedName] = {canonicalize_name(p) for p in packages}

        main_packages_to_remove = packages.copy()
        self.update_log(f"Запрошено удаление пакетов: {main_packages_to_remove}")

        protected_deps: Set[NormalizedName] = set()

        all_installed = resolver.get_all_installed_packages()

        for prot_pkg in self.protected_packages:
            prot_canon = canonicalize_name(prot_pkg)
            if prot_canon in all_installed:
                deps = resolver.get_dependency_tree(prot_pkg) or {prot_canon}
                protected_deps.update(deps)
                self.update_log(f"Защищенный пакет {prot_pkg} и его зависимости: {deps}")

        candidates: Set[NormalizedName] = set()
        if include_dependencies:
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
                # Пакеты без RECORD (битая/прерванная установка, ручной pip) менеджер
                # удалить не может — uv/pip падают с "missing RECORD file" и оставляют
                # каталоги кода на месте. Не тратим на них попытку, сразу чистим вручную.
                has_record = os.path.isfile(os.path.join(dist_path, "RECORD"))
                base_cmd = self._resolve_installer_base_cmd()
                use_uv = self._is_uv_command(base_cmd)
                if use_uv and has_record:
                    cmd = list(base_cmd) + ["uninstall", "--target", str(self.libs_path_abs), str(pkg)]
                    success = self._run_pip_process(cmd, f"Удаление {pkg}")
                else:
                    success = False
                    if use_uv and not has_record:
                        self.update_log(
                            f"{pkg}: в {os.path.basename(dist_path)} нет RECORD — "
                            f"менеджер пакетов его не удалит, сразу чистим вручную."
                        )
                if not success:
                    self.update_log(f"Автоматическое удаление не смогло удалить {pkg}, пробуем ручное удаление...")
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

    def _collect_removal_targets(self, dist_info_path: str, pkg_name: str) -> List[str]:
        """Список путей для ручного удаления пакета: файлы/каталоги кода + сам dist-info.

        Источники имён кода (по приоритету):
          1) RECORD — точный список установленных файлов. Удаляем ИМЕННО эти файлы,
             а не их top-level каталоги: иначе при общем namespace-каталоге
             (google/, mpl_toolkits/, ruamel/ …) сносим файлы соседних пакетов.
          2) top_level.txt — import-имена верхнего уровня (когда RECORD отсутствует/битый);
             тут точного списка файлов нет, поэтому удаляем каталог целиком.
          3) фоллбэк по канон-имени пакета (torch -> torch/) — только если 1-2 ничего не дали.
        Всё ограничено целевой папкой Lib, чтобы случайно не выйти за её пределы.
        dist-info всегда возвращается последним — чтобы при сбое на коде по нему можно
        было повторить удаление.
        """
        libs = os.path.abspath(self.libs_path_abs)
        dist_info_abs = os.path.abspath(dist_info_path)

        def _norm(rel_or_abs: str) -> Optional[str]:
            if not rel_or_abs:
                return None
            p = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(libs, rel_or_abs)
            p = os.path.abspath(p)
            try:
                if os.path.commonpath([libs, p]) != libs or p == libs:
                    return None
            except Exception:
                return None
            return p

        def _under_dist_info(p: str) -> bool:
            return p == dist_info_abs or p.startswith(dist_info_abs + os.sep)

        code_targets: set[str] = set()

        # --- 1) RECORD: точные файлы (исключая содержимое самого dist-info) ---
        record = os.path.join(dist_info_path, "RECORD")
        if os.path.isfile(record):
            try:
                with open(record, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        rel = line.split(",", 1)[0].strip().strip('"')
                        if not rel or rel.startswith(("/", "\\", "..")):
                            continue
                        if ".." in rel.replace("\\", "/").split("/"):
                            continue
                        p = _norm(rel)
                        if p and not _under_dist_info(p):
                            code_targets.add(p)
            except Exception as ex:
                logger.warning(f"[installer] {pkg_name}: failed to read RECORD: {ex}")

            if code_targets:
                # RECORD дал точный список — этого достаточно, каталоги не трогаем.
                targets = sorted(t for t in code_targets if os.path.exists(t))
                if os.path.exists(dist_info_abs):
                    targets.append(dist_info_abs)
                return targets

        # --- 2/3) Нет валидного RECORD: удаляем по каталогам (точного списка нет) ---
        top_level = os.path.join(dist_info_path, "top_level.txt")
        if os.path.isfile(top_level):
            try:
                with open(top_level, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        name = line.strip()
                        if not name:
                            continue
                        for cand in (name, name + ".py"):
                            p = _norm(cand)
                            if p and not _under_dist_info(p):
                                code_targets.add(p)
            except Exception as ex:
                logger.warning(f"[installer] {pkg_name}: failed to read top_level.txt: {ex}")

        if not code_targets:
            base = canonicalize_name(pkg_name).replace("-", "_")
            for cand in (base, base + ".py"):
                p = _norm(cand)
                if p and not _under_dist_info(p):
                    code_targets.add(p)

        targets = sorted(t for t in code_targets if os.path.exists(t))
        if os.path.exists(dist_info_abs):
            targets.append(dist_info_abs)
        return targets

    def _prune_empty_dirs(self, file_paths: List[str]) -> None:
        """После удаления файлов из RECORD подчищаем опустевшие каталоги пакета.

        Идём от каждого файла вверх к Lib, собираем родительские каталоги и
        удаляем те из них, что стали пустыми (глубже — раньше). Сам Lib и всё
        вне него не трогаем."""
        libs = os.path.abspath(self.libs_path_abs)
        dirs: set[str] = set()
        for f in file_paths:
            d = os.path.dirname(os.path.abspath(f))
            while d and d != libs:
                try:
                    if os.path.commonpath([libs, d]) != libs:
                        break
                except Exception:
                    break
                dirs.add(d)
                parent = os.path.dirname(d)
                if parent == d:
                    break
                d = parent
        for d in sorted(dirs, key=len, reverse=True):
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass

    def _rmtree_with_retries(self, path: str, pkg_name: str) -> bool:
        if not os.path.exists(path):
            return True

        retries = 5
        wait = [0.5, 1, 2, 3, 5]
        for attempt in range(retries):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=False)
                else:
                    os.remove(path)
                if not os.path.exists(path):
                    logger.info(f"[installer] {pkg_name}: removed {path}")
                    return True
            except Exception as ex:
                logger.warning(
                    f"[installer] {pkg_name}: failed to remove {path} (attempt {attempt+1}/{retries}): {ex}"
                )
                self._unload_module_from_sys(pkg_name)
                gc.collect()
                time.sleep(wait[attempt])
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        except Exception:
            pass
        if os.path.exists(path):
            logger.error(f"[installer] {pkg_name}: failed to remove {path} after all retries")
            return False
        logger.info(f"[installer] {pkg_name}: removed {path} after retry")
        return True

    def _manual_remove(self, path: str, pkg_name: str) -> bool:
        if not os.path.exists(path):
            return True

        targets = self._collect_removal_targets(path, pkg_name)
        if not targets:
            return True

        all_ok = True
        removed_files: List[str] = []
        for target in targets:
            was_file = os.path.isfile(target)
            if not self._rmtree_with_retries(target, pkg_name):
                all_ok = False
            elif was_file:
                removed_files.append(target)
        # Удаляли точечно по RECORD — подчистим опустевшие каталоги пакета.
        if removed_files:
            self._prune_empty_dirs(removed_files)
        return all_ok

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

    def repair_broken_target_metadata(self) -> int:
        """Repair confidently broken metadata only inside staging targets.

        Active immutable environments are never mutated because of a transient
        antivirus/OneDrive read failure. Staging directories are disposable and
        may be repaired before a retry.
        """
        libs = self.libs_path_abs
        if not os.path.isdir(libs):
            return 0
        target_parts = {part.lower() for part in Path(libs).parts}
        is_staging = bool(
            {".staging", ".install-staging"} & target_parts
            or any(part.startswith(".core-staging-") for part in target_parts)
        )
        if not is_staging:
            return 0
        try:
            entries = os.listdir(libs)
        except OSError:
            return 0

        repaired = 0
        for item in entries:
            if not item.endswith(".dist-info"):
                continue
            di = os.path.join(libs, item)
            meta = os.path.join(di, "METADATA")
            try:
                healthy = os.stat(meta).st_size > 0
            except FileNotFoundError:
                healthy = False
            except OSError:
                # Inaccessible is not equivalent to absent. Do not destroy a
                # healthy package because a scanner temporarily locked it.
                continue
            if healthy:
                continue
            try:
                age = time.time() - os.stat(di).st_mtime
            except OSError:
                continue
            if age < 0.25:
                time.sleep(0.25 - max(0.0, age))
                try:
                    if os.stat(meta).st_size > 0:
                        continue
                except FileNotFoundError:
                    pass
                except OSError:
                    continue
            pkg = item.rsplit("-", 1)[0]
            self.update_log(
                f"Битая metadata в staging: {item} — удаляю dist-info перед повторной установкой."
            )
            if self._rmtree_with_retries(di, pkg):
                repaired += 1
            else:
                self.update_log(
                    f"Не удалось удалить битый {item} (возможно, файл занят антивирусом/OneDrive)."
                )
        if repaired:
            self.update_log(f"Очищено битых пакетов перед установкой: {repaired}.")
        return repaired

    def _maybe_warn_fragile_location(self) -> None:
        """Один раз предупреждаем о «хрупком» расположении Lib: OneDrive и/или
        не-ASCII символы в пути — частые причины пропавших METADATA, незавершённых
        удалений, 'python.exe not found' и прочих трудновоспроизводимых ошибок."""
        if getattr(self, "_fragile_location_warned", False):
            return
        self._fragile_location_warned = True

        path = self.libs_path_abs or ""
        low = path.lower()

        if "onedrive" in low:
            self.update_log(
                "⚠️ Папка установки находится внутри OneDrive: "
                f"{path}\n"
                "OneDrive выгружает/блокирует файлы (ошибки 'METADATA не найден', "
                "пакеты не удаляются, python.exe не запускается). Настоятельно "
                "рекомендуется перенести приложение в обычную локальную папку вне "
                "OneDrive."
            )

        non_ascii = [ch for ch in path if ord(ch) > 127]
        if non_ascii:
            sample = "".join(dict.fromkeys(non_ascii))[:20]
            self.update_log(
                "⚠️ В пути установки есть не-ASCII символы "
                f"({sample}): {path}\n"
                "Это может непредсказуемо ломать установку/запуск пакетов "
                "(uv/pip, subprocess, кодировки). Рекомендуется перенести "
                "приложение в путь только из латинских букв, цифр и '_' — "
                "например C:\\Games\\NeuroMita."
            )

    def _ensure_libs_path(self):
        os.makedirs(self.libs_path_abs, exist_ok=True)
        main_core = os.path.abspath(
            os.environ.get("NEUROMITA_CORE_DIR")
            or os.environ.get("NEUROMITA_LIB_DIR")
            or os.path.join("Lib", "core")
        )
        if (
            os.path.normcase(self.libs_path_abs) == os.path.normcase(main_core)
            and self.libs_path_abs not in sys.path
        ):
            sys.path.insert(0, self.libs_path_abs)

    @staticmethod
    def _decode_subprocess_chunk(chunk: bytes) -> str:
        encodings = [
            "utf-8",
            locale.getpreferredencoding(False) or "",
            "cp1251",
            "cp866",
        ]
        seen: set[str] = set()
        for encoding in encodings:
            encoding = str(encoding or "").strip()
            if not encoding:
                continue
            key = encoding.lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                return chunk.decode(encoding, errors="replace")
            except Exception:
                continue
        return chunk.decode("utf-8", errors="replace")

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
            self.error_count: int = 0
            self.warning_count: int = 0
            self.resolver_error_active: bool = False
            self.recent_lines: Deque[str] = deque(maxlen=40)
            # Скорость загрузки: считаем по приросту скачанных байт во времени
            # (EMA для сглаживания рывков). Нужна для строки статуса «X МБ/с» (#28).
            self.last_bytes_done: float = 0.0
            self.last_bytes_time: float = self.start
            self.speed_bps: float = 0.0
            self.uv_progress: Optional["PipInstaller._UvProgressAggregator"] = None
            self.last_snapshot_emit: float = self.start
            self.is_pytorch_install: bool = (
                ("download.pytorch.org" in self.cmd_str_low)
                or ("torch" in self.cmd_str_low and "install" in self.cmd_str_low)
            )
            self.torch_hint_logged: bool = False

    class _UvProgressAggregator:
        RE_PCT = re.compile(r"(\d{1,3})\s*%")
        RE_PAIR = re.compile(
            r"(?P<done>\d+(?:\.\d+)?)\s*(?P<dunit>[KMGTP]?i?B|B)\s*/\s*"
            r"(?P<total>\d+(?:\.\d+)?)\s*(?P<tunit>[KMGTP]?i?B|B)",
            re.IGNORECASE,
        )
        RE_SPEED = re.compile(r"(?P<speed>\d+(?:\.\d+)?)\s*(?P<sunit>[KMGTP]?i?B|B)/s", re.IGNORECASE)
        RE_PREP = re.compile(
            r"preparing packages\.\.\.\s*\((\d+)\s*/\s*(\d+)\)",
            re.IGNORECASE,
        )
        # Вехи uv печатаются как итоговые строки и видны даже без TTY (в отличие
        # от indicatif-прогрессбаров, которые uv глушит при перехвате вывода в
        # пайп). По ним ведём стадийный прогресс: разрешение → подготовка →
        # установка. Требуем число + «package», чтобы голые токены-статусы
        # (Resolved/Installed без счётчика) не срабатывали.
        RE_RESOLVED = re.compile(r"\bresolved\s+(\d+)\s+packages?\b", re.IGNORECASE)
        RE_PREPARED = re.compile(r"\bprepared\s+(\d+)\s+packages?\b", re.IGNORECASE)
        RE_INSTALLED = re.compile(r"\binstalled\s+(\d+)\s+packages?\b", re.IGNORECASE)
        RE_AUDITED = re.compile(r"\baudited\s+(\d+)\s+packages?\b", re.IGNORECASE)
        RE_WHL = re.compile(r"([A-Za-z0-9_.+-]+-[0-9][^-\\/\s]*?.*?\.whl)", re.IGNORECASE)
        RE_TAR = re.compile(r"([A-Za-z0-9_.+-]+-.*?\.(?:tar\.gz|zip|bz2|xz))", re.IGNORECASE)
        RE_PATH = re.compile(r"([A-Za-z]:[^\s]+\.whl|/[^\s]+\.whl)", re.IGNORECASE)
        RE_TOKEN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]{1,})\b")
        RE_BARE_TOKEN = re.compile(r"^\s*[A-Za-z0-9][A-Za-z0-9_.-]{1,}\s*$")

        SPIN_CHARS = "⠋⠙⠚⠞⠖⠦⠴⠲⠶⠇⠧⠹⠼"
        NOISE_TOKENS = {
            "debug", "trace", "info", "warning", "warn", "error",
            "preparing", "prepared", "resolving", "resolved",
            "fetching", "fetched", "building", "built",
            "collecting", "collected",
            "installing", "installed", "uninstalling", "uninstalled",
            "downloading", "downloaded",
            # uv-преамбула: строки «Using CPython …», «Using uv dependency
            # overrides …», «Audited N packages», «Found …» и т.п. — не пакеты.
            # Без этого «Using» становится фантомной задачей без размеров и
            # висит как единственная «Активных задач: 1» на тихой фазе torch.
            "using", "audited", "found", "note", "updating", "creating",
        }

        def __init__(self):
            self.tasks: dict[str, dict] = {}
            self.completed: dict[str, dict] = {}
            self.peak_done: dict[str, int] = {}
            self.peak_total: dict[str, int] = {}
            self.phase_cur: int | None = None
            self.phase_tot: int | None = None
            # Стадия по вехам uv: resolving → preparing → installing → done.
            self.stage: str = "resolving"
            self.total_packages: int | None = None
            self.snapshot_tick: int = 0
            self.done_epsilon_ratio = 0.995
            self.stale_to_done_sec = 4.0
            self.hard_stale_sec = 15.0
            self.hist_window_sec = 8.0

        @staticmethod
        def unit_mul(unit: str) -> int:
            u = unit.upper()
            dec = {"B": 1, "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3, "TB": 1000 ** 4, "PB": 1000 ** 5}
            bin_ = {"KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3, "TIB": 1024 ** 4, "PIB": 1024 ** 5}
            return bin_.get(u, dec.get(u, 1))

        @staticmethod
        def fmt_bytes(n: float | int) -> str:
            try:
                n = float(n)
            except Exception:
                return "?"
            for unit, mul in (("B", 1), ("KiB", 1024), ("MiB", 1024 ** 2), ("GiB", 1024 ** 3), ("TiB", 1024 ** 4)):
                if n < mul * 1024 or unit == "TiB":
                    return f"{n / mul:.1f} {unit}"
            return f"{n:.1f} B"

        @staticmethod
        def fmt_rate(bps: float | int | None) -> str:
            if not bps:
                return "-"
            try:
                bps = float(bps)
            except Exception:
                return "-"
            for unit, mul in (("B/s", 1), ("KiB/s", 1024), ("MiB/s", 1024 ** 2), ("GiB/s", 1024 ** 3)):
                if bps < mul * 1024 or unit == "GiB/s":
                    return f"{bps / mul:.1f} {unit}"
            return f"{bps:.1f} B/s"

        @staticmethod
        def fmt_eta(seconds: float | None) -> str | None:
            if seconds is None or seconds < 0:
                return None
            seconds = int(seconds)
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

        def bar(self, pct: int | None, width: int = 22, *, indeterminate: bool = False) -> str:
            if indeterminate:
                if width <= 0:
                    return "||"
                span = max(3, min(6, width // 4 or 1))
                travel = max(1, width - span + 1)
                pos = self.snapshot_tick % travel
                body = ["·"] * width
                for i in range(span):
                    idx = min(width - 1, pos + i)
                    body[idx] = "█" if i == span // 2 else "■"
                return "|" + "".join(body) + "|"
            if pct is None:
                return "|" + "·" * width + "|"
            fill = max(0, min(width, int(round((pct / 100) * width))))
            return "|" + "█" * fill + "_" * (width - fill) + "|"

        def ident_and_display(self, s: str) -> tuple[str, str] | None:
            m = self.RE_WHL.search(s) or self.RE_TAR.search(s) or self.RE_PATH.search(s)
            if m:
                return self.canon_name_from_wheel(m.group(1))
            m = self.RE_TOKEN.match(s)
            if not m:
                return None
            tok = m.group(1)
            low = tok.lower()
            if low in self.NOISE_TOKENS:
                return None
            if tok and (tok[0] in self.SPIN_CHARS or tok in ("i.", ":", ";", ".", "…")):
                return None
            normalized = low.replace("_", "-")
            return normalized, tok.replace("_", "-")

        @staticmethod
        def canon_name_from_wheel(wheel_path: str) -> tuple[str, str]:
            base = wheel_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            pkg = base.split("-", 1)[0]
            return base.lower(), pkg

        def _ensure_hist(self, task: dict) -> None:
            if "hist" not in task:
                task["hist"] = deque(maxlen=120)

        def _push_hist(self, task: dict, ts: float) -> None:
            self._ensure_hist(task)
            done = task.get("done")
            if done is None:
                return
            hist = task["hist"]
            if not hist or hist[-1][1] != done:
                hist.append((ts, int(done)))
            while len(hist) >= 2 and (ts - hist[0][0] > max(self.hist_window_sec * 1.5, 2 * self.hist_window_sec)):
                hist.popleft()

        def estimate_speed(self, task: dict) -> float:
            speed = task.get("speed_bps")
            if speed and speed > 0:
                return float(speed)
            hist = task.get("hist") or []
            if len(hist) < 2:
                return 0.0
            ts_now = hist[-1][0]
            idx = 0
            for i in range(len(hist) - 2, -1, -1):
                if ts_now - hist[i][0] > self.hist_window_sec:
                    idx = i
                    break
            dt = ts_now - hist[idx][0]
            if dt <= 0:
                return 0.0
            dd = float(hist[-1][1] - hist[idx][1])
            if dd <= 0:
                return 0.0
            return dd / dt

        def update(self, raw_line: str) -> None:
            s = PipInstaller._clean_line(raw_line).strip()
            if not s:
                return

            prep = self.RE_PREP.search(s)
            if prep:
                try:
                    self.phase_cur = int(prep.group(1))
                    self.phase_tot = int(prep.group(2))
                except Exception:
                    pass
                if self.stage == "resolving":
                    self.stage = "preparing"
                return

            # Вехи uv: обновляем стадию и общее число пакетов.
            m = self.RE_RESOLVED.search(s)
            if m:
                try:
                    self.total_packages = int(m.group(1))
                except Exception:
                    pass
                if self.stage == "resolving":
                    self.stage = "preparing"
                return
            m = self.RE_PREPARED.search(s)
            if m:
                if self.total_packages is None:
                    try:
                        self.total_packages = int(m.group(1))
                    except Exception:
                        pass
                self.stage = "installing"
                # Фаза подготовки завершена — сбрасываем её счётчик, иначе он
                # застопорил бы прогресс/подпись на «Подготовка X/Y».
                self.phase_cur = self.phase_tot = None
                return
            if self.RE_INSTALLED.search(s) or self.RE_AUDITED.search(s):
                self.stage = "done"
                self.phase_cur = self.phase_tot = None
                return

            pct_match = self.RE_PCT.search(s)
            pair_match = self.RE_PAIR.search(s)
            speed_match = self.RE_SPEED.search(s)
            has_artifact = bool(self.RE_WHL.search(s) or self.RE_TAR.search(s) or self.RE_PATH.search(s))
            has_spinner = any(ch in s for ch in self.SPIN_CHARS)
            is_bare_package = bool(self.RE_BARE_TOKEN.fullmatch(s))
            if not (pct_match or pair_match or speed_match or has_artifact or has_spinner or is_bare_package):
                return

            ident_disp = self.ident_and_display(s)
            if not ident_disp:
                return
            cid, disp = ident_disp

            task = self.tasks.get(cid)
            if not task:
                task = {
                    "id": cid,
                    "name": disp,
                    "pct": None,
                    "done": None,
                    "total": None,
                    "speed_bps": None,
                    "eta": None,
                    "ts": time.time(),
                }
                self.tasks[cid] = task

            # uv under a real PTY sometimes emits only the normalized package
            # name while preparing it. Keep that as an indeterminate task so
            # the install dialog shows activity instead of an empty raw view.
            if is_bare_package and not (pct_match or pair_match or speed_match or has_artifact or has_spinner):
                task["ts"] = time.time()
                return

            if pct_match:
                try:
                    task["pct"] = max(0, min(100, int(pct_match.group(1))))
                except Exception:
                    pass

            if pair_match:
                try:
                    done = float(pair_match.group("done")) * self.unit_mul(pair_match.group("dunit"))
                    total = float(pair_match.group("total")) * self.unit_mul(pair_match.group("tunit"))
                    task["done"], task["total"] = int(done), int(total)
                    if total > 0:
                        task["pct"] = max(0, min(100, int(round(done / total * 100))))
                except Exception:
                    pass

            if speed_match:
                try:
                    task["speed_bps"] = float(speed_match.group("speed")) * self.unit_mul(speed_match.group("sunit"))
                except Exception:
                    task["speed_bps"] = None

            now = time.time()
            if task.get("done") is not None:
                self._push_hist(task, now)

            if task.get("done") is not None and task.get("total") is not None:
                remaining = max(0.0, float(task["total"] - task["done"]))
                speed_est = self.estimate_speed(task)
                task["eta"] = self.fmt_eta(remaining / speed_est if speed_est > 0 else None)
            else:
                task["eta"] = None

            self._record_peaks(task)
            task["ts"] = now

        def _record_peaks(self, task: dict) -> None:
            cid = task["id"]
            if task.get("total") is not None:
                self.peak_total[cid] = max(self.peak_total.get(cid, 0), int(task["total"]))
            if task.get("done") is not None:
                peak_total = self.peak_total.get(cid, int(task.get("done", 0)))
                self.peak_done[cid] = max(self.peak_done.get(cid, 0), min(int(task.get("done", 0)), peak_total))

        def prune(self, now: float) -> None:
            to_close: list[str] = []
            for cid, task in list(self.tasks.items()):
                pct = task.get("pct")
                done, total = task.get("done"), task.get("total")
                ratio = (float(done) / float(total)) if (done is not None and total) else None
                if (pct is not None and pct >= 99) or (ratio is not None and ratio >= self.done_epsilon_ratio):
                    to_close.append(cid)
                    continue
                idle = now - task["ts"]
                if ratio is not None and ratio >= 0.95 and idle >= self.stale_to_done_sec:
                    to_close.append(cid)
                    continue
                if idle >= self.hard_stale_sec:
                    to_close.append(cid)

            for cid in to_close:
                task = self.tasks.pop(cid, None)
                if task:
                    self._record_peaks(task)
                    self.completed[cid] = task

        def _stage_percent(self) -> int | None:
            """Прогресс без байтовых размеров: по счётчику «Preparing (X/Y)» либо
            по стадии-вехе uv. Полосы: разрешение 0–10, подготовка/скачивание
            10–90, установка 90–100."""
            if self.phase_tot and self.phase_tot > 0 and self.phase_cur is not None:
                frac = self.phase_cur / self.phase_tot
                return int(max(0, min(100, round(10 + 80 * frac))))
            if self.stage == "done":
                return 100
            if self.stage == "installing":
                return 92
            if self.stage == "preparing":
                # Скачивание идёт, гранулярности нет — держим начало полосы.
                return 12
            return None

        def overall_percent(self) -> int | None:
            if not self.peak_total:
                # uv часто не отдаёт размеры пакетов (байтовый путь пуст) —
                # ведём прогресс по стадиям/счётчику подготовки, чтобы бар шёл.
                return self._stage_percent()
            total_total = sum(self.peak_total.values())
            if total_total <= 0:
                return self._stage_percent()
            total_done = 0
            for cid, total in self.peak_total.items():
                total_done += min(self.peak_done.get(cid, 0), total)
            return int(max(0, min(100, round(total_done / total_total * 100))))

        def has_activity(self) -> bool:
            return bool(self.tasks or self.completed or (self.phase_cur is not None and self.phase_tot is not None))

        def has_confident_progress(self) -> bool:
            # Счётчик «Preparing packages... (X/Y)» и вехи uv — надёжные
            # детерминированные сигналы даже без байтовых размеров.
            if self.phase_tot and self.phase_tot > 0 and self.phase_cur is not None:
                return True
            if self.stage in ("preparing", "installing", "done"):
                return True
            total_bytes = sum(self.peak_total.values())
            total_tasks = sum(1 for total in self.peak_total.values() if total > 0)
            pct = self.overall_percent() or 0
            return total_tasks > 0 and (total_bytes >= 8 * 1024 * 1024 or total_tasks >= 2 or pct >= 5)

        def overall_speed_bps(self) -> float:
            return sum(self.estimate_speed(task) for task in self.tasks.values())

        def cumulative_bytes(self) -> tuple[int, int]:
            """Скачано/всего байт по пикам всех задач (включая завершённые) —
            монотонный кумулятивный размер загрузки за всю установку."""
            done = 0
            for cid, total in self.peak_total.items():
                done += min(self.peak_done.get(cid, 0), total)
            total = sum(self.peak_total.values())
            return int(done), int(total)

        def packages_progress(self) -> tuple[int | None, int | None]:
            """Счётчик пакетов X/Y: приоритет — «Preparing packages... (X/Y)»
            (инкрементально), иначе завершённые задачи из total_packages."""
            if self.phase_cur is not None and self.phase_tot:
                return self.phase_cur, self.phase_tot
            if self.total_packages:
                if self.stage == "done":
                    return self.total_packages, self.total_packages
                return len(self.completed), self.total_packages
            return None, None

        def overall_eta_bytes(self) -> float | None:
            sum_total = 0.0
            sum_done = 0.0
            sum_speed = 0.0
            for task in self.tasks.values():
                total = task.get("total")
                done = task.get("done")
                if total is None or done is None:
                    continue
                sum_total += float(total)
                sum_done += float(done)
                speed = self.estimate_speed(task)
                if speed > 0:
                    sum_speed += speed
            if sum_total <= 0 or sum_speed <= 0:
                return None
            remaining = max(0.0, sum_total - sum_done)
            if remaining <= 0:
                return 0.0
            return remaining / sum_speed

        def _stage_label(self) -> str:
            total = f" ({self.total_packages})" if self.total_packages else ""
            return {
                "preparing": f"Скачивание и подготовка пакетов…{total}",
                "installing": f"Установка пакетов…{total}",
                "done": "Установка завершена",
            }.get(self.stage, "")

        def snapshot_lines(self, max_lines: int = 8) -> list[str]:
            self.snapshot_tick += 1
            lines: list[str] = []
            if self.phase_cur is not None and self.phase_tot is not None:
                lines.append(f"Подготовка пакетов: {self.phase_cur}/{self.phase_tot}")
            elif self.stage != "resolving":
                # Нет счётчика подготовки — показываем стадию по вехам uv.
                label = self._stage_label()
                if label:
                    lines.append(label)

            if not self.tasks:
                return lines

            items = sorted(self.tasks.values(), key=lambda task: (-task["ts"], task["name"]))
            sum_done = sum((task.get("done") or 0) for task in items if task.get("total"))
            sum_total = sum((task.get("total") or 0) for task in items if task.get("total"))
            pcts = [task["pct"] for task in items if task.get("pct") is not None]
            summary = f"Активных задач: {len(items)}"
            if sum_total > 0:
                avg = int(round(sum(pcts) / len(pcts))) if pcts else 0
                summary += f"  Средний прогресс: {avg}%"
                summary += f"  Σ {self.fmt_bytes(sum_done)}/{self.fmt_bytes(sum_total)}"
                sum_speed = self.overall_speed_bps()
                if sum_speed > 0:
                    eta_sec = (sum_total - sum_done) / sum_speed if sum_total > sum_done else 0.0
                    eta_txt = self.fmt_eta(eta_sec)
                    if eta_txt:
                        summary += f"  Σскорость: {self.fmt_rate(sum_speed)}  ETA: {eta_txt}"
            elif self.phase_tot and self.phase_cur is not None:
                # Прогресс идёт по счётчику «Preparing packages... (X/Y)» (см.
                # строку выше) — байтовых размеров uv не дал, поэтому Σ не пишем.
                pass
            else:
                summary += "  Ожидание данных о размере пакетов…"
            lines.append(summary)

            for index, task in enumerate(items):
                if index >= max_lines:
                    break
                name = task["name"]
                if len(name) > 28:
                    name = name[:25] + "..."
                right: list[str] = []
                indeterminate = task.get("total") is None
                if task.get("pct") is not None:
                    right.append(f"{task['pct']:3d}%")
                if task.get("done") is not None and task.get("total") is not None:
                    right.append(f"{self.fmt_bytes(task['done'])}/{self.fmt_bytes(task['total'])}")
                speed = self.estimate_speed(task)
                if speed > 0:
                    right.append(self.fmt_rate(speed))
                if task.get("eta"):
                    right.append(f"ETA {task['eta']}")
                suffix = f"  {'  '.join(right)}" if right else ""
                lines.append(f"{name:28} {self.bar(task.get('pct'), indeterminate=indeterminate)}{suffix}")
            return lines

    # Настройки времени/таймаутов
    STALL_INFO_SEC = 10
    STALL_HINT_SEC = 60
    TIMEOUT_SEC = DEFAULT_INSTALL_TIMEOUT_SEC
    NO_ACTIVITY_SEC = DEFAULT_INSTALL_NO_ACTIVITY_SEC

    # Раннер: период опроса и «мягкий» прогресс, пока реальный % ещё не парсится.
    _POLL_INTERVAL_SEC = 0.03
    _SOFT_PROGRESS_MAX = 95        # выше этого «мягкий» бамп не поднимает бар
    _PIPE_LINE_WEIGHT = 0.4        # вклад одной строки пайпа в «мягкий» прогресс

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

    @staticmethod
    def _fmt_speed(bps: float) -> str:
        """Человекочитаемая скорость загрузки (#28)."""
        if bps <= 0:
            return ""
        units = ("Б/с", "КБ/с", "МБ/с", "ГБ/с")
        v = float(bps)
        i = 0
        while v >= 1024.0 and i < len(units) - 1:
            v /= 1024.0
            i += 1
        return f"{v:.1f} {units[i]}" if v < 100 else f"{v:.0f} {units[i]}"

    def _update_speed(self, state: "_RunState", bytes_done: float) -> None:
        """Считаем мгновенную скорость по приросту скачанных байт и сглаживаем EMA.
        При смене файла счётчик может обнулиться — отрицательную дельту игнорируем."""
        now = time.time()
        dt = now - state.last_bytes_time
        db = bytes_done - state.last_bytes_done
        if dt >= 0.3:
            if db > 0:
                inst = db / dt
                # EMA: сглаживаем рывки сети.
                state.speed_bps = inst if state.speed_bps <= 0 else (state.speed_bps * 0.6 + inst * 0.4)
            elif db < 0:
                # Новый файл — сбрасываем точку отсчёта без потери последней скорости.
                pass
            state.last_bytes_done = bytes_done
            state.last_bytes_time = now

    @classmethod
    def _clean_line(cls, s: str) -> str:
        if not s:
            return ""
        return cls._ANSI_RE.sub('', s).replace("\x1b", "")

    @classmethod
    def _looks_like_progress_redraw(cls, line: str) -> bool:
        """Return True only for terminal lines that are safe to discard on ``\r``.

        uv renders both progress bars and resolver diagnostics through the PTY.
        Treating every carriage-return line as ephemeral used to hide the actual
        ``No solution found`` block and fed words such as ``Because`` and
        ``torchaudio`` into the progress-task parser.
        """
        text = str(line or "").strip()
        if not text:
            return True
        low = text.lower()
        if any(marker in low for marker in (
            "no solution found",
            "failed to resolve",
            "requirements are unsatisfiable",
            "cannot be used",
            "we can conclude",
            "because ",
            "help:",
        )):
            return False
        return bool(
            cls._RE_PCT.search(text)
            or cls._RE_PAIR.search(text)
            or any(ch in text for ch in cls._UvProgressAggregator.SPIN_CHARS)
            or cls._UvProgressAggregator.RE_PREP.search(text)
            or cls._UvProgressAggregator.RE_RESOLVED.search(text)
            or cls._UvProgressAggregator.RE_PREPARED.search(text)
            or cls._UvProgressAggregator.RE_INSTALLED.search(text)
            or cls._UvProgressAggregator.RE_AUDITED.search(text)
        )

    def _prepare_env(self, tty: bool = False) -> dict:
        env = os.environ.copy()
        env["PYTHONNOUSERSITE"] = "1"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        env["PIP_CONFIG_FILE"] = os.devnull
        env.setdefault("PIP_PROGRESS_BAR", "on")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        if tty:
            # Под PTY разрешаем UV/pip рисовать живой прогресс-бар (иначе на больших
            # бинарях torch было «нет вывода 16 с»). Цвет/прогресс включаем,
            # «dumb»-настройки убираем (#27/#28).
            for k in ("NO_COLOR", "TERM", "CLICOLOR", "FORCE_COLOR", "PY_COLORS"):
                env.pop(k, None)
            env["UV_TTY"] = "1"
            env["FORCE_COLOR"] = "1"
            env["CLICOLOR_FORCE"] = "1"
            env["PIP_PROGRESS_BAR"] = "on"
            env["TERM"] = "xterm-256color"
            env["COLUMNS"] = env.get("COLUMNS", "120")
        else:
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

    def _ensure_pty_available(self) -> bool:
        """Use PTY only when it is already part of the application core.

        Runtime dependency installation is uv-only. The installer must not
        mutate the embedded Python merely to improve its own presentation;
        when pywinpty is absent the same uv command runs through ordinary
        stdout/stderr pipes.
        """
        if os.name != "nt" or os.environ.get("UV_TTY") == "0":
            return False
        ok, _ = self._detect_pty()
        if not ok and not self._pty_bootstrap_attempted:
            self._pty_bootstrap_attempted = True
            self.update_log(
                "pywinpty is not installed in the application core; "
                "using raw stdout/stderr pipes."
            )
        return ok

    def _emit_raw_log(self, chunk: str) -> None:
        try:
            self.update_raw_log(chunk)
        except Exception:
            logger.debug("Installer raw-log callback failed", exc_info=True)

    def _process_line(self, state: _RunState, line: str, transient: bool = False):
        # transient=True — строка пришла с возвратом каретки (\r): это «живая»
        # перерисовка прогресс-бара. Из неё извлекаем процент/скорость и обновляем
        # статус, но НЕ копим её в постоянный лог (иначе сотни копий прогресс-бара).
        if not line:
            return
        clean = self._clean_line(line.rstrip())
        if not clean:
            return
        transient = bool(transient and self._looks_like_progress_redraw(clean))
        if not transient:
            state.recent_lines.append(clean)

        low = clean.lower()
        resolver_start = any(marker in low for marker in (
            "no solution found",
            "failed to resolve",
            "requirements are unsatisfiable",
            "resolution impossible",
        ))
        if resolver_start:
            state.resolver_error_active = True

        is_error_line = (
            state.resolver_error_active
            or any(k in low for k in ("error:", "ошибка:", "failed:", "traceback", "exception", "critical"))
            or (("error" in low or "failed" in low) and "build\\" not in low and "bdist." not in low)
        )
        if (not transient) and is_error_line:
            logger.error(clean)
            self.update_log(clean)
            state.error_seen = True
            state.error_count += 1
        else:
            if (not transient) and any(k in low for k in ("warning:", "warn:", "предупреж", "deprecat")):
                state.warning_count += 1
            if state.uv_progress is not None:
                try:
                    state.uv_progress.update(clean)
                    self._update_progress_from_aggregator(state)
                except Exception:
                    pass

            # Попробуем вытащить отношение done/total
            has_byte_pair = False
            m2 = self._RE_PAIR.search(clean)
            if m2:
                try:
                    has_byte_pair = True
                    d = float(m2.group("done"))  * self._unit_mul(m2.group("dunit"))
                    T = float(m2.group("total")) * self._unit_mul(m2.group("tunit"))
                    if T > 0:
                        pct2 = int(round(d / T * 100))
                        if pct2 > state.percent:
                            state.percent = min(99, max(0, pct2))
                            self.update_progress(state.percent)
                            state.history.append((time.time(), state.percent))
                    # Скорость: прирост скачанных байт за время между измерениями (#28).
                    self._update_speed(state, d)
                except Exception:
                    pass

            # Попробуем вытащить проценты
            m = self._RE_PCT.search(clean)
            if m:
                try:
                    pct = max(0, min(100, int(m.group(1))))
                    if self._should_accept_percent(state, pct, has_byte_pair=has_byte_pair) and pct > state.percent:
                        state.percent = min(99, pct)  # не прыгать на 100 до конца
                        self.update_progress(state.percent)
                        state.history.append((time.time(), state.percent))
                except Exception:
                    pass

            # Транзиентные (\r) перерисовки прогресса в постоянный лог не пишем.
            if not transient:
                self.update_log(clean)

        state.last_activity = time.time()
        if transient:
            # Живой прогресс-бар — сразу обновим строку статуса (со скоростью).
            self._update_status_if_needed(state)

    def _is_progress_confident(self, state: _RunState) -> bool:
        agg = state.uv_progress
        if agg is not None and agg.has_confident_progress():
            return True
        return state.percent >= 3 and (agg is None or not agg.has_activity())

    def _should_accept_percent(self, state: _RunState, pct: int, *, has_byte_pair: bool) -> bool:
        if has_byte_pair:
            return True
        agg = state.uv_progress
        if agg is None:
            return True
        if agg.has_confident_progress():
            return True
        if not agg.has_activity():
            return pct >= 3
        return pct >= 5

    def _update_progress_from_aggregator(self, state: _RunState) -> None:
        agg = state.uv_progress
        if agg is None:
            return
        if not agg.has_confident_progress():
            return
        pct = agg.overall_percent()
        if pct is None:
            return
        pct = min(99, max(3, int(pct)))
        if pct > state.percent:
            state.percent = pct
            self.update_progress(state.percent)
            state.history.append((time.time(), state.percent))

    def _emit_snapshot_if_needed(self, state: _RunState, *, force: bool = False) -> None:
        agg = state.uv_progress
        if agg is None:
            return
        now = time.time()
        agg.prune(now)
        if not force and now - state.last_snapshot_emit < 0.1:
            return
        lines = agg.snapshot_lines()
        if lines:
            self.update_log("__SNAPSHOT_START__\n" + "\n".join(lines) + "\n__SNAPSHOT_END__")
        self._emit_stats(state, agg)
        state.last_snapshot_emit = now

    def _emit_stats(self, state: _RunState, agg: "_UvProgressAggregator") -> None:
        """Структурные метрики для шапки окна установки — отдельным JSON-маркером
        на том же log-канале, что и __SNAPSHOT__ (established-паттерн). Окно парсит
        их в счётчик пакетов, скорость/скачано, стадию и число ошибок; консольные
        потребители просто игнорируют неизвестный маркер."""
        try:
            pkg_done, pkg_total = agg.packages_progress()
            dl_done, dl_total = agg.cumulative_bytes()
            stats = {
                "packages_done": pkg_done,
                "packages_total": pkg_total,
                "active_tasks": len(agg.tasks),
                "speed_bps": agg.overall_speed_bps(),
                "downloaded_bytes": dl_done,
                "total_bytes": dl_total,
                "stage": agg.stage,
                "errors": state.error_count,
                "warnings": state.warning_count,
            }
            self.update_log("__STATS__" + json.dumps(stats, ensure_ascii=True))
        except Exception:
            pass

    def _update_status_if_needed(self, state: _RunState):
        now = time.time()
        if now - state.last_status_emit < 0.5:
            return

        eta_txt = ""
        eta_seconds = state.uv_progress.overall_eta_bytes() if state.uv_progress is not None else None
        if eta_seconds is None and len(state.history) >= 2 and state.percent >= 3:
            t0, p0 = state.history[0]
            dt = now - t0
            dp = state.percent - p0
            if dt > 0 and dp > 0:
                eta_seconds = max(0.0, (100.0 - state.percent)) / (dp / dt)
        if eta_seconds is not None:
            eta_txt = f" (ETA {self._fmt_hms(eta_seconds)})"

        # Скорость считаем «свежей» только если данные обновлялись недавно.
        speed_txt = ""
        agg_speed_bps = state.uv_progress.overall_speed_bps() if state.uv_progress is not None else 0.0
        live_speed_bps = agg_speed_bps if agg_speed_bps > 0 else (
            state.speed_bps if state.speed_bps > 0 and (now - state.last_bytes_time) < 5.0 else 0.0
        )
        if live_speed_bps > 0:
            s = self._fmt_speed(live_speed_bps)
            if s:
                speed_txt = f" · {s}"

        stalled_sec = int(now - state.last_activity)
        elapsed_sec = int(now - state.start)
        # Пока реальный процент не удаётся распарсить (частый случай uv в
        # не-TTY режиме — он почти не пишет проценты в пайп), НЕ показываем
        # вводящий в заблуждение «— 0%»: из-за него длинный шаг выглядит
        # зависшим (фидбэк Артёма: «просто тупо молчаливая установка»).
        # Вместо этого крутим живой счётчик прошедшего времени — видно, что
        # процесс идёт.
        if state.percent > 0 and self._is_progress_confident(state):
            msg = f"{state.description} — {state.percent}%"
        else:
            msg = f"{state.description} — идёт… {self._fmt_hms(elapsed_sec)}"
        if speed_txt:
            msg += speed_txt
        if eta_txt:
            msg += eta_txt
        elif not speed_txt and stalled_sec >= self.STALL_INFO_SEC:
            msg += f" (нет вывода {stalled_sec} с, процесс работает)"

        if msg != state.last_status_message:
            self.update_status(msg)
            state.last_status_message = msg

        # Подсказка для больших бинарей PyTorch
        if state.is_pytorch_install and (stalled_sec >= self.STALL_HINT_SEC) and not state.torch_hint_logged:
            self.update_log("Похоже, идёт загрузка больших бинарников PyTorch. Это может занимать длительное время без вывода.")
            state.torch_hint_logged = True

        state.last_status_emit = now

    def _assert_not_gui_thread(self) -> None:
        try:
            from PyQt6.QtCore import QCoreApplication, QThread

            app = QCoreApplication.instance()
            if app and QThread.currentThread() == app.thread():
                raise RuntimeError(
                    "PipInstaller cannot run in the Qt GUI thread; submit it "
                    "through InstallQueueService/TaskSupervisor"
                )
        except RuntimeError:
            raise
        except Exception:
            return

    def cancel(self) -> None:
        self._cancel_event.set()
        with self._active_process_lock:
            killer = self._active_process_killer
        if callable(killer):
            try:
                killer()
            except Exception:
                pass

    def _set_active_process(self, process, killer) -> None:
        with self._active_process_lock:
            self._active_process = process
            self._active_process_killer = killer

    def _clear_active_process(self, process) -> None:
        with self._active_process_lock:
            if self._active_process is process:
                self._active_process = None
                self._active_process_killer = None

    def _terminate_process(self, proc, reason: str = ""):
        try:
            if reason:
                self.update_log(reason)
            proc.terminate()
            time.sleep(0.5)
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass

    def _advance_soft_progress(self, state: _RunState, weight: float) -> None:
        """Общий «мягкий» бамп верхней полосы для обоих раннеров (PTY и пайпы).

        Пока реальный процент/байты ещё не парсятся (uv не начал качать), двигаем
        полосу по факту прихода вывода — чтобы окно не выглядело зависшим. Реальный
        процент из агрегатора всё равно перекроет это, когда появится. Вес задаёт
        вызывающий: пайпы копят по строке, PTY — по завершённой (\\n) строке."""
        if weight <= 0 or state.percent >= self._SOFT_PROGRESS_MAX:
            return
        next_percent = min(self._SOFT_PROGRESS_MAX, int(round(state.percent + weight)))
        if next_percent > state.percent:
            state.percent = next_percent
            self.update_progress(state.percent)
            state.history.append((time.time(), state.percent))

    def _check_timeouts(self, state: _RunState, kill) -> Optional[Tuple[bool, int]]:
        """Общая проверка таймаутов неактивности/общего для обоих раннеров.

        При срабатывании вызывает kill() (способ убийства процесса зависит от
        раннера), пишет статус и возвращает (False, -1); иначе None."""
        now = time.time()
        if now - state.last_activity > self.NO_ACTIVITY_SEC:
            kill()
            self.update_status(state.description + " — прервано по таймауту неактивности.")
            return False, -1
        if now - state.start > self.TIMEOUT_SEC:
            kill()
            self.update_status(state.description + " — прервано по общему таймауту.")
            return False, -1
        return None

    def _service_tick(self, state: _RunState, kill) -> Optional[Tuple[bool, int]]:
        """Общий «хвост» итерации цикла опроса для обоих раннеров: снимок прогресса,
        обновление статуса, проверка таймаутов, прокачка Qt-событий и пауза.
        Возвращает (False, -1) если пора прерваться (таймаут), иначе None."""
        self._emit_snapshot_if_needed(state)
        self._update_status_if_needed(state)
        if self._cancel_event.is_set():
            kill()
            self.update_status(state.description + " — cancelled.")
            return False, -1
        aborted = self._check_timeouts(state, kill)
        if aborted is not None:
            return aborted
        time.sleep(self._POLL_INTERVAL_SEC)
        return None

    def _log_failure_context(self, cmd: List[str], state: _RunState, ret: int) -> None:
        recent = [line for line in state.recent_lines if str(line).strip()]
        if recent:
            heading = "Последние строки установщика перед ошибкой:"
            self.update_log(heading)
            logger.error(f"[installer] {heading}")
            for line in recent[-12:]:
                self.update_log(line)
                logger.error(f"[installer] {line}")
        elif state.uv_progress is not None and state.uv_progress.has_activity():
            lines = state.uv_progress.snapshot_lines(max_lines=10)
            if lines:
                heading = "Последний снимок прогресса перед ошибкой:"
                self.update_log(heading)
                logger.error(f"[installer] {heading}")
                self.update_log("__SNAPSHOT_START__\n" + "\n".join(lines) + "\n__SNAPSHOT_END__")
                for line in lines:
                    logger.error(f"[installer] {line}")
        final_line = f"Команда завершилась с кодом {ret}: {' '.join(cmd)}"
        self.update_log(final_line)
        logger.error(f"[installer] {final_line}")

    def _is_uv_cache_access_denied_failure(self, cmd: List[str], state: _RunState, ret: int) -> bool:
        if ret == 0 or not self._is_uv_command(cmd):
            return False
        for line in state.recent_lines:
            low = line.lower()
            if ("uv\\cache" in low or "uv/cache" in low) and "rename" in low and (
                "access is denied" in low or "os error 5" in low
            ):
                return True
        return False

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

        self._set_active_process(proc, lambda: self._terminate_process(proc, "Installation cancelled."))
        q_out, q_err = queue.Queue(), queue.Queue()

        def _reader(pipe, q):
            try:
                for line in iter(pipe.readline, ""):
                    q.put(line)
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        t_out = task_supervisor().start_thread(
            proc,
            "pip-stdout-reader",
            _reader,
            args=(proc.stdout, q_out),
        )
        t_err = task_supervisor().start_thread(
            proc,
            "pip-stderr-reader",
            _reader,
            args=(proc.stderr, q_err),
        )

        while proc.poll() is None or t_out.is_alive() or t_err.is_alive():
            processed_weight = 0.0
            for q in (q_out, q_err):
                while not q.empty():
                    raw_line = q.get_nowait()
                    self._emit_raw_log(raw_line)
                    self._process_line(state, raw_line.rstrip("\r\n"))
                    processed_weight += self._PIPE_LINE_WEIGHT

            self._advance_soft_progress(state, processed_weight)

            aborted = self._service_tick(state, lambda: self._terminate_process(proc))
            if aborted is not None:
                self._clear_active_process(proc)
                task_supervisor().cancel_owner(proc, timeout=0.5)
                return aborted

        # Дочистим очереди
        while not q_out.empty():
            raw_line = q_out.get_nowait()
            self._emit_raw_log(raw_line)
            self._process_line(state, raw_line.rstrip("\r\n"))
        while not q_err.empty():
            raw_line = q_err.get_nowait()
            self._emit_raw_log(raw_line)
            self._process_line(state, raw_line.rstrip("\r\n"))
        self._emit_snapshot_if_needed(state, force=True)

        self._clear_active_process(proc)
        task_supervisor().cancel_owner(proc, timeout=0.5)
        return True, (proc.returncode or 0)

    def _run_with_winpty(self, cmd: List[str], env: dict, state: _RunState, PtyProcess) -> Tuple[bool, int]:
        # На Windows запускаем команду через winpty/pywinpty и читаем как текстовый поток
        try:
            try:
                cmdline = subprocess.list2cmdline(cmd)
            except Exception:
                import shlex
                cmdline = " ".join(shlex.quote(c) if " " in c else c for c in cmd)

            # Современные pywinpty принимают env — передаём TTY-окружение, чтобы UV
            # рисовал живой прогресс. Старые версии env не знают → фоллбэк без него.
            try:
                pty = PtyProcess.spawn(cmdline, env=env)
            except TypeError:
                pty = PtyProcess.spawn(cmdline)
        except Exception as e:
            logger.warning(f"PTY-режим недоступен или ошибка запуска PTY: {e}")
            return False, -1

        self._set_active_process(pty, lambda: pty.close(force=True))
        buffer = ""
        q_chunks: queue.Queue = queue.Queue()

        def _kill_pty():
            try:
                pty.close(force=True)
            except Exception:
                pass

        def _pty_reader() -> None:
            while True:
                try:
                    chunk = pty.read(4096)
                except Exception:
                    chunk = ""
                if chunk:
                    q_chunks.put(chunk)
                    continue
                if not pty.isalive():
                    break
                time.sleep(0.03)

        reader = task_supervisor().start_thread(
            pty,
            "pip-pty-reader",
            _pty_reader,
        )

        while pty.isalive() or reader.is_alive() or not q_chunks.empty():
            chunk = ""
            while not q_chunks.empty():
                try:
                    part = q_chunks.get_nowait()
                except queue.Empty:
                    break
                if isinstance(part, bytes):
                    part = self._decode_subprocess_chunk(part)
                chunk += part or ""

            if chunk:
                self._emit_raw_log(chunk)
                buffer += chunk
                parts = re.split(r'(\r|\n)', buffer)
                buffer = ""
                acc = ""
                i = 0
                permanent_lines = 0
                while i < len(parts):
                    tok = parts[i]
                    if tok in ("\r", "\n"):
                        line = acc.strip()
                        if line:
                            # \r — живая перерисовка прогресс-бара (transient),
                            # \n — завершённая строка лога.
                            self._process_line(state, line, transient=(tok == "\r"))
                            if tok == "\n":
                                permanent_lines += 1
                        acc = ""
                    else:
                        acc += tok
                    i += 1
                buffer = acc

                # Как в древнем TTY-раннере: двигаем полосу по факту прихода
                # завершённых (\n) строк, пока реальный процент ещё не парсится.
                self._advance_soft_progress(state, permanent_lines)

            aborted = self._service_tick(state, _kill_pty)
            if aborted is not None:
                self._clear_active_process(pty)
                task_supervisor().cancel_owner(pty, timeout=0.5)
                return aborted

        tail = self._clean_line(buffer.strip())
        if tail:
            self._process_line(state, tail)
        self._emit_snapshot_if_needed(state, force=True)
        ret = pty.exitstatus or 0
        self._clear_active_process(pty)
        task_supervisor().cancel_owner(pty, timeout=0.5)
        return True, ret

    def _run_pip_process(self, cmd: List[str], description: str) -> bool:
        """
        Запуск UV/PIP с подробным прогрессом:
        - под PTY читаем живой UV/pip-вывод и рендерим снапшоты активных задач;
        - без PTY читаем тот же процесс через обычные pipes и двигаем верхний progress bar;
        - статус предпочитает реальную скорость/ETA по байтам, а не грубую оценку по времени.
        """
        self._assert_not_gui_thread()
        self._cancel_event.clear()
        state = self._RunState(description, cmd)
        state.uv_progress = self._UvProgressAggregator()

        self.update_status(description)
        self.update_log("Выполняем: " + " ".join(cmd))

        # Используем PTY только если pywinpty уже входит в core-зависимости.
        self._ensure_pty_available()

        use_pty, PtyProcess = self._detect_pty()
        ok, ret = False, -1

        if use_pty and PtyProcess is not None and os.name == "nt":
            # Под PTY — окружение с включённым цветом/прогрессом; для пайпов — «dumb».
            ok, ret = self._run_with_winpty(cmd, self._prepare_env(tty=True), state, PtyProcess)
            if not ok:
                # Повторяем тот же uv command через обычные pipes.
                ok, ret = self._run_with_pipes(cmd, self._prepare_env(), state)
        else:
            ok, ret = self._run_with_pipes(cmd, self._prepare_env(), state)
        self._last_run_uv_cache_access_denied = self._is_uv_cache_access_denied_failure(cmd, state, ret)
        self._last_run_returncode = ret
        self._last_run_recent_lines = list(state.recent_lines)

        # Завершение
        elapsed = time.time() - state.start
        self.update_status(f"{description} — завершено за {self._fmt_hms(elapsed)}")

        if not ok or ret != 0:
            self._log_failure_context(cmd, state, ret)
            err_msg = f"ОШИБКА: Процесс завершился с кодом {ret}."
            if not state.error_seen:
                self.update_log(err_msg)
            if self._is_uv_command(cmd) and ret == 2:
                self.update_log(
                    "uv не смог разрешить совместимый набор зависимостей. "
                    "Автоматический fallback на pip отключён: он мог бы собрать "
                    "другой, непроверенный runtime. Активная среда не изменена."
                )
            # Принудительно пишем в основной логгер
            logger.error(f"[installer] pip process failed with code {ret}. Command: {cmd}")
            return False
        
        self.update_progress(100)
        self.update_log(f"pip завершился успешно (код {ret})")
        return True
