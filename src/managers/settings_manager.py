from __future__ import annotations

import atexit
import json
import os
import queue
import shutil
import threading
import time
from typing import Any, Iterable

from core.app_paths import settings_path
from core.settings_registry import SettingChange, SettingsRegistry, SettingsSubscription
from core.task_supervisor import task_supervisor
from main_logger import logger


class SettingsManager:
    """Owns the in-memory registry and asynchronous JSON persistence.

    ``settings`` intentionally points to ``registry`` for compatibility with
    legacy code that treated it as a mutable dict. New code should use
    ``get/set/snapshot/subscribe`` directly.
    """

    instance: "SettingsManager | None" = None
    SAVE_DEBOUNCE_SEC = 0.5
    _SENTINEL = object()
    _fallback_settings: dict[str, Any] = {}
    _fallback_path: str | None = None
    _fallback_mtime: float | None = None
    _fallback_lock = threading.RLock()

    def __init__(self, config_path: str):
        self.config_path = os.path.abspath(config_path)
        self._save_queue: "queue.Queue[object]" = queue.Queue(maxsize=1)
        self._stop_lock = threading.Lock()
        self._stopped = False

        loaded = self._read_settings_file()
        self.registry = SettingsRegistry(loaded, on_mutated=self._schedule_save)
        self.settings = self.registry
        SettingsManager.instance = self

        self._writer_thread = task_supervisor().start_thread(
            self,
            "settings-saver",
            self._save_worker,
        )
        atexit.register(self._stop_writer)

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        inst = SettingsManager.instance
        if inst:
            return inst.registry.get(key, default)
        fallback = SettingsManager._load_fallback_settings()
        return fallback.get(key, default)

    @staticmethod
    def set(key: str, value: Any, *, source: str = "runtime") -> bool:
        inst = SettingsManager.instance
        if not inst:
            logger.error("SettingsManager.set() called before init")
            return False
        return inst.registry.set(key, value, source=source)

    def require(self, key: str) -> Any:
        return self.registry.require(key)

    def snapshot(self, keys: Iterable[str] | None = None) -> dict[str, Any]:
        return self.registry.snapshot(keys)

    def update_many(
        self,
        values: dict[str, Any],
        *,
        source: str = "runtime",
    ) -> tuple[SettingChange, ...]:
        return self.registry.update_many(values, source=source)

    def subscribe(
        self,
        callback,
        *,
        keys: Iterable[str] | None = None,
        replay: bool = False,
    ) -> SettingsSubscription:
        return self.registry.subscribe(callback, keys=keys, replay=replay)

    @staticmethod
    def _fallback_config_path() -> str:
        return str(settings_path("settings.json"))

    @staticmethod
    def _load_fallback_settings() -> dict[str, Any]:
        path = SettingsManager._fallback_config_path()
        with SettingsManager._fallback_lock:
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                SettingsManager._fallback_settings = {}
                SettingsManager._fallback_path = path
                SettingsManager._fallback_mtime = None
                return SettingsManager._fallback_settings

            if (
                SettingsManager._fallback_path == path
                and SettingsManager._fallback_mtime == mtime
            ):
                return SettingsManager._fallback_settings

            try:
                with open(path, "r", encoding="utf-8") as source:
                    loaded = json.load(source)
                SettingsManager._fallback_settings = loaded if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                SettingsManager._fallback_settings = {}
            SettingsManager._fallback_path = path
            SettingsManager._fallback_mtime = mtime
            return SettingsManager._fallback_settings

    def _read_settings_file(self) -> dict[str, Any]:
        try:
            if not os.path.exists(self.config_path):
                logger.info("Файл настроек не найден – используем дефолты")
                return {}

            with open(self.config_path, "r", encoding="utf-8") as source:
                loaded = json.load(source)
            logger.info("Настройки загружены")
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError as exc:
            logger.error(f"Не удалось загрузить настройки: {exc}")
            self._backup_corrupt_settings_file()
            return {}
        except OSError as exc:
            logger.error(f"Не удалось загрузить настройки: {exc}")
            return {}

    def _backup_corrupt_settings_file(self) -> None:
        if not os.path.isfile(self.config_path):
            return
        backup_path = f"{self.config_path}.corrupt-{int(time.time())}.json"
        try:
            shutil.copy2(self.config_path, backup_path)
            logger.warning(f"Повреждённые настройки сохранены в: {backup_path}")
        except OSError as exc:
            logger.error(f"Не удалось сохранить резервную копию настроек: {exc}")

    def load_settings(self) -> None:
        self.registry.replace_all(self._read_settings_file(), notify=False)

    def _snapshot(self) -> dict[str, Any]:
        return self.registry.snapshot()

    def _write_file(self) -> None:
        snapshot = self._snapshot()
        tmp_path = self.config_path + ".tmp"
        directory = os.path.dirname(self.config_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        with open(tmp_path, "w", encoding="utf-8") as target:
            json.dump(snapshot, target, ensure_ascii=False, indent=4)
            target.flush()
            os.fsync(target.fileno())

        os.replace(tmp_path, self.config_path)
        logger.debug("Настройки сохранены")

    def _schedule_save(self) -> None:
        if self._stopped:
            return
        try:
            self._save_queue.put_nowait(1)
        except queue.Full:
            pass

    def save_settings(self) -> None:
        self._schedule_save()

    @staticmethod
    def save() -> None:
        inst = SettingsManager.instance
        if inst:
            inst._schedule_save()

    def _save_worker(self) -> None:
        stop_requested = False
        while not stop_requested:
            item = self._save_queue.get()
            if item is SettingsManager._SENTINEL:
                break

            while True:
                try:
                    item = self._save_queue.get(timeout=self.SAVE_DEBOUNCE_SEC)
                except queue.Empty:
                    break
                if item is SettingsManager._SENTINEL:
                    stop_requested = True
                    break

            try:
                self._write_file()
            except Exception as exc:
                logger.error(f"Ошибка сохранения настроек: {exc}")

    def close(self) -> None:
        self._stop_writer()

    def _stop_writer(self) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True

        while True:
            try:
                self._save_queue.get_nowait()
            except queue.Empty:
                break
        try:
            self._save_queue.put_nowait(SettingsManager._SENTINEL)
        except queue.Full:
            pass

        if self._writer_thread.is_alive() and self._writer_thread is not threading.current_thread():
            self._writer_thread.join(timeout=2.0)
        try:
            self._write_file()
        except Exception as exc:
            logger.error(f"Ошибка финального сохранения настроек: {exc}")
        self.registry.close()
        task_supervisor().cancel_owner(self, timeout=0.5)
