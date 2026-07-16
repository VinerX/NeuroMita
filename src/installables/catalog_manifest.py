from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.installables.types import coerce_compatibility_spec
from installables.compatibility_specs import (
    F5_CPU_FALLBACK_COMPATIBILITY,
    F5_RVC_FALLBACK_COMPATIBILITY,
    FISH_CUDA_COMPATIBILITY,
    FISH_SPEECH_BACKEND,
    FISH_TRITON_COMPATIBILITY,
)


@dataclass(frozen=True, slots=True)
class InstallableCatalogEntry:
    id: str
    loader: str
    metadata_ru: dict[str, Any]
    metadata_en: dict[str, Any]

    @property
    def declared_backend(self) -> str:
        """Language-independent backend declared by the component manifest."""
        ru_backend = str(self.metadata_ru.get("backend") or "none").strip().lower()
        en_backend = str(self.metadata_en.get("backend") or "none").strip().lower()
        if ru_backend != en_backend:
            raise ValueError(f"Backend declaration differs between locales for {self.id}")
        return ru_backend

    @property
    def declared_compatibility(self) -> dict[str, Any]:
        ru_value = self.metadata_ru.get("compatibility") or {}
        en_value = self.metadata_en.get("compatibility") or {}
        if ru_value != en_value:
            raise ValueError(f"Compatibility declaration differs between locales for {self.id}")
        return coerce_compatibility_spec(ru_value).as_dict()


