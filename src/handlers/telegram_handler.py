from telethon import TelegramClient, events
import os
import sys
import time
import random
import asyncio

from telethon.tl.types import MessageMediaDocument, DocumentAttributeAudio
from telethon.errors import SessionPasswordNeededError

from utils.audio_converter import AudioConverter
from handlers.audio_handler import AudioHandler
from main_logger import logger
from utils import SH
import platform
from core.events import get_event_bus, Events


class TelegramBotHandler:
    def __init__(self, api_id, api_hash, phone, tg_bot, message_limit_per_minute=20):
        self.event_bus = get_event_bus()

        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.tg_bot = tg_bot

        self.last_speaker_command = ""
        self._last_speaker_command_norm = ""
        self.last_send_time = -1.0

        settings_result = self.event_bus.emit_and_wait(Events.Settings.GET_SETTINGS, timeout=1.0)
        settings = settings_result[0] if settings_result else {}
        try:
            self.silero_time_limit = int(settings.get("SILERO_TIME", "10"))
        except Exception:
            self.silero_time_limit = 10
        if not hasattr(self, "silero_time_limit") or self.silero_time_limit is None:
            self.silero_time_limit = 10

        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(sys.executable)
            alt_base_dir = getattr(sys, "_MEIPASS", base_dir)
        else:
            base_dir = os.path.dirname(__file__)
            alt_base_dir = base_dir

        ffmpeg_rel_path = os.path.join("ffmpeg-7.1-essentials_build", "bin", "ffmpeg.exe")
        ffmpeg_path = os.path.join(base_dir, ffmpeg_rel_path)
        if not os.path.exists(ffmpeg_path):
            ffmpeg_path = os.path.join(alt_base_dir, ffmpeg_rel_path)
        self.ffmpeg_path = ffmpeg_path

        device_model = platform.node()
        system_version = f"{platform.system()} {platform.release()}"
        app_version = "1.0.0"

        self.message_limit_per_minute = int(message_limit_per_minute or 20)
        self.message_count = 0
        self.start_time = time.time()

        self.client = None
        try:
            self.client = TelegramClient(
                "session_name",
                int(self.api_id),
                self.api_hash,
                device_model=device_model,
                system_version=system_version,
                app_version=app_version,
            )
        except Exception as e:
            logger.info(f"Проблема в ините тг: {e}")
            logger.info(SH(self.api_id))
            logger.info(SH(self.api_hash))

    def reset_message_count(self):
        if time.time() - self.start_time > 60:
            self.message_count = 0
            self.start_time = time.time()

    def _norm_cmd(self, s: str) -> str:
        return " ".join(str(s or "").strip().lower().split())

    async def _wait_rate_window_if_needed(self):
        self.reset_message_count()
        if self.message_count < self.message_limit_per_minute:
            return

        now = time.time()
        remain = (self.start_time + 60.0) - now
        if remain < 0:
            remain = 0.0
        jitter = random.uniform(0.5, 1.5)
        sleep_for = remain + jitter
        logger.warning(f"Telegram rate limit: waiting {sleep_for:.1f}s to avoid spamming bot")
        await asyncio.sleep(sleep_for)
        self.reset_message_count()

    async def _sleep_between_messages(self, min_gap: float = 1.5):
        now = time.time()
        if self.last_send_time > 0:
            dt = now - self.last_send_time
            if dt < min_gap:
                await asyncio.sleep(min_gap - dt)

    async def _safe_send_message(self, text: str, *, min_gap: float = 1.5, count: bool = True):
        if not self.client:
            raise RuntimeError("Telegram client not initialized")

        await self._wait_rate_window_if_needed()
        await self._sleep_between_messages(min_gap=min_gap)

        await self.client.send_message(self.tg_bot, text)

        self.last_send_time = time.time()
        if count:
            self.message_count += 1

    async def _get_last_chat_message_id(self) -> int:
        if not self.client:
            return 0
        try:
            msg = await self.getLastMessage()
            if msg and hasattr(msg, "id"):
                return int(msg.id)
        except Exception:
            pass
        return 0

    async def send_and_receive(
        self,
        input_message,
        speaker_command,
        message_id,
        voice_future: asyncio.Future | None = None,
    ):
        if not input_message or not speaker_command:
            return None
        if not self.client:
            raise RuntimeError("Telegram client not initialized")

        speaker_command = str(speaker_command or "").strip()
        input_message = str(input_message or "").strip()
        if not input_message or not speaker_command:
            return None

        logger.info(f"Telegram voice request → {self.tg_bot}: {speaker_command} {input_message[:64]}...")

        base_id = await self._get_last_chat_message_id()

        # Speaker command: avoid resending if effectively same
        cmd_norm = self._norm_cmd(speaker_command)
        if cmd_norm and cmd_norm != self._last_speaker_command_norm:
            await self._safe_send_message(speaker_command, min_gap=1.5, count=True)
            self.last_speaker_command = speaker_command
            self._last_speaker_command_norm = cmd_norm
            await asyncio.sleep(0.5)

        # Some bots require prefix command
        if self.tg_bot == "@CrazyMitaAIbot":
            input_message = f"/voice {input_message}"

        await self._safe_send_message(input_message, min_gap=1.5, count=True)

        logger.debug("Ожидание ответа от бота (audio)...")

        response = None
        attempts = 0
        attempts_per_second = 3
        attempts_max = int(self.silero_time_limit * attempts_per_second)

        await asyncio.sleep(0.5)

        while attempts <= attempts_max:
            try:
                # Only look for messages newer than base_id to avoid grabbing old audio
                async for message in self.client.iter_messages(self.tg_bot, limit=5, min_id=base_id):
                    if getattr(message, "out", False):
                        continue
                    if getattr(message, "id", 0) <= base_id:
                        continue
                    if message.media and isinstance(message.media, MessageMediaDocument):
                        doc = message.media.document
                        mime = getattr(doc, "mime_type", "") or ""
                        attrs = getattr(doc, "attributes", []) or []
                        is_voice_ogg = ("audio/ogg" in mime) and any(
                            isinstance(attr, DocumentAttributeAudio) and getattr(attr, "voice", False) for attr in attrs
                        )
                        is_mp3 = "audio/mpeg" in mime
                        if is_mp3 or is_voice_ogg:
                            response = message
                            break
            except Exception:
                response = None

            if response:
                break

            # Reduce log spam: only debug occasionally
            if attempts % 6 == 0:
                logger.debug(f"Waiting bot audio... attempt {attempts + 1}/{attempts_max}")

            attempts += 1
            await asyncio.sleep(1 / attempts_per_second)

        if not response:
            logger.info(f"Ответ от бота не получен (timeout={self.silero_time_limit}s)")
            return None

        logger.info("Ответ (audio) получен")

        path_to_file: str | None = None

        if response.media and isinstance(response.media, MessageMediaDocument):
            temp_dir = os.path.join(os.getcwd(), "temp")
            os.makedirs(temp_dir, exist_ok=True)
            file_path = await self.client.download_media(response.media, file=temp_dir)
            logger.info(f"Файл загружен: {file_path}")

            # Wait for file to stabilize
            start_time = time.time()
            last_size = -1
            while True:
                try:
                    if os.path.exists(file_path):
                        size = os.path.getsize(file_path)
                        if size > 0 and size == last_size:
                            break
                        last_size = size
                except OSError:
                    pass
                if time.time() - start_time > 10.0:
                    break
                await asyncio.sleep(0.1)

            sound_absolute_path = os.path.abspath(file_path)

            # Check game connection status via event bus
            connection_result = await asyncio.get_event_loop().run_in_executor(
                None,
                self.event_bus.emit_and_wait,
                Events.Server.GET_GAME_CONNECTION,
                {},
                1.0
            )
            connected_to_game = connection_result[0] if connection_result else False

            if connected_to_game:
                logger.info("Подключен к игре, нужна конвертация")
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                wav_path = os.path.join(os.path.dirname(file_path), f"{base_name}.wav")
                absolute_wav_path = os.path.abspath(wav_path)

                await AudioConverter.convert_to_wav(sound_absolute_path, absolute_wav_path)

                try:
                    os.remove(sound_absolute_path)
                except OSError as remove_error:
                    logger.info(f"Ошибка при удалении файла {sound_absolute_path}: {remove_error}")

                self.event_bus.emit(Events.Server.SET_PATCH_TO_SOUND_FILE, absolute_wav_path)
                self.event_bus.emit_and_wait(Events.Server.SET_ID_SOUND, {'id': message_id})

                path_to_file = absolute_wav_path
            else:
                path_to_file = sound_absolute_path
                await AudioHandler.handle_voice_file(file_path)

        elif response.text:
            logger.info(f"Ответ от бота (text): {response.text}")

        return path_to_file

    async def start(self):
        logger.info("Запуск коннектора ТГ!")
        try:
            if not self.client:
                raise RuntimeError("Telegram client not initialized")

            await self.client.connect()

            loop_results = await asyncio.get_event_loop().run_in_executor(
                None,
                self.event_bus.emit_and_wait,
                Events.Core.GET_EVENT_LOOP,
                {},
                1.0
            )
            loop = loop_results[0] if loop_results else asyncio.get_event_loop()

            if not await self.client.is_user_authorized():
                try:
                    await self.client.send_code_request(self.phone)

                    code_future = loop.create_future()
                    self.event_bus.emit(Events.Telegram.PROMPT_FOR_TG_CODE, {'future': code_future})
                    verification_code = await code_future

                    try:
                        await self.client.sign_in(phone=self.phone, code=verification_code)
                    except SessionPasswordNeededError:
                        password_future = loop.create_future()
                        self.event_bus.emit(Events.Telegram.PROMPT_FOR_TG_PASSWORD, {'future': password_future})
                        password = await password_future
                        await self.client.sign_in(password=password)

                except asyncio.CancelledError:
                    logger.info("Авторизация отменена пользователем.")
                    raise
                except Exception as e:
                    logger.error(f"Ошибка при авторизации: {e}")
                    raise

            # Bot init sequence with rate limiting to avoid bot spam
            await self._safe_send_message("/start", min_gap=1.5, count=True)

            self.event_bus.emit(Events.Telegram.SET_SILERO_CONNECTED, {'connected': True})

            if self.tg_bot == "@silero_voice_bot":
                await self._safe_send_message("/speaker mita", min_gap=1.2, count=True)
                self.last_speaker_command = "/speaker mita"
                self._last_speaker_command_norm = self._norm_cmd(self.last_speaker_command)

                await self._safe_send_message("/mp3", min_gap=1.2, count=True)
                await asyncio.sleep(0.25)

                await self.TurnOnHd()
                await asyncio.sleep(0.25)

                await self.TurnOffCircles()

            logger.info("Telegram bot configured for voiceover")
        except Exception as e:
            self.event_bus.emit(Events.Telegram.SET_SILERO_CONNECTED, {'connected': False})
            logger.error(f"Ошибка авторизации/старта: {e}")

    async def getLastMessage(self):
        if not self.client:
            return None
        try:
            messages = await self.client.get_messages(self.tg_bot, limit=1)
            return messages[0] if messages else None
        except Exception:
            return None

    async def TurnOnHd(self):
        return await self.execute_toggle_command(
            command="/hd",
            active_response="Режим HD включен!",
            inactive_response="Режим HD выключен!"
        )

    async def TurnOffCircles(self):
        return await self.execute_toggle_command(
            command="/videonotes",
            active_response="Кружки выключены!",
            inactive_response="Кружки включены!"
        )

    async def execute_toggle_command(
        self,
        command: str,
        active_response: str,
        inactive_response: str,
        max_attempts: int = 3,
        initial_delay: float = 0.5,
        retry_delay: float = 1.0
    ):
        attempts = 0
        while attempts < max_attempts:
            attempts += 1
            try:
                base_id = await self._get_last_chat_message_id()

                await self._safe_send_message(command, min_gap=1.2, count=True)
                await asyncio.sleep(initial_delay)

                last_message = await self.getLastMessage()
                if not last_message or not hasattr(last_message, 'text'):
                    continue

                txt = last_message.text or ""
                if "Слишком много запросов" in txt:
                    if attempts < max_attempts:
                        await asyncio.sleep(retry_delay)
                    continue

                if txt == inactive_response:
                    await asyncio.sleep(retry_delay)
                    await self._safe_send_message(command, min_gap=1.2, count=True)
                    return True

                if txt == active_response:
                    return True

            except Exception as e:
                logger.info(f"Ошибка при выполнении команды {command}: {str(e)}")
                if attempts < max_attempts:
                    await asyncio.sleep(retry_delay)

        return False