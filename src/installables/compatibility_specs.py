from __future__ import annotations


FISH_SPEECH_BACKEND = "cuda"

FISH_CUDA_COMPATIBILITY = {
    "supported_vendors": ["NVIDIA"],
    "rules": [],
}

FISH_TRITON_COMPATIBILITY = {
    "supported_vendors": ["NVIDIA"],
    "rules": [
        {
            "code": "triton_sm80_recommended",
            "effect": "not_recommended",
            "vendors": ["NVIDIA"],
            "minimum_compute_capability": 80,
            "tag": "RTX 30+",
            "tag_variant": "danger",
            "warning_ru": (
                "Компиляция Fish Speech через Triton рассчитана на NVIDIA с compute capability "
                "SM 8.0 или новее — это RTX 30xx, RTX 40xx, RTX 50xx и сопоставимые "
                "профессиональные модели. Установка разрешена, но на более старой архитектуре "
                "компиляция или запуск могут завершиться ошибкой."
            ),
            "warning_en": (
                "Fish Speech compilation through Triton is designed for NVIDIA GPUs with compute "
                "capability SM 8.0 or newer, including RTX 30xx, RTX 40xx, RTX 50xx and comparable "
                "professional models. Installation is allowed, but compilation or startup may fail "
                "on an older architecture."
            ),
        }
    ],
}

F5_CPU_FALLBACK_COMPATIBILITY = {
    "rules": [
        {
            "code": "cpu_fallback",
            "effect": "warning",
            "vendors": ["AMD", "INTEL", "CPU"],
            "warning_ru": "F5-TTS будет работать через CPU fallback и может быть заметно медленнее.",
            "warning_en": "F5-TTS will use its CPU fallback and may be noticeably slower.",
        }
    ]
}

F5_RVC_FALLBACK_COMPATIBILITY = {
    "rules": [
        {
            "code": "mixed_cpu_onnx_fallback",
            "effect": "warning",
            "vendors": ["AMD", "INTEL", "CPU"],
            "warning_ru": (
                "F5-TTS использует CPU fallback, а RVC — ONNX/DirectML; режим поддерживается, "
                "но работает медленнее."
            ),
            "warning_en": (
                "F5-TTS uses its CPU fallback while RVC uses ONNX/DirectML; this is supported but slower."
            ),
        }
    ]
}
