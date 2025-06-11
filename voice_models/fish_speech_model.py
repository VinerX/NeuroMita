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

class FishSpeechModel(IVoiceModel):
    # __init__, _load_module, get_display_name, is_installed, install, uninstall, cleanup_state, initialize
    # остаются без изменений.
    def __init__(self, parent: 'LocalVoice', model_id: str):
        super().__init__(parent, model_id)
        self.fish_speech_module = None
        self.current_fish_speech = None
        self._load_module()

    def _load_module(self):
        try:
            from fish_speech_lib.inference import FishSpeech
            self.fish_speech_module = FishSpeech
        except ImportError:
            self.fish_speech_module = None

    def get_display_name(self) -> str:
        return "Fish Speech / +RVC"

    def is_installed(self) -> bool:
        self._load_module()
        if self.model_id in ["medium+", "medium+low"]:
            return self.fish_speech_module is not None and self.parent.is_triton_installed()
        return self.fish_speech_module is not None

    def install(self) -> bool:
        success = self.parent.download_fish_speech_internal()
        if not success:
            return False
            
        if self.model_id in ["medium+", "medium+low"]:
            logger.info(f"Модель {self.model_id} требует Triton. Начинаю установку Triton...")
            triton_success = self.parent.download_triton_internal()
            if not triton_success:
                logger.warning("Fish Speech был установлен, но установка Triton не удалась.")
                return True 
        
        return True

    def uninstall(self) -> bool:
        return self.parent._uninstall_component("Fish Speech", "fish-speech-lib")

    def cleanup_state(self):
        super().cleanup_state()
        self.current_fish_speech = None
        self.fish_speech_module = None
        if self.parent.first_compiled is not None:
            logger.info("Сброс состояния компиляции Fish Speech из-за удаления.")
            self.parent.first_compiled = None
        logger.info(f"Состояние для модели {self.model_id} сброшено.")

    def initialize(self, init: bool = False) -> bool:
        if self.initialized:
            return True

        if self.fish_speech_module is None:
            logger.error(f"Модуль fish_speech_lib не установлен, но требуется для модели {self.model_id}")
            return False

        compile_model = self.model_id in ["medium+", "medium+low"]
        if self.parent.first_compiled is not None and self.parent.first_compiled != compile_model:
            logger.error("КОНФЛИКТ: Невозможно переключиться между скомпилированной и нескомпилированной версией Fish Speech без перезапуска программы.")
            return False

        if self.current_fish_speech is None:
            settings = self.load_model_settings()
            device = settings.get("fsprvc_fsp_device" if self.model_id == "medium+low" else "device", "cuda")
            half = settings.get("fsprvc_fsp_half" if self.model_id == "medium+low" else "half", "True" if compile_model else "False").lower() == "true"

            self.current_fish_speech = self.fish_speech_module(device=device, half=half, compile_model=compile_model)
            
            self.parent.first_compiled = compile_model
            logger.info(f"Компонент Fish Speech для модели '{self.model_id}' инициализирован (compile={compile_model}).")
        
        self.initialized = True

        if init:
            init_text = f"Инициализация модели {self.model_id}" if self.parent.voice_language == "ru" else f"{self.model_id} Model Initialization"
            logger.info(f"Выполнение тестового прогона для {self.model_id}...")
            try:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(self.voiceover(init_text))
                logger.info(f"Тестовый прогон для {self.model_id} успешно завершен.")
            except Exception as e:
                logger.error(f"Ошибка во время тестового прогона модели {self.model_id}: {e}", exc_info=True)
                self.initialized = False
                return False

        return True

    async def voiceover(self, text: str, character: Optional[Any] = None, **kwargs) -> Optional[str]:
        if not self.initialized:
            raise Exception(f"Модель {self.model_id} не инициализирована.")
            
        if self.fish_speech_module is None:
            raise ImportError("Модуль fish_speech_lib не установлен.")

        try:
            settings = self.load_model_settings()
            is_combined_model = self.model_id == "medium+low"
            
            temp_key = "fsprvc_fsp_temperature" if is_combined_model else "temperature"
            top_p_key = "fsprvc_fsp_top_p" if is_combined_model else "top_p"
            rep_penalty_key = "fsprvc_fsp_repetition_penalty" if is_combined_model else "repetition_penalty"
            chunk_len_key = "fsprvc_fsp_chunk_length" if is_combined_model else "chunk_length"
            max_tokens_key = "fsprvc_fsp_max_tokens" if is_combined_model else "max_new_tokens"

            reference_audio_path = self.parent.clone_voice_filename if self.parent.clone_voice_filename and os.path.exists(self.parent.clone_voice_filename) else None
            reference_text = ""
            if reference_audio_path and self.parent.clone_voice_text and os.path.exists(self.parent.clone_voice_text):
                with open(self.parent.clone_voice_text, "r", encoding="utf-8") as file:
                    reference_text = file.read().strip()

            sample_rate, audio_data = self.current_fish_speech(
                text=text,
                reference_audio=reference_audio_path,
                reference_audio_text=reference_text,
                top_p=float(settings.get(top_p_key, 0.7)),
                temperature=float(settings.get(temp_key, 0.7)),
                repetition_penalty=float(settings.get(rep_penalty_key, 1.2)),
                max_new_tokens=int(settings.get(max_tokens_key, 1024)),
                chunk_length=int(settings.get(chunk_len_key, 200)),
                use_memory_cache=True,
            )

            hash_object = hashlib.sha1(f"{text[:20]}_{datetime.now().timestamp()}".encode())
            raw_output_filename = f"fish_raw_{hash_object.hexdigest()[:10]}.wav"
            raw_output_path = os.path.abspath(os.path.join("temp", raw_output_filename))
            os.makedirs("temp", exist_ok=True)
            
            import soundfile as sf
            sf.write(raw_output_path, audio_data, sample_rate)

            if not os.path.exists(raw_output_path) or os.path.getsize(raw_output_path) == 0:
                return None

            stereo_output_path = raw_output_path.replace("_raw", "_stereo")
            converted_file = await self.parent.convert_wav_to_stereo(raw_output_path, stereo_output_path, volume="1.5")
            
            processed_output_path = stereo_output_path if converted_file and os.path.exists(converted_file) else raw_output_path
            if processed_output_path == stereo_output_path:
                try: os.remove(raw_output_path)
                except OSError: pass
            
            final_output_path = processed_output_path

            if self.model_id == "medium+low":
                logger.info(f"Применяем RVC к файлу: {final_output_path}")
                # <<< ИСПРАВЛЕНИЕ: Передаем ID нашей модели, чтобы RVC использовал правильные настройки >>>
                rvc_output_path = await self.parent.apply_rvc_to_file(final_output_path, original_model_id=self.model_id)
                
                if rvc_output_path and os.path.exists(rvc_output_path):
                    if final_output_path != rvc_output_path:
                        try: os.remove(final_output_path)
                        except OSError: pass
                    final_output_path = rvc_output_path
                else:
                    logger.warning("Ошибка во время обработки RVC. Возвращается результат до RVC.")

            if self.parent.parent and hasattr(self.parent.parent, 'patch_to_sound_file'):
                self.parent.parent.patch_to_sound_file = final_output_path
            
            return final_output_path
        except Exception as error:
            traceback.print_exc()
            logger.info(f"Ошибка при создании озвучки с Fish Speech ({self.model_id}): {error}")
            return None