CATALOG_ENTRIES: tuple[InstallableCatalogEntry, ...] = (
    InstallableCatalogEntry(
        id='backend:cpu',
        loader='core.backends.installable_component:create_backend_installable_components',
        metadata_ru={'id': 'backend:cpu',
         'item_id': 'cpu',
         'category': 'backend',
         'title': 'PyTorch CPU',
         'description': 'Базовый runtime для CPU-моделей. CUDA runtime также поддерживает CPU-режим, поэтому отдельно устанавливать оба варианта не требуется.',
         'backend': 'cpu',
         'legacy_kind': 'backend',
         'tags': ['system', 'cpu'],
         'languages': [],
         'size': ''},
        metadata_en={'id': 'backend:cpu',
         'item_id': 'cpu',
         'category': 'backend',
         'title': 'PyTorch CPU',
         'description': 'Base runtime for CPU models. The CUDA runtime also supports CPU execution, so both variants do not need to be installed separately.',
         'backend': 'cpu',
         'legacy_kind': 'backend',
         'tags': ['system', 'cpu'],
         'languages': [],
         'size': ''},
    ),
    InstallableCatalogEntry(
        id='backend:cuda',
        loader='core.backends.installable_component:create_backend_installable_components',
        metadata_ru={'id': 'backend:cuda',
         'item_id': 'cuda',
         'category': 'backend',
         'title': 'PyTorch CUDA',
         'description': 'Основной runtime для NVIDIA. Может быть установлен одновременно с ONNX Runtime.',
         'backend': 'cuda',
         'legacy_kind': 'backend',
         'tags': ['system', 'cuda'],
         'languages': [],
         'size': ''},
        metadata_en={'id': 'backend:cuda',
         'item_id': 'cuda',
         'category': 'backend',
         'title': 'PyTorch CUDA',
         'description': 'Primary NVIDIA runtime. It can be installed alongside ONNX Runtime.',
         'backend': 'cuda',
         'legacy_kind': 'backend',
         'tags': ['system', 'cuda'],
         'languages': [],
         'size': ''},
    ),
    InstallableCatalogEntry(
        id='backend:onnx',
        loader='core.backends.installable_component:create_backend_installable_components',
        metadata_ru={'id': 'backend:onnx',
         'item_id': 'onnx',
         'category': 'backend',
         'title': 'ONNX Runtime',
         'description': 'DirectML на Windows для NVIDIA, AMD и Intel с CPU fallback. Устанавливается рядом с PyTorch и не удаляет его.',
         'backend': 'onnx',
         'legacy_kind': 'backend',
         'tags': ['system', 'onnx'],
         'languages': [],
         'size': ''},
        metadata_en={'id': 'backend:onnx',
         'item_id': 'onnx',
         'category': 'backend',
         'title': 'ONNX Runtime',
         'description': 'Uses DirectML on Windows for NVIDIA, AMD, and Intel with CPU fallback. Installs alongside PyTorch without removing it.',
         'backend': 'onnx',
         'legacy_kind': 'backend',
         'tags': ['system', 'onnx'],
         'languages': [],
         'size': ''},
    ),
    InstallableCatalogEntry(
        id='tts:edge_tts_rvc_cuda',
        loader='handlers.voice_models.edge_tts_rvc_model:EdgeTTSRVCCudaModel.create_installable_components',
        metadata_ru={'id': 'tts:edge_tts_rvc_cuda',
         'item_id': 'edge_tts_rvc_cuda',
         'category': 'tts',
         'title': 'Edge-TTS + RVC (CUDA)',
         'description': 'Edge-TTS с RVC через PyTorch/CUDA. Подходит для NVIDIA и поддерживает fp16.',
         'backend': 'cuda',
         'legacy_kind': 'voice',
         'tags': ['CUDA', 'Быстро', 'FP16'],
         'languages': ['Russian', 'English'],
         'size': '~3 GB'},
        metadata_en={'id': 'tts:edge_tts_rvc_cuda',
         'item_id': 'edge_tts_rvc_cuda',
         'category': 'tts',
         'title': 'Edge-TTS + RVC (CUDA)',
         'description': 'Edge-TTS with RVC through PyTorch/CUDA. Suitable for NVIDIA and supports fp16.',
         'backend': 'cuda',
         'legacy_kind': 'voice',
         'tags': ['CUDA', 'Fast', 'FP16'],
         'languages': ['Russian', 'English'],
         'size': '~3 GB'},
    ),
    InstallableCatalogEntry(
        id='tts:silero_rvc_cuda',
        loader='handlers.voice_models.edge_tts_rvc_model:EdgeTTSRVCCudaModel.create_installable_components',
        metadata_ru={'id': 'tts:silero_rvc_cuda',
         'item_id': 'silero_rvc_cuda',
         'category': 'tts',
         'title': 'Silero + RVC (CUDA)',
         'description': 'Silero генерирует речь локально, RVC работает через PyTorch/CUDA.',
         'backend': 'cuda',
         'legacy_kind': 'voice',
         'tags': ['CUDA', 'Локальный синтез', 'FP16'],
         'languages': ['Russian', 'English'],
         'size': '~3 GB'},
        metadata_en={'id': 'tts:silero_rvc_cuda',
         'item_id': 'silero_rvc_cuda',
         'category': 'tts',
         'title': 'Silero + RVC (CUDA)',
         'description': 'Silero generates speech locally, while RVC runs through PyTorch/CUDA.',
         'backend': 'cuda',
         'legacy_kind': 'voice',
         'tags': ['CUDA', 'Local synthesis', 'FP16'],
         'languages': ['Russian', 'English'],
         'size': '~3 GB'},
    ),
    InstallableCatalogEntry(
        id='tts:edge_tts_rvc_onnx',
        loader='handlers.voice_models.edge_tts_rvc_model:EdgeTTSRVCOnnxModel.create_installable_components',
        metadata_ru={'id': 'tts:edge_tts_rvc_onnx',
         'item_id': 'edge_tts_rvc_onnx',
         'category': 'tts',
         'title': 'Edge-TTS + RVC (ONNX)',
         'description': 'Edge-TTS с RVC через ONNX/DirectML на AMD, Intel и NVIDIA с CPU fallback. На NVIDIA рекомендуется CUDA-версия.',
         'backend': 'onnx',
         'legacy_kind': 'voice',
         'tags': ['ONNX', 'Стабильно'],
         'languages': ['Russian', 'English'],
         'size': '~3 GB'},
        metadata_en={'id': 'tts:edge_tts_rvc_onnx',
         'item_id': 'edge_tts_rvc_onnx',
         'category': 'tts',
         'title': 'Edge-TTS + RVC (ONNX)',
         'description': 'Edge-TTS with RVC through ONNX/DirectML on AMD, Intel, and NVIDIA with CPU fallback. The CUDA variant is recommended on NVIDIA.',
         'backend': 'onnx',
         'legacy_kind': 'voice',
         'tags': ['ONNX', 'Stable'],
         'languages': ['Russian', 'English'],
         'size': '~3 GB'},
    ),
    InstallableCatalogEntry(
        id='tts:silero_rvc_onnx',
        loader='handlers.voice_models.edge_tts_rvc_model:EdgeTTSRVCOnnxModel.create_installable_components',
        metadata_ru={'id': 'tts:silero_rvc_onnx',
         'item_id': 'silero_rvc_onnx',
         'category': 'tts',
         'title': 'Silero + RVC (ONNX)',
         'description': 'Silero + RVC через ONNX/DirectML на Windows с CPU fallback. На NVIDIA рекомендуется CUDA-версия.',
         'backend': 'onnx',
         'legacy_kind': 'voice',
         'tags': ['ONNX', 'Локальный синтез'],
         'languages': ['Russian', 'English'],
         'size': '~3 GB'},
        metadata_en={'id': 'tts:silero_rvc_onnx',
         'item_id': 'silero_rvc_onnx',
         'category': 'tts',
         'title': 'Silero + RVC (ONNX)',
         'description': 'Silero + RVC through ONNX/DirectML on Windows with CPU fallback. The CUDA variant is recommended on NVIDIA.',
         'backend': 'onnx',
         'legacy_kind': 'voice',
         'tags': ['ONNX', 'Local synthesis'],
         'languages': ['Russian', 'English'],
         'size': '~3 GB'},
    ),
    InstallableCatalogEntry(
        id='tts:medium',
        loader='handlers.voice_models.fish_speech_model:FishSpeechModel.create_installable_components',
        metadata_ru={'id': 'tts:medium',
         'item_id': 'medium',
         'category': 'tts',
         'title': 'Fish Speech',
         'description': 'Генерация речи хорошего качества. Требует больше ресурсов, чем быстрые модели.',
         'backend': FISH_SPEECH_BACKEND,
         'legacy_kind': 'voice',
         'tags': ['Качество', 'Сбалансировано'],
         'languages': ['Russian',
                       'English',
                       'Chinese',
                       'German',
                       'Japanese',
                       'French',
                       'Korean',
                       'Arabic',
                       'Dutch',
                       'Italian',
                       'Polish',
                       'Portuguese'],
         'size': '~5 GB',
         'compatibility': FISH_CUDA_COMPATIBILITY},
        metadata_en={'id': 'tts:medium',
         'item_id': 'medium',
         'category': 'tts',
         'title': 'Fish Speech',
         'description': 'High-quality speech generation. Requires more resources than fast models.',
         'backend': FISH_SPEECH_BACKEND,
         'legacy_kind': 'voice',
         'tags': ['Quality', 'Balanced'],
         'languages': ['Russian',
                       'English',
                       'Chinese',
                       'German',
                       'Japanese',
                       'French',
                       'Korean',
                       'Arabic',
                       'Dutch',
                       'Italian',
                       'Polish',
                       'Portuguese'],
         'size': '~5 GB',
         'compatibility': FISH_CUDA_COMPATIBILITY},
    ),
    InstallableCatalogEntry(
        id='tts:medium+',
        loader='handlers.voice_models.fish_speech_model:FishSpeechModel.create_installable_components',
        metadata_ru={'id': 'tts:medium+',
         'item_id': 'medium+',
         'category': 'tts',
         'title': 'Fish Speech+',
         'description': 'Версия Fish Speech, скомпилированная под GPU. Требует больше места и современную '
                        'NVIDIA.',
         'backend': FISH_SPEECH_BACKEND,
         'legacy_kind': 'voice',
         'tags': ['Качество', 'Triton'],
         'languages': ['Russian',
                       'English',
                       'Chinese',
                       'German',
                       'Japanese',
                       'French',
                       'Korean',
                       'Arabic',
                       'Dutch',
                       'Italian',
                       'Polish',
                       'Portuguese'],
         'size': '~10 GB',
         'compatibility': FISH_TRITON_COMPATIBILITY},
        metadata_en={'id': 'tts:medium+',
         'item_id': 'medium+',
         'category': 'tts',
         'title': 'Fish Speech+',
         'description': 'A GPU-compiled version of Fish Speech. Requires more disk space and a modern NVIDIA '
                        'GPU.',
         'backend': FISH_SPEECH_BACKEND,
         'legacy_kind': 'voice',
         'tags': ['Quality', 'Triton'],
         'languages': ['Russian',
                       'English',
                       'Chinese',
                       'German',
                       'Japanese',
                       'French',
                       'Korean',
                       'Arabic',
                       'Dutch',
                       'Italian',
                       'Polish',
                       'Portuguese'],
         'size': '~10 GB',
         'compatibility': FISH_TRITON_COMPATIBILITY},
    ),
    InstallableCatalogEntry(
        id='tts:medium+low',
        loader='handlers.voice_models.fish_speech_model:FishSpeechModel.create_installable_components',
        metadata_ru={'id': 'tts:medium+low',
         'item_id': 'medium+low',
         'category': 'tts',
         'title': 'Fish Speech+ + RVC',
         'description': 'Комбинация Fish Speech+ и RVC для высококачественного изменения тембра.',
         'backend': FISH_SPEECH_BACKEND,
         'legacy_kind': 'voice',
         'tags': ['Качество', 'Конверсия голоса'],
         'languages': ['Russian',
                       'English',
                       'Chinese',
                       'German',
                       'Japanese',
                       'French',
                       'Korean',
                       'Arabic',
                       'Dutch',
                       'Italian',
                       'Polish',
                       'Portuguese'],
         'size': '~15 GB',
         'compatibility': FISH_TRITON_COMPATIBILITY},
        metadata_en={'id': 'tts:medium+low',
         'item_id': 'medium+low',
         'category': 'tts',
         'title': 'Fish Speech+ + RVC',
         'description': 'Fish Speech+ combined with RVC for high-quality voice timbre conversion.',
         'backend': FISH_SPEECH_BACKEND,
         'legacy_kind': 'voice',
         'tags': ['Quality', 'Voice conversion'],
         'languages': ['Russian',
                       'English',
                       'Chinese',
                       'German',
                       'Japanese',
                       'French',
                       'Korean',
                       'Arabic',
                       'Dutch',
                       'Italian',
                       'Polish',
                       'Portuguese'],
         'size': '~15 GB',
         'compatibility': FISH_TRITON_COMPATIBILITY},
    ),
    InstallableCatalogEntry(
        id='tts:high',
        loader='handlers.voice_models.f5_tts_model:F5TTSModel.create_installable_components',
        metadata_ru={'id': 'tts:high',
         'item_id': 'high',
         'category': 'tts',
         'title': 'F5-TTS',
         'description': 'Эмоциональная диффузионная модель с высоким качеством. Самая требовательная к '
                        'GPU.',
         'backend': 'cpu',
         'legacy_kind': 'voice',
         'tags': ['Эмоции', 'Качество'],
         'languages': ['Russian', 'English'],
         'size': '~4 GB',
         'compatibility': F5_CPU_FALLBACK_COMPATIBILITY},
        metadata_en={'id': 'tts:high',
         'item_id': 'high',
         'category': 'tts',
         'title': 'F5-TTS',
         'description': 'A high-quality emotional diffusion model. The most demanding option for the GPU.',
         'backend': 'cpu',
         'legacy_kind': 'voice',
         'tags': ['Emotions', 'Quality'],
         'languages': ['Russian', 'English'],
         'size': '~4 GB',
         'compatibility': F5_CPU_FALLBACK_COMPATIBILITY},
    ),
    InstallableCatalogEntry(
        id='tts:high+low',
        loader='handlers.voice_models.f5_tts_model:F5TTSModel.create_installable_components',
        metadata_ru={'id': 'tts:high+low',
         'item_id': 'high+low',
         'category': 'tts',
         'title': 'F5-TTS + RVC',
         'description': 'F5‑TTS с последующей конверсией тембра через RVC.',
         'backend': 'cpu',
         'legacy_kind': 'voice',
         'tags': ['Эмоции', 'Конверсия голоса'],
         'languages': ['Russian', 'English'],
         'size': '~7 GB',
         'compatibility': F5_RVC_FALLBACK_COMPATIBILITY},
        metadata_en={'id': 'tts:high+low',
         'item_id': 'high+low',
         'category': 'tts',
         'title': 'F5-TTS + RVC',
         'description': 'F5-TTS followed by voice timbre conversion through RVC.',
         'backend': 'cpu',
         'legacy_kind': 'voice',
         'tags': ['Emotions', 'Voice conversion'],
         'languages': ['Russian', 'English'],
         'size': '~7 GB',
         'compatibility': F5_RVC_FALLBACK_COMPATIBILITY},
    ),
    InstallableCatalogEntry(
        id='asr:google',
        loader='handlers.asr_handler:SpeechRecognition.create_installable_components',
        metadata_ru={'id': 'asr:google',
         'item_id': 'google',
         'category': 'asr',
         'title': 'Google',
         'description': 'Онлайн-распознавание через SpeechRecognition (Google Web Speech API). Без '
                        'скачивания весов модели, но нужен интернет.',
         'backend': 'cpu',
         'legacy_kind': 'asr',
         'tags': ['Онлайн'],
         'languages': ['Russian', 'English'],
         'size': ''},
        metadata_en={'id': 'asr:google',
         'item_id': 'google',
         'category': 'asr',
         'title': 'Google',
         'description': 'Online speech recognition through SpeechRecognition (Google Web Speech API). No model '
                        'weights need to be downloaded, but an internet connection is required.',
         'backend': 'cpu',
         'legacy_kind': 'asr',
         'tags': ['Online'],
         'languages': ['Russian', 'English'],
         'size': ''},
    ),
    InstallableCatalogEntry(
        id='asr:gigaam',
        loader='handlers.asr_handler:SpeechRecognition.create_installable_components',
        metadata_ru={'id': 'asr:gigaam',
         'item_id': 'gigaam',
         'category': 'asr',
         'title': 'GigaAM',
         'description': 'Offline speech recognition based on GigaAM (PyTorch). Runs in current process.',
         'backend': 'cpu',
         'legacy_kind': 'asr',
         'tags': ['Local', 'No separate process'],
         'languages': ['Russian'],
         'size': ''},
        metadata_en={'id': 'asr:gigaam',
         'item_id': 'gigaam',
         'category': 'asr',
         'title': 'GigaAM',
         'description': 'Offline speech recognition based on GigaAM (PyTorch). Runs in current process.',
         'backend': 'cpu',
         'legacy_kind': 'asr',
         'tags': ['Local', 'No separate process'],
         'languages': ['Russian'],
         'size': ''},
    ),
    InstallableCatalogEntry(
        id='asr:gigaam_onnx',
        loader='handlers.asr_handler:SpeechRecognition.create_installable_components',
        metadata_ru={'id': 'asr:gigaam_onnx',
         'item_id': 'gigaam_onnx',
         'category': 'asr',
         'title': 'GigaAM ONNX',
         'description': 'Офлайн-распознавание речи на базе GigaAM через ONNXRuntime DirectML на Windows '
                        'с CPU fallback. Запускается в отдельном процессе.',
         'backend': 'onnx',
         'legacy_kind': 'asr',
         'tags': ['ONNX', 'Отдельный процесс', 'CPU/DirectML'],
         'languages': ['Russian'],
         'size': ''},
        metadata_en={'id': 'asr:gigaam_onnx',
         'item_id': 'gigaam_onnx',
         'category': 'asr',
         'title': 'GigaAM ONNX',
         'description': 'Offline speech recognition based on GigaAM through ONNXRuntime. Uses DirectML on '
                        'Windows with CPU fallback and runs in a separate process.',
         'backend': 'onnx',
         'legacy_kind': 'asr',
         'tags': ['ONNX', 'Separate process', 'CPU/DirectML'],
         'languages': ['Russian'],
         'size': ''},
    ),
    InstallableCatalogEntry(
        id='asr:whisper',
        loader='handlers.asr_handler:SpeechRecognition.create_installable_components',
        metadata_ru={'id': 'asr:whisper',
         'item_id': 'whisper',
         'category': 'asr',
         'title': 'Whisper Large v3 turbo',
         'description': 'Офлайн Whisper через faster-whisper (CTranslate2). Быстро работает на NVIDIA GPU '
                        '(CUDA), на CPU тоже поддерживается. Требует скачивания модели в локальный кэш.',
         'backend': 'cpu',
         'legacy_kind': 'asr',
         'tags': ['Офлайн', 'Локально'],
         'languages': ['Multilingual'],
         'size': ''},
        metadata_en={'id': 'asr:whisper',
         'item_id': 'whisper',
         'category': 'asr',
         'title': 'Whisper Large v3 turbo',
         'description': 'Offline Whisper through faster-whisper (CTranslate2). Runs quickly on NVIDIA GPUs '
                        '(CUDA) and also supports CPU. Requires downloading the model to a local cache.',
         'backend': 'cpu',
         'legacy_kind': 'asr',
         'tags': ['Offline', 'Local'],
         'languages': ['Multilingual'],
         'size': ''},
    ),
    InstallableCatalogEntry(
        id='asr:whisper_onnx',
        loader='handlers.asr_handler:SpeechRecognition.create_installable_components',
        metadata_ru={'id': 'asr:whisper_onnx',
         'item_id': 'whisper_onnx',
         'category': 'asr',
         'title': 'Whisper Large v3 turbo (ONNX)',
         'description': 'Офлайн Whisper в формате ONNX. Использует DirectML на Windows для AMD, Intel и NVIDIA '
                        'с CPU fallback. Модель и файлы transformers скачиваются локально.',
         'backend': 'onnx',
         'legacy_kind': 'asr',
         'tags': ['Локально', 'ONNX'],
         'languages': ['Multilingual'],
         'size': ''},
        metadata_en={'id': 'asr:whisper_onnx',
         'item_id': 'whisper_onnx',
         'category': 'asr',
         'title': 'Whisper Large v3 turbo (ONNX)',
         'description': 'Offline Whisper in ONNX format. Uses DirectML on Windows for AMD, Intel, and NVIDIA '
                        'with CPU fallback. The model and Transformers files are downloaded locally.',
         'backend': 'onnx',
         'legacy_kind': 'asr',
         'tags': ['Local', 'ONNX'],
         'languages': ['Multilingual'],
         'size': ''},
    ),
    # RAG embeddings/reranker выводятся ОТДЕЛЬНОЙ карточкой на каждую модель
    # пресета — они генерируются динамически из пресетов ниже (см.
    # _rag_model_catalog_entries), чтобы заголовок карточки и реально
    # скачиваемая модель не расходились.
    InstallableCatalogEntry(
        id='beats:beat_this',
        loader='game_connections.services.beat_install:create_beat_installable_components',
        metadata_ru={'id': 'beats:beat_this',
         'item_id': 'beat_this',
         'category': 'beats',
         'title': 'Beat This',
         'description': 'Neural beat synchronization backend.',
         'backend': 'cpu',
         'legacy_kind': 'beats',
         'tags': ['beat'],
         'languages': [],
         'size': ''},
        metadata_en={'id': 'beats:beat_this',
         'item_id': 'beat_this',
         'category': 'beats',
         'title': 'Beat This',
         'description': 'Neural beat synchronization backend.',
         'backend': 'cpu',
         'legacy_kind': 'beats',
         'tags': ['beat'],
         'languages': [],
         'size': ''},
    ),
    InstallableCatalogEntry(
        id='dependency:ffmpeg',
        loader='installables.ffmpeg_component:create_ffmpeg_installable_components',
        metadata_ru={'id': 'dependency:ffmpeg',
         'item_id': 'ffmpeg',
         'category': 'dependency',
         'title': 'FFmpeg',
         'description': 'Утилита обработки аудио/видео. Нужна для локальной озвучки (RVC) и работы с '
                        'медиа. Скачивается автоматически.',
         'backend': 'none',
         'legacy_kind': 'deps',
         'tags': ['system', 'ffmpeg'],
         'languages': [],
         'size': '~120 MB'},
        metadata_en={'id': 'dependency:ffmpeg',
         'item_id': 'ffmpeg',
         'category': 'dependency',
         'title': 'FFmpeg',
         'description': 'Audio/video processing tool. Needed for local voiceover (RVC) and media handling. '
                        'Downloaded automatically.',
         'backend': 'none',
         'legacy_kind': 'deps',
         'tags': ['system', 'ffmpeg'],
         'languages': [],
         'size': '~120 MB'},
    ),
    InstallableCatalogEntry(
        id='dependency:opencv',
        loader='installables.opencv_component:create_opencv_installable_components',
        metadata_ru={'id': 'dependency:opencv',
         'item_id': 'opencv',
         'category': 'dependency',
         'title': 'OpenCV',
         'description': 'Библиотека компьютерного зрения (cv2). Нужна для работы камеры — захвата кадров и '
                        'выбора устройства в настройках.',
         'backend': 'none',
         'legacy_kind': 'deps',
         'tags': ['system', 'camera', 'opencv'],
         'languages': [],
         'size': '~40 MB'},
        metadata_en={'id': 'dependency:opencv',
         'item_id': 'opencv',
         'category': 'dependency',
         'title': 'OpenCV',
         'description': 'Computer-vision library (cv2). Needed for the camera — frame capture and device '
                        'selection in settings.',
         'backend': 'none',
         'legacy_kind': 'deps',
         'tags': ['system', 'camera', 'opencv'],
         'languages': [],
         'size': '~40 MB'},
    ),
    InstallableCatalogEntry(
        id='voices:all',
        loader='installables.voice_assets:create_voice_asset_installable_components',
        metadata_ru={'id': 'voices:all',
         'item_id': 'all',
         'category': 'voices',
         'title': 'Все голоса Мит',
         'description': 'Скачать голосовые модели всех персонажей разом. Уже установленные пропускаются.',
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'bundle', 'all'],
         'languages': [],
         'size': 'несколько ГБ'},
        metadata_en={'id': 'voices:all',
         'item_id': 'all',
         'category': 'voices',
         'title': 'All Mita voices',
         'description': "Download every character's voice model at once. Already installed voices are "
                        'skipped.',
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'bundle', 'all'],
         'languages': [],
         'size': 'several GB'},
    ),
    InstallableCatalogEntry(
        id='voices:CrazyMita',
        loader='installables.voice_assets:create_voice_asset_installable_components',
        metadata_ru={'id': 'voices:CrazyMita',
         'item_id': 'CrazyMita',
         'category': 'voices',
         'title': 'Crazy Mita',
         'description': 'Голосовая модель персонажа для локальной озвучки (RVC/F5). Нужна, чтобы движок '
                        'озвучки говорил голосом этой Миты.',
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'crazymita'],
         'languages': [],
         'size': '~250 MB'},
        metadata_en={'id': 'voices:CrazyMita',
         'item_id': 'CrazyMita',
         'category': 'voices',
         'title': 'Crazy Mita',
         'description': 'Character voice model for local voiceover (RVC/F5). Required for the TTS engine '
                        "to speak in this Mita's voice.",
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'crazymita'],
         'languages': [],
         'size': '~250 MB'},
    ),
    InstallableCatalogEntry(
        id='voices:MitaKind',
        loader='installables.voice_assets:create_voice_asset_installable_components',
        metadata_ru={'id': 'voices:MitaKind',
         'item_id': 'MitaKind',
         'category': 'voices',
         'title': 'Kind Mita',
         'description': 'Голосовая модель персонажа для локальной озвучки (RVC/F5). Нужна, чтобы движок '
                        'озвучки говорил голосом этой Миты.',
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'mitakind'],
         'languages': [],
         'size': '~230 MB'},
        metadata_en={'id': 'voices:MitaKind',
         'item_id': 'MitaKind',
         'category': 'voices',
         'title': 'Kind Mita',
         'description': 'Character voice model for local voiceover (RVC/F5). Required for the TTS engine '
                        "to speak in this Mita's voice.",
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'mitakind'],
         'languages': [],
         'size': '~230 MB'},
    ),
    InstallableCatalogEntry(
        id='voices:CappieMita',
        loader='installables.voice_assets:create_voice_asset_installable_components',
        metadata_ru={'id': 'voices:CappieMita',
         'item_id': 'CappieMita',
         'category': 'voices',
         'title': 'Cappie Mita',
         'description': 'Голосовая модель персонажа для локальной озвучки (RVC/F5). Нужна, чтобы движок '
                        'озвучки говорил голосом этой Миты.',
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'cappiemita'],
         'languages': [],
         'size': '~250 MB'},
        metadata_en={'id': 'voices:CappieMita',
         'item_id': 'CappieMita',
         'category': 'voices',
         'title': 'Cappie Mita',
         'description': 'Character voice model for local voiceover (RVC/F5). Required for the TTS engine '
                        "to speak in this Mita's voice.",
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'cappiemita'],
         'languages': [],
         'size': '~250 MB'},
    ),
    InstallableCatalogEntry(
        id='voices:Mila',
        loader='installables.voice_assets:create_voice_asset_installable_components',
        metadata_ru={'id': 'voices:Mila',
         'item_id': 'Mila',
         'category': 'voices',
         'title': 'Mila',
         'description': 'Голосовая модель персонажа для локальной озвучки (RVC/F5). Нужна, чтобы движок '
                        'озвучки говорил голосом этой Миты.',
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'mila'],
         'languages': [],
         'size': '~230 MB'},
        metadata_en={'id': 'voices:Mila',
         'item_id': 'Mila',
         'category': 'voices',
         'title': 'Mila',
         'description': 'Character voice model for local voiceover (RVC/F5). Required for the TTS engine '
                        "to speak in this Mita's voice.",
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'mila'],
         'languages': [],
         'size': '~230 MB'},
    ),
    InstallableCatalogEntry(
        id='voices:ShorthairMita',
        loader='installables.voice_assets:create_voice_asset_installable_components',
        metadata_ru={'id': 'voices:ShorthairMita',
         'item_id': 'ShorthairMita',
         'category': 'voices',
         'title': 'Shorthair Mita',
         'description': 'Голосовая модель персонажа для локальной озвучки (RVC/F5). Нужна, чтобы движок '
                        'озвучки говорил голосом этой Миты.',
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'shorthairmita'],
         'languages': [],
         'size': '~170 MB'},
        metadata_en={'id': 'voices:ShorthairMita',
         'item_id': 'ShorthairMita',
         'category': 'voices',
         'title': 'Shorthair Mita',
         'description': 'Character voice model for local voiceover (RVC/F5). Required for the TTS engine '
                        "to speak in this Mita's voice.",
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'shorthairmita'],
         'languages': [],
         'size': '~170 MB'},
    ),
    InstallableCatalogEntry(
        id='voices:SleepyMita',
        loader='installables.voice_assets:create_voice_asset_installable_components',
        metadata_ru={'id': 'voices:SleepyMita',
         'item_id': 'SleepyMita',
         'category': 'voices',
         'title': 'Sleepy Mita',
         'description': 'Голосовая модель персонажа для локальной озвучки (RVC/F5). Нужна, чтобы движок '
                        'озвучки говорил голосом этой Миты.',
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'sleepymita'],
         'languages': [],
         'size': '~170 MB'},
        metadata_en={'id': 'voices:SleepyMita',
         'item_id': 'SleepyMita',
         'category': 'voices',
         'title': 'Sleepy Mita',
         'description': 'Character voice model for local voiceover (RVC/F5). Required for the TTS engine '
                        "to speak in this Mita's voice.",
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'sleepymita'],
         'languages': [],
         'size': '~170 MB'},
    ),
    InstallableCatalogEntry(
        id='voices:GhostMita',
        loader='installables.voice_assets:create_voice_asset_installable_components',
        metadata_ru={'id': 'voices:GhostMita',
         'item_id': 'GhostMita',
         'category': 'voices',
         'title': 'Ghost Mita',
         'description': 'Голосовая модель персонажа для локальной озвучки (RVC/F5). Нужна, чтобы движок '
                        'озвучки говорил голосом этой Миты.',
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'ghostmita'],
         'languages': [],
         'size': '~190 MB'},
        metadata_en={'id': 'voices:GhostMita',
         'item_id': 'GhostMita',
         'category': 'voices',
         'title': 'Ghost Mita',
         'description': 'Character voice model for local voiceover (RVC/F5). Required for the TTS engine '
                        "to speak in this Mita's voice.",
         'backend': 'none',
         'legacy_kind': 'voices',
         'tags': ['voice', 'rvc', 'f5', 'ghostmita'],
         'languages': [],
         'size': '~190 MB'},
    ),
)

