from __future__ import annotations

import gc
import os
import traceback
from typing import Dict, Optional, Any, List

import ffmpeg
from core.app_paths import settings_path
from core.installables.helpers import build_runtime_ctx
from main_logger import logger
from utils import get_character_voice_paths
from utils.gpu_utils import check_gpu_provider

from handlers.voice_models.base_model import IVoiceModel
from handlers.voice_models.edge_tts_rvc_model import (
    EDGE_TTS_RVC_CUDA_ID,
    EDGE_TTS_RVC_ONNX_ID,
    SILERO_RVC_CUDA_ID,
    SILERO_RVC_ONNX_ID,
    EdgeTTSRVCCudaModel,
    EdgeTTSRVCOnnxModel,
)
from handlers.voice_models.fish_speech_model import FishSpeechModel
from handlers.voice_models.f5_tts_model import F5TTSModel


class LocalVoice:
    """
    Runtime registry/router for local voice models.

    Важно: НЕ читает SettingsManager напрямую.
    Все нужные параметры (например voice_language) должны быть переданы извне
    (контроллером) и/или обновляться через методы change_voice_language(...).
    """

    def __init__(self, *, voice_language: str = "ru"):
        self.provider = None
        try:
            self.provider = check_gpu_provider()
        except Exception:
            self.provider = None

        self.voice_language = str(voice_language or "ru")

        # важно для FishSpeech: запрещаем переключение compile False/True без рестарта
        self.first_compiled: Optional[bool] = None

        self.current_model_id: Optional[str] = None
        self.active_model_instance: Optional[IVoiceModel] = None

        edge_rvc_cuda_handler = EdgeTTSRVCCudaModel(self, "edge_rvc_cuda_handler")
        edge_rvc_onnx_handler = EdgeTTSRVCOnnxModel(self, "edge_rvc_onnx_handler")
        rvc_handler = edge_rvc_cuda_handler if self.provider == "NVIDIA" else edge_rvc_onnx_handler
        fish_handler = FishSpeechModel(self, "fish_handler", rvc_handler=rvc_handler)
        f5_handler = F5TTSModel(self, "f5_handler", rvc_handler=rvc_handler)

        self._registry: Dict[str, IVoiceModel] = self._build_registry_from_handlers(
            [edge_rvc_cuda_handler, edge_rvc_onnx_handler, fish_handler, f5_handler]
        )

        if not self._registry:
            self._registry = {
                EDGE_TTS_RVC_CUDA_ID: edge_rvc_cuda_handler,
                EDGE_TTS_RVC_ONNX_ID: edge_rvc_onnx_handler,
                SILERO_RVC_CUDA_ID: edge_rvc_cuda_handler,
                SILERO_RVC_ONNX_ID: edge_rvc_onnx_handler,
                "medium": fish_handler,
                "medium+": fish_handler,
                "medium+low": fish_handler,
                "high": f5_handler,
                "high+low": f5_handler,
            }

    def _resolve_model_id(self, model_id: str) -> str:
        model_id = str(model_id or "").strip()
        if model_id == "low":
            return EDGE_TTS_RVC_CUDA_ID if self.provider == "NVIDIA" else EDGE_TTS_RVC_ONNX_ID
        if model_id == "low+":
            return SILERO_RVC_CUDA_ID if self.provider == "NVIDIA" else SILERO_RVC_ONNX_ID
        return model_id

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
        model_id = self._resolve_model_id(model_id)
        if not model_id:
            return False

        try:
            model = self._registry.get(model_id)
            if model is None:
                return False

            ctx = build_runtime_ctx({"gpu_vendor": self.provider or "CPU"})
            return bool(model.__class__.is_model_installed(model_id, ctx))
        except Exception:
            return False

    def is_model_initialized(self, model_id: str) -> bool:
        model_id = self._resolve_model_id(model_id)
        model = self._registry.get(model_id)
        if not model:
            return False
        try:
            return bool(model.initialized) and (getattr(model, "initialized_for", None) == str(model_id))
        except Exception:
            return False

    def select_model(self, model_id: str) -> None:
        model_id = self._resolve_model_id(model_id)
        model = self._registry.get(model_id)
        if not model:
            raise RuntimeError(f"Unknown voice model_id: {model_id}")

        self.current_model_id = model_id
        self.active_model_instance = model

    def initialize_model(self, model_id: str, *, init: bool = False) -> bool:
        model_id = self._resolve_model_id(model_id)
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
            logger.info(
                f"initialize_model start: model_id='{model_id}', "
                f"handler='{type(model).__name__}', init={bool(init)}"
            )
            ok = bool(model.initialize(init=init))
        except Exception as e:
            logger.error(f"initialize_model failed for {model_id}: {e}", exc_info=True)
            ok = False

        if ok:
            self.active_model_instance = model
            logger.info(
                f"initialize_model done: model_id='{model_id}', "
                f"handler='{type(model).__name__}', initialized_for='{getattr(model, 'initialized_for', None)}'"
            )
        else:
            logger.error(
                f"initialize_model returned False: model_id='{model_id}', "
                f"handler='{type(model).__name__}'"
            )
        return ok

    def change_voice_language(self, new_voice_language: str):
        self.voice_language = str(new_voice_language or "ru")
        if self.active_model_instance:
            try:
                self.active_model_instance.cleanup_state()
            except Exception:
                pass
        self.active_model_instance = None

    def shutdown(self) -> None:
        seen: set[int] = set()
        for model in self._registry.values():
            marker = id(model)
            if marker in seen:
                continue
            seen.add(marker)
            try:
                model.cleanup_state()
            except Exception as exc:
                logger.warning(f"Voice model cleanup failed for {type(model).__name__}: {exc}")

        self.active_model_instance = None
        self.current_model_id = None
        self.first_compiled = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def load_model_settings(self, model_id: str) -> Dict[str, Any]:
        try:
            settings_file = str(settings_path("voice_model_settings.json", create_parent=True))
            if os.path.exists(settings_file):
                import json
                with open(settings_file, "r", encoding="utf-8") as f:
                    all_settings = json.load(f)
                    return all_settings.get(model_id, {}) if isinstance(all_settings, dict) else {}
            return {}
        except Exception as e:
            logger.info(f"load_model_settings error for {model_id}: {e}")
            return {}

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
