import asyncio
import os
import subprocess

from main_logger import logger


class AudioConverter:
    ffmpeg_path = os.path.join("ffmpeg.exe")
    default_timeout_sec = 600.0

    @staticmethod
    def _timeout_sec() -> float:
        raw_value = os.environ.get("NEUROMITA_FFMPEG_TIMEOUT_SEC", "")
        if not raw_value:
            return AudioConverter.default_timeout_sec
        try:
            return max(1.0, float(raw_value))
        except (TypeError, ValueError):
            logger.warning(
                f"Invalid NEUROMITA_FFMPEG_TIMEOUT_SEC={raw_value!r}; "
                f"using {AudioConverter.default_timeout_sec:.0f}s"
            )
            return AudioConverter.default_timeout_sec

    @staticmethod
    async def convert_to_wav(input_file, output_file):
        logger.info(f"Начинаю конвертацию {input_file} в {output_file} с помощью {AudioConverter.ffmpeg_path}")

        try:
            command = [
                AudioConverter.ffmpeg_path,
                '-i', input_file,
                '-f', 'wav',
                '-acodec', 'pcm_s16le',
                '-ar', '44100', # Стандартная частота дискретизации
                '-ac', '2', # Стерео
                '-q:a', '0', # Высокое качество
                '-threads', '4', # Используем многопоточность
                '-preset', 'ultrafast', # Самый быстрый пресет
                output_file,
                '-y'
            ]
            await asyncio.to_thread(
                subprocess.run,
                command,
                check=True,
                capture_output=True,
                timeout=AudioConverter._timeout_sec(),
            )
            return True
        except subprocess.TimeoutExpired as e:
            logger.error(
                f"FFmpeg conversion timed out after {e.timeout}s: "
                f"{input_file} -> {output_file}"
            )
            return False
        except subprocess.CalledProcessError as e:
            stderr = (
                e.stderr.decode(errors="replace")
                if isinstance(e.stderr, bytes)
                else str(e.stderr or "")
            )
            logger.error(f"Ошибка при конвертации аудио: {e}; stderr={stderr[-2000:]}")
            return False
        except FileNotFoundError:
            logger.error(f"FFmpeg executable not found: {AudioConverter.ffmpeg_path}")
            return False
