import time
import asyncio
import json
import sys
import os
import wave
from collections import deque
from threading import Lock
from io import BytesIO

# Используем стандартный логгер
from Logger import logger

#os.environ['TORCH_FORCE_WEIGHTS_ONLY_LOAD'] = '1'

class AudioState:
    """Простой класс для хранения состояния аудио, не требует внешних библиотек."""
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
                self.audio_buffer = self.audio_buffer[-self.max_buffer_size // 2:]
            self.audio_buffer.append(data.copy())

audio_state = AudioState()


class SpeechRecognition:
    # --- Настройки ---
    microphone_index = 0
    active = True
    _recognizer_type = "vosk"  # 'google', 'vosk' или 'gigaam'
    vosk_model = "vosk-model-small-ru-0.22"
    gigaam_model = "v2_rnnt"  # Модель для GigaAM

    # Настройки для VAD-методов (Vosk, GigaAM)
    VOSK_SAMPLE_RATE = 16000
    CHUNK_SIZE = 512
    VAD_THRESHOLD = 0.5
    VAD_SILENCE_TIMEOUT_SEC = 1.0
    VAD_POST_SPEECH_DELAY_SEC = 0.2
    VAD_PRE_BUFFER_DURATION_SEC = 0.3

    FAILED_AUDIO_DIR = "FailedAudios"

    # --- Внутреннее состояние и буферы ---
    _text_lock = Lock()
    _text_buffer = deque(maxlen=15)
    _current_text = ""
    _is_processing_audio = asyncio.Lock()
    _is_running = False
    _recognition_task = None # Для хранения ссылки на задачу распознавания

    # --- Переменные для ленивой загрузки библиотек и функций ---
    _torch = None
    _sd = None
    _np = None
    _sr = None
    _vosk_Model = None
    _vosk_KaldiRecognizer = None
    _vosk_SetLogLevel = None
    _silero_vad_loader = None
    _omegaconf = None
    _gigaam = None  # Для модуля gigaam

    # --- Переменные для хранения инициализированных объектов ---
    _vosk_model_instance = None
    _vosk_rec_instance = None
    _silero_vad_model = None
    _gigaam_model_instance = None  # Для модели gigaam

    @staticmethod
    def _init_dependencies():
        """Выполняет JIT-импорт всех необходимых библиотек."""
        if SpeechRecognition._recognizer_type == 'vosk':
            try:
                if SpeechRecognition._torch is None:
                    import torch
                    SpeechRecognition._torch = torch
                if SpeechRecognition._sd is None:
                    import sounddevice as sd
                    SpeechRecognition._sd = sd
                if SpeechRecognition._np is None:
                    import numpy as np
                    SpeechRecognition._np = np
                
                if SpeechRecognition._vosk_Model is None:
                    from vosk import Model, KaldiRecognizer, SetLogLevel
                    SpeechRecognition._vosk_Model = Model
                    SpeechRecognition._vosk_KaldiRecognizer = KaldiRecognizer
                    SpeechRecognition._vosk_SetLogLevel = SetLogLevel
                    SpeechRecognition._vosk_SetLogLevel(-1)
                
                if SpeechRecognition._silero_vad_loader is None:
                    from silero_vad import load_silero_vad
                    SpeechRecognition._silero_vad_loader = load_silero_vad
                return True
            except ImportError as e:
                logger.critical(f"Критическая ошибка: не удалось импортировать библиотеку: {e}. Установите 'torch', 'sounddevice', 'numpy', 'vosk' и 'silero-vad'.")
                return False

        elif SpeechRecognition._recognizer_type == 'gigaam':
            try:
                # Общие зависимости для VAD
                if SpeechRecognition._torch is None:
                    import torch
                    import omegaconf
                    import typing
                    import collections
                    torch.serialization.add_safe_globals([omegaconf.dictconfig.DictConfig])
                    torch.serialization.add_safe_globals([omegaconf.base.ContainerMetadata])
                    torch.serialization.add_safe_globals([typing.Any])
                    torch.serialization.add_safe_globals([dict])
                    torch.serialization.add_safe_globals([collections.defaultdict])
                    torch.serialization.add_safe_globals([omegaconf.nodes.AnyNode])
                    torch.serialization.add_safe_globals([omegaconf.nodes.Metadata])
                    torch.serialization.add_safe_globals([omegaconf.listconfig.ListConfig])
                    torch.serialization.add_safe_globals([list])
                    torch.serialization.add_safe_globals([int])
                    # torch.serialization.safe_globals([omegaconf.dictconfig.DictConfig])
                    # torch.serialization.safe_globals([omegaconf.base.ContainerMetadata])
                    # torch.serialization.safe_globals([[typing.Any]])
                    logger.warning("TORCH ADDED SAFE GLOBALS!")
                    SpeechRecognition._torch = torch
                if SpeechRecognition._sd is None:
                    import sounddevice as sd
                    SpeechRecognition._sd = sd
                if SpeechRecognition._np is None:
                    import numpy as np
                    SpeechRecognition._np = np
                if SpeechRecognition._silero_vad_loader is None:
                    from silero_vad import load_silero_vad
                    SpeechRecognition._silero_vad_loader = load_silero_vad
                
                # Зависимость GigaAM
                if SpeechRecognition._gigaam is None:
                    import gigaam
                    SpeechRecognition._gigaam = gigaam
                return True
            except ImportError as e:
                logger.critical(f"Критическая ошибка: не удалось импортировать библиотеку: {e}. Установите 'torch', 'sounddevice', 'numpy', 'silero-vad' и 'gigaam'.")
                return False

        elif SpeechRecognition._recognizer_type == 'google':
            try:
                if SpeechRecognition._sr is None:
                    import speech_recognition as sr
                    SpeechRecognition._sr = sr
                return True
            except ImportError as e:
                logger.critical(f"Критическая ошибка: не удалось импортировать 'speech_recognition': {e}.")
                return False
        return False

    @staticmethod
    def set_recognizer_type(recognizer_type: str = None):
        if recognizer_type in ["google", "vosk", "gigaam"]:
            SpeechRecognition._recognizer_type = recognizer_type
            logger.info(f"Тип распознавателя установлен на: {recognizer_type}")
        else:
            logger.warning(f"Неизвестный тип распознавателя: {recognizer_type}. Используется 'google'.")

    @staticmethod
    def receive_text() -> str:
        with SpeechRecognition._text_lock:
            result = " ".join(SpeechRecognition._text_buffer).strip()
            SpeechRecognition._text_buffer.clear()
            SpeechRecognition._current_text = ""
            return result

    @staticmethod
    def list_microphones():
        if SpeechRecognition._sd is None:
            try:
                import sounddevice as sd
                SpeechRecognition._sd = sd
            except ImportError:
                logger.error("Библиотека 'sounddevice' не найдена для вывода списка микрофонов.")
                return ["Ошибка: библиотека sounddevice не установлена"]
        
        try:
            devices = SpeechRecognition._sd.query_devices()
            input_devices = [dev['name'] for dev in devices if dev['max_input_channels'] > 0]
            return input_devices if input_devices else ["Микрофоны не найдены"]
        except Exception as e:
            logger.error(f"Не удалось получить список микрофонов: {e}")
            return [f"Ошибка: {e}"]

    @staticmethod
    async def handle_voice_message(recognized_text: str) -> None:
        text_clean = recognized_text.strip()
        if text_clean:
            with SpeechRecognition._text_lock:
                SpeechRecognition._text_buffer.append(text_clean)
                SpeechRecognition._current_text += f"{text_clean}. "

    @staticmethod
    def _init_vosk_recognizer():
        if SpeechRecognition._vosk_model_instance is None:
            model_path = f"SpeechRecognitionModels/Vosk/{SpeechRecognition.vosk_model}"
            try:
                SpeechRecognition._vosk_model_instance = SpeechRecognition._vosk_Model(model_path)
                logger.info(f"Модель Vosk загружена из: {model_path}")
            except Exception as e:
                logger.error(f"Ошибка загрузки модели Vosk из {model_path}: {e}")
                return False
        if SpeechRecognition._vosk_rec_instance is None:
            SpeechRecognition._vosk_rec_instance = SpeechRecognition._vosk_KaldiRecognizer(
                SpeechRecognition._vosk_model_instance, SpeechRecognition.VOSK_SAMPLE_RATE
            )
            logger.info(f"Распознаватель Vosk инициализирован с sample_rate={SpeechRecognition.VOSK_SAMPLE_RATE}.")
        return True

    @staticmethod
    def _init_gigaam_recognizer():
        if SpeechRecognition._gigaam_model_instance is None:
            if SpeechRecognition._gigaam is None:
                logger.error("Модуль GigaAM не был импортирован.")
                return False
            try:
                logger.info(f"Загрузка модели GigaAM: {SpeechRecognition.gigaam_model}...")
                model = SpeechRecognition._gigaam.load_model(SpeechRecognition.gigaam_model)
                SpeechRecognition._gigaam_model_instance = model
                logger.info(f"Модель GigaAM '{SpeechRecognition.gigaam_model}' успешно загружена.")
            except Exception as e:
                logger.error(f"Ошибка загрузки модели GigaAM '{SpeechRecognition.gigaam_model}': {e}")
                return False
        return True

    @staticmethod
    def _init_silero_vad():
        if SpeechRecognition._silero_vad_model is None:
            if SpeechRecognition._silero_vad_loader is None:
                logger.error("Функция загрузки Silero VAD не была импортирована.")
                return False
            try:
                model = SpeechRecognition._silero_vad_loader()
                SpeechRecognition._silero_vad_model = model
                logger.info("Модель Silero VAD успешно загружена через pip-пакет.")
            except Exception as e:
                logger.error(f"Не удалось загрузить модель Silero VAD. Ошибка: {e}")
                return False
        return True

    @staticmethod
    async def _recognize_vosk_from_buffer(audio_data: "np.ndarray") -> None:
        np = SpeechRecognition._np
        rec = SpeechRecognition._vosk_rec_instance
        if rec is None or np is None:
            logger.error("Распознаватель Vosk или Numpy не инициализирован.")
            return

        audio_data_int16 = (audio_data * 32767).astype(np.int16)
        
        rec.AcceptWaveform(audio_data_int16.tobytes())
        result_json = json.loads(rec.FinalResult())
        rec.Reset()

        if 'text' in result_json and result_json['text']:
            recognized_text = result_json['text']
            logger.info(f"Vosk распознал: {recognized_text}")
            await SpeechRecognition.handle_voice_message(recognized_text)
        else:
            logger.info("Vosk не распознал текст. Сохранение аудиофрагмента...")
            try:
                os.makedirs(SpeechRecognition.FAILED_AUDIO_DIR, exist_ok=True)
                timestamp = int(time.time())
                filename = os.path.join(SpeechRecognition.FAILED_AUDIO_DIR, f"failed_{timestamp}.wav")
                with wave.open(filename, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(SpeechRecognition.VOSK_SAMPLE_RATE)
                    wf.writeframes(audio_data_int16.tobytes())
                logger.info(f"Фрагмент сохранен в: {filename}")
            except Exception as e:
                logger.error(f"Не удалось сохранить аудиофрагмент: {e}")

    @staticmethod
    async def _recognize_gigaam_from_buffer(audio_data: "np.ndarray") -> None:
        model = SpeechRecognition._gigaam_model_instance
        if model is None:
            logger.error("Распознаватель GigaAM не инициализирован.")
            return

        np = SpeechRecognition._np
        TEMP_AUDIO_DIR = "TempAudios"
        os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)
        temp_filepath = os.path.join(TEMP_AUDIO_DIR, f"temp_gigaam_{time.time_ns()}.wav")
        
        recognized_successfully = False
        try:
            audio_data_int16 = (audio_data * 32767).astype(np.int16)
            with wave.open(temp_filepath, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SpeechRecognition.VOSK_SAMPLE_RATE)
                wf.writeframes(audio_data_int16.tobytes())

            transcription = model.transcribe(temp_filepath)
            if transcription and transcription.strip() != '':
                recognized_text = transcription  
                logger.info(f"GigaAM распознал: {recognized_text}")
                await SpeechRecognition.handle_voice_message(recognized_text)
                recognized_successfully = True
            else:
                logger.info("GigaAM не распознал текст.")

        except Exception as e:
            logger.error(f"Ошибка во время распознавания GigaAM: {e}")

        finally:
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except OSError as e:
                    logger.error(f"Не удалось удалить временный файл {temp_filepath}: {e}")

        if not recognized_successfully:
            logger.info("Сохранение аудиофрагмента в папку Failed...")
            try:
                os.makedirs(SpeechRecognition.FAILED_AUDIO_DIR, exist_ok=True)
                timestamp = int(time.time())
                filename = os.path.join(SpeechRecognition.FAILED_AUDIO_DIR, f"failed_{timestamp}.wav")
                
                # Используем уже сконвертированные данные, если они есть, или конвертируем заново
                if 'audio_data_int16' not in locals():
                    audio_data_int16 = (audio_data * 32767).astype(np.int16)

                with wave.open(filename, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(SpeechRecognition.VOSK_SAMPLE_RATE)
                    wf.writeframes(audio_data_int16.tobytes())
                logger.info(f"Фрагмент сохранен в: {filename}")
            except Exception as e:
                logger.error(f"Не удалось сохранить аудиофрагмент: {e}")

    @staticmethod
    async def _process_audio_task(audio_data: "np.ndarray"):
        async with SpeechRecognition._is_processing_audio:
            if SpeechRecognition._recognizer_type == "vosk":
                await SpeechRecognition._recognize_vosk_from_buffer(audio_data)
            elif SpeechRecognition._recognizer_type == "gigaam":
                await SpeechRecognition._recognize_gigaam_from_buffer(audio_data)

    @staticmethod
    async def live_recognition() -> None:
        """Основной метод, запускающий процесс распознавания с пред-буферизацией."""
        try:
            if not SpeechRecognition._init_dependencies():
                return

            if SpeechRecognition._recognizer_type == "vosk":
                if not SpeechRecognition._init_silero_vad() or not SpeechRecognition._init_vosk_recognizer():
                    logger.error("Не удалось инициализировать Vosk или Silero VAD. Распознавание остановлено.")
                    return

                sd = SpeechRecognition._sd
                np = SpeechRecognition._np
                torch = SpeechRecognition._torch
                vad_model = SpeechRecognition._silero_vad_model
                
                silence_chunks_needed = int(SpeechRecognition.VAD_SILENCE_TIMEOUT_SEC * SpeechRecognition.VOSK_SAMPLE_RATE / SpeechRecognition.CHUNK_SIZE)
                pre_buffer_size = int(SpeechRecognition.VAD_PRE_BUFFER_DURATION_SEC * SpeechRecognition.VOSK_SAMPLE_RATE / SpeechRecognition.CHUNK_SIZE)
                
                try:
                    mic_name = SpeechRecognition.list_microphones()[SpeechRecognition.microphone_index]
                    logger.info(f"Используется микрофон: {mic_name}")
                except IndexError:
                    logger.error(f"Ошибка: микрофон с индексом {SpeechRecognition.microphone_index} не найден.")
                    return

                logger.info("Ожидание речи (Vosk + Silero VAD с пред-буферизацией)...")

                pre_speech_buffer = deque(maxlen=pre_buffer_size)
                speech_buffer = []
                is_speaking = False
                silence_counter = 0

                with sd.InputStream(
                    samplerate=SpeechRecognition.VOSK_SAMPLE_RATE,
                    channels=1,
                    dtype='float32',
                    blocksize=SpeechRecognition.CHUNK_SIZE,
                    device=SpeechRecognition.microphone_index
                ) as stream:
                    while SpeechRecognition.active:
                        audio_chunk, overflowed = stream.read(SpeechRecognition.CHUNK_SIZE)
                        if overflowed:
                            logger.warning("Переполнение буфера аудиопотока!")

                        if not is_speaking:
                            pre_speech_buffer.append(audio_chunk)

                        audio_tensor = torch.from_numpy(audio_chunk.flatten())
                        speech_prob = vad_model(audio_tensor, SpeechRecognition.VOSK_SAMPLE_RATE).item()

                        if speech_prob > SpeechRecognition.VAD_THRESHOLD:
                            if not is_speaking:
                                logger.debug("🟢 Начало речи. Захват из пред-буфера.")
                                is_speaking = True
                                speech_buffer.clear()
                                speech_buffer.extend(list(pre_speech_buffer))
                            
                            speech_buffer.append(audio_chunk)
                            silence_counter = 0
                        
                        elif is_speaking:
                            speech_buffer.append(audio_chunk)
                            silence_counter += 1
                            if silence_counter > silence_chunks_needed:
                                logger.debug("🔴 Конец речи. Отправка на распознавание.")
                                audio_to_process = np.concatenate(speech_buffer)
                                
                                is_speaking = False
                                speech_buffer.clear()
                                silence_counter = 0
                                
                                asyncio.create_task(SpeechRecognition._process_audio_task(audio_to_process))
                        
                        await asyncio.sleep(0.01)
            
            elif SpeechRecognition._recognizer_type == "gigaam":
                if not SpeechRecognition._init_silero_vad() or not SpeechRecognition._init_gigaam_recognizer():
                    logger.error("Не удалось инициализировать GigaAM или Silero VAD. Распознавание остановлено.")
                    return

                sd = SpeechRecognition._sd
                np = SpeechRecognition._np
                torch = SpeechRecognition._torch
                vad_model = SpeechRecognition._silero_vad_model
                
                silence_chunks_needed = int(SpeechRecognition.VAD_SILENCE_TIMEOUT_SEC * SpeechRecognition.VOSK_SAMPLE_RATE / SpeechRecognition.CHUNK_SIZE)
                pre_buffer_size = int(SpeechRecognition.VAD_PRE_BUFFER_DURATION_SEC * SpeechRecognition.VOSK_SAMPLE_RATE / SpeechRecognition.CHUNK_SIZE)
                
                try:
                    mic_name = SpeechRecognition.list_microphones()[SpeechRecognition.microphone_index]
                    logger.info(f"Используется микрофон: {mic_name}")
                except IndexError:
                    logger.error(f"Ошибка: микрофон с индексом {SpeechRecognition.microphone_index} не найден.")
                    return

                logger.info("Ожидание речи (GigaAM + Silero VAD с пред-буферизацией)...")

                pre_speech_buffer = deque(maxlen=pre_buffer_size)
                speech_buffer = []
                is_speaking = False
                silence_counter = 0

                with sd.InputStream(
                    samplerate=SpeechRecognition.VOSK_SAMPLE_RATE,
                    channels=1,
                    dtype='float32',
                    blocksize=SpeechRecognition.CHUNK_SIZE,
                    device=SpeechRecognition.microphone_index
                ) as stream:
                    while SpeechRecognition.active:
                        audio_chunk, overflowed = stream.read(SpeechRecognition.CHUNK_SIZE)
                        if overflowed:
                            logger.warning("Переполнение буфера аудиопотока!")

                        if not is_speaking:
                            pre_speech_buffer.append(audio_chunk)

                        audio_tensor = torch.from_numpy(audio_chunk.flatten())
                        speech_prob = vad_model(audio_tensor, SpeechRecognition.VOSK_SAMPLE_RATE).item()

                        if speech_prob > SpeechRecognition.VAD_THRESHOLD:
                            if not is_speaking:
                                logger.debug("🟢 Начало речи. Захват из пред-буфера.")
                                is_speaking = True
                                speech_buffer.clear()
                                speech_buffer.extend(list(pre_speech_buffer))
                            
                            speech_buffer.append(audio_chunk)
                            silence_counter = 0
                        
                        elif is_speaking:
                            speech_buffer.append(audio_chunk)
                            silence_counter += 1
                            if silence_counter > silence_chunks_needed:
                                logger.debug("🔴 Конец речи. Отправка на распознавание.")
                                audio_to_process = np.concatenate(speech_buffer)
                                
                                is_speaking = False
                                speech_buffer.clear()
                                silence_counter = 0
                                
                                asyncio.create_task(SpeechRecognition._process_audio_task(audio_to_process))
                        
                        await asyncio.sleep(0.01)

            elif SpeechRecognition._recognizer_type == "google":
                sr = SpeechRecognition._sr
                recognizer = sr.Recognizer()
                google_sample_rate = 44100
                with sr.Microphone(device_index=SpeechRecognition.microphone_index, sample_rate=google_sample_rate,
                                   chunk_size=SpeechRecognition.CHUNK_SIZE) as source:
                    logger.info(f"Используется микрофон: {sr.Microphone.list_microphone_names()[SpeechRecognition.microphone_index]}")
                    recognizer.adjust_for_ambient_noise(source)
                    logger.info("Скажите что-нибудь (Google)...")
                    while SpeechRecognition.active:
                        try:
                            audio = await asyncio.get_event_loop().run_in_executor(None, lambda: recognizer.listen(source, timeout=5))
                            text = await asyncio.get_event_loop().run_in_executor(None, lambda: recognizer.recognize_google(audio, language="ru-RU"))
                            if text: await SpeechRecognition.handle_voice_message(text)
                        except sr.WaitTimeoutError: pass
                        except sr.UnknownValueError: pass
                        except Exception as e:
                            logger.error(f"Ошибка при распознавании Google: {e}")
                            break
        except Exception as e:
            logger.error(f"Критическая ошибка в цикле распознавания: {e}", exc_info=True)
        finally:
            SpeechRecognition._is_running = False
            logger.info("Цикл распознавания речи остановлен.")


    @staticmethod
    async def speach_recognition_start_async():
        await SpeechRecognition.live_recognition()

    @staticmethod
    def speach_recognition_start(device_id: int, loop):
        if SpeechRecognition._is_running:
            logger.warning("Попытка запустить распознавание, когда оно уже запущено. Игнорируется.")
            return

        SpeechRecognition._is_running = True
        SpeechRecognition.active = True
        SpeechRecognition.microphone_index = device_id
        SpeechRecognition._recognition_task = asyncio.run_coroutine_threadsafe(SpeechRecognition.speach_recognition_start_async(), loop)

    @staticmethod
    def speach_recognition_stop():
        if not SpeechRecognition._is_running:
            logger.warning("Попытка остановить распознавание, когда оно не запущено. Игнорируется.")
            return

        SpeechRecognition.active = False
        SpeechRecognition._is_running = False
        logger.info("Запрос на остановку распознавания речи...")

        if SpeechRecognition._recognition_task and not SpeechRecognition._recognition_task.done():
            try:
                # Ждем завершения задачи, чтобы убедиться, что цикл live_recognition завершился
                # Используем небольшой таймаут, чтобы не блокировать основной поток GUI надолго
                # В реальном приложении, возможно, лучше использовать asyncio.wait_for в отдельном потоке
                # или более сложную логику для неблокирующего ожидания.
                # Для простоты, здесь мы просто ждем.
                SpeechRecognition._recognition_task.result(timeout=1.0) # Ждем до 1 секунды
                logger.info("Задача распознавания речи успешно завершена.")
            except asyncio.TimeoutError:
                logger.warning("Таймаут при ожидании завершения задачи распознавания речи.")
            except Exception as e:
                logger.error(f"Ошибка при ожидании завершения задачи распознавания речи: {e}")
        else:
            logger.info("Задача распознавания речи уже завершена или не была запущена.")

        SpeechRecognition._recognition_task = None # Очищаем ссылку

    @staticmethod
    async def get_current_text() -> str:
        with SpeechRecognition._text_lock:
            return SpeechRecognition._current_text.strip()
