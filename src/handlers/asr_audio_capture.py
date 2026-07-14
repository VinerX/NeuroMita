from __future__ import annotations

import asyncio
import re
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable

import numpy as np


class AudioCaptureError(RuntimeError):
    """Raised when the selected input device cannot be opened or read."""


def _device_description(sounddevice, microphone_index: int) -> tuple[str | None, str | None]:
    try:
        device = sounddevice.query_devices(microphone_index)
    except Exception:
        return None, None

    try:
        device_name = str(device.get("name") or "").strip() or None
    except Exception:
        device_name = None

    try:
        host_api_index = int(device.get("hostapi"))
        host_api = sounddevice.query_hostapis(host_api_index)
        host_api_name = str(host_api.get("name") or "").strip() or None
    except Exception:
        host_api_name = None
    return device_name, host_api_name


def _describe_audio_capture_error(
    exc: BaseException,
    *,
    microphone_index: int,
    operation: str,
    device_name: str | None = None,
    host_api_name: str | None = None,
    sample_rate: int | None = None,
) -> str:
    raw = " ".join(str(exc or "unknown audio error").split())
    normalized = raw.casefold()
    host_api = str(host_api_name or "").strip()
    host_api_normalized = host_api.casefold()

    if "blocking api not supported" in normalized or (
        "wdm-ks" in normalized and "not supported" in normalized
    ):
        reason = (
            "аудиодрайвер Windows WDM-KS не поддерживает блокирующий режим захвата, "
            "который использует ASR"
        )
        recommendation = (
            "выберите вариант этого микрофона через Windows WASAPI, DirectSound или MME"
        )
    elif "invalid sample rate" in normalized or "-9997" in normalized:
        rate = f" {sample_rate} Гц" if sample_rate else ""
        reason = f"аудиоустройство не поддерживает частоту захвата{rate}"
        recommendation = "выберите другое устройство или поддерживаемую частоту дискретизации"
    elif "invalid number of channels" in normalized or "-9998" in normalized:
        reason = "аудиоустройство не поддерживает монофонический входной канал"
        recommendation = "выберите устройство с доступным входным каналом"
    elif "device unavailable" in normalized or "-9985" in normalized:
        reason = "аудиоустройство занято, отключено или недоступно в текущем сеансе Windows"
        recommendation = "закройте приложения, использующие микрофон, и проверьте устройство ввода"
    elif "invalid device" in normalized or "-9996" in normalized:
        reason = "выбранный идентификатор микрофона больше не существует в текущем сеансе Windows"
        recommendation = "обновите список микрофонов и выберите устройство заново"
    elif "permission" in normalized or "access denied" in normalized:
        reason = "Windows запретила приложению доступ к микрофону"
        recommendation = "разрешите доступ к микрофону в параметрах конфиденциальности Windows"
    elif "wdm-ks" in normalized or "wdm-ks" in host_api_normalized:
        reason = "аудиодрайвер Windows WDM-KS не смог открыть выбранный вход"
        recommendation = "выберите вариант устройства через WASAPI, DirectSound или MME"
    else:
        reason = "PortAudio не смог открыть аудиоустройство" if operation == "open" else "PortAudio потерял доступ к аудиоустройству"
        recommendation = "обновите список микрофонов и проверьте настройки устройства ввода"

    target = f"микрофон {microphone_index}"
    if device_name:
        target += f" «{device_name}»"
    action = "Не удалось открыть" if operation == "open" else "Не удалось читать"

    technical = []
    code_match = re.search(r"PaErrorCode\s*(-?\d+)", raw, flags=re.IGNORECASE)
    if code_match:
        technical.append(f"PortAudio {code_match.group(1)}")
    if host_api:
        technical.append(host_api)
    elif "wdm-ks" in normalized:
        technical.append("Windows WDM-KS")
    suffix = f" [{', '.join(dict.fromkeys(technical))}]" if technical else ""

    return f"{action} {target}: {reason}; {recommendation}.{suffix}"


