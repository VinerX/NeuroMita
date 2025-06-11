import os
import sys
import importlib
import traceback
import hashlib
from datetime import datetime
import asyncio

from .base_model import IVoiceModel
from typing import Optional, Any
from Logger import logger

class F5TTSModel(IVoiceModel):
    def __init__(self, parent: 'LocalVoice', model_id: str):
        super().__init__(parent, model_id)
        self.f5_pipeline_module = None
        self.current_f5_pipeline = None
        self._load_module()

    def _load_module(self):
        try:
            from LocalPipelines.F5_TTS.f5_pipeline import F5TTSPipeline
            self.f5_pipeline_module = F5TTSPipeline
        except ImportError:
            self.f5_pipeline_module = None

    def get_display_name(self) -> str:
        return "F5-TTS"

    def is_installed(self) -> bool:
        self._load_module()
        model_dir = os.path.join("checkpoints", "F5-TTS")
        ckpt_path = os.path.join(model_dir, "model_240000_inference.safetensors")
        vocab_path = os.path.join(model_dir, "vocab.txt")
        return self.f5_pipeline_module is not None and os.path.exists(ckpt_path) and os.path.exists(vocab_path)

    def install(self) -> bool:
        return self.parent.download_f5_tts_internal()

    def uninstall(self) -> bool:
        return self.parent._uninstall_component("F5-TTS", "f5-tts")

    def cleanup_state(self):
        super().cleanup_state()
        self.current_f5_pipeline = None
        self.f5_pipeline_module = None
        logger.info(f"Состояние для модели {self.model_id} сброшено.")

    def initialize(self, init: bool = False) -> bool:
        if self.initialized:
            return True

        if self.f5_pipeline_module is None:
            logger.error("Модуль f5_pipeline не установлен или не загружен.")
            return False
        
        if self.current_f5_pipeline is None:
            model_dir = os.path.join("checkpoints", "F5-TTS")
            ckpt_path = os.path.join(model_dir, "model_240000_inference.safetensors")
            vocab_path = os.path.join(model_dir, "vocab.txt")

            if not all(os.path.exists(p) for p in [ckpt_path, vocab_path]):
                logger.error(f"Не найдены файлы модели F5-TTS в {model_dir}. Переустановите модель.")
                return False
            
            device = "cuda" if self.parent.provider == "NVIDIA" else "cpu"
            self.current_f5_pipeline = self.f5_pipeline_module(model="F5TTS_v1_Base", ckpt_file=ckpt_path, vocab_file=vocab_path, device=device)
            logger.info(f"F5-TTS Pipeline инициализирован на устройстве: {device}.")

        # <<< ИСПРАВЛЕНИЕ: Устанавливаем флаг ДО тестового прогона >>>
        self.initialized = True

        if init:
            init_text = f"Инициализация модели {self.model_id}" if self.parent.voice_language == "ru" else f"{self.model_id} Model Initialization"
            logger.info(f"Выполнение тестового прогона для {self.model_id}...")
            try:
                asyncio.run(self.voiceover(init_text))
                logger.info(f"Тестовый прогон для {self.model_id} успешно завершен.")
            except Exception as e:
                logger.error(f"Ошибка во время тестового прогона модели {self.model_id}: {e}", exc_info=True)
                self.initialized = False # Сбрасываем флаг в случае ошибки
                return False

        return True

    async def voiceover(self, text: str, character: Optional[Any] = None, **kwargs) -> Optional[str]:
        if not self.initialized:
            raise Exception("Пайплайн F5-TTS не инициализирован.")
        
        try:
            settings = self.load_model_settings()
            reference_postfix = kwargs.get("reference_postfix", "default")

            ref_audio_path = None
            ref_text_content = ""
            if character and hasattr(character, 'short_name'):
                char_name = character.short_name
                potential_audio_path = os.path.join("Models", f"{char_name}_Cuts", f"{char_name}_{reference_postfix}.wav")
                potential_text_path = os.path.join("Models", f"{char_name}_Cuts", f"{char_name}_{reference_postfix}.txt")
                if os.path.exists(potential_audio_path):
                    ref_audio_path = potential_audio_path
                    if os.path.exists(potential_text_path):
                        with open(potential_text_path, "r", encoding="utf-8") as f: ref_text_content = f.read().strip()
            
            if not ref_audio_path:
                default_audio_path = os.path.join("Models", "Mila.wav")
                default_text_path = os.path.join("Models", "Mila.txt")
                if os.path.exists(default_audio_path):
                    ref_audio_path = default_audio_path
                    if os.path.exists(default_text_path):
                        with open(default_text_path, "r", encoding="utf-8") as f: ref_text_content = f.read().strip()
            
            if not ref_audio_path:
                raise FileNotFoundError("Для F5-TTS требуется референсное аудио, но оно не найдено.")
            
            hash_object = hashlib.sha1(f"{text[:20]}_{datetime.now().timestamp()}".encode())
            output_path = os.path.join("temp", f"f5_raw_{hash_object.hexdigest()[:10]}.wav")
            os.makedirs("temp", exist_ok=True)
            
            await asyncio.to_thread(
                self.current_f5_pipeline.generate,
                text_to_generate=text,
                output_path=output_path,
                ref_audio=ref_audio_path,
                ref_text=ref_text_content,
                speed=float(settings.get("speed", 1.0)),
                remove_silence=settings.get("remove_silence", True),
                nfe_step=int(settings.get("nfe_step", 32))
            )

            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                return None
            
            stereo_output_path = output_path.replace("_raw", "_stereo")
            converted_file = await self.parent.convert_wav_to_stereo(output_path, stereo_output_path)

            if converted_file and os.path.exists(converted_file):
                final_output_path = stereo_output_path
                try: os.remove(output_path)
                except OSError: pass
            else:
                final_output_path = output_path
            
            if self.parent.parent.ConnectedToGame:
                self.parent.parent.patch_to_sound_file = final_output_path

            return final_output_path
        except Exception as e:
            logger.error(f"Ошибка при создании озвучки с F5-TTS: {e}")
            traceback.print_exc()
            return None