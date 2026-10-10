from __future__ import annotations
from core.error_utils import format_exception
from dataclasses import replace

from typing import Any

from PyQt6.QtCore import Qt, QTimer

from core.events import Events, Event
from domain.audio_input import ASRInputDevice, AudioInputCatalog, EndpointIdentityStatus
from services.audio_input_contracts import MicrophoneIdentityUnavailable
from services.microphone_selection import (
    find_display_device,
    microphone_backends,
    resolve_microphone,
)
from infrastructure.settings.microphone_preferences import (
    read_microphone_selection,
    MICROPHONE_SETTING_KEYS,
)
from core.services import services
from services.contracts import ASRCaptureState, InstallableCatalogService, SpeechService
from main_logger import logger
from services.asr_settings_service import ensure_asr_settings_service
from handlers.asr_input_gate import normalize_input_mode
from localization.schema import option_label
from localization.live import register
import weakref
from utils import getTranslationVariant as _
from .base_controller import BaseController


class MicrophoneSettingsController(BaseController):
    # Значения VAD-параметров по умолчанию (ключ настройки -> дефолт).
    VAD_DEFAULTS: dict[str, Any] = {
        "VOSK_SAMPLE_RATE": 16000,
        "CHUNK_SIZE": 512,
        "VAD_THRESHOLD": 0.5,
        "VAD_SILENCE_TIMEOUT_SEC": 0.6,
        "VAD_PRE_BUFFER_DURATION_SEC": 0.4,
        "MAX_SPEECH_DURATION_SEC": 30.0,
        "MIN_SPEECH_DURATION_SEC": 0.35,
    }

    def __init__(self, main_controller, view):
        self._bound_sig: tuple[int, ...] | None = None
        super().__init__(main_controller, view)

    # Настройки-переключатели микрофона, которые могут меняться извне (например,
    # тумблерами на странице песочницы) → атрибут чекбокса в UI.
    _EXTERNAL_TOGGLES: dict[str, str] = {
        "MIC_ACTIVE": "mic_active_checkbox",
        "MIC_INSTANT_SENT": "mic_instant_checkbox",
        "MIC_INSTANT_SEND_DELAY_ENABLED": "mic_instant_delay_checkbox",
        "MIC_INSTANT_MERGE_CHAT_INPUT": "mic_instant_merge_input_checkbox",
        "MIC_MUTE_WHILE_SPEAKING": "mic_mute_while_speaking_checkbox",
    }

    def subscribe_to_events(self):
        eb = self.event_bus
        eb.subscribe(
            Events.Install.TASK_FINISHED, self._on_install_finished, weak=False
        )
        eb.subscribe(Events.Install.TASK_FAILED, self._on_install_failed, weak=False)
        eb.subscribe(
            Events.Install.CATALOG_CHANGED, self._on_catalog_changed, weak=False
        )
        eb.subscribe(
            Events.Speech.ASR_CAPTURE_CHANGED,
            self._on_capture_state_changed,
            weak=False,
        )

        # Живая синхронизация: если MIC_* поменяли не на этой странице (песочница,
        # другой контрол), подтягиваем чекбоксы, а не показываем устаревшее значение.
        self._subscribe_settings(
            self._reflect_external_setting,
            keys=(
                *self._EXTERNAL_TOGGLES,
                "ASR_INPUT_MODE",
                *MICROPHONE_SETTING_KEYS,
            ),
        )

        subscription = ensure_asr_settings_service().subscribe(
            lambda change: self._ui(self._refresh_asr_language)
        )
        self._settings_subscriptions.append(subscription)
        self._ui(self._bind_if_ready)

    def _reflect_external_setting(self, change) -> None:
        v = self.view
        if not v:
            return
        if change.key in MICROPHONE_SETTING_KEYS:
            self.refresh_microphones(prefer_saved=True)
            return
        if change.key == "ASR_INPUT_MODE":
            combo = getattr(v, "asr_input_mode_combobox", None)
            if combo is not None:
                combo.blockSignals(True)
                try:
                    combo.setCurrentIndex(
                        combo.findData(normalize_input_mode(change.value))
                    )
                finally:
                    combo.blockSignals(False)
            return
        attr = self._EXTERNAL_TOGGLES.get(str(getattr(change, "key", "") or ""))
        if not attr or not hasattr(v, attr):
            return
        checkbox = getattr(v, attr)
        value = bool(getattr(change, "value", False))
        if str(getattr(change, "key", "") or "") == "MIC_ACTIVE":
            restart = getattr(v, "asr_restart_button", None)
            if restart is not None:
                restart.setEnabled(value)
        if checkbox is None or checkbox.isChecked() == value:
            return
        checkbox.blockSignals(True)
        try:
            checkbox.setChecked(value)
        finally:
            checkbox.blockSignals(False)

        # Сигналы гасим, чтобы значение не ушло обратно в настройки, но вид
        # зависит от галки (скрытые строки) — его обновляем явно. Слоты
        # контроллера сидят на stateChanged, петли не будет.
        checkbox.toggled.emit(value)

    def _on_capture_state_changed(self, event: Event) -> None:
        state = event.data
        if isinstance(state, ASRCaptureState):
            self._ui(lambda: self._set_input_mode_enabled(not state.active))

    def _set_input_mode_enabled(self, enabled: bool) -> None:
        self._asr_capture_active = not enabled
        language = getattr(self.view, "asr_language_combobox", None)
        if language is not None:
            language.setEnabled(enabled and bool(language.property("language_editable")))
        combo = getattr(self.view, "asr_input_mode_combobox", None)
        if combo is not None:
            combo.setEnabled(enabled)

    def _widgets_signature(self) -> tuple[int, ...] | None:
        v = self.view
        if not v:
            return None
        need = (
            "mic_combobox",
            "mic_refresh_button",
            "recognizer_combobox",
            "asr_refresh_button",
            "mic_active_checkbox",
            "mic_instant_checkbox",
            "mic_instant_delay_checkbox",
            "mic_instant_delay_spin",
            "mic_instant_merge_input_checkbox",
            "mic_mute_while_speaking_checkbox",
            "asr_restart_button",
            "vad_apply_button",
            "asr_input_mode_combobox",
            "asr_language_combobox",
        )
        for n in need:
            if getattr(v, n, None) is None:
                return None
        return tuple(id(getattr(v, n)) for n in need)

    def _bind_if_ready(self):
        sig = self._widgets_signature()
        if sig is None:
            QTimer.singleShot(350, lambda: self._ui(self._bind_if_ready))
            return

        if self._bound_sig == sig:
            self._reflect_capture_mode_lock()
            QTimer.singleShot(1200, lambda: self._ui(self._bind_if_ready))
            return

        self._bound_sig = sig
        v = self.view
        self._reflect_capture_mode_lock()

        def safe_disconnect(qt_signal, slot):
            try:
                qt_signal.disconnect(slot)
            except TypeError:
                return

        safe_disconnect(
            v.asr_input_mode_combobox.currentIndexChanged, self._on_input_mode_changed
        )
        v.asr_input_mode_combobox.currentIndexChanged.connect(
            self._on_input_mode_changed
        )

        safe_disconnect(v.mic_refresh_button.clicked, self.refresh_microphones)
        v.mic_refresh_button.clicked.connect(self.refresh_microphones)

        safe_disconnect(v.asr_refresh_button.clicked, self.refresh_engines)
        v.asr_refresh_button.clicked.connect(self.refresh_engines)

        safe_disconnect(v.asr_restart_button.clicked, self._on_restart_asr)
        v.asr_restart_button.clicked.connect(self._on_restart_asr)

        safe_disconnect(v.mic_combobox.activated, self._on_mic_changed)
        v.mic_combobox.activated.connect(self._on_mic_changed)
        backend = getattr(v, "mic_backend_combobox", None)
        if backend is not None:
            safe_disconnect(backend.activated, self._on_backend_changed)
            backend.activated.connect(self._on_backend_changed)

        safe_disconnect(
            v.recognizer_combobox.currentTextChanged, self._on_engine_changed
        )
        v.recognizer_combobox.currentTextChanged.connect(self._on_engine_changed)

        safe_disconnect(v.asr_language_combobox.activated, self._on_asr_language_changed)
        v.asr_language_combobox.activated.connect(self._on_asr_language_changed)
        controller_ref = weakref.ref(self)

        def refresh_language(_widget):
            controller = controller_ref()
            if controller is not None and not controller._closed:
                controller._refresh_asr_language()

        register(v.asr_language_combobox, refresh_language)


        safe_disconnect(v.mic_active_checkbox.stateChanged, self._on_active_toggled)
        v.mic_active_checkbox.stateChanged.connect(self._on_active_toggled)

        safe_disconnect(v.mic_instant_checkbox.stateChanged, self._on_instant_toggled)
        v.mic_instant_checkbox.stateChanged.connect(self._on_instant_toggled)

        safe_disconnect(
            v.mic_instant_delay_checkbox.stateChanged, self._on_instant_delay_toggled
        )
        v.mic_instant_delay_checkbox.stateChanged.connect(
            self._on_instant_delay_toggled
        )

        safe_disconnect(
            v.mic_instant_delay_spin.valueChanged, self._on_instant_delay_changed
        )
        v.mic_instant_delay_spin.valueChanged.connect(self._on_instant_delay_changed)

        safe_disconnect(
            v.mic_instant_merge_input_checkbox.stateChanged,
            self._on_instant_merge_input_toggled,
        )
        v.mic_instant_merge_input_checkbox.stateChanged.connect(
            self._on_instant_merge_input_toggled
        )

        safe_disconnect(
            v.mic_mute_while_speaking_checkbox.stateChanged,
            self._on_mute_while_speaking_toggled,
        )
        v.mic_mute_while_speaking_checkbox.stateChanged.connect(
            self._on_mute_while_speaking_toggled
        )

        if hasattr(v, "asr_manage_button") and v.asr_manage_button:
            safe_disconnect(v.asr_manage_button.clicked, self._open_asr_catalog)
            v.asr_manage_button.clicked.connect(self._open_asr_catalog)

        if hasattr(v, "vad_apply_button") and v.vad_apply_button:
            safe_disconnect(v.vad_apply_button.clicked, self._on_apply_vad_params)
            v.vad_apply_button.clicked.connect(self._on_apply_vad_params)

        if hasattr(v, "vad_reset_button") and v.vad_reset_button:
            safe_disconnect(v.vad_reset_button.clicked, self._on_reset_vad_params)
            v.vad_reset_button.clicked.connect(self._on_reset_vad_params)

        self._load_vad_params()

        self.refresh_microphones()
        self.refresh_engines()
        QTimer.singleShot(400, lambda: self._ui(self.refresh_engines))

        QTimer.singleShot(1200, lambda: self._ui(self._bind_if_ready))

    def _on_input_mode_changed(self, _index):
        self._save_setting(
            "ASR_INPUT_MODE",
            normalize_input_mode(self.view.asr_input_mode_combobox.currentData()),
        )

    def _reflect_capture_mode_lock(self) -> None:
        speech = services().get_optional(SpeechService)
        if speech is not None:
            self._set_input_mode_enabled(not speech.capture_state().active)

    def _load_vad_params(self):
        v = self.view
        if not v:
            return
        try:
            settings = getattr(v, "settings", None) or {}
            if hasattr(v, "vad_sample_rate_spinbox"):
                v.vad_sample_rate_spinbox.setValue(
                    int(settings.get("VOSK_SAMPLE_RATE", 16000))
                )
            if hasattr(v, "vad_chunk_size_spinbox"):
                v.vad_chunk_size_spinbox.setValue(int(settings.get("CHUNK_SIZE", 512)))
            if hasattr(v, "vad_threshold_spinbox"):
                v.vad_threshold_spinbox.setValue(
                    float(settings.get("VAD_THRESHOLD", 0.5))
                )
            if hasattr(v, "vad_silence_timeout_spinbox"):
                v.vad_silence_timeout_spinbox.setValue(
                    float(settings.get("VAD_SILENCE_TIMEOUT_SEC", 0.6))
                )
            if hasattr(v, "vad_pre_buffer_spinbox"):
                v.vad_pre_buffer_spinbox.setValue(
                    float(settings.get("VAD_PRE_BUFFER_DURATION_SEC", 0.4))
                )
            if hasattr(v, "vad_max_speech_duration_spinbox"):
                v.vad_max_speech_duration_spinbox.setValue(
                    float(settings.get("MAX_SPEECH_DURATION_SEC", 30.0))
                )
            if hasattr(v, "vad_min_speech_duration_spinbox"):
                v.vad_min_speech_duration_spinbox.setValue(
                    float(settings.get("MIN_SPEECH_DURATION_SEC", 0.35))
                )
        except Exception as e:
            logger.debug(f"VAD params load error: {format_exception(e)}")

    def _on_apply_vad_params(self):
        v = self.view
        if not v:
            return
        try:
            if hasattr(v, "vad_sample_rate_spinbox"):
                self._save_setting(
                    "VOSK_SAMPLE_RATE", v.vad_sample_rate_spinbox.value()
                )
            if hasattr(v, "vad_chunk_size_spinbox"):
                self._save_setting("CHUNK_SIZE", v.vad_chunk_size_spinbox.value())
            if hasattr(v, "vad_threshold_spinbox"):
                self._save_setting("VAD_THRESHOLD", v.vad_threshold_spinbox.value())
            if hasattr(v, "vad_silence_timeout_spinbox"):
                self._save_setting(
                    "VAD_SILENCE_TIMEOUT_SEC", v.vad_silence_timeout_spinbox.value()
                )
            if hasattr(v, "vad_pre_buffer_spinbox"):
                self._save_setting(
                    "VAD_PRE_BUFFER_DURATION_SEC", v.vad_pre_buffer_spinbox.value()
                )
            if hasattr(v, "vad_max_speech_duration_spinbox"):
                self._save_setting(
                    "MAX_SPEECH_DURATION_SEC", v.vad_max_speech_duration_spinbox.value()
                )
            if hasattr(v, "vad_min_speech_duration_spinbox"):
                self._save_setting(
                    "MIN_SPEECH_DURATION_SEC", v.vad_min_speech_duration_spinbox.value()
                )
            logger.info("VAD параметры применены")
        except Exception as e:
            logger.error(f"VAD params apply error: {format_exception(e)}")

    def _on_reset_vad_params(self):
        """Сброс параметров распознавания к значениям по умолчанию: ставим
        дефолты в спинбоксы и сразу сохраняем (как «Применить»)."""
        v = self.view
        if not v:
            return
        d = self.VAD_DEFAULTS
        try:
            if hasattr(v, "vad_sample_rate_spinbox"):
                v.vad_sample_rate_spinbox.setValue(int(d["VOSK_SAMPLE_RATE"]))
            if hasattr(v, "vad_chunk_size_spinbox"):
                v.vad_chunk_size_spinbox.setValue(int(d["CHUNK_SIZE"]))
            if hasattr(v, "vad_threshold_spinbox"):
                v.vad_threshold_spinbox.setValue(float(d["VAD_THRESHOLD"]))
            if hasattr(v, "vad_silence_timeout_spinbox"):
                v.vad_silence_timeout_spinbox.setValue(
                    float(d["VAD_SILENCE_TIMEOUT_SEC"])
                )
            if hasattr(v, "vad_pre_buffer_spinbox"):
                v.vad_pre_buffer_spinbox.setValue(
                    float(d["VAD_PRE_BUFFER_DURATION_SEC"])
                )
            if hasattr(v, "vad_max_speech_duration_spinbox"):
                v.vad_max_speech_duration_spinbox.setValue(
                    float(d["MAX_SPEECH_DURATION_SEC"])
                )
            if hasattr(v, "vad_min_speech_duration_spinbox"):
                v.vad_min_speech_duration_spinbox.setValue(
                    float(d["MIN_SPEECH_DURATION_SEC"])
                )
            self._on_apply_vad_params()
            logger.info("VAD параметры сброшены к значениям по умолчанию")
        except Exception as e:
            logger.error(f"VAD params reset error: {format_exception(e)}")

    def _open_asr_catalog(self):
        self.event_bus.emit(
            Events.GUI.SHOW_WINDOW,
            {"window_id": "ai_hub", "payload": {"category": "asr"}},
        )

    def _save_setting(self, key: str, value: Any):
        v = self.view
        if v and hasattr(v, "_save_setting"):
            try:
                v._save_setting(key, value)
                return
            except Exception:
                pass

        super()._save_setting(key, value)

    def _reset_init_status(self):
        v = self.view
        if not v:
            return
        if (
            hasattr(v, "asr_set_pill")
            and hasattr(v, "asr_init_status")
            and v.asr_init_status is not None
        ):
            try:
                v.asr_set_pill.emit(
                    {"label": v.asr_init_status, "text": "—", "kind": "info"}
                )
            except Exception:
                pass

    # SpeechService — ленивая optional-фича: если открыть настройки микрофона
    # раньше, чем она поднялась, список залипал на «микрофоны не найдены» и не
    # обновлялся сам (микрофон физически есть, распознавание потом работает).
    # Пока сервис не появился — коротко повторяем запрос.
    _SPEECH_WAIT_MAX = 25  # ~15 c при 600 мс
    _SPEECH_WAIT_INTERVAL_MS = 600

    def _speech_service_or_retry(self, retry_fn, counter_attr: str):
        """Возвращает (service, gave_up). Если сервиса ещё нет — планирует
        повтор retry_fn и возвращает (None, False); при исчерпании попыток —
        (None, True), чтобы вызывающий показал финальную заглушку."""
        speech = services().get_optional(SpeechService)
        if speech is not None:
            setattr(self, counter_attr, 0)
            return speech, False
        ticks = int(getattr(self, counter_attr, 0))
        if ticks < self._SPEECH_WAIT_MAX:
            setattr(self, counter_attr, ticks + 1)
            QTimer.singleShot(self._SPEECH_WAIT_INTERVAL_MS, lambda: self._ui(retry_fn))
            return None, False
        return None, True

    def refresh_microphones(self, *, prefer_saved=False):
        v = self.view
        if not v:
            return
        combo = getattr(v, "mic_combobox", None)
        refresh_button = getattr(v, "mic_refresh_button", None)
        if combo is None or refresh_button is None:
            return
        monitor = getattr(v, "mic_monitor_controller", None)
        if monitor:
            monitor.stop()
        req_id = int(getattr(v, "_mic_list_req_id", 0)) + 1
        v._mic_list_req_id = req_id
        previous = None if prefer_saved else v.mic_combobox.currentData()
        previous_selection = (
            previous.selection if isinstance(previous, ASRInputDevice) else None
        )
        v.mic_combobox.setEnabled(False)
        v.mic_refresh_button.setEnabled(False)

        def cb(result, error=None):
            def apply():
                if (
                    self.is_closed
                    or int(getattr(v, "_mic_list_req_id", 0)) != req_id
                    or getattr(v, "mic_combobox", None) is not combo
                    or getattr(v, "mic_refresh_button", None) is not refresh_button
                ):
                    return
                catalog = (
                    result
                    if isinstance(result, AudioInputCatalog)
                    else AudioInputCatalog(tuple(result or ()))
                )
                self._microphone_catalog = catalog
                devices = [d for d in catalog.devices if isinstance(d, ASRInputDevice)]
                combo.blockSignals(True)
                try:
                    combo.clear()
                    selected = -1
                    saved = read_microphone_selection(v.settings)
                    selection = (
                        previous_selection
                        if previous_selection
                        and previous_selection.uid
                        and not prefer_saved
                        else saved
                    )
                    saved_name, saved_uid = selection.name, selection.uid
                    try:
                        chosen = resolve_microphone(
                            catalog, replace(selection, backend="")
                        )
                    except MicrophoneIdentityUnavailable:
                        chosen = None
                    for device in devices:
                        combo.addItem(device.label, device)
                        i = combo.count() - 1
                        detail = f"{device.label}\n{device.host_api} · PortAudio {device.index}"
                        if not device.uid:
                            detail += "\n" + _(
                                "Постоянный ID недоступен — выбор по имени и индексу.",
                                "Persistent ID unavailable — selection uses name and index.",
                            )
                        combo.setItemData(
                            i,
                            detail,
                            Qt.ItemDataRole.ToolTipRole,
                        )
                        if device == chosen:
                            selected = i
                    if selected < 0 and (saved_name or saved_uid):
                        binding_unknown = bool(saved_uid) and (
                            error is not None
                            or catalog.identity_status
                            != EndpointIdentityStatus.AVAILABLE
                        )
                        title = (
                            _(
                                "Не удалось проверить привязку микрофона",
                                "Could not verify microphone binding",
                            )
                            if binding_unknown
                            else _(
                                "Выбранный микрофон недоступен",
                                "Selected microphone is unavailable",
                            )
                        )
                        combo.insertItem(
                            0,
                            title + ": " + (saved_name or str(saved_uid)),
                            None,
                        )
                        selected = 0
                        if binding_unknown:
                            combo.setItemData(
                                0,
                                _(
                                    "Не удалось прочитать Windows ID микрофона. Привязка сохранена; обновите список устройств.",
                                    "Could not read the microphone's Windows ID. Binding is preserved; refresh the device list.",
                                ),
                                Qt.ItemDataRole.ToolTipRole,
                            )
                    elif selected < 0 and devices:
                        selected = 0
                    elif not devices and not saved_name:
                        combo.addItem(
                            _("Ошибка загрузки", "Loading error")
                            if error
                            else _("Микрофоны не найдены", "No microphones found")
                        )
                        selected = 0
                    combo.setCurrentIndex(selected)
                    combo.setEnabled(bool(devices))
                    combo.setToolTip(
                        combo.currentData(Qt.ItemDataRole.ToolTipRole)
                        or combo.currentText()
                    )
                finally:
                    combo.blockSignals(False)
                    v.mic_refresh_button.setEnabled(True)
                self._populate_backends(saved.backend)
                if monitor:
                    monitor._render()

            self._ui(apply)

        speech, gave_up = self._speech_service_or_retry(
            self.refresh_microphones, "_mic_speech_wait"
        )
        if speech is None:
            if gave_up:
                cb([], RuntimeError("Speech service is unavailable"))
            return
        try:
            request = getattr(speech, "microphone_catalog_async", None)
            if callable(request):
                request(cb)
            else:
                speech.microphone_list_async(cb)
        except Exception as exc:
            logger.warning("Microphone list request failed: %s", format_exception(exc))
            cb([], exc)

    def refresh_engines(self, select_engine: str | None = None):
        v = self.view
        if not v or getattr(v, "recognizer_combobox", None) is None:
            return

        req_id = int(getattr(v, "_asr_glossary_req_id", 0)) + 1
        v._asr_glossary_req_id = req_id

        try:
            prev_engine = (
                v.recognizer_combobox.currentText()
                if v.recognizer_combobox.isEnabled()
                else ""
            )
        except Exception:
            prev_engine = ""

        def show_loading():
            v.recognizer_combobox.setVisible(True)
            empty_status = getattr(v, "asr_models_empty_status", None)
            if empty_status is not None:
                empty_status.setVisible(False)
            v.recognizer_combobox.blockSignals(True)
            try:
                v.recognizer_combobox.clear()
                v.recognizer_combobox.setEnabled(False)
                v.recognizer_combobox.addItem(_("Загрузка...", "Loading..."))
            finally:
                v.recognizer_combobox.blockSignals(False)
            self._refresh_asr_language()

        self._ui(show_loading)

        desired = ""
        try:
            desired = (select_engine or v.settings.get("RECOGNIZER_TYPE") or "").strip()
        except Exception:
            desired = (select_engine or "").strip()

        def cb(result, error=None):
            def apply():
                if int(getattr(v, "_asr_glossary_req_id", 0)) != req_id:
                    return

                glossary = result if isinstance(result, list) else []
                engines: list[str] = []
                for item in glossary:
                    try:
                        metadata = (
                            item.get("metadata") if isinstance(item, dict) else None
                        )
                        status = item.get("status") if isinstance(item, dict) else None
                        if (
                            isinstance(metadata, dict)
                            and isinstance(status, dict)
                            and bool(status.get("ready", False))
                            and metadata.get("item_id")
                        ):
                            engines.append(str(metadata["item_id"]))
                    except Exception:
                        pass

                v.recognizer_combobox.blockSignals(True)
                try:
                    v.recognizer_combobox.clear()
                    if engines:
                        v.recognizer_combobox.setVisible(True)
                        empty_status = getattr(v, "asr_models_empty_status", None)
                        if empty_status is not None:
                            empty_status.setVisible(False)
                        v.recognizer_combobox.setEnabled(True)
                        v.recognizer_combobox.addItems(engines)

                        idx = v.recognizer_combobox.findText(desired)
                        if idx >= 0:
                            v.recognizer_combobox.setCurrentIndex(idx)
                        else:
                            v.recognizer_combobox.setCurrentIndex(0)
                            self._save_setting(
                                "RECOGNIZER_TYPE", v.recognizer_combobox.currentText()
                            )
                    else:
                        v.recognizer_combobox.setEnabled(False)
                        v.recognizer_combobox.setVisible(False)
                        empty_status = getattr(v, "asr_models_empty_status", None)
                        if empty_status is not None:
                            empty_status.setVisible(True)
                finally:
                    v.recognizer_combobox.blockSignals(False)

                try:
                    new_engine = (
                        v.recognizer_combobox.currentText()
                        if v.recognizer_combobox.isEnabled()
                        else ""
                    )
                except Exception:
                    new_engine = ""

                if new_engine != prev_engine:
                    self._reset_init_status()

                self._refresh_asr_language()
                self._apply_asr_install_status(new_engine if engines else "")

            self._ui(apply)

        catalog = services().get_optional(InstallableCatalogService)
        if catalog is None:
            cb([], RuntimeError("Installable catalog service is unavailable"))
            return
        try:
            catalog.list_rows_async(
                cb,
                include_status=True,
                category="asr",
                status_category="asr",
            )
        except Exception as e:
            logger.error(f"ASR component catalog request failed: {format_exception(e)}")
            cb([], e)

    def _apply_asr_install_status(self, engine: str):
        v = self.view
        if not v or not hasattr(v, "mic_active_checkbox"):
            return

        if (
            not engine
            or not getattr(v, "recognizer_combobox", None)
            or not v.recognizer_combobox.isEnabled()
        ):

            def off():
                try:
                    v.mic_active_checkbox.setChecked(False)
                    v.mic_active_checkbox.setEnabled(False)
                except Exception:
                    pass

            self._ui(off)
            return

        req_id = int(getattr(v, "_asr_installed_req_id", 0)) + 1
        v._asr_installed_req_id = req_id

        def lock():
            try:
                v.mic_active_checkbox.setEnabled(False)
            except Exception:
                pass

        self._ui(lock)

        def cb(result, error=None):
            def apply():
                if int(getattr(v, "_asr_installed_req_id", 0)) != req_id:
                    return

                installed = (
                    bool(result.get("ready", False))
                    if error is None and isinstance(result, dict)
                    else False
                )
                try:
                    v.mic_active_checkbox.setEnabled(bool(installed))
                    if not installed:
                        v.mic_active_checkbox.setChecked(False)
                except Exception:
                    pass

            self._ui(apply)

        catalog = services().get_optional(InstallableCatalogService)
        if catalog is None:
            cb({}, RuntimeError("Installable catalog service is unavailable"))
            return
        try:
            catalog.get_status_async(f"asr:{engine}", cb)
        except Exception as exc:
            cb({}, exc)

    def _populate_backends(self, backend=""):
        combo = getattr(self.view, "mic_backend_combobox", None)
        if combo is None:
            return
        device = self.view.mic_combobox.currentData()
        catalog = getattr(self, "_microphone_catalog", AudioInputCatalog())
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(_("Авто", "Auto"), "")
            if isinstance(device, ASRInputDevice):
                for candidate in microphone_backends(catalog, device):
                    if combo.findData(candidate.host_api) < 0:
                        combo.addItem(
                            candidate.host_api.removeprefix("Windows "),
                            candidate.host_api,
                        )
            index = combo.findData(backend)
            if index < 0 and backend:
                combo.addItem(backend + " — " + _("Недоступно", "Unavailable"), backend)
                index = combo.count() - 1
            combo.setCurrentIndex(max(0, index))
            combo.setEnabled(isinstance(device, ASRInputDevice))
        finally:
            combo.blockSignals(False)
        self._reflect_backend_device()

    def _reflect_backend_device(self):
        combo = getattr(self.view, "mic_backend_combobox", None)
        device = self.view.mic_combobox.currentData()
        if combo is None or not isinstance(device, ASRInputDevice):
            return
        catalog = getattr(self, "_microphone_catalog", AudioInputCatalog())
        selected = next(
            (
                d
                for d in microphone_backends(catalog, device)
                if d.host_api == combo.currentData()
            ),
            None,
        )
        if not combo.currentData():
            selected = find_display_device(catalog.devices, device.selection)
        if selected is not None:
            self.view.mic_combobox.setItemData(
                self.view.mic_combobox.currentIndex(), selected
            )
            self.view.mic_combobox.setToolTip(
                f"{selected.label}\n{selected.host_api} · PortAudio {selected.index}"
            )
        monitor = getattr(self.view, "mic_monitor_controller", None)
        if monitor:
            monitor.set_device_available(selected is not None)

    def _on_backend_changed(self, _index):
        monitor = getattr(self.view, "mic_monitor_controller", None)
        if monitor:
            monitor.stop()
        self._reflect_backend_device()
        self._emit_microphone_selection()

    def _emit_microphone_selection(self):
        device = self.view.mic_combobox.currentData()
        if not isinstance(device, ASRInputDevice):
            return
        backend = getattr(self.view, "mic_backend_combobox", None)
        selection = (
            replace(device.selection, backend=backend.currentData() or "")
            if backend
            else device.selection
        )
        self.event_bus.emit(Events.Speech.SET_MICROPHONE, selection)
        if self.view.settings.get("MIC_ACTIVE", False):
            self.event_bus.emit(
                Events.Speech.RESTART_SPEECH_RECOGNITION, {"device_id": device.index}
            )

    def _on_mic_changed(self, index: int):
        v = self.view
        if not v or index < 0:
            return
        device = v.mic_combobox.itemData(index)
        if not isinstance(device, ASRInputDevice):
            return
        v.mic_combobox.setToolTip(
            v.mic_combobox.itemData(index, Qt.ItemDataRole.ToolTipRole) or device.label
        )
        if v.mic_combobox.currentIndex() != index:
            v.mic_combobox.blockSignals(True)
            v.mic_combobox.setCurrentIndex(index)
            v.mic_combobox.blockSignals(False)
        self._populate_backends()
        self._emit_microphone_selection()

    def _on_engine_changed(self, engine: str):
        v = self.view
        if (
            not v
            or not getattr(v, "recognizer_combobox", None)
            or not v.recognizer_combobox.isEnabled()
        ):
            return
        eng = str(engine or "").strip()
        if not eng:
            return
        self._reset_init_status()
        self._save_setting("RECOGNIZER_TYPE", eng)
        self._refresh_asr_language()
        self._apply_asr_install_status(eng)

    def _refresh_asr_language(self):
        combo = getattr(self.view, "asr_language_combobox", None)
        hint = getattr(self.view, "asr_language_hint", None)
        engine_combo = getattr(self.view, "recognizer_combobox", None)
        if combo is None or hint is None or engine_combo is None:
            return
        engine = engine_combo.currentText() if engine_combo.isEnabled() else ""
        catalog = services().get_optional(InstallableCatalogService)
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.setEnabled(False)
            combo.setProperty("language_editable", False)
            combo.setProperty("engine_id", engine)
            if not engine or catalog is None:
                hint.setText(_("Выберите модель распознавания", "Select a recognition model"))
                return
            field = next((entry for entry in catalog.settings_schema(f"asr:{engine}")
                          if entry.get("key") == "language"), None)
            if field is None:
                hint.setText(_("Выбор языка для этой модели недоступен.", "Language selection is unavailable for this model."))
                return
            for code in field.get("options") or []:
                combo.addItem(option_label(field, code), str(code))
            values = catalog.load_settings(f"asr:{engine}")
            selected = str(values.get("language") or field.get("default") or "")
            index = combo.findData(selected)
            help_text = _(field.get("help_ru", ""), field.get("help_en", ""))
            if index < 0:
                combo.addItem(_("Недоступно: ", "Unavailable: ") + selected, selected)
                index = combo.count() - 1
                help_text = _("Сохранённый язык не поддерживается. Выберите доступный язык.",
                              "The saved language is unsupported. Select an available language.") + " " + help_text
            combo.setCurrentIndex(index)
            editable = bool(field.get("enabled", True)) and not bool(field.get("locked"))
            combo.setProperty("language_editable", editable)
            combo.setEnabled(editable and not getattr(self, "_asr_capture_active", False))
            combo.setToolTip(combo.currentText() + "\n" + help_text)
            hint.setText(help_text)
        except Exception as exc:
            hint.setText(_("Не удалось загрузить языки: ", "Could not load languages: ") + format_exception(exc))
        finally:
            combo.blockSignals(False)

    def _on_asr_language_changed(self, index: int):
        combo = self.view.asr_language_combobox
        if index < 0 or not combo.isEnabled():
            return
        engine = str(combo.property("engine_id") or "")
        if engine != self.view.recognizer_combobox.currentText():
            self._refresh_asr_language()
            return
        catalog = services().get_optional(InstallableCatalogService)
        if catalog is None:
            return
        value = combo.itemData(index)
        values = catalog.load_settings(f"asr:{engine}")
        values["language"] = value
        result = catalog.save_component_settings(f"asr:{engine}", values)
        if not result.get("ok"):
            self._refresh_asr_language()
            self.view.asr_language_hint.setText(str(result.get("errors") or _("Не удалось сохранить язык", "Could not save language")))
            return
        self.event_bus.emit(Events.Speech.SET_RECOGNIZER_OPTION,
                            {"engine": engine, "key": "language", "value": value})
        if self.view.settings.get("MIC_ACTIVE", False):
            self.event_bus.emit(Events.Speech.RESTART_SPEECH_RECOGNITION, {"full_restart": True})

    def _on_active_toggled(self, state: int):
        self._save_setting("MIC_ACTIVE", bool(state))
        restart = getattr(self.view, "asr_restart_button", None)
        if restart is not None:
            restart.setEnabled(bool(state))

    def _on_restart_asr(self):
        v = self.view
        if not v or not bool(v.settings.get("MIC_ACTIVE", False)):
            return
        self.event_bus.emit(
            Events.Speech.RESTART_SPEECH_RECOGNITION,
            {"full_restart": True},
        )

    def _on_instant_toggled(self, state: int):
        self._save_setting("MIC_INSTANT_SENT", bool(state))

    def _on_instant_delay_toggled(self, state: int):
        self._save_setting("MIC_INSTANT_SEND_DELAY_ENABLED", bool(state))

    def _on_instant_delay_changed(self, value: float):
        self._save_setting("MIC_INSTANT_SEND_DELAY_SEC", float(value))

    def _on_instant_merge_input_toggled(self, state: int):
        self._save_setting("MIC_INSTANT_MERGE_CHAT_INPUT", bool(state))

    def _on_mute_while_speaking_toggled(self, state: int):
        self._save_setting("MIC_MUTE_WHILE_SPEAKING", bool(state))

    def _is_asr_task(self, data: dict) -> bool:
        if not isinstance(data, dict):
            return False
        if data.get("kind") == "asr":
            return True
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        return meta.get("kind") == "asr"

    def _on_install_finished(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        self._ui(self.refresh_engines)

    def _on_catalog_changed(self, _event: Event):
        self._ui(self.refresh_engines)

    def _on_install_failed(self, event: Event):
        data = event.data or {}
        if not self._is_asr_task(data):
            return
        self._ui(self.refresh_engines)
