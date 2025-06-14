import asyncio
import os
import threading

import pygame

from Logger import logger


class AudioHandler:
    _lock = threading.Lock()

    @classmethod
    async def handle_voice_file(cls, file_path, delete :bool = True):
        """Проигрывает звуковой файл (MP3 или OGG)."""
        try:
            logger.info(f"Проигрываю файл: {file_path}")
            await cls.play_audio_with_pygame(file_path)
            if os.path.exists(file_path) and delete:
                try:
                    await asyncio.sleep(0.02)
                    os.remove(file_path)
                    logger.info(f"Файл {file_path} удалён.")
                except Exception as e:
                    logger.info(f"Файл {file_path} НЕ удалён. Ошибка: {e}")
        except Exception as e:
            logger.info(f"Ошибка при воспроизведении файла: {e}")

    @classmethod
    async def play_audio_with_pygame(self, file_path):
        """Проигрывает аудиофайл."""

        def play():
            with AudioHandler._lock:
                pygame.mixer.init()
                pygame.mixer.music.load(file_path)  # Pygame поддерживает MP3 и OGG
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():  # Ждем завершения воспроизведения
                    pygame.time.Clock().tick(10)
                pygame.mixer.music.stop()
                pygame.mixer.quit()

        await asyncio.to_thread(play)  # Запуск в отдельном потоке