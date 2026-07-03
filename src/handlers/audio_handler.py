import asyncio
import os
import tempfile
import threading

import pygame

from main_logger import logger


class AudioHandler:
    _lock = threading.Lock()

    @classmethod
    async def handle_voice_file(cls, file_path, delete: bool = True, volume: int = 100):
        """Проигрывает звуковой файл (MP3 или OGG).

        volume — громкость воспроизведения в процентах (100 = как есть).
        Значения выше 100 усиливают WAV-файл покадрово, т.к. громкость
        pygame ограничена сверху 1.0.
        """
        try:
            logger.info(f"Проигрываю файл: {file_path}")
            await cls.play_audio_with_pygame(file_path, volume)
            if os.path.exists(file_path) and delete:
                try:
                    await asyncio.sleep(0.02)
                    os.remove(file_path)
                    logger.info(f"Файл {file_path} удалён.")
                except Exception as e:
                    logger.info(f"Файл {file_path} НЕ удалён. Ошибка: {e}")
        except Exception as e:
            logger.info(f"Ошибка при воспроизведении файла: {e}")

    @staticmethod
    def _amplify_wav(path: str, gain: float) -> str | None:
        """Пишет усиленную копию WAV во временный файл, возвращает путь к ней.

        Нужен для громкости > 100%: pygame сам не умеет усиливать выше 1.0.
        При недоступности numpy/soundfile тихо возвращает None (откат на set_volume)."""
        try:
            import numpy as np
            import soundfile as sf

            data, sr = sf.read(path, dtype="float32")
            data = np.clip(data * gain, -1.0, 1.0)
            fd, tmp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            sf.write(tmp_path, data, sr)
            return tmp_path
        except Exception as e:
            logger.info(f"Не удалось усилить WAV (откат на set_volume): {e}")
            return None

    @classmethod
    async def play_audio_with_pygame(self, file_path, volume: int = 100):
        """Проигрывает аудиофайл с учётом громкости."""

        def play():
            with AudioHandler._lock:
                gain = max(0.0, float(volume) / 100.0)
                play_path = file_path
                temp_path = None
                mixer_volume = min(gain, 1.0)

                # Усиление выше 100% возможно только через перезапись сэмплов.
                if gain > 1.0 and str(file_path).lower().endswith(".wav"):
                    amplified = AudioHandler._amplify_wav(file_path, gain)
                    if amplified:
                        temp_path = amplified
                        play_path = amplified
                        mixer_volume = 1.0

                try:
                    pygame.mixer.init()
                    pygame.mixer.music.load(play_path)  # Pygame поддерживает MP3 и OGG
                    pygame.mixer.music.set_volume(mixer_volume)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():  # Ждем завершения воспроизведения
                        pygame.time.Clock().tick(10)
                    pygame.mixer.music.stop()
                    pygame.mixer.quit()
                finally:
                    if temp_path and os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass

        await asyncio.to_thread(play)  # Запуск в отдельном потоке
