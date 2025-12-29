# src/handlers/asr_models/google_recognizer.py
import asyncio
from typing import Optional
import numpy as np

from handlers.asr_models.speech_recognizer_base import SpeechRecognizerInterface
from handlers.asr_models.requirements import AsrRequirement, check_requirements
from utils import getTranslationVariant as _


class GoogleRecognizer(SpeechRecognizerInterface):
    """
    Pip-установку НЕ делает.
    - pip_install_steps(ctx) отдаёт что поставить (SpeechRecognition + optional pyaudio)
    - install() ничего не скачивает (артефактов нет) и возвращает True
    - is_installed() проверяет наличие python-модулей по requirements
    """

    MODEL_CONFIGS = [
        {
            "id": "google",
            "name": "Google",
            "languages": ["Russian", "English"],
            "gpu_vendor": ["CPU"],
            "tags": [
                _("Онлайн", "Online"),
            ],
            "description": _(
                "Онлайн-распознавание через SpeechRecognition (Google Web Speech API). "
                "Без скачивания весов модели, но нужен интернет.",
                "Online recognition via SpeechRecognition (Google Web Speech API). "
                "No model weights download, but internet is required.",
            ),
            "links": [
                {"label": "SpeechRecognition (PyPI)", "url": "https://pypi.org/project/SpeechRecognition/"}
            ],
        }
    ]

    def __init__(self, pip_installer, logger):
        super().__init__(pip_installer, logger)
        self._sr = None

    def settings_spec(self):
        return []

    def get_default_settings(self):
        return {}

    def apply_settings(self, settings: dict):
        pass

    def requirements(self):
        return [
            AsrRequirement(id="speech_recognition", kind="python_module", module="speech_recognition", required=True),
            AsrRequirement(id="pyaudio", kind="python_module", module="pyaudio", required=False),
        ]

    def pip_install_steps(self, ctx: dict):
        return [
            {
                "progress": 20,
                "description": _("Установка SpeechRecognition...", "Installing SpeechRecognition..."),
                "packages": ["SpeechRecognition"],
                "extra_args": None
            },
        ]

    def is_installed(self) -> bool:
        st = check_requirements(self.requirements(), ctx={})
        return bool(st.get("ok"))

    async def install(self) -> bool:
        return True

    async def init(self, **kwargs) -> bool:
        if not self.is_installed():
            return False
        if self._sr is None:
            try:
                import speech_recognition as sr
                self._sr = sr
            except Exception:
                return False
        self._is_initialized = True
        return True

    async def transcribe(self, audio_data: np.ndarray, sample_rate: int) -> Optional[str]:
        if not self._is_initialized or self._sr is None:
            return None

        recognizer = self._sr.Recognizer()
        audio_data_int16 = (audio_data * 32767).astype(np.int16)

        audio = self._sr.AudioData(
            audio_data_int16.tobytes(),
            sample_rate=sample_rate,
            sample_width=2
        )

        try:
            return recognizer.recognize_google(audio, language="ru-RU")
        except self._sr.UnknownValueError:
            return None
        except Exception as e:
            self.logger.error(f"Ошибка при распознавании Google: {e}")
            return None

    def _check_microphone_permissions(self, microphone_index):
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            try:
                device_info = pa.get_device_info_by_index(microphone_index)
                if device_info["maxInputChannels"] == 0:
                    return False, "Выбранное устройство не поддерживает аудио ввод"

                try:
                    test_stream = pa.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=int(device_info["defaultSampleRate"]),
                        input=True,
                        input_device_index=microphone_index,
                        frames_per_buffer=1024
                    )
                    test_stream.close()
                    return True, "OK"
                except Exception as stream_error:
                    error_msg = str(stream_error).lower()
                    if "invalid device" in error_msg:
                        return False, "Устройство недоступно или отключено"
                    if "unanticipated host error" in error_msg or "access denied" in error_msg:
                        return False, "Нет разрешения на доступ к микрофону"
                    return False, f"Ошибка доступа к микрофону: {stream_error}"
            finally:
                pa.terminate()
        except Exception as e:
            return False, f"Ошибка проверки микрофона: {e}"

    async def live_recognition(self, microphone_index: int, handle_voice_callback,
                              vad_model, active_flag, **kwargs) -> None:
        if self._sr is None:
            self.logger.error("Модуль SpeechRecognition не инициализирован")
            return

        try:
            mic_list = self._sr.Microphone.list_microphone_names()
            if microphone_index >= len(mic_list):
                self.logger.error(f"Индекс микрофона {microphone_index} выходит за пределы списка")
                return
        except Exception as e:
            self.logger.error(f"Не удалось получить список микрофонов: {e}")
            return

        ok, err = self._check_microphone_permissions(microphone_index)
        if not ok:
            self.logger.error(f"Проблема с доступом к микрофону: {err}")
            return

        recognizer = self._sr.Recognizer()
        recognizer.pause_threshold = 0.8
        recognizer.non_speaking_duration = 0.3
        recognizer.dynamic_energy_threshold = False

        chunk_size = kwargs.get("chunk_size", 1024)
        configs = [
            {"sample_rate": 44100, "chunk_size": chunk_size},
            {"sample_rate": 22050, "chunk_size": chunk_size},
            {"sample_rate": 16000, "chunk_size": chunk_size},
        ]

        chosen_cfg = None
        for cfg in configs:
            try:
                with self._sr.Microphone(
                    device_index=microphone_index,
                    sample_rate=cfg["sample_rate"],
                    chunk_size=cfg["chunk_size"]
                ) as test_source:
                    try:
                        recognizer.adjust_for_ambient_noise(test_source, duration=0.5)
                    except Exception:
                        pass
                chosen_cfg = cfg
                self.logger.info(
                    f"Микрофон подключён: {mic_list[microphone_index]} "
                    f"(sr={cfg['sample_rate']}, chunk={cfg['chunk_size']})"
                )
                break
            except Exception as e:
                self.logger.debug(f"Конфигурация {cfg} не подошла: {e}")

        if chosen_cfg is None:
            self.logger.error("Не удалось подключиться к микрофону ни по одной конфигурации")
            return

        source = self._sr.Microphone(
            device_index=microphone_index,
            sample_rate=chosen_cfg["sample_rate"],
            chunk_size=chosen_cfg["chunk_size"],
        )
        try:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
        except Exception:
            pass

        loop = asyncio.get_running_loop()

        def _bg_callback(rec, audio):
            try:
                text = rec.recognize_google(audio, language="ru-RU")
                if text and text.strip():
                    self.logger.info(f"Распознано (google): {text}")
                    loop.call_soon_threadsafe(lambda t=text: asyncio.create_task(handle_voice_callback(t)))
            except self._sr.UnknownValueError:
                pass
            except self._sr.RequestError as e:
                self.logger.warning(f"Google API error (bg-thread): {e}")
            except TimeoutError as e:
                self.logger.warning(f"Google API timeout (bg-thread): {e}")
            except Exception as e:
                self.logger.exception(f"Ошибка в bg-callback: {e}")

        stop_listening = recognizer.listen_in_background(
            source,
            _bg_callback,
            phrase_time_limit=10,
        )

        self.logger.success("Микрофон готов к распознаванию (listen_in_background запущен).")

        try:
            while active_flag():
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            self.logger.info("live_recognition отменена пользователем.")
        finally:
            try:
                stop_listening(wait_for_stop=False)
            except Exception as e:
                self.logger.warning(f"Ошибка при stop_listening: {e}")

            self.logger.info("Микрофон (Google) корректно закрыт.")

    def cleanup(self) -> None:
        self._sr = None
        self._is_initialized = False