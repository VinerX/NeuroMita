import os
import sys
import importlib
import traceback
import tempfile
import soundfile as sf
import asyncio
import re
from xml.sax.saxutils import escape

from .base_model import IVoiceModel
from typing import Optional, Any
from Logger import logger

class EdgeTTS_RVC_Model(IVoiceModel):
    def __init__(self, parent: 'LocalVoice', model_id: str):
        # model_id здесь больше не используется для определения режима,
        # но остается для совместимости с интерфейсом.
        super().__init__(parent, model_id)
        self.tts_rvc_module = None
        self.current_tts_rvc = None
        self.current_silero_model = None
        self.current_silero_sample_rate = 48000
        self._load_module()

    def _load_module(self):
        try:
            from tts_with_rvc import TTS_RVC
            self.tts_rvc_module = TTS_RVC
        except ImportError:
            self.tts_rvc_module = None
    
    def get_display_name(self) -> str:
        return "EdgeTTS+RVC / Silero+RVC"

    def is_installed(self) -> bool:
        self._load_module()
        return self.tts_rvc_module is not None

    def install(self) -> bool:
        return self.parent.download_edge_tts_rvc_internal()

    def uninstall(self) -> bool:
        return self.parent._uninstall_component("EdgeTTS+RVC", "tts-with-rvc")

    def cleanup_state(self):
        super().cleanup_state()
        self.current_tts_rvc = None
        self.current_silero_model = None
        self.tts_rvc_module = None
        logger.info(f"Состояние для обработчика EdgeTTS/Silero+RVC сброшено.")

    def initialize(self, init: bool = False) -> bool:
        # Эта функция теперь вызывается с конкретным model_id, который определяет режим работы
        current_mode = self.parent.current_model_id
        logger.info(f"Запрос на инициализацию обработчика в режиме: '{current_mode}'")

        # Шаг 1: Инициализация базового RVC, если его еще нет
        if self.current_tts_rvc is None:
            logger.info("Инициализация базового компонента RVC...")
            if self.tts_rvc_module is None:
                logger.error("Модуль tts_with_rvc не установлен.")
                return False
            
            settings = self.parent.load_model_settings(current_mode)
            device = settings.get("device", "cuda:0" if self.parent.provider == "NVIDIA" else "dml")
            f0_method = settings.get("f0method", "rmvpe" if self.parent.provider == "NVIDIA" else "pm")
            
            is_nvidia = self.parent.provider in ["NVIDIA"]
            model_ext = 'pth' if is_nvidia else 'onnx'
            default_model_path = os.path.join("Models", f"Mila.{model_ext}")
            
            model_path_to_use = self.parent.pth_path if self.parent.pth_path and os.path.exists(self.parent.pth_path) else default_model_path
            if not os.path.exists(model_path_to_use):
                logger.error(f"Не найден файл RVC модели: {model_path_to_use}")
                return False

            self.current_tts_rvc = self.tts_rvc_module(model_path=model_path_to_use, device=device, f0_method=f0_method)
            logger.info("Базовый компонент RVC инициализирован.")
        
        # Обновляем голос EdgeTTS в RVC в любом случае
        if self.parent.voice_language == "ru":
            self.current_tts_rvc.set_voice("ru-RU-SvetlanaNeural")
        else:
            self.current_tts_rvc.set_voice("en-US-MichelleNeural")

        # Шаг 2: Управление компонентом Silero в зависимости от режима
        if current_mode == "low+":
            if self.current_silero_model is None:
                logger.info("Требуется режим 'low+', инициализация компонента Silero...")
                try:
                    import torch
                    settings = self.parent.load_model_settings(current_mode)
                    silero_device = settings.get("silero_device", "cuda" if self.parent.provider == "NVIDIA" else "cpu")
                    self.current_silero_sample_rate = int(settings.get("silero_sample_rate", 48000))
                    language = 'en' if self.parent.voice_language == 'en' else 'ru'
                    model_id_silero = 'v3_en' if language == 'en' else 'v4_ru'
                    
                    logger.info(f"Загрузка модели Silero ({language}/{model_id_silero})...")
                    model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models', model='silero_tts', language=language, speaker=model_id_silero, trust_repo=True)
                    model.to(silero_device)
                    self.current_silero_model = model
                    logger.info("Компонент Silero для 'low+' успешно инициализирован.")
                except Exception as e:
                    logger.error(f"Ошибка инициализации компонента Silero: {e}", exc_info=True)
                    return False
        else: # Для режима "low" или любого другого, убедимся, что Silero выгружен
            if self.current_silero_model is not None:
                logger.info("Переключение в режим без Silero. Выгрузка компонента Silero...")
                self.current_silero_model = None
                import gc
                gc.collect()

        # Шаг 3: Установка флага и тестовый прогон
        # Проверяем, что все необходимые компоненты на месте
        is_ready = self.current_tts_rvc is not None
        if current_mode == "low+":
            is_ready = is_ready and self.current_silero_model is not None

        if not is_ready:
            logger.error(f"Не все компоненты для модели '{current_mode}' удалось инициализировать.")
            self.initialized = False
            return False

        # Если мы дошли сюда, значит все нужные компоненты загружены.
        # Запускаем тестовый прогон только если модель еще не была помечена как инициализированная.
        if not self.initialized and init:
            self.initialized = True # Ставим флаг до прогона
            init_text = f"Инициализация модели {current_mode}" if self.parent.voice_language == "ru" else f"{current_mode} Model Initialization"
            logger.info(f"Выполнение тестового прогона для {current_mode}...")
            try:
                loop = asyncio.get_event_loop()
                loop.run_until_complete(self.voiceover(init_text))
                logger.info(f"Тестовый прогон для {current_mode} успешно завершен.")
            except Exception as e:
                logger.error(f"Ошибка во время тестового прогона модели {current_mode}: {e}", exc_info=True)
                self.initialized = False # Сбрасываем флаг в случае ошибки
                return False
        
        self.initialized = True
        return True

    async def voiceover(self, text: str, character: Optional[Any] = None, **kwargs) -> Optional[str]:
        current_mode = self.parent.current_model_id
        if not self.initialized:
            raise Exception(f"Обработчик не инициализирован для режима '{current_mode}'.")
            
        if current_mode == "low":
            return await self._voiceover_edge_tts_rvc(text, **kwargs)
        elif current_mode == "low+":
            return await self._voiceover_silero_rvc(text, character)
        else:
            raise ValueError(f"Обработчик вызван с неизвестным режимом: {current_mode}")

    async def _voiceover_edge_tts_rvc(self, text, TEST_WITH_DONE_AUDIO: str = None, settings_model_id: Optional[str] = None):
        if self.current_tts_rvc is None:
            raise Exception("Компонент RVC не инициализирован.")
        try:
            config_id = settings_model_id if settings_model_id else self.parent.current_model_id
            settings = self.parent.load_model_settings(config_id)
            logger.info(f"RVC использует конфигурацию от модели: '{config_id}'")

            is_combined_model = config_id == "medium+low"
            pitch_key = "fsprvc_rvc_pitch" if is_combined_model else "pitch"
            index_rate_key = "fsprvc_index_rate" if is_combined_model else "index_rate"
            protect_key = "fsprvc_protect" if is_combined_model else "protect"
            filter_radius_key = "fsprvc_filter_radius" if is_combined_model else "filter_radius"
            rms_mix_rate_key = "fsprvc_rvc_rms_mix_rate" if is_combined_model else "rms_mix_rate"
            is_half_key = "fsprvc_is_half" if is_combined_model else "is_half"
            f0method_key = "fsprvc_f0method" if is_combined_model else "f0method"
            use_index_file_key = "fsprvc_use_index_file" if is_combined_model else "use_index_file"
            tts_rate_key = "tts_rate"

            pitch = float(settings.get(pitch_key, 0))
            if self.parent.current_character_name == "Player" and not is_combined_model:
                pitch = -12
            
            index_rate = float(settings.get(index_rate_key, 0.75))
            protect = float(settings.get(protect_key, 0.33))
            filter_radius = int(settings.get(filter_radius_key, 3))
            rms_mix_rate = float(settings.get(rms_mix_rate_key, 0.5))
            is_half = settings.get(is_half_key, "True").lower() == "true"
            use_index_file = settings.get(use_index_file_key, True)
            f0method_override = settings.get(f0method_key, None)
            tts_rate = int(settings.get(tts_rate_key, 0)) if not is_combined_model else 0

            if use_index_file and self.parent.index_path and os.path.exists(self.parent.index_path):
                self.current_tts_rvc.set_index_path(self.parent.index_path)
            else:
                self.current_tts_rvc.set_index_path("")
            
            if self.parent.provider in ["NVIDIA"]:
                inference_params = {"pitch": pitch, "index_rate": index_rate, "protect": protect, "filter_radius": filter_radius, "rms_mix_rate": rms_mix_rate, "is_half": is_half}
            else:
                inference_params = {"pitch": pitch, "index_rate": index_rate, "protect": protect, "filter_radius": filter_radius, "rms_mix_rate": rms_mix_rate}
            if f0method_override:
                inference_params["f0method"] = f0method_override
            
            if os.path.abspath(self.parent.pth_path) != os.path.abspath(self.current_tts_rvc.current_model):
                if self.parent.provider in ["NVIDIA"]:
                    self.current_tts_rvc.current_model = self.parent.pth_path
                elif self.parent.provider in ["AMD"]:
                    # if hasattr(self.current_tts_rvc, 'set_model'):
                    #     self.current_tts_rvc.set_model(self.parent.pth_path)
                    # else:
                    self.current_tts_rvc.current_model = self.parent.pth_path

            if not TEST_WITH_DONE_AUDIO:
                inference_params["tts_rate"] = tts_rate
                output_file_rvc = self.current_tts_rvc(text=text, **inference_params)
            else:
                output_file_rvc = self.current_tts_rvc.voiceover_file(input_path=TEST_WITH_DONE_AUDIO, **inference_params)

            if not output_file_rvc or not os.path.exists(output_file_rvc) or os.path.getsize(output_file_rvc) == 0:
                return None
            
            stereo_output_file = output_file_rvc.replace(".wav", "_stereo.wav")
            converted_file = await self.parent.convert_wav_to_stereo(output_file_rvc, stereo_output_file, atempo=1.0, pitch=(4 if self.parent.current_character_name == 'ShorthairMita' and self.parent.provider in ['AMD'] else 0))

            if converted_file and os.path.exists(converted_file):
                final_output_path = stereo_output_file
                try: os.remove(output_file_rvc)
                except OSError: pass
            else:
                final_output_path = output_file_rvc
            
            if self.parent.parent.ConnectedToGame and TEST_WITH_DONE_AUDIO is None:
                self.parent.parent.patch_to_sound_file = final_output_path
            return final_output_path
        except Exception as error:
            traceback.print_exc()
            logger.info(f"Ошибка при создании озвучки с Edge-TTS + RVC: {error}")
            return None

    def _preprocess_text_to_ssml(self, text: str):
        lang = self.parent.voice_language
        defaults = {'en': {'pitch': 6, 'speaker': "en_88"}, 'ru': {'pitch': 2, 'speaker': "kseniya"}}
        lang_defaults = defaults.get(lang, defaults['en'])
        char_params = {
            'en': {"CappieMita": (6, "en_26"), "CrazyMita": (6, "en_60"), "GhostMita": (6, "en_33"), "Mila": (6, "en_88"), "MitaKind": (3, "en_33"), "ShorthairMita": (6, "en_60"), "SleepyMita": (6, "en_33"), "TinyMita": (2, "en_60"), "Player": (0, "en_27")},
            'ru': {"CappieMita": (6, "kseniya"), "MitaKind": (1, "kseniya"), "ShorthairMita": (2, "kseniya"), "CrazyMita": (2, "kseniya"), "Mila": (2, "kseniya"), "TinyMita": (-3, "baya"), "SleepyMita": (2, "baya"), "GhostMita": (1, "baya"), "Player": (0, "aidar")}
        }
        character_rvc_pitch, character_speaker = lang_defaults['pitch'], lang_defaults['speaker']
        character_short_name = self.parent.current_character_name
        current_lang_params = char_params.get(lang, char_params['en'])
        if specific_params := current_lang_params.get(character_short_name):
            character_rvc_pitch, character_speaker = specific_params
        
        text = escape(re.sub(r'<[^>]*>', '', text)).replace("Mita", "M+ita").replace("Mila", "M+ila").replace("mita", "m+ita").replace("mila", "m+ila")
        parts = re.split(r'([.!?]+[^A-Za-zА-Яа-я0-9_]*)(\s+)', text.strip())
        processed_text = ""
        i = 0
        while i < len(parts):
            if text_part := parts[i]: processed_text += text_part
            if i + 2 < len(parts):
                if punctuation_part := parts[i+1]: processed_text += punctuation_part
                if (whitespace_part := parts[i+2]) and i + 3 < len(parts) and parts[i+3]: processed_text += f' <break time="300ms"/> '
                elif whitespace_part: processed_text += whitespace_part
            i += 3
        ssml_content = processed_text.strip()
        ssml_output = f'<speak><p>{ssml_content}</p></speak>' if ssml_content else '<speak></speak>'
        return ssml_output, character_rvc_pitch, character_speaker
    
    async def _voiceover_silero_rvc(self, text, character=None):
        if self.current_silero_model is None or self.current_tts_rvc is None:
            raise Exception("Компоненты Silero или RVC не инициализированы для режима low+.")
        
        self.parent.current_character = character if character is not None else getattr(self.parent, 'current_character', None)
        temp_wav = None
        try:
            ssml_text, character_base_rvc_pitch, character_speaker = self._preprocess_text_to_ssml(text)
            settings = self.parent.load_model_settings('low+')
            
            audio_tensor = self.current_silero_model.apply_tts(
                ssml_text=ssml_text, speaker=character_speaker, sample_rate=self.current_silero_sample_rate,
                put_accent=settings.get("silero_put_accent", True), put_yo=settings.get("silero_put_yo", True)
            )
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav_file:
                temp_wav = temp_wav_file.name
            sf.write(temp_wav, audio_tensor.cpu().numpy(), self.current_silero_sample_rate)
            
            if not os.path.exists(temp_wav) or os.path.getsize(temp_wav) == 0:
                 return None

            base_rvc_pitch_from_settings = float(settings.get("silero_rvc_pitch", 6))
            final_rvc_pitch = base_rvc_pitch_from_settings - (6 - character_base_rvc_pitch)

            rvc_params = {
                "pitch": final_rvc_pitch,
                "index_rate": float(settings.get("silero_rvc_index_rate", 0.75)),
                "protect": float(settings.get("silero_rvc_protect", 0.33)),
                "filter_radius": int(settings.get("silero_rvc_filter_radius", 3)),
                "rms_mix_rate": float(settings.get("silero_rvc_rms_mix_rate", 0.5)),
            }
            if self.parent.provider == "NVIDIA": rvc_params["is_half"] = settings.get("silero_rvc_is_half", "True").lower() == "true"
            if f0method_override := settings.get("silero_rvc_f0method", None): rvc_params["f0method"] = f0method_override
            
            is_nvidia = self.parent.provider in ["NVIDIA"]
            model_ext = 'pth' if is_nvidia else 'onnx'
            rvc_model_short_name = str(getattr(character, 'short_name', "Mila"))
            self.parent.pth_path = os.path.join(self.parent.clone_voice_folder, f"{rvc_model_short_name}.{model_ext}")
            self.parent.index_path = os.path.join(self.parent.clone_voice_folder, f"{rvc_model_short_name}.index")
            if not os.path.exists(self.parent.pth_path): raise Exception(f"Файл модели RVC не найден: {self.parent.pth_path}")

            if os.path.abspath(self.parent.pth_path) != os.path.abspath(getattr(self.current_tts_rvc, 'current_model', '')):
                logger.info(f"Смена RVC модели на: {self.parent.pth_path}")
                if self.parent.provider in ["NVIDIA"]:
                    self.current_tts_rvc.current_model = self.parent.pth_path
                elif self.parent.provider in ["AMD"]:
                    if hasattr(self.current_tts_rvc, 'set_model'):
                        self.current_tts_rvc.set_model(self.parent.pth_path)
                    else:
                        self.current_tts_rvc.current_model = self.parent.pth_path
                        logger.warning("Метод 'set_model' не найден, используется прямое присваивание (может не работать на AMD).")

            if settings.get("use_index_file", True) and self.parent.index_path and os.path.exists(self.parent.index_path):
                self.current_tts_rvc.set_index_path(self.parent.index_path)
            else:
                self.current_tts_rvc.set_index_path("")
            
            output_file_rvc = self.current_tts_rvc.voiceover_file(input_path=temp_wav, **rvc_params)

            if not output_file_rvc or not os.path.exists(output_file_rvc) or os.path.getsize(output_file_rvc) == 0:
                return None

            stereo_output_file = output_file_rvc.replace(".wav", "_stereo.wav")

            # For VinerX: в этом файле я использую ffmpeg rubberband питчинг - почитай про него. Но при прослушивании голос почему-то не меняется у шортхейр миты. Надо это посмотреть и исправить
            # Что касается файла: он создаётся правильно, но воспроизводится незапитченная версия почему то в интерфейсе (в игре не тестил). Вот команда, которая хорошо отрабатывает: ffmpeg -i 05fbd3d5.wav -af "rubberband=pitch=1.3" out.mp3
            # Посмотри её, если сможешь, исправь, пожалуйста. Это также и про silero/edge tts
            converted_file = await self.parent.convert_wav_to_stereo(output_file_rvc, stereo_output_file, atempo=1.0, pitch=(4 if self.parent.current_character_name == 'ShorthairMita' and self.parent.provider in ['AMD'] else 0))


            if converted_file and os.path.exists(converted_file):
                final_output_path = stereo_output_file
                try: os.remove(output_file_rvc)
                except OSError: pass
            else:
                final_output_path = output_file_rvc
            
            if hasattr(self.parent.parent, 'ConnectedToGame') and self.parent.parent.ConnectedToGame:
                self.parent.parent.patch_to_sound_file = final_output_path
            return final_output_path
        except Exception as error:
            traceback.print_exc()
            logger.info(f"Ошибка при создании озвучки с Silero + RVC: {error}")
            return None
        finally:
            if temp_wav and os.path.exists(temp_wav):
                try: os.remove(temp_wav)
                except OSError: pass