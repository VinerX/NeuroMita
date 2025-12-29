import os
import asyncio
import traceback
import time
import wave
from multiprocessing import Queue
from typing import Optional, List, Any

import numpy as np


def run_gigaam_onnx_process(command_queue: Queue, result_queue: Queue, log_queue: Queue):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        worker = GigaAMOnnxProcessWorker(command_queue, result_queue, log_queue)
        loop.run_until_complete(worker.process_commands())
    except Exception as e:
        log_queue.put(("error", f"Критическая ошибка в процессе GigaAM ONNX: {e}\n{traceback.format_exc()}"))
    finally:
        try:
            loop.close()
        except Exception:
            pass


class GigaAMOnnxProcessWorker:
    """
    ONNX-only воркер:
    - грузит/экспортирует ONNX (если нет)
    - грузит onnxruntime sessions + yaml cfg
    - transcribe через gigaam.onnx_utils.transcribe_sample(...)
    """

    def __init__(self, command_queue: Queue, result_queue: Queue, log_queue: Queue):
        self.command_queue = command_queue
        self.result_queue = result_queue
        self.log_queue = log_queue

        self.gigaam_model = "v2_rnnt"
        self.gigaam_device = "auto"  # auto/cpu/dml
        self.gigaam_onnx_export_path = "SpeechRecognitionModels/GigaAM_ONNX"
        self.gigaam_model_path = "SpeechRecognitionModels/GigaAM"

        self._sessions = None
        self._model_cfg = None
        self._preprocessor = None
        self._tokenizer = None

    async def init_recognizer(self, options: dict):
        try:
            self.info("Инициализация GigaAM ONNX в отдельном процессе...")

            self.gigaam_device = (options.get("device", "auto") or "auto").strip().lower()
            self.gigaam_model = (options.get("model", "v2_rnnt") or "v2_rnnt").strip()
            self.gigaam_onnx_export_path = options.get("onnx_path", self.gigaam_onnx_export_path)
            self.gigaam_model_path = options.get("model_path", self.gigaam_model_path)

            # Важно для hydra instantiate внутри ckpt/yaml:
            import sys
            import torch
            import handlers.asr_models.gigaam as gigaam
            sys.modules["gigaam"] = gigaam

            # safe_globals для torch.load(ckpt) (экспорт в onnx может потребовать)
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
                int,
            ])

            # --- providers ---
            import onnxruntime as rt
            providers: List[str] = ["CPUExecutionProvider"]

            want_dml = self.gigaam_device == "dml"
            is_auto = self.gigaam_device == "auto"

            if want_dml or is_auto:
                available = set()
                try:
                    available = set(rt.get_available_providers())
                except Exception:
                    pass
                if "DmlExecutionProvider" in available:
                    providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                elif want_dml:
                    self.warning(f"DmlExecutionProvider недоступен (доступно: {sorted(available)}). Используем CPU.")

            self.info(f"ONNX providers: {providers}")

            # --- ensure ONNX exported ---
            onnx_dir = self.gigaam_onnx_export_path
            os.makedirs(onnx_dir, exist_ok=True)

            # Проверяем наличие артефактов (rnnt: 3 файла, ctc: 1 файл)
            if "ctc" in self.gigaam_model and "rnnt" not in self.gigaam_model:
                need_files = [os.path.join(onnx_dir, f"{self.gigaam_model}.onnx")]
            else:
                need_files = [
                    os.path.join(onnx_dir, f"{self.gigaam_model}_encoder.onnx"),
                    os.path.join(onnx_dir, f"{self.gigaam_model}_decoder.onnx"),
                    os.path.join(onnx_dir, f"{self.gigaam_model}_joint.onnx"),
                ]
            need_yaml = os.path.join(onnx_dir, f"{self.gigaam_model}.yaml")

            if (not all(os.path.exists(p) for p in need_files)) or (not os.path.exists(need_yaml)):
                self.warning("ONNX артефакты не найдены, выполняется экспорт из ckpt...")
                temp_model = gigaam.load_model(
                    self.gigaam_model,
                    device="cpu",
                    fp16_encoder=False,
                    use_flash=False,
                    download_root=self.gigaam_model_path,
                )
                temp_model.to_onnx(dir_path=onnx_dir)
                del temp_model
                try:
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
                self.info("Экспорт ONNX завершён.")

            # --- load sessions + cfg ---
            from gigaam.onnx_utils import load_onnx
            sessions, model_cfg = load_onnx(onnx_dir=onnx_dir, model_version=self.gigaam_model, providers=providers)
            self._sessions = sessions
            self._model_cfg = model_cfg

            # Предсоздаём preprocessor/tokenizer (чтобы не инстанцировать каждый раз)
            import hydra
            self._preprocessor = hydra.utils.instantiate(model_cfg.preprocessor)
            self._tokenizer = hydra.utils.instantiate(model_cfg.decoding).tokenizer

            self.result_queue.put(("init_success", True))
            self.info("GigaAM ONNX успешно инициализирован.")
        except Exception as e:
            self.error(f"Ошибка инициализации GigaAM ONNX: {e}", exc_info=True)
            self.result_queue.put(("init_error", str(e)))

    async def transcribe_audio(self, audio_data: np.ndarray, sample_rate: int):
        try:
            if self._sessions is None or self._model_cfg is None:
                self.error("GigaAM ONNX не инициализирован")
                self.result_queue.put(("transcription", None))
                return

            # текущий пайплайн у вас через временный wav (оставляем как есть)
            temp_dir = "TempAudios"
            os.makedirs(temp_dir, exist_ok=True)
            temp_filepath = os.path.join(temp_dir, f"temp_gigaam_onnx_{time.time_ns()}.wav")

            try:
                audio = np.asarray(audio_data, dtype=np.float32).reshape(-1)
                audio_i16 = np.clip(audio, -1.0, 1.0)
                audio_i16 = (audio_i16 * 32767.0).astype(np.int16)

                with wave.open(temp_filepath, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(int(sample_rate))
                    wf.writeframes(audio_i16.tobytes())

                from gigaam.onnx_utils import transcribe_sample
                text = transcribe_sample(
                    wav_file=temp_filepath,
                    model_cfg=self._model_cfg,
                    sessions=self._sessions,
                    preprocessor=self._preprocessor,
                    tokenizer=self._tokenizer,
                )

                if text and text.strip():
                    self.result_queue.put(("transcription", text))
                else:
                    self.result_queue.put(("transcription", None))
            finally:
                try:
                    if os.path.exists(temp_filepath):
                        os.remove(temp_filepath)
                except Exception:
                    pass

        except Exception as e:
            self.error(f"Ошибка транскрибации ONNX: {e}", exc_info=True)
            self.result_queue.put(("transcription_error", str(e)))

    async def process_commands(self):
        while True:
            try:
                if not self.command_queue.empty():
                    command = self.command_queue.get()
                    cmd_type = command[0]

                    if cmd_type == "init":
                        await self.init_recognizer(command[1])
                    elif cmd_type == "transcribe":
                        audio_data, sample_rate = command[1], command[2]
                        await self.transcribe_audio(audio_data, sample_rate)
                    elif cmd_type == "shutdown":
                        self.info("Получена команда завершения работы.")
                        break

                await asyncio.sleep(0.01)
            except Exception as e:
                self.error(f"Ошибка в цикле команд: {e}\n{traceback.format_exc()}")

        self._sessions = None
        self._model_cfg = None
        self._preprocessor = None
        self._tokenizer = None

    def info(self, msg: str):
        self.log_queue.put(("info", msg))

    def warning(self, msg: str):
        self.log_queue.put(("warning", msg))

    def error(self, msg: str, exc_info: bool = False):
        if exc_info:
            msg += f"\n{traceback.format_exc()}"
        self.log_queue.put(("error", msg))