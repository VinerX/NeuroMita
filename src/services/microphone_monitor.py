from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock, Thread
from uuid import uuid4

import numpy as np

from domain.audio_input import ASRInputDevice
from core.events import Events, get_event_bus
from handlers.asr_audio_devices import (
    normalize_device_name,
    portaudio_stream_scope,
    resolve_asr_input_device,
)
from main_logger import logger


class MonitorBuffer:
    """Bounded mono FIFO with continuous resampling between device clocks."""

    def __init__(self, input_rate: int, output_rate: int):
        self.ratio = input_rate / output_rate
        self.limit = max(2, int(input_rate * 0.12))
        self._samples = np.empty(0, dtype=np.float32)
        self._position = 0.0
        self._lock = Lock()

    def push(self, samples):
        with self._lock:
            self._samples = np.concatenate(
                (self._samples, np.asarray(samples, dtype=np.float32).reshape(-1))
            )
            if len(self._samples) > self.limit:
                self._samples = self._samples[-self.limit :]
                self._position = 0.0

    def read(self, frames: int):
        result = np.zeros(frames, dtype=np.float32)
        with self._lock:
            if len(self._samples) < 2:
                return result
            count = min(
                frames,
                max(
                    0,
                    int(
                        np.ceil((len(self._samples) - 1 - self._position) / self.ratio)
                    ),
                ),
            )
            if count:
                positions = self._position + np.arange(count) * self.ratio
                result[:count] = np.interp(
                    positions, np.arange(len(self._samples)), self._samples
                )
                position = self._position + count * self.ratio
                consumed = min(int(position), len(self._samples) - 1)
                self._samples = self._samples[consumed:]
                self._position = position - consumed
        return result


@dataclass(frozen=True, slots=True)
class MonitorState:
    phase: str = "stopped"
    device: ASRInputDevice | None = None
    level: float = 0.0
    error: str = ""


class MicrophoneMonitor:
    def __init__(self, audio_backend=None, event_bus=None):
        self._backend = audio_backend
        self._events = event_bus or get_event_bus()
        self._session_id = uuid4().hex
        self._lock = Lock()
        self._state = MonitorState()
        self._thread = None
        self._cancelled = Event()

    def snapshot(self):
        with self._lock:
            return self._state

    def start(self, device: ASRInputDevice):
        if self._thread is not None and self._thread.is_alive():
            return False
        self._cancelled = Event()
        with self._lock:
            self._state = MonitorState("starting", device)
        self._thread = Thread(
            target=self._run,
            args=(device, self._cancelled),
            name="microphone-monitor",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self):
        self._cancelled.set()
        with self._lock:
            if self._state.phase in {"starting", "listening"}:
                self._state = MonitorState("stopping", self._state.device)

    def close(self):
        self.stop()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self, device, cancelled):
        try:
            self._events.emit(
                Events.Speech.MICROPHONE_TEST_CHANGED,
                {"active": True, "session_id": self._session_id},
            )
            if self._backend is None:
                import sounddevice

                backend = sounddevice
            else:
                backend = self._backend
            with portaudio_stream_scope():
                if device.uid:
                    device = resolve_asr_input_device(
                        backend,
                        requested_index=device.index,
                        requested_name=None,
                        requested_uid=device.uid,
                        requested_backend=device.host_api,
                    )
                    if device is None:
                        raise RuntimeError("Selected input device is unavailable")
                info = backend.query_devices(device.index, "input")
                if not device.uid and normalize_device_name(
                    info["name"]
                ) != normalize_device_name(device.name):
                    raise RuntimeError(
                        "Selected input index now belongs to another device"
                    )
                output_info = backend.query_devices(kind="output")
                input_rate = int(round(info["default_samplerate"]))
                output_rate = int(round(output_info["default_samplerate"]))
                channels = min(2, int(output_info["max_output_channels"]))
                if channels < 1:
                    raise RuntimeError("No output channels available")
                buffer = MonitorBuffer(input_rate, output_rate)

                def capture(data, frames, time_info, status):
                    if cancelled.is_set():
                        return
                    mono = data[:, 0]
                    buffer.push(mono)
                    rms = float(np.sqrt(np.mean(np.square(mono)))) if len(mono) else 0.0
                    level = float(
                        np.clip((20 * np.log10(max(rms, 1e-6)) + 60) / 60, 0, 1)
                    )
                    with self._lock:
                        if not cancelled.is_set():
                            self._state = MonitorState("listening", device, level)

                def play(data, frames, time_info, status):
                    data.fill(0)
                    if not cancelled.is_set():
                        data[:] = buffer.read(frames)[:, None]

                if cancelled.is_set():
                    return
                with backend.InputStream(
                    device=device.index,
                    samplerate=input_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=max(1, input_rate // 100),
                    callback=capture,
                ) as input_stream:
                    if cancelled.is_set():
                        return
                    with backend.OutputStream(
                        samplerate=output_rate,
                        channels=channels,
                        dtype="float32",
                        blocksize=0,
                        latency="low",
                        callback=play,
                    ) as output_stream:
                        logger.info(
                            "[MicMonitor] Started; device=%d; name=%r; input_rate=%d; output_rate=%d",
                            device.index,
                            device.name,
                            input_rate,
                            output_rate,
                        )
                        while not cancelled.wait(0.05):
                            if not input_stream.active or not output_stream.active:
                                raise RuntimeError("Audio stream stopped unexpectedly")
        except Exception as exc:
            logger.warning(
                "[MicMonitor] Failed; device=%d; reason=%s", device.index, str(exc)
            )
            with self._lock:
                if not cancelled.is_set():
                    self._state = MonitorState(
                        "error",
                        device,
                        error="Не удалось запустить тест микрофона. Проверьте устройство ввода и вывод звука.",
                    )
        finally:
            self._events.emit(
                Events.Speech.MICROPHONE_TEST_CHANGED,
                {"active": False, "session_id": self._session_id},
            )
            with self._lock:
                if self._state.phase != "error" or cancelled.is_set():
                    self._state = MonitorState()
            logger.info("[MicMonitor] Stopped; device=%d", device.index)