@dataclass(frozen=True)
class AudioCaptureConfig:
    sample_rate: int = 16000
    chunk_size: int = 512
    vad_threshold: float = 0.5
    silence_timeout: float = 0.15
    pre_buffer_duration: float = 0.3
    max_speech_duration: float = 30.0


class AudioCaptureService:
    """Owns live microphone capture, VAD and speech-segment assembly."""

    def __init__(self, logger):
        self._logger = logger

    async def run(
        self,
        *,
        microphone_index: int,
        config: AudioCaptureConfig,
        is_active: Callable[[], bool],
        speech_probability: Callable[[np.ndarray, int], float],
        on_segment: Callable[[np.ndarray, int], Awaitable[None]],
        on_ready: Callable[[], None] | None = None,
    ) -> None:
        try:
            import sounddevice as sd
        except Exception as exc:
            raise AudioCaptureError(f"Не удалось загрузить sounddevice: {exc}") from exc

        device_name, host_api_name = _device_description(sd, microphone_index)

        silence_chunks_needed = max(1, int(config.silence_timeout * config.sample_rate / config.chunk_size))
        pre_buffer_size = max(0, int(config.pre_buffer_duration * config.sample_rate / config.chunk_size))
        max_speech_chunks = max(1, int(config.max_speech_duration * config.sample_rate / config.chunk_size))
        pre_speech_buffer = deque(maxlen=pre_buffer_size) if pre_buffer_size else None
        speech_buffer: list[np.ndarray] = []
        is_speaking = False
        silence_counter = 0
        overflow_count = 0
        loop = asyncio.get_running_loop()

        try:
            with sd.InputStream(
                samplerate=config.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=config.chunk_size,
                device=microphone_index,
            ) as stream:
                self._logger.info(
                    f"Микрофон подключён: device={microphone_index}, "
                    f"sr={config.sample_rate}, chunk={config.chunk_size}"
                )
                ready_reported = False
                while is_active():
                    try:
                        audio_chunk, overflowed = await loop.run_in_executor(
                            None, stream.read, config.chunk_size
                        )
                    except Exception as exc:
                        if is_active():
                            raise AudioCaptureError(
                                _describe_audio_capture_error(
                                    exc,
                                    microphone_index=microphone_index,
                                    operation="read",
                                    device_name=device_name,
                                    host_api_name=host_api_name,
                                    sample_rate=config.sample_rate,
                                )
                            ) from exc
                        break

                    if not ready_reported:
                        ready_reported = True
                        if on_ready is not None:
                            on_ready()

                    if overflowed:
                        overflow_count += 1
                        self._logger.warning("Переполнение буфера аудиопотока.")

                    probability = float(speech_probability(audio_chunk.reshape(-1), config.sample_rate))
                    should_finalize = False
                    if probability > config.vad_threshold:
                        if not is_speaking:
                            is_speaking = True
                            speech_buffer.clear()
                            if pre_speech_buffer is not None:
                                speech_buffer.extend(pre_speech_buffer)
                        speech_buffer.append(audio_chunk)
                        silence_counter = 0
                        should_finalize = len(speech_buffer) >= max_speech_chunks
                    elif is_speaking:
                        speech_buffer.append(audio_chunk)
                        silence_counter += 1
                        should_finalize = (
                            silence_counter >= silence_chunks_needed
                            or len(speech_buffer) >= max_speech_chunks
                        )
                    elif pre_speech_buffer is not None:
                        pre_speech_buffer.append(audio_chunk)

                    if should_finalize and speech_buffer:
                        audio = np.concatenate(speech_buffer).reshape(-1)
                        speech_buffer.clear()
                        is_speaking = False
                        silence_counter = 0
                        await on_segment(audio, config.sample_rate)
        except AudioCaptureError:
            raise
        except Exception as exc:
            raise AudioCaptureError(
                _describe_audio_capture_error(
                    exc,
                    microphone_index=microphone_index,
                    operation="open",
                    device_name=device_name,
                    host_api_name=host_api_name,
                    sample_rate=config.sample_rate,
                )
            ) from exc
        finally:
            if overflow_count:
                self._logger.warning(f"Переполнений буфера аудиопотока: {overflow_count}")
