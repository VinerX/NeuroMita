# src/handlers/asr_models/whisper_onnx_process.py
import os
import asyncio
import traceback
from multiprocessing import Queue
from typing import Optional, Dict, Any, List

import numpy as np

class WhisperOnnxProcessWorker:
    """
    Whisper large-v3-turbo ONNX через transformers+optimum (accelerator=ort).
    """

    def __init__(self, command_queue: Queue, result_queue: Queue, log_queue: Queue):
        self.command_queue = command_queue
        self.result_queue = result_queue
        self.log_queue = log_queue

        self.device = "auto"
        self.language = "ru"
        self.max_tokens = 192

        self.model_dir = "SpeechRecognitionModels/WhisperONNX/large-v3-turbo"
        self.onnx_subfolder = "onnx"
        self.encoder_file_name = "encoder_model.onnx"
        self.decoder_file_name = "decoder_model_merged.onnx"

        self._torch = None
        self._torchaudio_F = None
        self._rt = None

        self._processor = None
        self._generation_config = None
        self._asr = None

    def info(self, msg: str):
        self.log_queue.put(("info", f"[WhisperONNX] {msg}"))

    def error(self, msg: str, exc_info: bool = False):
        if exc_info:
            msg += "\n" + traceback.format_exc()
        self.log_queue.put(("error", f"[WhisperONNX] {msg}"))

    def _select_provider(self) -> str:
        available: List[str] = []
        try:
            available = list(self._rt.get_available_providers())
        except Exception:
            available = []

        dev = (self.device or "auto").strip().lower()

        if dev == "cuda":
            return "CUDAExecutionProvider" if "CUDAExecutionProvider" in available else "CPUExecutionProvider"
        if dev == "dml":
            return "DmlExecutionProvider" if "DmlExecutionProvider" in available else "CPUExecutionProvider"
        if dev == "cpu":
            return "CPUExecutionProvider"

        if "CUDAExecutionProvider" in available:
            return "CUDAExecutionProvider"
        if "DmlExecutionProvider" in available:
            return "DmlExecutionProvider"
        return "CPUExecutionProvider"

    def _make_session_options(self, provider: str):
        so = self._rt.SessionOptions()
        if provider == "DmlExecutionProvider":
            # DML specific settings to avoid crashes
            so.graph_optimization_level = self._rt.GraphOptimizationLevel.ORT_DISABLE_ALL
            so.execution_mode = self._rt.ExecutionMode.ORT_SEQUENTIAL
            so.enable_mem_pattern = False
        else:
            so.graph_optimization_level = self._rt.GraphOptimizationLevel.ORT_ENABLE_ALL
        return so

    def _build_generation_config(self):
        from transformers import GenerationConfig

        gc = GenerationConfig.from_pretrained(self.model_dir, local_files_only=True)
        try:
            gc.max_new_tokens = int(self.max_tokens)
        except Exception:
            pass

        if (self.language or "").strip().lower() == "auto":
            gc.forced_decoder_ids = None
            return gc

        lang = (self.language or "ru").strip().lower()

        forced = None
        try:
            forced = self._processor.get_decoder_prompt_ids(language=lang, task="transcribe", no_timestamps=True)
        except TypeError:
            forced = self._processor.get_decoder_prompt_ids(language=lang, task="transcribe")
        except Exception:
            forced = None

        gc.forced_decoder_ids = forced
        return gc

    # ------------------ ИСПРАВЛЕННЫЙ МЕТОД ------------------
    def _build_pipeline(self):
        # Используем стандартный pipeline, но с явно загруженной ORT моделью
        from transformers import pipeline
        from optimum.onnxruntime import ORTModelForSpeechSeq2Seq

        provider = self._select_provider()
        so = self._make_session_options(provider)

        # Параметры, которые нужны для ЗАГРУЗКИ модели (они вызывали ошибку при генерации)
        base_load_kwargs = {
            "subfolder": self.onnx_subfolder,
            "encoder_file_name": self.encoder_file_name,
            "decoder_file_name": self.decoder_file_name,
            "local_files_only": True
        }

        # Варианты конфигурации для попытки загрузки (как в вашем коде)
        attempts = [
            dict(provider=provider, session_options=so),
            dict(provider=provider),
            dict(), # Fallback (CPU default)
        ]

        model = None
        last_err: Optional[Exception] = None

        # 1. Явно загружаем модель
        for extra in attempts:
            try:
                # Объединяем параметры
                load_kwargs = {**base_load_kwargs, **extra}
                
                model = ORTModelForSpeechSeq2Seq.from_pretrained(
                    self.model_dir,
                    **load_kwargs
                )
                break # Если загрузилась успешно, выходим из цикла
            except Exception as e:
                last_err = e

        if model is None:
            raise RuntimeError(f"Failed to load optimum ORTModel: {last_err}")

        # 2. Создаем pipeline, передавая уже ГОТОВЫЙ объект модели.
        # Теперь pipeline не знает про provider/subfolder и не передаст их в generate.
        return pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=self._processor.tokenizer,
            feature_extractor=self._processor.feature_extractor,
            device=-1 # Для ORT устройство управляется провайдером внутри модели, ставим CPU для pipeline
        )
    # --------------------------------------------------------

    async def init_recognizer(self, options: dict):
        try:
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

            self.model_dir = str(options.get("model_dir", self.model_dir))
            self.onnx_subfolder = str(options.get("onnx_subfolder", self.onnx_subfolder))

            self.device = str(options.get("device", self.device)).strip().lower()
            self.language = str(options.get("language", self.language)).strip().lower()

            mt = options.get("max_tokens", self.max_tokens)
            try:
                self.max_tokens = int(mt)
            except Exception:
                pass

            self.encoder_file_name = str(options.get("encoder_file_name", self.encoder_file_name))
            self.decoder_file_name = str(options.get("decoder_file_name", self.decoder_file_name))

            import torch
            import torchaudio
            import onnxruntime as rt
            from transformers import WhisperProcessor

            self._torch = torch
            self._torchaudio_F = torchaudio.functional
            self._rt = rt

            self._processor = WhisperProcessor.from_pretrained(self.model_dir, local_files_only=True)
            self._generation_config = self._build_generation_config()
            
            # Сборка пайплайна
            self._asr = self._build_pipeline()

            self.info(
                f"Init OK. provider={self._select_provider()} "
                f"lang={self.language} max_tokens={self.max_tokens} "
                f"onnx={self.onnx_subfolder}/{self.encoder_file_name},{self.decoder_file_name}"
            )
            self.result_queue.put(("init_success", True))

        except Exception as e:
            self.error(f"Init error: {e}", exc_info=True)
            self.result_queue.put(("init_error", str(e)))

    async def transcribe_audio(self, audio_data: np.ndarray, sample_rate: int):
        try:
            if not self._asr or not self._processor or not self._generation_config:
                raise RuntimeError("Recognizer not initialized")

            audio = np.asarray(audio_data, dtype=np.float32).reshape(-1)
            sr = int(sample_rate)

            if sr != 16000:
                t = self._torch.from_numpy(audio).float()
                t = self._torchaudio_F.resample(t, orig_freq=sr, new_freq=16000)
                audio_16k = t.cpu().numpy().astype(np.float32, copy=False)
            else:
                audio_16k = audio

            # Вызов пайплайна
            result = self._asr(
                audio_16k,
                return_timestamps=False,
                generate_kwargs={"generation_config": self._generation_config},
            )

            if isinstance(result, dict):
                text = result.get("text")
            else:
                text = str(result)

            self.result_queue.put(("transcription", (text or "").strip()))

        except Exception as e:
            self.error(f"Transcribe error: {e}", exc_info=True)
            self.result_queue.put(("transcription_error", str(e)))

    async def process_commands(self):
        import queue as py_queue

        while True:
            try:
                try:
                    cmd = self.command_queue.get(timeout=0.1)
                except py_queue.Empty:
                    await asyncio.sleep(0.01)
                    continue

                if cmd[0] == "init":
                    await self.init_recognizer(cmd[1])
                elif cmd[0] == "transcribe":
                    await self.transcribe_audio(cmd[1], cmd[2])
                elif cmd[0] == "shutdown":
                    break
            except Exception as e:
                self.error(f"Loop error: {e}", exc_info=True)

def run_whisper_onnx_process(command_queue: Queue, result_queue: Queue, log_queue: Queue):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        worker = WhisperOnnxProcessWorker(command_queue, result_queue, log_queue)
        loop.run_until_complete(worker.process_commands())
    except Exception as e:
        log_queue.put(("error", f"Critical error: {e}\n{traceback.format_exc()}"))