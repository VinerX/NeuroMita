import os
import asyncio
import multiprocessing as mp
from multiprocessing import Queue
import traceback
import time
import wave
from typing import Optional
import numpy as np


def run_gigaam_process(command_queue: Queue, result_queue: Queue, log_queue: Queue):
    """Точка входа для процесса"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        process = GigaAMProcessWorker(command_queue, result_queue, log_queue)
        loop.run_until_complete(process.process_commands())
        
    except Exception as e:
        log_queue.put(('error', f"Критическая ошибка в процессе GigaAM: {e}\n{traceback.format_exc()}"))
    finally:
        loop.close()


class GigaAMProcessWorker:
    """Рабочий класс для выполнения в отдельном процессе"""
    def __init__(self, command_queue: Queue, result_queue: Queue, log_queue: Queue):
        self.command_queue = command_queue
        self.result_queue = result_queue
        self.log_queue = log_queue
        
        self._gigaam_model_instance = None
        self._gigaam_onnx_sessions = None
        
        self.gigaam_model = "v2_rnnt"
        self.gigaam_device = "auto"
        self.gigaam_onnx_export_path = "SpeechRecognitionModels/GigaAM_ONNX"
        self.gigaam_model_path = "SpeechRecognitionModels/GigaAM"
        
    async def init_recognizer(self, options):
        """Инициализация распознавателя - только импорт и загрузка модели"""
        try:
            self.info("Инициализация GigaAM в отдельном процессе...")

            self.gigaam_device = options.get('device', 'auto')
            self.gigaam_model = options.get('model', 'v2_rnnt')
            self.gigaam_onnx_export_path = options.get('onnx_path', 'SpeechRecognitionModels/GigaAM_ONNX')
            self.gigaam_model_path = options.get('model_path', 'SpeechRecognitionModels/GigaAM')

            import torch
            import gigaam
            from utils.gpu_utils import check_gpu_provider
            from utils import getTranslationVariant as _

            import omegaconf, typing, collections
            torch.serialization.add_safe_globals([
                omegaconf.dictconfig.DictConfig,
                omegaconf.base.ContainerMetadata,
                typing.Any,
                dict,
                collections.defaultdict,
                omegaconf.nodes.AnyNode,
                omegaconf.nodes.Metadata,
                omegaconf.listconfig.ListConfig,
                list,
                int
            ])

            # ---- GPU detect: НИКОГДА не валим инициализацию из-за ошибок/None ----
            try:
                detected_gpu = check_gpu_provider()
            except Exception as e:
                self.warning(f"Не удалось определить GPU ({e}). Переходим на CPU.")
                detected_gpu = None

            current_gpu = detected_gpu or "CPU"
            device_choice = (self.gigaam_device or "auto").strip().lower()
            is_nvidia = (current_gpu == "NVIDIA")

            want_cuda = device_choice in ("cuda",)
            want_dml = device_choice in ("dml",)
            is_auto = device_choice in ("auto",)

            if want_cuda and (not is_nvidia or not torch.cuda.is_available()):
                self.warning("Запрошен CUDA, но NVIDIA/CUDA недоступны. Переходим на CPU.")
                device_choice = "cpu"
                want_cuda = False
                want_dml = False
                is_auto = False

            if is_nvidia and torch.cuda.is_available() and (device_choice in ("auto", "cuda")):
                device = "cuda"
                self.info(f"Загрузка PyTorch модели GigaAM на {device}...")

                model = gigaam.load_model(
                    self.gigaam_model,
                    device=device,
                    download_root=self.gigaam_model_path
                )
                self._gigaam_model_instance = model
                self._gigaam_onnx_sessions = None

                self.info(f"Модель GigaAM '{self.gigaam_model}' успешно загружена на {device}.")
                self.result_queue.put(('init_success', True))
                self.info("GigaAM успешно инициализирован в отдельном процессе")
                return

            import onnxruntime as rt

            providers = ["CPUExecutionProvider"]

            if want_dml:
                providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
            elif is_auto:
                if current_gpu not in ("CPU", "", None) and not is_nvidia:
                    providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                else:
                    providers = ["CPUExecutionProvider"]
            else:
                providers = ["CPUExecutionProvider"]

            try:
                available = set(rt.get_available_providers())
            except Exception:
                available = set()

            if "DmlExecutionProvider" in providers and "DmlExecutionProvider" not in available:
                self.warning(
                    f"DmlExecutionProvider недоступен (доступно: {sorted(available)}). "
                    f"Используем CPUExecutionProvider."
                )
                providers = ["CPUExecutionProvider"]

            self.info(f"Загрузка ONNX модели GigaAM с провайдерами: {providers}")

            onnx_dir = self.gigaam_onnx_export_path
            encoder_path = os.path.join(onnx_dir, f"{self.gigaam_model}_encoder.onnx")

            if not os.path.exists(encoder_path):
                self.warning("ONNX модель не найдена, выполняется экспорт...")
                os.makedirs(onnx_dir, exist_ok=True)

                temp_model = gigaam.load_model(
                    self.gigaam_model,
                    device="cpu",
                    fp16_encoder=False,
                    use_flash=False,
                    download_root=self.gigaam_model_path
                )
                temp_model.to_onnx(dir_path=onnx_dir)
                del temp_model
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                self.info("Модель GigaAM успешно экспортирована в ONNX")

            sessions = self._load_onnx_sessions(onnx_dir, self.gigaam_model, providers)
            self._gigaam_onnx_sessions = sessions
            self._gigaam_model_instance = None

            self.info(f"ONNX сессии для GigaAM успешно загружены с провайдерами {providers}.")

            self.result_queue.put(('init_success', True))
            self.info("GigaAM успешно инициализирован в отдельном процессе")

        except Exception as e:
            self.error(f"Ошибка инициализации GigaAM: {e}", exc_info=True)
            self.result_queue.put(('init_error', str(e)))

    def _load_onnx_sessions(self, onnx_dir: str, model_version: str, providers):
        """Загрузка ONNX сессий"""
        import onnxruntime as rt
        
        if isinstance(providers, str):
            providers = [providers]
        else:
            providers = list(providers)
        if "CPUExecutionProvider" not in providers:
            providers.append("CPUExecutionProvider")

        if "_" in model_version:
            version, model_type = model_version.split("_", 1)
        else:
            version, model_type = "v2", model_version

        opts = rt.SessionOptions()
        opts.intra_op_num_threads = 16
        opts.execution_mode = rt.ExecutionMode.ORT_SEQUENTIAL

        sessions = []

        if model_type == "ctc":
            model_path = os.path.join(onnx_dir, f"{version}_{model_type}.onnx")
            sessions.append(rt.InferenceSession(model_path,
                                                providers=providers,
                                                sess_options=opts))
        else:
            base = os.path.join(onnx_dir, f"{version}_{model_type}")
            for part in ("encoder", "decoder", "joint"):
                path = f"{base}_{part}.onnx"
                sessions.append(rt.InferenceSession(path,
                                                    providers=providers,
                                                    sess_options=opts))
        return sessions
    
    async def transcribe_audio(self, audio_data: np.ndarray, sample_rate: int):
        """Транскрибация аудио"""
        try:
            pytorch_model = self._gigaam_model_instance
            onnx_sessions = self._gigaam_onnx_sessions

            if pytorch_model is None and onnx_sessions is None:
                self.error("Распознаватель GigaAM не инициализирован")
                self.result_queue.put(('transcription', None))
                return
            
            TEMP_AUDIO_DIR = "TempAudios"
            os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)
            temp_filepath = os.path.join(TEMP_AUDIO_DIR, f"temp_gigaam_{time.time_ns()}.wav")
            
            try:
                audio_data_int16 = (audio_data * 32767).astype(np.int16)
                with wave.open(temp_filepath, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(audio_data_int16.tobytes())

                transcription = ""
                if pytorch_model:
                    transcription = pytorch_model.transcribe(temp_filepath)
                else:
                    from gigaam.onnx_utils import transcribe_sample
                    model_type = self.gigaam_model.split("_", 1)[-1]
                    transcription = transcribe_sample(
                            temp_filepath,
                            model_type,
                            onnx_sessions
                    )

                if transcription and transcription.strip() != '':
                    self.result_queue.put(('transcription', transcription))
                else:
                    self.info("GigaAM не распознал текст")
                    self.result_queue.put(('transcription', None))

            finally:
                if os.path.exists(temp_filepath):
                    try:
                        os.remove(temp_filepath)
                    except OSError as e:
                        self.error(f"Не удалось удалить временный файл {temp_filepath}: {e}")
                        
        except Exception as e:
            self.error(f"Ошибка транскрибации: {e}", exc_info=True)
            self.result_queue.put(('transcription_error', str(e)))

    async def process_commands(self):
        """Основной цикл обработки команд"""
        while True:
            try:
                if not self.command_queue.empty():
                    command = self.command_queue.get()
                    cmd_type = command[0]
                    
                    if cmd_type == 'init':
                        await self.init_recognizer(command[1])
                        
                    elif cmd_type == 'transcribe':
                        audio_data, sample_rate = command[1], command[2]
                        await self.transcribe_audio(audio_data, sample_rate)
                        
                    elif cmd_type == 'shutdown':
                        self.info("Получена команда завершения работы")
                        break
                        
                await asyncio.sleep(0.01)
                
            except Exception as e:
                self.error(f"Ошибка в цикле команд: {e}\n{traceback.format_exc()}")
                
        if hasattr(self, '_gigaam_model_instance') and self._gigaam_model_instance:
            del self._gigaam_model_instance
        if hasattr(self, '_gigaam_onnx_sessions') and self._gigaam_onnx_sessions:
            del self._gigaam_onnx_sessions
    
    def info(self, msg):
        self.log_queue.put(('info', msg))
    
    def warning(self, msg):
        self.log_queue.put(('warning', msg))
    
    def error(self, msg, exc_info=False):
        if exc_info:
            msg += f"\n{traceback.format_exc()}"
        self.log_queue.put(('error', msg))
    
    def debug(self, msg):
        self.log_queue.put(('debug', msg))
    
    def critical(self, msg):
        self.log_queue.put(('critical', msg))