_RAG_LOADER = 'managers.rag.install_spec:create_rag_installable_components'


def _rag_model_catalog_entries() -> tuple[InstallableCatalogEntry, ...]:
    """Карточки конкретных RAG-моделей, построенные из пресетов.

    Источник правды — те же пресеты, что и в настройках RAG, поэтому список
    карточек всегда соответствует реально устанавливаемым моделям. Если пресеты
    почему-то не читаются, возвращаем пустой набор — каталог остальных
    компонентов от этого не ломается.
    """
    try:
        from managers.rag.model_catalog import all_model_specs
    except Exception:
        return ()

    entries: list[InstallableCatalogEntry] = []
    try:
        for spec in all_model_specs():
            meta = {
                'id': spec['id'],
                'item_id': spec['kind'],
                'category': 'rag',
                'title': spec['hf_id'],
                'description': spec['display'],
                'backend': 'cpu',
                'legacy_kind': 'rag',
                'tags': ['rag', spec['kind']],
                'languages': [],
                'size': '',
            }
            entries.append(
                InstallableCatalogEntry(
                    id=spec['id'],
                    loader=_RAG_LOADER,
                    metadata_ru=dict(meta),
                    metadata_en=dict(meta),
                )
            )
    except Exception:
        return ()
    return tuple(entries)


