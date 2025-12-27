import os
import json
import time
import threading
import sounddevice as sd

from handlers.asr_handler import SpeechRecognition
from main_logger import logger
from core.events import get_event_bus, Events, Event
from utils import getTranslationVariant as _


class SpeechController:
    def __init__(self):
        self.settings = None
        self.device_id = 0
        self.selected_microphone = ""
        self.mic_recognition_active = False
        self.instant_send = False
        self.events_bus = get_event_bus()

        self._asr_settings_path = os.path.join("Settings", "asr_settings.json")
        self._asr_settings = {
            "engine": "google",
            "models": {
                "google": {},
                "gigaam": {"device": "auto"}
            }
        }

        self._subscribe_to_events()

    # ——— settings json
    def _load_asr_settings(self):
        try:
            os.makedirs("Settings", exist_ok=True)
            if os.path.exists(self._asr_settings_path):
                with open(self._asr_settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._asr_settings.update(data)
        except Exception as e:
            logger.error(f"ASR settings load error: {e}")

    def _save_asr_settings(self):
        try:
            os.makedirs("Settings", exist_ok=True)
            with open(self._asr_settings_path, "w", encoding="utf-8") as f:
                json.dump(self._asr_settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"ASR settings save error: {e}")

    # ——— subscriptions
    def _subscribe_to_events(self):
        eb = self.events_bus
        eb.subscribe("speech_settings_loaded", self._on_speech_settings_loaded, weak=False)
        eb.subscribe("setting_changed", self._on_setting_changed, weak=False)

        eb.subscribe(Events.Speech.GET_INSTANT_SEND_STATUS, self._on_get_instant_send_status, weak=False)
        eb.subscribe(Events.Speech.SET_INSTANT_SEND_STATUS, self._on_set_instant_send_status, weak=False)
        eb.subscribe(Events.Speech.SPEECH_TEXT_RECOGNIZED, self._on_speech_text_recognized, weak=False)
        eb.subscribe(Events.Speech.GET_MIC_STATUS, self._on_get_mic_status, weak=False)
        eb.subscribe(Events.Speech.GET_USER_INPUT, self._on_get_user_input, weak=False)

        eb.subscribe(Events.Speech.SET_MICROPHONE, self._on_set_microphone, weak=False)
        eb.subscribe(Events.Speech.START_SPEECH_RECOGNITION, self._on_start_speech_recognition, weak=False)
        eb.subscribe(Events.Speech.STOP_SPEECH_RECOGNITION, self._on_stop_speech_recognition, weak=False)
        eb.subscribe(Events.Speech.RESTART_SPEECH_RECOGNITION, self._on_restart_speech_recognition, weak=False)

        eb.subscribe(Events.Speech.GET_MICROPHONE_LIST, self._on_get_microphone_list, weak=False)
        eb.subscribe(Events.Speech.REFRESH_MICROPHONE_LIST, self._on_refresh_microphone_list, weak=False)

        # Новые универсальные события настроек распознавателя
        eb.subscribe(Events.Speech.GET_RECOGNIZER_SETTINGS_SCHEMA, self._on_get_recognizer_settings_schema, weak=False)
        eb.subscribe(Events.Speech.GET_RECOGNIZER_SETTINGS, self._on_get_recognizer_settings, weak=False)
        eb.subscribe(Events.Speech.SET_RECOGNIZER_OPTION, self._on_set_recognizer_option, weak=False)
        eb.subscribe(Events.Speech.APPLY_RECOGNIZER_SETTINGS, self._on_apply_recognizer_settings, weak=False)

        eb.subscribe(Events.Speech.INSTALL_ASR_MODEL, self._on_install_asr_model, weak=False)
        eb.subscribe(Events.Speech.CHECK_ASR_MODEL_INSTALLED, self._on_check_asr_model_installed, weak=False)

    # ——— event handlers
    def _on_speech_settings_loaded(self, event: Event):
        self.settings = event.data.get('settings')
        self._load_asr_settings()

        engine = self.settings.get("RECOGNIZER_TYPE", self._asr_settings.get("engine", "google"))
        self._asr_settings["engine"] = engine

        SpeechRecognition.set_recognizer_type(engine)
        SpeechRecognition.apply_settings(engine, self._asr_settings["models"].get(engine, {}))

        self.device_id = self.settings.get("NM_MICROPHONE_ID", 0)
        self.selected_microphone = self.settings.get("NM_MICROPHONE_NAME", "")

        logger.info(f"Тип распознавателя установлен на: {engine}")
        if self.selected_microphone:
            logger.info(f"Загружен микрофон из настроек: {self.selected_microphone} (ID: {self.device_id})")

        # Автозапуск, если включено
        if self.settings.get("MIC_ACTIVE", False) and not self.mic_recognition_active:
            def _delayed_start():
                try:
                    self._start_maybe_install()
                except Exception as e:
                    logger.error(f"Автозапуск распознавания не удался: {e}")
            threading.Thread(target=_delayed_start, daemon=True).start()

    def _on_setting_changed(self, event: Event):
        key = event.data.get('key')
        value = event.data.get('value')

        if key == "MIC_ACTIVE":
            if bool(value):
                self._start_maybe_install()
            else:
                SpeechRecognition.speech_recognition_stop()
                self.mic_recognition_active = False
            self.events_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

        elif key == "RECOGNIZER_TYPE":
            engine = str(value)
            current = self._asr_settings.get("engine", "google")

            # если движок не поменялся — ничего не делаем, чтобы не рвать текущий поток
            if engine == current:
                logger.info(f"Тип распознавателя установлен на: {engine}")
                # на всякий случай применим актуальные настройки для текущего движка
                SpeechRecognition.apply_settings(engine, self._asr_settings["models"].get(engine, {}))
                return

            self._asr_settings["engine"] = engine
            self._save_asr_settings()

            if self.mic_recognition_active:
                SpeechRecognition.speech_recognition_stop()
                self.mic_recognition_active = False  # ВАЖНО: сбросить флаг
                time.sleep(0.2)

            SpeechRecognition.set_recognizer_type(engine)
            SpeechRecognition.apply_settings(engine, self._asr_settings["models"].get(engine, {}))

            logger.info(f"Тип распознавателя установлен на: {engine}")

            if self.settings and self.settings.get("MIC_ACTIVE", False):
                self._start_maybe_install()
        elif key == "SILENCE_THRESHOLD":
            SpeechRecognition.SILENCE_THRESHOLD = float(value)
        elif key == "SILENCE_DURATION":
            SpeechRecognition.SILENCE_DURATION = float(value)

    def _start_maybe_install(self):
        if self.mic_recognition_active:
            return
        engine = self._asr_settings.get("engine", "google")
        if not self._check_model_installed(engine):
            self.events_bus.emit(Events.GUI.SHOW_INFO_MESSAGE, {
                'title': _('Требуется установка', 'Installation required'),
                'message': _('Модель распознавания речи не установлена. Начинается установка...', 'ASR model is not installed. Installing now...')
            })
            self._install_model_async(engine)
            return

        loop_res = self.events_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
        loop = loop_res[0] if loop_res else None
        if loop:
            SpeechRecognition.speech_recognition_start(self.device_id or 0, loop)
            self.mic_recognition_active = True
        else:
            logger.error("Не удалось получить event loop для запуска распознавания речи")

    # —— universal ASR settings IO
    def _on_get_recognizer_settings_schema(self, event: Event):
        if not self._asr_settings or not self._asr_settings.get("models"):
            self._load_asr_settings()
        engine = (event.data or {}).get('engine') or self._asr_settings.get("engine", "google")
        return SpeechRecognition.get_settings_schema(engine)

    def _on_get_recognizer_settings(self, event: Event):
        if not self._asr_settings or not self._asr_settings.get("models"):
            self._load_asr_settings()
        engine = (event.data or {}).get('engine') or self._asr_settings.get("engine", "google")
        model_map = self._asr_settings.get("models", {})
        return model_map.get(engine, {})

    def _on_set_recognizer_option(self, event: Event):
        data = event.data or {}
        engine = data.get('engine') or self._asr_settings.get("engine", "google")
        key = data.get('key')
        value = data.get('value')
        if key is None:
            return
        self._asr_settings.setdefault("models", {}).setdefault(engine, {})[key] = value
        self._save_asr_settings()
        # применим для текущего движка на лету
        if engine == self._asr_settings.get("engine"):
            SpeechRecognition.apply_settings(engine, self._asr_settings["models"][engine])

    def _on_apply_recognizer_settings(self, event: Event):
        data = event.data or {}
        engine = data.get('engine') or self._asr_settings.get("engine", "google")
        settings = data.get('settings', {})
        self._asr_settings.setdefault("models", {})[engine] = settings
        self._save_asr_settings()
        if engine == self._asr_settings.get("engine"):
            SpeechRecognition.apply_settings(engine, settings)

    # —— install/check
    def _on_install_asr_model(self, event: Event):
        model_type = (event.data or {}).get('model', self._asr_settings.get("engine", "google"))
        self._install_model_async(model_type)

    def _on_check_asr_model_installed(self, event: Event):
        model_type = (event.data or {}).get('model', self._asr_settings.get("engine", "google"))
        return self._check_model_installed(model_type)

    def _check_model_installed(self, model_type: str) -> bool:
        return SpeechRecognition.check_model_installed(model_type)

    def _install_model_async(self, model_type: str):
        def install():
            try:
                loop = self.events_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)[0]
                import asyncio
                fut = asyncio.run_coroutine_threadsafe(SpeechRecognition.install_model(model_type), loop)
                success = fut.result(timeout=3600)
                if success:
                    logger.success(f"Модель {model_type} успешно установлена")
                    if self.settings and self.settings.get("MIC_ACTIVE", False):
                        self.events_bus.emit(Events.Speech.START_SPEECH_RECOGNITION, {'device_id': self.device_id})
                else:
                    logger.error(f"Не удалось установить модель {model_type}")
            except Exception as e:
                logger.error(f"Ошибка при установке модели: {e}")
                self.events_bus.emit(Events.Speech.ASR_MODEL_INSTALL_FAILED, {"model": model_type, "error": str(e)})
        threading.Thread(target=install, daemon=True).start()

    # —— mic & pipeline glue
    def _on_get_instant_send_status(self, _event: Event):
        return bool(self.settings.get("MIC_INSTANT_SENT"))

    def _on_set_instant_send_status(self, event: Event):
        self.instant_send = event.data.get('status', False)

    def _on_speech_text_recognized(self, event: Event):
        text = (event.data or {}).get('text', '').strip()
        if not text or not self.settings:
            return
        if not bool(self.settings.get("MIC_ACTIVE")):
            return

        if bool(self.settings.get("MIC_INSTANT_SENT")):
            waiting = self.events_bus.emit_and_wait(Events.Audio.GET_WAITING_ANSWER, timeout=0.5)
            waiting_answer = waiting[0] if waiting else False
            if not waiting_answer:
                self._send_instant(text)
            else:
                pass
        else:
            connected = self.events_bus.emit_and_wait(Events.Server.GET_GAME_CONNECTION, timeout=0.5)
            if connected and connected[0]:
                pass # сюда добавить отправку клиенту.
            
            self.events_bus.emit(Events.GUI.INSERT_TEXT_TO_INPUT, {"text": text})

    def _send_instant(self, text):
        self.events_bus.emit(Events.GUI.UPDATE_CHAT_UI, {'role': 'user', 'response': text, 'is_initial': False, 'emotion': ''})
        self.events_bus.emit(Events.Chat.SEND_MESSAGE, {'user_input': text, 'system_input': '', 'image_data': []})

    def _on_get_mic_status(self, _event: Event):
        return self.mic_recognition_active

    def _on_set_microphone(self, event: Event):
        name = event.data.get('name')
        dev_id = event.data.get('device_id')
        if name and dev_id is not None:
            self.selected_microphone = name
            self.device_id = dev_id
            if self.settings:
                self.settings.set("NM_MICROPHONE_ID", dev_id)
                self.settings.set("NM_MICROPHONE_NAME", name)
                self.settings.save_settings()
            logger.info(f"Выбран микрофон: {name} (ID: {dev_id})")

    def _on_start_speech_recognition(self, event: Event):
        dev_id = event.data.get('device_id', self.device_id)
        loop_result = self.events_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
        loop = loop_result[0] if loop_result else None
        if loop:
            SpeechRecognition.speech_recognition_start(dev_id, loop)
            self.mic_recognition_active = True
        else:
            logger.error("Не удалось получить event loop для запуска распознавания речи")

    def _on_stop_speech_recognition(self, _event: Event):
        SpeechRecognition.speech_recognition_stop()
        self.mic_recognition_active = False

    def _on_restart_speech_recognition(self, event: Event):
        dev_id = event.data.get('device_id', self.device_id)

        def restart():
            try:
                self.events_bus.emit(Events.Speech.STOP_SPEECH_RECOGNITION)
                start = time.time()
                while SpeechRecognition._is_running and time.time() - start < 5:
                    time.sleep(0.1)
                self.events_bus.emit(Events.Speech.START_SPEECH_RECOGNITION, {'device_id': dev_id})
            except Exception as e:
                logger.error(f"Ошибка перезапуска распознавания: {e}")

        threading.Thread(target=restart, daemon=True).start()

    def _on_get_user_input(self, _event: Event):
        return ""  # собираем в GUI
    
    def _on_get_microphone_list(self, event: Event):
        """Вернуть список доступных входных устройств в формате 'Название (id)'."""
        try:
            devices = sd.query_devices()
            result = []
            for i, d in enumerate(devices):
                if d.get('max_input_channels', 0) > 0:
                    name = d.get('name', f"Device {i}")
                    result.append(f"{name} ({i})")
            return result or ["Микрофоны не найдены"]
        except Exception as e:
            logger.error(f"Ошибка получения списка микрофонов: {e}")
            return ["Ошибка загрузки"]

    def _on_refresh_microphone_list(self, event: Event):
        """Просто переиспользуем логику получения списка."""
        return self._on_get_microphone_list(event)