from __future__ import annotations

import os
import traceback
from typing import Dict, Optional, Any, List

import ffmpeg
from main_logger import logger
from managers.settings_manager import SettingsManager
from utils import getTranslationVariant as _, get_character_voice_paths
from utils.gpu_utils import check_gpu_provider

from handlers.voice_models.base_model import IVoiceModel
from handlers.voice_models.edge_tts_rvc_model import EdgeTTS_RVC_Model
from handlers.voice_models.fish_speech_model import FishSpeechModel
from handlers.voice_models.f5_tts_model import F5TTSModel


class LocalVoice:
    """
    Runtime registry/router for local voice models.
    """

    def __init__(self, main_controller: Optional[object] = None):
        self.settings = getattr(main_controller, "settings", None) or SettingsManager()

        self.provider = None
        try:
            self.provider = check_gpu_provider()
        except Exception:
            self.provider = None

        self.voice_language = self.settings.get("VOICE_LANGUAGE", "ru")

        # важно для FishSpeech: запрещаем переключение compile False/True без рестарта
        self.first_compiled: Optional[bool] = None

        self.current_model_id: Optional[str] = None
        self.active_model_instance: Optional[IVoiceModel] = None

        edge_rvc_handler = EdgeTTS_RVC_Model(self, "edge_rvc_handler")
        fish_handler = FishSpeechModel(self, "fish_handler", rvc_handler=edge_rvc_handler)
        f5_handler = F5TTSModel(self, "f5_handler", rvc_handler=edge_rvc_handler)

        self._registry: Dict[str, IVoiceModel] = self._build_registry_from_handlers(
            [edge_rvc_handler, fish_handler, f5_handler]
        )

        if not self._registry:
            self._registry = {
                "low": edge_rvc_handler,
                "low+": edge_rvc_handler,
                "medium": fish_handler,
                "medium+": fish_handler,
                "medium+low": fish_handler,
                "high": f5_handler,
                "high+low": f5_handler,
            }

    def _build_registry_from_handlers(self, handlers: List[IVoiceModel]) -> Dict[str, IVoiceModel]:
        reg: Dict[str, IVoiceModel] = {}

        for h in handlers or []:
            if not h:
                continue

            cfgs = []
            try:
                cfgs = h.get_model_configs() or []
            except Exception:
                cfgs = []

            for cfg in cfgs:
                if not isinstance(cfg, dict):
                    continue
                mid = str(cfg.get("id") or "").strip()
                if not mid:
                    continue

                prev = reg.get(mid)
                if prev is not None and prev is not h:
                    logger.warning(f"LocalVoice registry conflict for model_id='{mid}': {type(prev)} vs {type(h)}")

                reg[mid] = h

        return reg

    def get_all_model_configs(self):
        configs = []
        seen = set()
        for _mid, handler in self._registry.items():
            if not handler or not hasattr(handler, "get_model_configs"):
                continue
            try:
                for cfg in (handler.get_model_configs() or []):
                    cid = cfg.get("id")
                    if not cid or cid in seen:
                        continue
                    configs.append(cfg)
                    seen.add(cid)
            except Exception as e:
                logger.warning(f"LocalVoice.get_all_model_configs error: {e}")
        return configs

    def is_model_installed(self, model_id: str) -> bool:
        model = self._registry.get(model_id)
        if not model:
            return False
        try:
            return bool(model.is_installed(model_id))
        except Exception:
            return False

    def is_model_initialized(self, model_id: str) -> bool:
        model = self._registry.get(model_id)
        if not model:
            return False
        try:
            return bool(model.initialized) and (getattr(model, "initialized_for", None) == str(model_id))
        except Exception:
            return False

    def select_model(self, model_id: str) -> None:
        model_id = str(model_id or "").strip()
        model = self._registry.get(model_id)
        if not model:
            raise RuntimeError(f"Unknown voice model_id: {model_id}")

        self.current_model_id = model_id
        self.active_model_instance = model

    def initialize_model(self, model_id: str, *, init: bool = False) -> bool:
        model_id = str(model_id or "").strip()
        model = self._registry.get(model_id)
        if not model:
            logger.error(f"Unknown model id for init: {model_id}")
            return False

        if not self.is_model_installed(model_id):
            logger.error(f"Model '{model_id}' is not installed.")
            return False

        self.current_model_id = model_id
        ok = False
        try:
            ok = bool(model.initialize(init=init))
        except Exception as e:
            logger.error(f"initialize_model failed for {model_id}: {e}", exc_info=True)
            ok = False

        if ok:
            self.active_model_instance = model
        return ok

    def change_voice_language(self, new_voice_language: str):
        self.voice_language = str(new_voice_language or "ru")
        if self.active_model_instance:
            try:
                self.active_model_instance.cleanup_state()
            except Exception:
                pass
        self.active_model_instance = None

    def load_model_settings(self, model_id: str) -> Dict[str, Any]:
        try:
            settings_file = os.path.join("Settings", "voice_model_settings.json")
            if os.path.exists(settings_file):
                import json
                with open(settings_file, "r", encoding="utf-8") as f:
                    all_settings = json.load(f)
                    return all_settings.get(model_id, {}) if isinstance(all_settings, dict) else {}
            return {}
        except Exception as e:
            logger.info(f"load_model_settings error for {model_id}: {e}")
            return {}

    def is_cuda_available(self) -> bool:
        try:
            import torch
            return bool(torch.cuda.is_available())
        except Exception:
            return False

    def convert_wav_to_stereo(
        self,
        input_path: str,
        output_path: str,
        *,
        atempo: float = 1.0,
        volume: str = "1.0",
        pitch: float = 0.0,
    ) -> str | None:
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"File not found: {input_path}")

        try:
            pitch_ratio = 2 ** (float(pitch) / 12.0)
            (
                ffmpeg
                .input(input_path)
                .filter("rubberband", pitch=pitch_ratio, pitchq="quality")
                .filter("atempo", float(atempo))
                .filter("volume", volume=volume)
                .output(output_path, format="wav", acodec="pcm_s16le", ar="44100", ac=2)
                .run(cmd=["ffmpeg", "-nostdin"], capture_stdout=True, capture_stderr=True, overwrite_output=True)
            )
            return output_path
        except ffmpeg.Error as fe:
            err = fe.stderr.decode(errors="ignore") if getattr(fe, "stderr", None) else ""
            logger.error(f"FFmpeg error:\n{err}\n{traceback.format_exc()}")
            return None
        except Exception:
            logger.error(f"convert_wav_to_stereo error:\n{traceback.format_exc()}")
            return None

    async def voiceover(self, text: str, *, output_file: str, character: Optional[Any] = None) -> Optional[str]:
        if not self.current_model_id or not self.active_model_instance:
            raise RuntimeError("No active voice model selected")

        mid = self.current_model_id
        if not self.is_model_initialized(mid):
            ok = self.initialize_model(mid, init=False)
            if not ok:
                raise RuntimeError(f"Failed to initialize model '{mid}'")

        os.makedirs(os.path.dirname(os.path.abspath(output_file)) or ".", exist_ok=True)

        try:
            _paths = get_character_voice_paths(character, self.provider)
            self.pth_path = _paths.get("pth_path")
            self.index_path = _paths.get("index_path")
            self.clone_voice_filename = _paths.get("clone_voice_filename")
            self.clone_voice_text = _paths.get("clone_voice_text")
            self.current_character_name = _paths.get("character_name")
        except Exception:
            pass

        try:
            return await self.active_model_instance.voiceover(text, character, output_file=output_file)
        except TypeError:
            return await self.active_model_instance.voiceover(text, character)
        
