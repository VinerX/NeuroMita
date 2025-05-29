import time
from io import BytesIO
import asyncio
import logging
import soundfile as sf
import numpy as np
import speech_recognition as sr
import sounddevice as sd
from collections import deque
from threading import Lock
from Logger import logger
import httpx
import json
class AudioState:
    def __init__(self):
        self.is_recording = False
        self.audio_buffer = []
        self.last_sound_time = time.time()
        self.is_playing = False
        self.lock = asyncio.Lock()
        self.vc = None
        self.max_buffer_size = 9999999

    async def add_to_buffer(self, data):
        async with self.lock:
            if len(self.audio_buffer) >= self.max_buffer_size:
                self.audio_buffer = self.audio_buffer[-self.max_buffer_size // 2:]  # Сохраняем последние 50%
            self.audio_buffer.append(data.copy())


audio_state = AudioState()


class SpeechRecognition:
    user_input = ""
    microphone_index = 0
    active = True
    _recognizer_type = "google"  # 'google', 'vosk' или 'whisper'
    vosk_model = "vosk-model-ru-0.10" #vosk-model-small-ru
    whisper_api_url = "http://127.0.0.1:5100/api/speech-recognition/whisper/process-audio"

    SAMPLE_RATE = 44000
    CHUNK_SIZE = 512
    TIMEOUT_MESSAGE = True
    SILENCE_THRESHOLD = 0.02  # Порог тишины
    SILENCE_DURATION = 4  # Длительность тишины для завершения записи
    SILENCE_TIMEOUT = 2.0
    MIN_RECORDING = 1.0
    MIN_RECORDING_DURATION = 1  # Минимальная длительность записи
    BUFFER_TIMEOUT = 0.05
    VOSK_PROCESS_INTERVAL = 0.1 # Интервал обработки Vosk (сек)
    _text_lock = Lock()
    _text_buffer = deque(maxlen=10)  # Храним последние 10 фраз
    _current_text = ""
    _last_delimiter = ". "

    @staticmethod
    def set_recognizer_type(recognizer_type: str):
        if recognizer_type in ["google", "vosk", "whisper"]:
            SpeechRecognition._recognizer_type = recognizer_type
            logger.info(f"Тип распознавателя установлен на: {recognizer_type}")
        else:
            logger.warning(f"Неизвестный тип распознавателя: {recognizer_type}. Используется 'google'.")


    @staticmethod
    def receive_text() -> str:
        """Получение и сброс текста (синхронный метод)"""
        with SpeechRecognition._text_lock:
            result = " ".join(SpeechRecognition._text_buffer).strip()
            SpeechRecognition._text_buffer.clear()
            SpeechRecognition._current_text = ""
            #logger.debug(f"Returned text: {result}")
            return result

    @staticmethod
    def list_microphones():
        return sr.Microphone.list_microphone_names()

    @staticmethod
    async def handle_voice_message(recognized_text: str) -> None:
        """Асинхронная обработка текста"""
        text_clean = recognized_text.strip()
        if text_clean:
            with SpeechRecognition._text_lock:
                # Определение разделителя
                last_char = SpeechRecognition._current_text[-1] if SpeechRecognition._current_text else ""
                delimiter = "" if last_char in {'.', '!', '?', ','} else " "

                SpeechRecognition._text_buffer.append(text_clean)
                SpeechRecognition._current_text += f"{delimiter}{text_clean}"

    @staticmethod
    async def recognize_vosk(audio_data: np.ndarray) -> str | None:
        """Распознавание речи с помощью Vosk API."""
        try:
            # Преобразование numpy array в BytesIO объект в формате WAV
            with BytesIO() as buffer:
                sf.write(buffer, audio_data, SpeechRecognition.SAMPLE_RATE, format='WAV')
                buffer.seek(0)
                audio_bytes = buffer.read()

            async with httpx.AsyncClient() as client:
                # Отправка аудио на Vosk API
                response = await client.post(
                    "http://127.0.0.1:8000/vtt/transcribe",  # Предполагаем, что сервер Vosk запущен локально
                    files={"audio_file": ("audio.wav", audio_bytes, "audio/wav")}
                )
                response.raise_for_status()  # Вызовет исключение для статусов 4xx/5xx
                result = response.json()
                text = result.get("text")
                if text:
                    logger.info(f"Vosk распознал: {text}")
                    return text
                else:
                    logger.warning("Vosk не распознал текст.")
                    return None
        except httpx.RequestError as e:
            logger.error(f"Ошибка запроса к Vosk API: {e}")
            return None
        except json.JSONDecodeError:
            logger.error("Ошибка декодирования JSON ответа от Vosk API.")
            return None
        except Exception as e:
            logger.error(f"Неизвестная ошибка при распознавании Vosk: {e}")
            return None

    @staticmethod
    async def recognize_whisper(audio_data: np.ndarray) -> str | None:
        """Распознавание речи с помощью Whisper API."""
        try:
            # Преобразование numpy array в BytesIO объект в формате WAV
            with BytesIO() as buffer:
                sf.write(buffer, audio_data, SpeechRecognition.SAMPLE_RATE, format='WAV')
                buffer.seek(0)
                audio_bytes = buffer.read()

            async with httpx.AsyncClient() as client:
                # Отправка аудио на Whisper API
                response = await client.post(
                    SpeechRecognition.whisper_api_url,
                    files={"AudioFile": ("audio.wav", audio_bytes, "audio/wav")}
                )
                response.raise_for_status()  # Вызовет исключение для статусов 4xx/5xx
                result = response.json()
                text = result.get("transcript")
                if text:
                    logger.info(f"Whisper распознал: {text}")
                    return text
                else:
                    logger.warning("Whisper не распознал текст.")
                    return None
        except httpx.RequestError as e:
            logger.error(f"Ошибка запроса к Whisper API: {e}")
            return None
        except json.JSONDecodeError:
            logger.error("Ошибка декодирования JSON ответа от Whisper API.")
            return None
        except Exception as e:
            logger.error(f"Неизвестная ошибка при распознавании Whisper: {e}")
            return None

    @staticmethod
    async def live_recognition() -> None:
        # Этот метод будет работать по-разному в зависимости от выбранного распознавателя.
        # Для Google будет использоваться speech_recognition.Microphone.
        # Для Vosk/Whisper будет использоваться sounddevice для прямого захвата и отправки в API.

        if SpeechRecognition._recognizer_type == "google":
            recognizer = sr.Recognizer()
            with sr.Microphone(device_index=SpeechRecognition.microphone_index, sample_rate=SpeechRecognition.SAMPLE_RATE,
                               chunk_size=SpeechRecognition.CHUNK_SIZE) as source:
                logger.info(
                    f"Используется микрофон: {sr.Microphone.list_microphone_names()[SpeechRecognition.microphone_index]}")
                recognizer.adjust_for_ambient_noise(source)
                logger.info("Скажите что-нибудь (Google)...")

                while SpeechRecognition.active:
                    try:
                        audio = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: recognizer.listen(source, timeout=5)
                        )

                        text = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: recognizer.recognize_google(audio, language="ru-RU")
                        )
                        if not text:
                            text = await asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda: recognizer.recognize_google(audio, language="en-EN")
                            )

                        if text:
                            await SpeechRecognition.handle_voice_message(text)

                    except sr.WaitTimeoutError:
                        if SpeechRecognition.TIMEOUT_MESSAGE:
                            ...
                    except sr.UnknownValueError:
                        ...
                    except Exception as e:
                        logger.error(f"Ошибка при распознавании Google: {e}")
                        break
        elif SpeechRecognition._recognizer_type in ["vosk", "whisper"]:
            recognizer_name = "Vosk" if SpeechRecognition._recognizer_type == "vosk" else "Whisper"
            logger.info(f"Скажите что-нибудь ({recognizer_name})...")
            
            live_audio_buffer = []
            is_recording = False
            last_sound_time = time.time()

            async def live_callback(indata, frames, time_info, status):
                nonlocal is_recording, last_sound_time
                if status:
                    logger.warning(f"{recognizer_name} live callback status: {status}")

                rms = np.sqrt(np.mean(indata ** 2))
                current_time = time.time()

                if rms > SpeechRecognition.SILENCE_THRESHOLD:
                    last_sound_time = current_time
                    if not is_recording:
                        logger.debug(f"🟢 Начало записи ({recognizer_name} live)")
                        is_recording = True
                    live_audio_buffer.append(indata.copy())
                elif is_recording and (current_time - last_sound_time > SpeechRecognition.SILENCE_DURATION):
                    logger.debug(f"🔴 Обнаружена тишина, завершение записи ({recognizer_name} live)")
                    is_recording = False
                    if live_audio_buffer:
                        audio_data_to_process = np.concatenate(live_audio_buffer)
                        live_audio_buffer.clear()
                        if SpeechRecognition._recognizer_type == "vosk":
                            asyncio.create_task(SpeechRecognition.recognize_vosk(audio_data_to_process))
                        elif SpeechRecognition._recognizer_type == "whisper":
                            asyncio.create_task(SpeechRecognition.recognize_whisper(audio_data_to_process))
                        await asyncio.sleep(SpeechRecognition.VOSK_PROCESS_INTERVAL)  # Добавлена задержка
                elif is_recording: # Продолжаем запись, если звук ниже порога, но тишина еще не достигла SILENCE_DURATION
                    live_audio_buffer.append(indata.copy())
                    await asyncio.sleep(SpeechRecognition.VOSK_PROCESS_INTERVAL)  # Добавлена задержка
                else: # Если не записываем и нет звука, очищаем буфер, если там что-то есть
                    if live_audio_buffer:
                        logger.debug(f"❌ Слишком короткая запись или ложная активация, сброс ({recognizer_name} live)")
                        live_audio_buffer.clear()
                    await asyncio.sleep(SpeechRecognition.VOSK_PROCESS_INTERVAL)  # Добавлена задержка

            try:
                def start_stream():
                    with sd.RawInputStream(
                            callback=live_callback,
                            channels=1,
                            samplerate=SpeechRecognition.SAMPLE_RATE,
                            blocksize=SpeechRecognition.CHUNK_SIZE,
                            dtype='float32',
                            device=SpeechRecognition.microphone_index
                    ):
                        while SpeechRecognition.active:
                            time.sleep(0.001)

                import threading
                thread = threading.Thread(target=start_stream)
                thread.start()

                while SpeechRecognition.active:
                    await asyncio.sleep(0.1)  # Небольшая задержка для цикла
            except Exception as e:
                logger.critical(f"Критическая ошибка в live_recognition ({recognizer_name}): {str(e)}")

    @staticmethod
    async def async_audio_callback(indata):
        try:
            current_time = time.time()
            rms = np.sqrt(np.mean(indata ** 2))

            async with audio_state.lock:
                if rms > SpeechRecognition.SILENCE_THRESHOLD:
                    audio_state.last_sound_time = current_time
                    if not audio_state.is_recording:
                        logger.debug("🟢 Начало записи")
                        audio_state.is_recording = True
                    await audio_state.add_to_buffer(indata)

                elif audio_state.is_recording:
                    silence_duration = 4
                    audio_state.is_recording = False
                    await SpeechRecognition.process_audio()
                else:
                    logger.debug("❌ Слишком короткая запись, сброс")
                    audio_state.audio_buffer.clear()
                    audio_state.is_recording = False

        except Exception as e:
            logger.error(f"Ошибка в колбэке: {str(e)}")

    @staticmethod
    async def process_audio():
        try:
            async with audio_state.lock:
                if not audio_state.audio_buffer:
                    return

                audio_data = np.concatenate(audio_state.audio_buffer)
                audio_state.audio_buffer.clear()

                text = None
                if SpeechRecognition._recognizer_type == "google":
                    with BytesIO() as buffer:
                        sf.write(buffer, audio_data, SpeechRecognition.SAMPLE_RATE, format='WAV')
                        buffer.seek(0)

                        try:
                            recognizer = sr.Recognizer()
                            with sr.AudioFile(buffer) as source:
                                audio = recognizer.record(source)
                                text = recognizer.recognize_google(audio, language="ru-RU")
                                logger.info(f"Google распознал: {text}")
                        except sr.UnknownValueError:
                            logger.warning("Google не распознал речь.")
                        except Exception as e:
                            logger.error(f"Ошибка распознавания Google: {str(e)}")
                elif SpeechRecognition._recognizer_type == "vosk":
                    text = await SpeechRecognition.recognize_vosk(audio_data)
                elif SpeechRecognition._recognizer_type == "whisper":
                    text = await SpeechRecognition.recognize_whisper(audio_data)

                if text:
                    await SpeechRecognition.handle_voice_message(text)
        except Exception as e:
            logger.error(f"Ошибка обработки: {str(e)}")

    @staticmethod
    async def recognize_speech(audio_buffer):
        # Этот метод используется для распознавания из буфера,
        # который уже является AudioFile-подобным объектом.
        # Для Vosk API нам нужен numpy array.
        # Поэтому, если выбран Vosk, нужно будет преобразовать audio_buffer в numpy array.
        # Или же этот метод будет использоваться только для Google.
        # Пока оставим его для Google, так как он принимает AudioFile.
        # Если потребуется Vosk здесь, нужно будет пересмотреть.
        recognizer = sr.Recognizer()
        text = None

        if SpeechRecognition._recognizer_type == "google":
            try:
                with sr.AudioFile(audio_buffer) as source:
                    audio = recognizer.record(source)

                text = recognizer.recognize_google(audio, language="ru-RU")
                if not text:
                    text = recognizer.recognize_google(audio, language="en-EN")
                return text
            except sr.UnknownValueError:
                logger.error("Google: Не удалось распознать речь")
                return None
            except sr.RequestError as e:
                logger.error(f"Google: Ошибка API: {e}")
                return None
        elif SpeechRecognition._recognizer_type in ["vosk", "whisper"]:
            # Здесь нужно будет преобразовать audio_buffer в numpy array
            # Это сложнее, так как audio_buffer может быть BytesIO или другим объектом
            # Для простоты, пока этот метод будет работать только с Google
            logger.warning(f"recognize_speech не поддерживает {SpeechRecognition._recognizer_type} напрямую с текущим типом audio_buffer.")
            return None

    @staticmethod
    async def speach_recognition_start_async_other_system():
        while SpeechRecognition.active:
            try:
                await SpeechRecognition.async_audio_callback(0)
                await asyncio.sleep(0.1)  # Уменьшим интервал
            except Exception as e:
                logger.error(f"Ошибка в speach_recognition_start_async_other_system: {e}")

    @staticmethod
    async def speach_recognition_start_async():
        await SpeechRecognition.live_recognition()

    @staticmethod
    def speach_recognition_start(device_id: int, loop):
        SpeechRecognition.microphone_index = device_id
        asyncio.run_coroutine_threadsafe(SpeechRecognition.speach_recognition_start_async(), loop)


    @staticmethod
    async def audio_monitoring():
        try:
            logger.info("🚀 Запуск аудиомониторинга")
            with sd.InputStream(
                    callback=lambda indata, *_: asyncio.create_task(SpeechRecognition.async_audio_callback(indata)),
                    channels=1,
                    samplerate=SpeechRecognition.SAMPLE_RATE,
                    blocksize=SpeechRecognition.CHUNK_SIZE,
                    device=SpeechRecognition.microphone_index
            ):
                while SpeechRecognition.active:
                    await asyncio.sleep(0.1)
        except Exception as e:
            logger.critical(f"Критическая ошибка: {str(e)}")

    @staticmethod
    async def get_current_text() -> str:
        async with SpeechRecognition._text_lock:
            return SpeechRecognition._current_text.strip()
