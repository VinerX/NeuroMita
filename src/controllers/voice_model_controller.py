import os
import platform
import time
import copy
import json
import threading
from typing import Any

from docs import DocsManager
from main_logger import logger
from managers.settings_manager import SettingsManager
from utils import getTranslationVariant as _

from core.events import get_event_bus, Events, Event

from handlers.voice_models.catalog import get_voice_spec

try:
    from utils.gpu_utils import check_gpu_provider, get_cuda_devices, get_gpu_name_by_id
except Exception:
    def check_gpu_provider():
        return None
    def get_cuda_devices():
        return []
    def get_gpu_name_by_id(_id):
        return None


class VoiceModelController:
    """
    Backend-контроллер локальных голосовых моделей.
    - source of truth for model catalog/settings (GET_MODEL_DATA)
    - source of truth for installed set (GET_INSTALLED_MODELS)
    - runs install/uninstall via InstallController (Events.Install.RUN_WITH_UI/HEADLESS)
    """

    def __init__(self, config_dir: str = "Settings"):
        self.config_dir = config_dir or os.path.dirname(os.path.abspath(__file__))
        self.settings_values_file = os.path.join(self.config_dir, "voice_model_settings.json")

        self._lock = threading.RLock()

        self._dependencies_status_cache: dict[str, Any] | None = None
        self._dependencies_status_ts: float = 0.0

        self.language = SettingsManager.get("LANGUAGE", "RU")

        self.model_descriptions: dict[str, str] = {}
        self.setting_descriptions: dict[str, str] = {}
        self.default_description_text = _(
            "Наведите курсор на элемент интерфейса для получения описания.",
            "Hover over an interface element to get a description."
        )

        self.detected_gpu_vendor = check_gpu_provider()
        self.detected_cuda_devices = get_cuda_devices()
        self.gpu_name = None
        if self.detected_cuda_devices:
            try:
                self.gpu_name = get_gpu_name_by_id(self.detected_cuda_devices[0])
            except Exception:
                self.gpu_name = None

        self.installed_models: set[str] = set()
        self.local_voice_models: list[dict] = []

        self.docs_manager = DocsManager()
        self.event_bus = get_event_bus()

        self.reload()
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        eb = self.event_bus
        eb.subscribe(Events.VoiceModel.GET_MODEL_DATA, self._handle_get_model_data, weak=False)
        eb.subscribe(Events.VoiceModel.GET_INSTALLED_MODELS, self._handle_get_installed_models, weak=False)
        eb.subscribe(Events.VoiceModel.GET_DEPENDENCIES_STATUS, self._handle_get_dependencies_status, weak=False)
        eb.subscribe(Events.VoiceModel.GET_DEFAULT_DESCRIPTION, self._handle_get_default_description, weak=False)
        eb.subscribe(Events.VoiceModel.GET_MODEL_DESCRIPTION, self._handle_get_model_description, weak=False)
        eb.subscribe(Events.VoiceModel.GET_SETTING_DESCRIPTION, self._handle_get_setting_description, weak=False)
        eb.subscribe(Events.VoiceModel.CHECK_GPU_RTX30_40, self._handle_check_gpu_rtx30_40, weak=False)
        eb.subscribe(Events.VoiceModel.OPEN_DOC, self._handle_open_doc, weak=False)

        eb.subscribe(Events.Install.TASK_FINISHED, self._on_install_task_finished, weak=False)
        eb.subscribe(Events.Install.TASK_FAILED, self._on_install_task_failed, weak=False)

    def _ctx(self) -> dict:
        return {
            "gpu_vendor": self.detected_gpu_vendor or "CPU",
            "cuda_devices": list(self.detected_cuda_devices or []),
            "gpu_name": self.gpu_name,
            "platform": platform.system(),
        }

    def _is_voice_task(self, data: dict) -> bool:
        if not isinstance(data, dict):
            return False
        if data.get("kind") == "voice":
            return True
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        return meta.get("kind") == "voice"

    def _task_model_id(self, data: dict) -> str | None:
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        return data.get("item_id") or meta.get("item_id")

    def _task_op(self, data: dict) -> str:
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        op = str(meta.get("op") or "").strip().lower()
        if op in ("install", "uninstall"):
            return op
        tid = str(data.get("task_id") or "")
        if "uninstall" in tid:
            return "uninstall"
        return "install"

    def _handle_get_model_data(self, event: Event):
        with self._lock:
            have = bool(self.local_voice_models)
        if not have:
            logger.warning("if not have в _handle_get_model_data")
            try:
                self.reload()
            except Exception:
                pass
        with self._lock:
            return self.local_voice_models
        

    def _handle_get_installed_models(self, event: Event):
        with self._lock:
            return self.installed_models.copy()

    def _handle_get_dependencies_status(self, event: Event):
        with self._lock:
            if self._dependencies_status_cache and (time.time() - self._dependencies_status_ts) < 3.0:
                return self._dependencies_status_cache

        res = self.event_bus.emit_and_wait(Events.Audio.GET_TRITON_STATUS, timeout=2.0)
        status = res[0] if res else {}
        status = status.copy() if isinstance(status, dict) else {}
        status["show_triton_checks"] = (platform.system() == "Windows")
        status["detected_gpu_vendor"] = self.detected_gpu_vendor

        with self._lock:
            self._dependencies_status_cache = status
            self._dependencies_status_ts = time.time()
        return status

    def _handle_get_default_description(self, event: Event):
        return self.default_description_text

    def _handle_get_model_description(self, event: Event):
        model_id = event.data
        with self._lock:
            return self.model_descriptions.get(model_id, self.default_description_text)

    def _handle_get_setting_description(self, event: Event):
        setting_key = event.data
        with self._lock:
            return self.setting_descriptions.get(setting_key, self.default_description_text)

    def _handle_check_gpu_rtx30_40(self, event: Event):
        return self.is_gpu_rtx30_or_40()

    def _handle_open_doc(self, event: Event):
        self.open_doc(event.data)

    def reload(self):
        self.load_settings()
        self.refresh_installed_models()
        with self._lock:
            self._dependencies_status_cache = None
            self._dependencies_status_ts = 0.0

    def _collect_descriptions_from_models(self, models: list[dict]):
        self.model_descriptions.clear()
        self.setting_descriptions.clear()

        for m in models or []:
            mid = m.get("id")
            if mid:
                desc = m.get("description") or m.get("desc")
                if isinstance(desc, str) and desc.strip():
                    self.model_descriptions[mid] = desc.strip()

            for s in (m.get("settings") or []):
                if not isinstance(s, dict):
                    continue
                key = s.get("key")
                if not key:
                    continue
                help_text = s.get("help") or s.get("description") or s.get("desc")
                if isinstance(help_text, str) and help_text.strip():
                    self.setting_descriptions[key] = help_text.strip()

    def get_default_model_structure(self):
        try:
            res = self.event_bus.emit_and_wait(Events.Audio.GET_ALL_LOCAL_MODEL_CONFIGS, timeout=2.0)
            if res and isinstance(res[0], list):
                return res[0]
        except Exception:
            pass
        return []

    def load_settings(self):
        default_model_structure = self.get_default_model_structure()
        adapted_default_structure = self.finalize_model_settings(
            default_model_structure, self.detected_gpu_vendor, self.detected_cuda_devices
        )

        saved_values = {}
        try:
            if os.path.exists(self.settings_values_file):
                with open(self.settings_values_file, "r", encoding="utf-8") as f:
                    saved_values = json.load(f)
        except Exception as e:
            logger.info(f"{_('Ошибка загрузки сохраненных значений из', 'Error loading saved values from')} {self.settings_values_file}: {e}")
            saved_values = {}

        merged_model_structure = copy.deepcopy(adapted_default_structure)
        for model_data in merged_model_structure:
            model_id = model_data.get("id")

            if model_id in saved_values:
                model_saved_values = saved_values[model_id]
                if isinstance(model_saved_values, dict):
                    for setting in model_data.get("settings", []):
                        setting_key = setting.get("key")
                        if setting_key in model_saved_values:
                            setting.setdefault("options", {})["default"] = model_saved_values[setting_key]

            if not isinstance(model_data.get("gpu_vendor"), (list, tuple)):
                model_data["gpu_vendor"] = [v for v in [model_data.get("gpu_vendor")] if v]

        with self._lock:
            self._collect_descriptions_from_models(merged_model_structure)
            self.local_voice_models = merged_model_structure

    def save_settings_values(self, values: dict) -> dict:
        """
        values: {model_id: {setting_key: value}}
        """
        if not isinstance(values, dict) or not values:
            return {"changed": 0, "changed_by_model": {}}

        os.makedirs(os.path.dirname(self.settings_values_file) or ".", exist_ok=True)

        try:
            current: dict = {}
            if os.path.exists(self.settings_values_file):
                with open(self.settings_values_file, "r", encoding="utf-8") as f:
                    current = json.load(f)
            if not isinstance(current, dict):
                current = {}
        except Exception as e:
            logger.warning(f"Failed to read {self.settings_values_file}: {e}")
            current = {}

        def norm(v):
            if isinstance(v, bool):
                return v
            if v is None:
                return ""
            return str(v).strip()

        changed_by_model: dict[str, list[str]] = {}
        changed_total = 0

        for mid, kv in values.items():
            mid = str(mid or "").strip()
            if not mid or not isinstance(kv, dict):
                continue

            prev = current.get(mid)
            if not isinstance(prev, dict):
                prev = {}

            for k, v in kv.items():
                k = str(k or "").strip()
                if not k:
                    continue

                old_v = prev.get(k, None)
                if norm(old_v) != norm(v):
                    prev[k] = v
                    changed_by_model.setdefault(mid, []).append(k)
                    changed_total += 1

            current[mid] = prev

        tmp_path = self.settings_values_file + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            if os.path.exists(self.settings_values_file):
                try:
                    os.remove(self.settings_values_file)
                except Exception:
                    pass
            os.replace(tmp_path, self.settings_values_file)
        except Exception as e:
            logger.error(f"Failed to write {self.settings_values_file}: {e}", exc_info=True)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return {"changed": 0, "changed_by_model": {}, "error": str(e)}

        if changed_total:
            logger.info(f"Voice model settings saved: {changed_total} changes ({changed_by_model})")

        self.load_settings()
        return {"changed": changed_total, "changed_by_model": changed_by_model}

    def refresh_installed_models(self):
        ctx_base = self._ctx()

        vendors = [self.detected_gpu_vendor] if self.detected_gpu_vendor else ["NVIDIA", "AMD", "CPU"]

        installed = set()
        for m in self.get_default_model_structure():
            mid = m.get("id")
            if not mid:
                continue
            spec = get_voice_spec(mid)
            if not spec:
                continue

            ok = False
            for v in vendors:
                ctx = dict(ctx_base)
                ctx["gpu_vendor"] = v
                try:
                    if spec.is_installed(mid, ctx):
                        ok = True
                        break
                except Exception:
                    continue

            if ok:
                installed.add(mid)

        with self._lock:
            self.installed_models = installed

    def start_install(self, model_id: str, *, with_ui: bool = True, timeout_sec: float = 3600.0) -> bool:
        mid = str(model_id or "").strip()
        spec = get_voice_spec(mid)
        if not spec:
            logger.error(f"Unknown voice model spec for '{mid}'")
            return False

        ctx = self._ctx()

        def runner(*args, **kwargs):
            run_ctx = (kwargs.get("ctx") or {})
            merged = dict(ctx)
            merged.update(run_ctx)
            return spec.build_install_plan(mid, merged)

        self.event_bus.emit(Events.VoiceModel.MODEL_INSTALL_STARTED, {"model_id": mid})

        self.event_bus.emit(
            Events.Install.RUN_WITH_UI if with_ui else Events.Install.RUN_HEADLESS,
            {
                "kind": "voice",
                "item_id": mid,
                "task_id": f"voice:install:{mid}",
                "title": spec.title(mid),
                "initial_status": _("Подготовка...", "Preparing..."),
                "timeout_sec": float(timeout_sec or 3600.0),
                "meta": {"kind": "voice", "item_id": mid, "op": "install"},
                "runner": runner,
            },
        )
        return True

    def start_uninstall(self, model_id: str, *, with_ui: bool = True, timeout_sec: float = 3600.0) -> bool:
        mid = str(model_id or "").strip()
        spec = get_voice_spec(mid)
        if not spec:
            logger.error(f"Unknown voice model spec for '{mid}'")
            return False

        ctx = self._ctx()

        def runner(*args, **kwargs):
            run_ctx = (kwargs.get("ctx") or {})
            merged = dict(ctx)
            merged.update(run_ctx)
            return spec.build_uninstall_plan(mid, merged)

        self.event_bus.emit(Events.VoiceModel.MODEL_UNINSTALL_STARTED, {"model_id": mid})

        self.event_bus.emit(
            Events.Install.RUN_WITH_UI if with_ui else Events.Install.RUN_HEADLESS,
            {
                "kind": "voice",
                "item_id": mid,
                "task_id": f"voice:uninstall:{mid}",
                "title": _("Удаление локальной модели: ", "Uninstalling local model: ") + mid,
                "initial_status": _("Подготовка...", "Preparing..."),
                "timeout_sec": float(timeout_sec or 3600.0),
                "meta": {"kind": "voice", "item_id": mid, "op": "uninstall"},
                "runner": runner,
            },
        )
        return True

    def _on_install_task_finished(self, event: Event):
        data = event.data or {}
        if not self._is_voice_task(data):
            return
        mid = self._task_model_id(data)
        if not mid:
            return

        op = self._task_op(data)
        self.refresh_installed_models()

        if op == "uninstall":
            self.event_bus.emit(Events.VoiceModel.MODEL_UNINSTALL_FINISHED, {"model_id": str(mid), "success": True})
        else:
            self.event_bus.emit(Events.VoiceModel.MODEL_INSTALL_FINISHED, {"model_id": str(mid), "success": True})

        self.event_bus.emit(Events.VoiceModel.REFRESH_MODEL_PANELS)

    def _on_install_task_failed(self, event: Event):
        data = event.data or {}
        if not self._is_voice_task(data):
            return
        mid = self._task_model_id(data)
        if not mid:
            return

        op = self._task_op(data)
        self.refresh_installed_models()
        err = str(data.get("error", "") or "")

        if op == "uninstall":
            self.event_bus.emit(Events.VoiceModel.MODEL_UNINSTALL_FINISHED, {"model_id": str(mid), "success": False, "error": err})
        else:
            self.event_bus.emit(Events.VoiceModel.MODEL_INSTALL_FINISHED, {"model_id": str(mid), "success": False, "error": err})

        self.event_bus.emit(Events.VoiceModel.REFRESH_MODEL_PANELS)

    def finalize_model_settings(self, models_list, detected_vendor, cuda_devices):
        import copy as _copy
        final_models = _copy.deepcopy(models_list)

        gpu_name_upper = self.gpu_name.upper() if self.gpu_name else ""
        force_fp32 = False

        if detected_vendor == "NVIDIA" and gpu_name_upper:
            if (
                ("16" in gpu_name_upper and "V100" not in gpu_name_upper)
                or "P40" in gpu_name_upper
                or "P10" in gpu_name_upper
                or "1060" in gpu_name_upper
                or "1070" in gpu_name_upper
                or "1080" in gpu_name_upper
            ):
                force_fp32 = True
        elif detected_vendor == "AMD":
            force_fp32 = True

        for model in final_models:
            model_vendors = model.get("gpu_vendor", [])
            vendor_to_adapt_for = None

            if detected_vendor == "NVIDIA" and "NVIDIA" in model_vendors:
                vendor_to_adapt_for = "NVIDIA"
            elif detected_vendor == "AMD" and "AMD" in model_vendors:
                vendor_to_adapt_for = "AMD"
            elif not detected_vendor or detected_vendor not in model_vendors:
                vendor_to_adapt_for = "OTHER"
            elif detected_vendor in model_vendors:
                vendor_to_adapt_for = detected_vendor

            for setting in model.get("settings", []):
                options = setting.get("options", {})
                setting_key = setting.get("key")
                widget_type = setting.get("type")
                is_device_setting = "device" in str(setting_key).lower()
                is_half_setting = setting_key in ["is_half", "silero_rvc_is_half", "fsprvc_is_half", "half", "fsprvc_fsp_half"]

                adapt_key_suffix = ""
                if vendor_to_adapt_for == "NVIDIA":
                    adapt_key_suffix = "_nvidia"
                elif vendor_to_adapt_for == "AMD":
                    adapt_key_suffix = "_amd"
                elif vendor_to_adapt_for == "OTHER":
                    adapt_key_suffix = "_other"

                values_key = f"values{adapt_key_suffix}"
                default_key = f"default{adapt_key_suffix}"

                final_values_list = None
                if values_key in options:
                    final_values_list = options[values_key]
                elif "values" in options:
                    final_values_list = options["values"]

                if default_key in options:
                    options["default"] = options[default_key]

                if is_device_setting:
                    if vendor_to_adapt_for == "NVIDIA":
                        base_nvidia_values = options.get("values_nvidia", [])
                        base_other_values = options.get("values_other", ["cpu"])
                        base_non_cuda_provider = base_nvidia_values if base_nvidia_values else base_other_values
                        non_cuda_options = [v for v in base_non_cuda_provider if not str(v).startswith("cuda")]
                        if cuda_devices:
                            final_values_list = list(cuda_devices) + non_cuda_options
                        else:
                            final_values_list = [v for v in base_other_values if v in ["cpu", "mps"]] or ["cpu"]
                    else:
                        if platform.system() == "Darwin":
                            base_values = final_values_list or options.get("values_other", options.get("values", [])) or ["cpu"]
                            if "mps" not in base_values:
                                base_values = list(base_values) + ["mps"]
                            final_values_list = base_values

                if final_values_list is not None and widget_type == "combobox":
                    options["values"] = final_values_list

                keys_to_remove = [k for k in list(options.keys()) if k.startswith("values_") or k.startswith("default_")]
                for key_to_remove in keys_to_remove:
                    options.pop(key_to_remove, None)

                if force_fp32 and is_half_setting:
                    options["default"] = "False"
                    setting["locked"] = True

                if widget_type == "combobox" and "default" in options and "values" in options:
                    current_values = options["values"]
                    if isinstance(current_values, list):
                        current_default = options["default"]
                        str_values = [str(v) for v in current_values]
                        str_default = str(current_default)
                        if str_default not in str_values:
                            options["default"] = str_values[0] if str_values else ""
                    else:
                        options["default"] = ""

        return final_models

    def is_gpu_rtx30_or_40(self):
        force_unsupported_str = os.environ.get("RTX_FORCE_UNSUPPORTED", "0")
        force_unsupported = force_unsupported_str.lower() in ["true", "1", "t", "y", "yes"]
        if force_unsupported:
            return False

        if self.detected_gpu_vendor != "NVIDIA" or not self.gpu_name:
            return False

        name_upper = self.gpu_name.upper()
        if "RTX" in name_upper:
            if any(f" {gen}" in name_upper or name_upper.endswith(gen) or f"-{gen}" in name_upper for gen in ["3050", "3060", "3070", "3080", "3090"]):
                return True
            if any(f" {gen}" in name_upper or name_upper.endswith(gen) or f"-{gen}" in name_upper for gen in ["4050", "4060", "4070", "4080", "4090"]):
                return True
        return False

    def open_doc(self, doc_name: str):
        self.docs_manager.open_doc(doc_name)