def _rag_aggregate_catalog_entries() -> tuple[InstallableCatalogEntry, ...]:
    """Агрегатные RAG-компоненты — только для lookup (не показываются в сетке).

    Используются settings-driven установкой АКТИВНОЙ (в т.ч. кастомной) модели
    через start_install(); заголовок резолвится вживую из настроек RAG.
    """
    out: list[InstallableCatalogEntry] = []
    for item_id, title in (('embeddings', 'RAG embeddings'), ('reranker', 'RAG reranker')):
        meta = {
            'id': f'rag:{item_id}',
            'item_id': item_id,
            'category': 'rag',
            'title': title,
            'description': 'Local RAG model artifacts.',
            'backend': 'cpu',
            'legacy_kind': 'rag',
            'tags': ['rag'],
            'languages': [],
            'size': '',
        }
        out.append(
            InstallableCatalogEntry(
                id=f'rag:{item_id}',
                loader=_RAG_LOADER,
                metadata_ru=dict(meta),
                metadata_en=dict(meta),
            )
        )
    return tuple(out)


def _rag_custom_catalog_entries() -> tuple[InstallableCatalogEntry, ...]:
    """Живые карточки для активной КАСТОМНОЙ модели (нет в пресетах).

    Пересчитываются на каждый запрос каталога (resolve_full_config кэширован),
    чтобы карточка появлялась сразу после выбора кастомной модели в настройках
    RAG. Пресетные модели сюда не попадают (у них уже есть статичная карточка).
    """
    try:
        from managers.rag.model_catalog import custom_active_model_specs

        specs = custom_active_model_specs()
    except Exception:
        return ()

    entries: list[InstallableCatalogEntry] = []
    for spec in specs:
        if spec["id"] in _BASE_BY_ID:
            continue
        meta = {
            'id': spec['id'],
            'item_id': spec['kind'],
            'category': 'rag',
            'title': spec['hf_id'],
            'description': spec['display'],
            'backend': 'cpu',
            'legacy_kind': 'rag',
            'tags': ['rag', spec['kind'], 'custom'],
            'languages': [],
            'size': '',
        }
        entries.append(
            InstallableCatalogEntry(
                id=spec['id'],
                loader=_RAG_LOADER,
                metadata_ru=dict(meta),
                metadata_en=dict(meta),
            )
        )
    return tuple(entries)


