from __future__ import annotations

import atexit
import json
import os
import queue
import threading

from main_logger import logger
from core.app_paths import settings_path


class SettingsManager:
    instance = None
    SAVE_DEBOUNCE_SEC = 0.5
    _SENTINEL = object()
    _fallback_settings: dict = {}
    _fallback_path: str | None = None
    _fallback_mtime: float | None = None
    _fallback_lock = threading.RLock()

    def __init__(self, config_path: str):
        self.config_path = os.path.abspath(config_path)
        self.settings: dict = {}
        self._settings_lock = threading.RLock()
        self._save_queue: "queue.Queue[object]" = queue.Queue(maxsize=1)
        self._stop_lock = threading.Lock()
        self._stopped = False

        self.load_settings()
        SettingsManager.instance = self

        self._writer_thread = threading.Thread(
            target=self._save_worker,
            name="SettingsSaver",
            daemon=True,
        )
        self._writer_thread.start()
        atexit.register(self._stop_writer)

    @staticmethod
    def get(key, default=None):
        inst = SettingsManager.instance
        if inst:
            with inst._settings_lock:
                return inst.settings.get(key, default)
        fallback = SettingsManager._load_fallback_settings()
        return fallback.get(key, default)

    @staticmethod
    def set(key, value):
        inst = SettingsManager.instance
        if not inst:
            logger.error("SettingsManager.set() called before init")
            return
        with inst._settings_lock:
            inst.settings[key] = value
        inst._schedule_save()

    @staticmethod
    def _fallback_config_path() -> str:
        return str(settings_path("settings.json"))

    @staticmethod
    def _load_fallback_settings() -> dict:
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

    def load_settings(self):
        try:
            if not os.path.exists(self.config_path):
                logger.info("Файл настроек не найден – используем дефолты")
                return

            with open(self.config_path, "r", encoding="utf-8") as source:
                loaded = json.load(source)
            with self._settings_lock:
                self.settings = loaded if isinstance(loaded, dict) else {}
            logger.info("Настройки загружены")
        except (OSError, json.JSONDecodeError) as exc:
            logger.error(f"Не удалось загрузить настройки: {exc}")
            with self._settings_lock:
                self.settings = {}

    def _snapshot(self) -> dict:
        with self._settings_lock:
            return dict(self.settings)

    def _write_file(self):
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

    def _schedule_save(self):
        if self._stopped:
            return
        try:
            self._save_queue.put_nowait(1)
        except queue.Full:
            pass

    def save_settings(self):
        self._schedule_save()

    @staticmethod
    def save():
        inst = SettingsManager.instance
        if inst:
            inst._schedule_save()

    def _save_worker(self):
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

    def close(self):
        self._stop_writer()

    def _stop_writer(self):
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
