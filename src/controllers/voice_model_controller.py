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
from core.install_types import DEFAULT_INSTALL_TIMEOUT_SEC
from core.task_supervisor import task_supervisor
from core.services import services
from services.contracts import (
    InstallableCatalogService,
    InstallableOperationsService,
    LocalVoiceService,
    VoiceModelService,
)

class VoiceModelController(VoiceModelService):
    """
    Backend-контроллер локальных голосовых моделей.
    - source of truth for model catalog/settings (GET_MODEL_DATA)
    - source of truth for installed set (GET_INSTALLED_MODELS)
    - routes install/uninstall through InstallableController
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

        self.detected_gpu_vendor = "CPU"
        self.detected_cuda_devices = []
        self.gpu_name = None
        self._installable_catalog = services().get_optional(InstallableCatalogService)
        self._refresh_gpu_runtime_info()

        self.installed_models: set[str] = set()
        self.local_voice_models: list[dict] = []

        self.docs_manager = DocsManager()
        self.event_bus = get_event_bus()
        self._last_voiceover_refresh_reload_ts: float = 0.0

        self.reload()
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        eb = self.event_bus
        eb.subscribe(Events.VoiceModel.OPEN_DOC, self._handle_open_doc, weak=False)

        eb.subscribe(Events.Install.TASK_FINISHED, self._on_install_task_finished, weak=False)
        eb.subscribe(Events.Install.TASK_FAILED, self._on_install_task_failed, weak=False)

        eb.subscribe(Events.GUI.VOICEOVER_REFRESH, self._on_voiceover_refresh, weak=False)

    def _on_voiceover_refresh(self, _event: Event):
        with self._lock:
            empty = not bool(self.local_voice_models)

        if not empty:
            return

        now = time.time()
        if (now - float(self._last_voiceover_refresh_reload_ts or 0.0)) < 1.0:
            return

        try:
            struct = self.get_default_model_structure()
            if not struct:
                return
        except Exception:
            return

        self._last_voiceover_refresh_reload_ts = now
        try:
            self.reload()
        except Exception:
            return

        self.event_bus.emit(Events.VoiceModel.REFRESH_MODEL_PANELS)

    def _refresh_gpu_runtime_info(self) -> tuple[bool, bool]:
        had_cuda = bool(getattr(self, "detected_cuda_devices", None))
        old_vendor = str(getattr(self, "detected_gpu_vendor", "") or "").upper()
        old_name = str(getattr(self, "gpu_name", "") or "").strip()

        catalog = self._installable_catalog or services().get_optional(InstallableCatalogService)
        try:
            snapshot = dict(catalog.hardware_snapshot() or {}) if catalog is not None else {}
        except Exception:
            snapshot = {}
        primary = snapshot.get("primary") if isinstance(snapshot.get("primary"), dict) else {}
        cuda = snapshot.get("cuda") if isinstance(snapshot.get("cuda"), dict) else {}
        self.detected_gpu_vendor = str(snapshot.get("vendor") or "CPU").strip().upper()
        self.detected_cuda_devices = [
            f"cuda:{int(device['ordinal'])}"
            for device in (cuda.get("devices") or ())
            if isinstance(device, dict) and device.get("ordinal") is not None
        ]
        self.gpu_name = str(primary.get("name") or "").strip() or None

        new_vendor = str(self.detected_gpu_vendor or "CPU").upper()
        new_name = str(self.gpu_name or "").strip()
        if new_vendor != old_vendor or new_name != old_name:
            logger.info(
                "Detected GPU runtime: "
                f"{self.gpu_name or self.detected_gpu_vendor or 'CPU'} "
                f"(cuda_devices={list(self.detected_cuda_devices or [])})"
            )

        return had_cuda, bool(self.detected_cuda_devices)

    def _auto_promote_saved_device_settings_to_cuda(self) -> None:
        if self.detected_gpu_vendor != "NVIDIA" or not self.detected_cuda_devices:
            return
        if not os.path.exists(self.settings_values_file):
            return

        try:
            with open(self.settings_values_file, "r", encoding="utf-8") as f:
                saved_values = json.load(f)
        except Exception:
            return

        if not isinstance(saved_values, dict) or not saved_values:
            return

        try:
            models = self.finalize_model_settings(
                self.get_default_model_structure(),
                self.detected_gpu_vendor,
                self.detected_cuda_devices,
            )
        except Exception:
            return

        first_cuda = str(self.detected_cuda_devices[0])
        changed = False

        for model in models or []:
            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue

            model_saved = saved_values.get(model_id)
            if not isinstance(model_saved, dict):
                continue

            for setting in model.get("settings", []) or []:
                if not isinstance(setting, dict):
                    continue

                setting_key = str(setting.get("key") or "").strip()
                if "device" not in setting_key.lower():
                    continue

                options = setting.get("options") if isinstance(setting.get("options"), dict) else {}
                values = [str(v) for v in (options.get("values") or []) if str(v).strip()]
                if not any(v.startswith("cuda:") for v in values):
                    continue

                current_value = str(model_saved.get(setting_key) or "").strip().lower()
                valid_values_lower = {str(v).strip().lower() for v in values}
                if current_value in ("", "cpu") or current_value not in valid_values_lower:
                    model_saved[setting_key] = first_cuda
                    changed = True

        if not changed:
            return

        tmp_path = self.settings_values_file + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(saved_values, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.settings_values_file)
            logger.info(
                f"Voice model settings auto-switched to CUDA after runtime refresh: {self.detected_cuda_devices}"
            )
        except Exception as e:
            logger.warning(f"Failed to auto-switch voice model device settings to CUDA: {e}")
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

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

    def model_catalog_snapshot(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self.local_voice_models)

    def installed_models_snapshot(self) -> set[str]:
        with self._lock:
            return self.installed_models.copy()

    def _handle_get_model_data(self, _event: Event):
        # Queries must be O(1). Refresh/import work belongs to reload() and the
        # install lifecycle, both of which run outside the GUI request path.
        return self.model_catalog_snapshot()

    def _handle_get_installed_models(self, _event: Event):
        return self.installed_models_snapshot()

    def dependencies_status(self) -> dict[str, Any]:
        return dict(self._handle_get_dependencies_status(Event(Events.VoiceModel.GET_DEPENDENCIES_STATUS)) or {})

    def _handle_get_dependencies_status(self, event: Event):
        with self._lock:
            if self._dependencies_status_cache and (time.time() - self._dependencies_status_ts) < 3.0:
                return self._dependencies_status_cache

        local_voice = services().get_optional(LocalVoiceService)
        status = local_voice.triton_status() if local_voice is not None else {}
        status = status.copy() if isinstance(status, dict) else {}
        status["show_triton_checks"] = (platform.system() == "Windows")
        status["detected_gpu_vendor"] = self.detected_gpu_vendor
        status["cuda_devices"] = list(self.detected_cuda_devices or [])
        status["gpu_name"] = self.gpu_name
        catalog = services().get_optional(InstallableCatalogService)
        backend_statuses: dict[str, dict[str, Any]] = {}
        if catalog is not None:
            try:
                for row in catalog.list_rows(
                    include_status=True,
                    category="backend",
                ):
                    metadata = row.get("metadata") if isinstance(row, dict) else {}
                    canonical_status = row.get("status") if isinstance(row, dict) else {}
                    backend_id = str((metadata or {}).get("item_id") or "")
                    if backend_id:
                        backend_statuses[backend_id] = dict(
                            (canonical_status or {}).get("details") or {}
                        )
            except Exception as exc:
                logger.warning(f"Failed to read canonical backend statuses: {exc}")
        status["backend_statuses"] = backend_statuses

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

    def _handle_open_doc(self, event: Event):
        self.open_doc(event.data)

    def reload(self):
        had_cuda, has_cuda = self._refresh_gpu_runtime_info()
        if (not had_cuda) and has_cuda:
            self._auto_promote_saved_device_settings_to_cuda()
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
        models: list[dict[str, Any]] = []
        seen: set[str] = set()
        catalog = services().get_optional(InstallableCatalogService)
        metadata_by_item: dict[str, dict[str, Any]] = {}
        catalog_metadata: list[dict[str, Any]] = []
        if catalog is not None:
            try:
                catalog_metadata = [
                    row["metadata"]
                    for row in catalog.list_rows(category="tts")
                    if isinstance(row, dict) and isinstance(row.get("metadata"), dict)
                ]
                metadata_by_item = {
                    str(metadata.get("item_id") or ""): metadata
                    for metadata in catalog_metadata
                }
            except Exception:
                catalog_metadata = []
                metadata_by_item = {}
        try:
            if catalog is None:
                raise RuntimeError("Installable catalog service is unavailable")
            components = [
                catalog.require_component(str(metadata.get("id") or ""))
                for metadata in catalog_metadata
                if metadata.get("id")
            ]
            for component in components:
                get_configs = getattr(component, "get_model_configs", None)
                if not callable(get_configs):
                    continue
                for config in get_configs() or ():
                    if not isinstance(config, dict):
                        continue
                    model_id = str(config.get("id") or "").strip()
                    if not model_id or model_id in seen:
                        continue
                    model = copy.deepcopy(config)
                    canonical = metadata_by_item.get(model_id) or {}
                    if canonical:
                        model["name"] = str(canonical.get("title") or model.get("name") or model_id)
                        model["description"] = str(canonical.get("description") or "")
                        model["tags"] = list(canonical.get("tags") or ())
                        model["languages"] = list(canonical.get("languages") or ())
                        model["backend"] = str(canonical.get("backend") or "none")
                    models.append(model)
                    seen.add(model_id)
        except Exception as exc:
            logger.warning(f"Failed to build local voice catalog from installables: {exc}")

        if models:
            return models

        try:
            from presets.local_voice_models import LOCAL_VOICE_MODELS

            return copy.deepcopy(LOCAL_VOICE_MODELS)
        except Exception:
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

    def _normalize_gpu_vendor(self, vendor: Any) -> str:
        value = str(vendor or "CPU").strip().upper()
        if value in {"NVIDIA", "AMD", "INTEL", "CPU"}:
            return value
        return "CPU"

    def _normalize_gpu_vendor_list(self, vendors: Any) -> list[str]:
        if not isinstance(vendors, (list, tuple, set)):
            vendors = [vendors]

        result: list[str] = []
        for vendor in vendors:
            normalized = self._normalize_gpu_vendor(vendor)
            if normalized not in result:
                result.append(normalized)
        return result

    def _build_model_compatibility(self, model: dict) -> dict[str, Any]:
        model_id = str(model.get("id") or "").strip()
        vendors = self._normalize_gpu_vendor_list(model.get("gpu_vendor", []))
        try:
            catalog = getattr(self, "_installable_catalog", None)
            if catalog is None:
                catalog = services().get(InstallableCatalogService)
            row = catalog.get_row(
                f"tts:{model_id}",
                include_status=False,
            )
            verdict = dict(row.get("compatibility") or {})
        except Exception as exc:
            logger.warning(f"Voice model compatibility is unavailable for '{model_id}': {exc}")
            verdict = {
                "supported": False,
                "recommended": False,
                "reason_code": "state_unavailable",
                "warning": _(
                    "Не удалось проверить совместимость модели. Обновите AI Hub и повторите попытку.",
                    "Model compatibility could not be verified. Refresh AI Hub and try again.",
                ),
            }

        verdict["vendors"] = vendors
        return verdict
    def _voice_installable_component(self, model_id: str):
        catalog = services().get(InstallableCatalogService)
        return catalog.require_component(f"tts:{str(model_id or '').strip()}")

    def get_install_preflight(self, model_id: str) -> dict[str, Any]:
        mid = str(model_id or "").strip()
        if not mid:
            return {"blocked": True}

        model = next((m for m in (self.local_voice_models or []) if str(m.get("id") or "") == mid), None)
        if model is None:
            try:
                model = next((m for m in self.get_default_model_structure() if str(m.get("id") or "") == mid), None)
            except Exception:
                model = None
        model = model or {"id": mid, "name": mid}

        compat = self._build_model_compatibility(model)
        vendor = self._normalize_gpu_vendor(compat.get("gpu_vendor"))
        vendor_label = str(self.gpu_name or vendor or "CPU")
        compatibility_warning = str(compat.get("warning") or "").strip()
        needs_warning = bool(
            compat.get("supported")
            and not compat.get("recommended", True)
            and compatibility_warning
        )

        if not compat["supported"]:
            return {
                "blocked": True,
                "title": _("Несовместимая модель", "Incompatible model"),
                "message": compatibility_warning or _(
                    f"Модель '{model.get('name', mid)}' не поддерживает текущее устройство ({vendor_label}).",
                    f"The model '{model.get('name', mid)}' does not support the current device ({vendor_label}).",
                ),
            }

        try:
            catalog = services().get(InstallableCatalogService)
            preview = catalog.install_preview(f"tts:{mid}")
        except Exception as exc:
            logger.warning(f"Voice install preflight failed for '{mid}': {exc}")
            return {"blocked": False}

        backend_kind = str(preview.get("backend_kind") or "none")
        backend_status = dict(preview.get("backend_status") or {})
        if bool(preview.get("backend_ready")) or backend_kind in ("", "none"):
            if needs_warning:
                return {
                    "blocked": False,
                    "ask": True,
                    "title": _("Предупреждение о совместимости", "Compatibility warning"),
                    "message": compatibility_warning,
                }
            return {"blocked": False}

        model_name = str(model.get("name") or mid)
        title = _("Backend не установлен", "Backend missing")
        cancel_message = _(
            "Установка модели отменена. Нужный backend можно установить вручную в AI Hub, затем повторить установку.",
            "Model installation was cancelled. You can install the required backend manually in AI Hub and retry.",
        )

        if backend_kind == "cuda" and vendor == "NVIDIA":
            message = _(
                f"Для модели '{model_name}' нужен NVIDIA backend (PyTorch CUDA).\n\n"
                f"Обнаружена видеокарта: {vendor_label}.\n\n"
                "Установить NVIDIA backend сейчас и добавить его в план установки?",
                f"The model '{model_name}' needs the NVIDIA backend (PyTorch CUDA).\n\n"
                f"Detected GPU: {vendor_label}.\n\n"
                "Install the NVIDIA backend now and add it to the install plan?",
            )
            cancel_message = _(
                "Установка модели отменена. Если хотите другой путь, можно отдельно поставить ONNX backend в AI Hub и потом вернуться к выбору модели.",
                "Model installation was cancelled. If you want another path, you can install the ONNX backend manually in AI Hub and return to model setup later.",
            )
        elif backend_kind == "onnx":
            backend_label = "ONNX / DirectML" if vendor in ("AMD", "INTEL") else "ONNX"
            message = _(
                f"Для модели '{model_name}' нужен backend {backend_label}.\n\n"
                f"Текущий GPU: {vendor_label}.\n\n"
                "Установить backend сейчас и добавить его в план установки?",
                f"The model '{model_name}' needs the {backend_label} backend.\n\n"
                f"Current GPU: {vendor_label}.\n\n"
                "Install this backend now and add it to the install plan?",
            )
        else:
            message = _(
                f"Для модели '{model_name}' нужен CPU backend (PyTorch).\n\n"
                "Установить его сейчас и добавить в план установки?",
                f"The model '{model_name}' needs the CPU backend (PyTorch).\n\n"
                "Install it now and add it to the install plan?",
            )

        if needs_warning:
            message = f"{compatibility_warning}\n\n{message}"

        return {
            "blocked": False,
            "ask": True,
            "title": title,
            "message": message,
            "cancel_message": cancel_message,
            "required_backend": backend_kind,
            "backend_status": backend_status,
        }

    def refresh_installed_models(self):
        try:
            catalog = services().get(InstallableCatalogService)
            installed = set(catalog.ready_item_ids("tts"))
        except Exception as exc:
            logger.error(f"Failed to read canonical TTS readiness: {exc}", exc_info=True)
            installed = set()

        with self._lock:
            self.installed_models = installed

    def start_install(self, model_id: str, *, with_ui: bool = True, timeout_sec: float = DEFAULT_INSTALL_TIMEOUT_SEC) -> bool:
        mid = str(model_id or "").strip()
        try:
            catalog = services().get(InstallableCatalogService)
            component_id = f"tts:{mid}"
            metadata = catalog.get_row(component_id, include_status=False)["metadata"]
            title = str(metadata.get("title") or mid)
        except Exception as exc:
            logger.error(f"Unknown voice installable component for '{mid}': {exc}")
            return False

        self.event_bus.emit(Events.VoiceModel.MODEL_INSTALL_STARTED, {"model_id": mid})

        operations = services().get_optional(InstallableOperationsService)
        if operations is None:
            return False
        admission = operations.install(
            {
                "component_id": component_id,
                "kind": "voice",
                "item_id": mid,
                "task_id": f"voice:install:{mid}",
                "title": title,
                "initial_status": _("Подготовка...", "Preparing..."),
                "timeout_sec": float(timeout_sec or DEFAULT_INSTALL_TIMEOUT_SEC),
                "with_ui": bool(with_ui),
                "meta": {"kind": "voice", "item_id": mid, "op": "install"},
            }
        )
        return bool(admission.accepted)

    def start_uninstall(self, model_id: str, *, with_ui: bool = True, timeout_sec: float = DEFAULT_INSTALL_TIMEOUT_SEC) -> bool:
        mid = str(model_id or "").strip()
        try:
            catalog = services().get(InstallableCatalogService)
            component_id = f"tts:{mid}"
            catalog.get_row(component_id, include_status=False)
        except Exception as exc:
            logger.error(f"Unknown voice installable component for '{mid}': {exc}")
            return False

        self.event_bus.emit(Events.VoiceModel.MODEL_UNINSTALL_STARTED, {"model_id": mid})

        operations = services().get_optional(InstallableOperationsService)
        if operations is None:
            return False
        admission = operations.uninstall(
            {
                "component_id": component_id,
                "kind": "voice",
                "item_id": mid,
                "task_id": f"voice:uninstall:{mid}",
                "title": _("Удаление локальной модели: ", "Uninstalling local model: ") + mid,
                "initial_status": _("Подготовка...", "Preparing..."),
                "timeout_sec": float(timeout_sec or DEFAULT_INSTALL_TIMEOUT_SEC),
                "with_ui": bool(with_ui),
                "meta": {"kind": "voice", "item_id": mid, "op": "uninstall"},
            }
        )
        return bool(admission.accepted)

    def _schedule_install_state_refresh(
        self,
        *,
        data: dict[str, Any],
        success: bool,
    ) -> None:
        model_id = self._task_model_id(data)
        if not model_id:
            return
        operation = self._task_op(data)
        error = str(data.get("error", "") or "")
        task_id = str(data.get("task_id") or f"{operation}:{model_id}")

        def refresh_state() -> None:
            self.reload()
            payload = {
                "model_id": str(model_id),
                "success": bool(success),
            }
            if error:
                payload["error"] = error

            if operation == "uninstall":
                self.event_bus.emit(
                    Events.VoiceModel.MODEL_UNINSTALL_FINISHED,
                    payload,
                )
            else:
                self.event_bus.emit(
                    Events.VoiceModel.MODEL_INSTALL_FINISHED,
                    payload,
                )

            self.event_bus.emit(Events.VoiceModel.REFRESH_SETTINGS_DISPLAY)
            self.event_bus.emit(Events.VoiceModel.REFRESH_MODEL_PANELS)

        try:
            task_supervisor().start_thread(
                self,
                f"voice-model-state-refresh:{task_id}",
                refresh_state,
            )
        except RuntimeError as exc:
            logger.debug(f"Voice model state refresh was skipped during shutdown: {exc}")

    def _on_install_task_finished(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        if not self._is_voice_task(data):
            return
        self._schedule_install_state_refresh(data=dict(data), success=True)

    def _on_install_task_failed(self, event: Event):
        data = event.data if isinstance(event.data, dict) else {}
        if not self._is_voice_task(data):
            return
        self._schedule_install_state_refresh(data=dict(data), success=False)

    def finalize_model_settings(self, models_list, detected_vendor, cuda_devices):
        import copy as _copy
        final_models = _copy.deepcopy(models_list)

        detected_vendor = self._normalize_gpu_vendor(detected_vendor)
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
        elif detected_vendor in {"AMD", "INTEL"}:
            force_fp32 = True

        for model in final_models:
            compat = self._build_model_compatibility(model)
            model_vendors = compat["vendors"]
            model["gpu_vendor"] = model_vendors
            model["compat_supported"] = compat["supported"]
            model["compat_warning"] = compat["warning"]
            model["compatibility"] = dict(compat)
            vendor_to_adapt_for = None

            if detected_vendor == "NVIDIA" and "NVIDIA" in model_vendors:
                vendor_to_adapt_for = "NVIDIA"
            elif detected_vendor == "AMD" and "AMD" in model_vendors:
                vendor_to_adapt_for = "AMD"
            elif detected_vendor == "INTEL" and "INTEL" in model_vendors:
                vendor_to_adapt_for = "INTEL"
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

                final_values_list = None
                suffix_candidates: list[str]
                if vendor_to_adapt_for == "NVIDIA":
                    suffix_candidates = ["_nvidia", ""]
                elif vendor_to_adapt_for == "AMD":
                    suffix_candidates = ["_amd", ""]
                elif vendor_to_adapt_for == "INTEL":
                    suffix_candidates = ["_intel", "_amd", ""]
                elif vendor_to_adapt_for == "CPU":
                    suffix_candidates = ["_cpu", "_other", ""]
                elif vendor_to_adapt_for == "OTHER":
                    suffix_candidates = ["_other", ""]
                else:
                    suffix_candidates = [""]

                for suffix in suffix_candidates:
                    values_key = f"values{suffix}"
                    if values_key in options:
                        final_values_list = options[values_key]
                        break

                for suffix in suffix_candidates:
                    default_key = f"default{suffix}"
                    if default_key in options:
                        options["default"] = options[default_key]
                        break

                if is_device_setting:
                    if vendor_to_adapt_for == "NVIDIA":
                        base_nvidia_values = options.get("values_nvidia", [])
                        base_other_values = options.get("values_other", ["cpu"])
                        base_non_cuda_provider = base_nvidia_values if base_nvidia_values else base_other_values
                        non_cuda_options = [v for v in base_non_cuda_provider if not str(v).startswith("cuda")]
                        allows_cuda = any(
                            str(value).startswith("cuda")
                            for value in (
                                list(base_nvidia_values)
                                + list(options.get("values", []))
                            )
                        )
                        if cuda_devices and allows_cuda:
                            final_values_list = list(cuda_devices) + non_cuda_options
                        else:
                            final_values_list = non_cuda_options or [
                                v for v in base_other_values if v in ["cpu", "mps"]
                            ] or ["cpu"]
                    else:
                        if platform.system() == "Darwin":
                            base_values = final_values_list or options.get("values_other", options.get("values", [])) or ["cpu"]
                            if "mps" not in base_values:
                                base_values = list(base_values) + ["mps"]
                            final_values_list = base_values

                if setting_key == "f5rvc_f5_device" and detected_vendor != "NVIDIA":
                    final_values_list = ["cpu"]
                    options["default"] = "cpu"
                    setting["locked"] = True

                if setting_key == "f5rvc_rvc_device":
                    if detected_vendor in {"AMD", "INTEL"}:
                        final_values_list = ["dml", "cpu"]
                        options["default"] = "dml"
                    elif detected_vendor == "CPU":
                        final_values_list = ["cpu", "dml"]
                        options["default"] = "cpu"

                if setting_key == "f5rvc_is_half" and detected_vendor != "NVIDIA":
                    options["default"] = "False"
                    setting["locked"] = True

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

    def open_doc(self, doc_name: str):
        self.docs_manager.open_doc(doc_name)