# Статичная часть каталога (не-RAG + карточки RAG-моделей из пресетов) считается
# один раз. Карточка активной кастомной модели добавляется вживую поверх неё.
_BASE_ENTRIES: tuple[InstallableCatalogEntry, ...] = CATALOG_ENTRIES + _rag_model_catalog_entries()
_BASE_BY_ID: dict[str, InstallableCatalogEntry] = {entry.id: entry for entry in _BASE_ENTRIES}
for _entry in _rag_aggregate_catalog_entries():
    _BASE_BY_ID.setdefault(_entry.id, _entry)


def catalog_entries() -> tuple[InstallableCatalogEntry, ...]:
    """Полный каталог для сетки AI Hub (со свежей кастомной карточкой)."""
    return _BASE_ENTRIES + _rag_custom_catalog_entries()


def catalog_by_id() -> dict[str, InstallableCatalogEntry]:
    """Индекс по id для require_component (включая агрегаты и кастом)."""
    custom = _rag_custom_catalog_entries()
    if not custom:
        return _BASE_BY_ID
    merged = dict(_BASE_BY_ID)
    for entry in custom:
        merged.setdefault(entry.id, entry)
    return merged


# Обратная совместимость: снапшот на момент импорта (без кастомной карточки).
# Новый код должен звать catalog_entries()/catalog_by_id() для живого списка.
CATALOG_ENTRIES = _BASE_ENTRIES
CATALOG_BY_ID = _BASE_BY_ID


def entries_for_category(category: str | None = None) -> tuple[InstallableCatalogEntry, ...]:
    entries = catalog_entries()
    if not category:
        return entries
    target = str(category).strip().lower()
    return tuple(
        entry for entry in entries
        if str(entry.metadata_ru.get("category") or "").strip().lower() == target
    )
