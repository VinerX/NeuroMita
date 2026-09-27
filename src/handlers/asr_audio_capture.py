from __future__ import annotations
from core.error_utils import format_exception

import asyncio
import re
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable

import numpy as np

from handlers.asr_audio_devices import refresh_portaudio_catalog


class AudioCaptureError(RuntimeError):
    """Raised when the selected input device cannot be opened or read."""


def _device_description(
    sounddevice,
    microphone_index: int,
) -> tuple[str | None, str | None, float | None]:
    try:
        device = sounddevice.query_devices(microphone_index)
    except Exception:
        return None, None, None

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

    try:
        default_sample_rate = float(device.get("default_samplerate"))
    except (TypeError, ValueError, AttributeError):
        default_sample_rate = None
    return device_name, host_api_name, default_sample_rate


def _capture_sample_rate(
    sounddevice,
    *,
    microphone_index: int,
    requested_sample_rate: int,
    default_sample_rate: float | None,
) -> int:
    """Choose a PortAudio rate, falling back to the endpoint's mix format."""

    checker = getattr(sounddevice, "check_input_settings", None)
    if not callable(checker):
        return int(requested_sample_rate)

    candidate_rates = [int(requested_sample_rate)]
    try:
        native_rate = int(round(float(default_sample_rate)))
    except (TypeError, ValueError):
        native_rate = 0
    if native_rate > 0 and native_rate not in candidate_rates:
        candidate_rates.append(native_rate)

    last_error: Exception | None = None
    for candidate_rate in candidate_rates:
        try:
            checker(
                device=int(microphone_index),
                channels=1,
                dtype="float32",
                samplerate=candidate_rate,
            )
            return candidate_rate
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return int(requested_sample_rate)


