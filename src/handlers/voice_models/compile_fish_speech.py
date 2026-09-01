from __future__ import annotations

import argparse
import os
import site
import sys
from pathlib import Path

from core.torch_compile_runtime import configure_compile_environment


REFERENCE_TEXT = (
    "О боже! Ты меня напугал! Блин, моё сохранение! Не поняла... А где игра? "
    "Ты мне весь рут испоганил! Ну, чего тебе? Я Мила."
)

_DLL_DIRECTORY_HANDLES: list[object] = []


def _runtime_paths() -> list[str]:
    raw = os.environ.get("NEUROMITA_RUNTIME_PYTHON_PATHS") or os.environ.get(
        "PYTHONPATH", ""
    )
    return list(
        dict.fromkeys(
            os.path.abspath(path)
            for path in raw.split(os.pathsep)
            if str(path).strip()
        )
    )


def _activate_runtime_paths(paths: list[str]) -> None:
    configure_compile_environment(paths)
    normalized = {
        os.path.normcase(os.path.abspath(path))
        for path in paths
    }
    sys.path[:] = [
        path
        for path in sys.path
        if os.path.normcase(os.path.abspath(path or ".")) not in normalized
    ]
    sys.path[:0] = paths
    for root in paths:
        if os.path.isdir(root):
            site.addsitedir(root)

    if os.name != "nt":
        return
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if not callable(add_dll_directory):
        return
    for root in paths:
        for candidate in (root, os.path.join(root, "torch", "lib")):
            if not os.path.isdir(candidate):
                continue
            try:
                _DLL_DIRECTORY_HANDLES.append(add_dll_directory(candidate))
            except OSError:
                continue


def compile_fish_speech(reference_audio: str, *, device: str = "cuda") -> None:
    _activate_runtime_paths(_runtime_paths())

    import fish_speech_lib

    package_root = Path(fish_speech_lib.__file__).resolve().parent
    (package_root / ".project-root").touch(exist_ok=True)

    from fish_speech_lib.inference import FishSpeech

    print("Загрузка Fish Speech+ и компиляция CUDA-ядер…", flush=True)
    tts = FishSpeech(device=device, half=False, compile_model=True)
    tts(
        "Проверка компиляции.",
        reference_audio=str(Path(reference_audio).resolve()),
        reference_audio_text=REFERENCE_TEXT,
        max_new_tokens=64,
        chunk_length=64,
        use_memory_cache=False,
    )
    print("Компиляция Fish Speech+ завершена.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile Fish Speech+ kernels")
    parser.add_argument("--reference-audio", required=True)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    compile_fish_speech(args.reference_audio, device=args.device)


if __name__ == "__main__":
    main()