def _resample_audio_chunk(
    audio_chunk: np.ndarray,
    *,
    source_sample_rate: int,
    target_sample_rate: int,
    target_frames: int,
) -> np.ndarray:
    """Resample one mono capture block to the fixed VAD/ASR block size."""

    audio = np.asarray(audio_chunk, dtype=np.float32).reshape(-1)
    if len(audio) == target_frames and source_sample_rate == target_sample_rate:
        return audio.reshape(-1, 1)
    if len(audio) == 0:
        return np.zeros((target_frames, 1), dtype=np.float32)
    if len(audio) == 1:
        return np.full((target_frames, 1), audio[0], dtype=np.float32)

    if source_sample_rate % target_sample_rate == 0:
        integer_ratio = source_sample_rate // target_sample_rate
        if len(audio) == target_frames * integer_ratio:
            # Average before decimation so high-frequency microphone noise is
            # not folded straight into Whisper's speech band.
            return audio.reshape(target_frames, integer_ratio).mean(
                axis=1,
                dtype=np.float32,
            ).reshape(-1, 1)

    source_positions = np.arange(len(audio), dtype=np.float64)
    target_positions = np.linspace(
        0.0,
        float(len(audio) - 1),
        num=target_frames,
        dtype=np.float64,
    )
    resampled = np.interp(target_positions, source_positions, audio)
    return np.asarray(resampled, dtype=np.float32).reshape(-1, 1)


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
    silence_timeout: float = 0.6
    pre_buffer_duration: float = 0.4
    max_speech_duration: float = 30.0
    # Сегменты короче отбрасываем: на щелчках, кашле и одиночных чанках шума
    # Whisper уверенно галлюцинирует («Продолжение следует...» и подобное).
    min_speech_duration: float = 0.35


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
            raise AudioCaptureError(f"Не удалось загрузить sounddevice: {format_exception(exc)}") from exc

        # ASR worker может жить дольше подключённого микрофона. Обновляем его
        # собственный PortAudio-каталог перед открытием выбранного GUI индекса.
        refresh_portaudio_catalog(sd)
        device_name, host_api_name, default_sample_rate = _device_description(
            sd,
            microphone_index,
        )
        try:
            capture_sample_rate = _capture_sample_rate(
                sd,
                microphone_index=microphone_index,
                requested_sample_rate=config.sample_rate,
                default_sample_rate=default_sample_rate,
            )
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
        capture_chunk_size = max(
            1,
            round(config.chunk_size * capture_sample_rate / config.sample_rate),
        )

        # Округляем, а не отсекаем: при chunk=512/16 кГц (32 мс на чанк) усечение
        # превращало выставленные в настройках 0.15 с в 0.128 с — фактическое
        # поведение не совпадало со значением в UI.
        chunks_per_sec = config.sample_rate / config.chunk_size
        silence_chunks_needed = max(1, round(config.silence_timeout * chunks_per_sec))
        pre_buffer_size = max(0, round(config.pre_buffer_duration * chunks_per_sec))
        max_speech_chunks = max(1, round(config.max_speech_duration * chunks_per_sec))
        min_speech_chunks = max(0, round(config.min_speech_duration * chunks_per_sec))
        diagnostic_chunks_needed = max(1, round(10.0 * chunks_per_sec))
        pre_speech_buffer = deque(maxlen=pre_buffer_size) if pre_buffer_size else None
        speech_buffer: list[np.ndarray] = []
        speech_chunks = 0
        is_speaking = False
        silence_counter = 0
        overflow_count = 0
        diagnostic_chunks = 0
        diagnostic_sample_count = 0
        diagnostic_square_sum = 0.0
        diagnostic_peak = 0.0
        diagnostic_max_vad = 0.0
        loop = asyncio.get_running_loop()

        try:
            with sd.InputStream(
                samplerate=capture_sample_rate,
                channels=1,
                dtype="float32",
                blocksize=capture_chunk_size,
                device=microphone_index,
            ) as stream:
                self._logger.info(
                    f"Микрофон подключён: device={microphone_index}, "
                    f"input_sr={capture_sample_rate}, input_chunk={capture_chunk_size}, "
                    f"asr_sr={config.sample_rate}, asr_chunk={config.chunk_size}"
                )
                ready_reported = False
                while is_active():
                    try:
                        audio_chunk, overflowed = await loop.run_in_executor(
                            None, stream.read, capture_chunk_size
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
                                    sample_rate=capture_sample_rate,
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

                    if (
                        capture_sample_rate != config.sample_rate
                        or len(audio_chunk) != config.chunk_size
                    ):
                        audio_chunk = _resample_audio_chunk(
                            audio_chunk,
                            source_sample_rate=capture_sample_rate,
                            target_sample_rate=config.sample_rate,
                            target_frames=config.chunk_size,
                        )

                    probability = float(speech_probability(audio_chunk.reshape(-1), config.sample_rate))
                    if diagnostic_chunks < diagnostic_chunks_needed:
                        flat_chunk = audio_chunk.reshape(-1)
                        diagnostic_chunks += 1
                        diagnostic_sample_count += len(flat_chunk)
                        diagnostic_square_sum += float(
                            np.dot(flat_chunk.astype(np.float64), flat_chunk.astype(np.float64))
                        )
                        diagnostic_peak = max(
                            diagnostic_peak,
                            float(np.max(np.abs(flat_chunk), initial=0.0)),
                        )
                        diagnostic_max_vad = max(diagnostic_max_vad, probability)
                        if diagnostic_chunks == diagnostic_chunks_needed:
                            rms = (
                                diagnostic_square_sum / max(1, diagnostic_sample_count)
                            ) ** 0.5
                            self._logger.info(
                                "Проверка входа ASR за первые 10 с: "
                                f"device={microphone_index}, peak={diagnostic_peak:.6f}, "
                                f"rms={rms:.6f}, max_vad={diagnostic_max_vad:.3f}, "
                                f"threshold={config.vad_threshold:.3f}"
                            )
                    should_finalize = False
                    if probability > config.vad_threshold:
                        if not is_speaking:
                            is_speaking = True
                            speech_buffer.clear()
                            speech_chunks = 0
                            if pre_speech_buffer is not None:
                                speech_buffer.extend(pre_speech_buffer)
                        speech_buffer.append(audio_chunk)
                        speech_chunks += 1
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
                        too_short = speech_chunks < min_speech_chunks
                        speech_buffer.clear()
                        speech_chunks = 0
                        is_speaking = False
                        silence_counter = 0
                        # Предбуфер копил звук ДО этой реплики: если речь
                        # продолжится сразу, он подмешал бы в новый сегмент
                        # хвост уже отданного.
                        if pre_speech_buffer is not None:
                            pre_speech_buffer.clear()
                        if too_short:
                            continue
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
                    sample_rate=capture_sample_rate,
                )
            ) from exc
        finally:
            if overflow_count:
                self._logger.warning(f"Переполнений буфера аудиопотока: {overflow_count}")
