import asyncio
import time
from typing import Any, Optional

from handlers.telegram_handler import TelegramBotHandler
from main_logger import logger
from utils import SH
from core.events import get_event_bus, Events, Event


class TelegramController:
    def __init__(self):
        self.settings: Any = None
        self.event_bus = get_event_bus()

        self.bot_handler: Optional[TelegramBotHandler] = None
        self.bot_handler_ready: bool = False

        self.silero_connected: bool = False
        self._connecting: bool = False

        self.api_hash = ""
        self.api_id = ""
        self.phone = ""

        self._loop = None
        self._waiting_for_loop = False

        self._last_start_attempt_ts: float = 0.0
        self._start_cooldown_sec: float = 20.0

        self._voice_queue: asyncio.Queue | None = None
        self._last_tg_request_ts: float = 0.0
        self._min_request_interval: float = 0.0

        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe("telegram_settings_loaded", self._on_telegram_settings_loaded, weak=False)
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)

        self.event_bus.subscribe(Events.Telegram.TELEGRAM_SEND_VOICE_REQUEST, self._on_send_voice_request, weak=False)
        self.event_bus.subscribe(Events.Telegram.SET_SILERO_CONNECTED, self._on_set_silero_connected, weak=False)
        self.event_bus.subscribe(Events.Telegram.GET_SILERO_STATUS, self._on_get_silero_status, weak=False)

        self.event_bus.subscribe(Events.Core.LOOP_READY, self._on_loop_ready, weak=False)

        # START/STOP events (если констант нет в Events.Telegram — используем строковые фолбэки)
        start_evt = getattr(Events.Telegram, "START_SILERO", "telegram_start_silero")
        stop_evt = getattr(Events.Telegram, "STOP_SILERO", "telegram_stop_silero")
        self.event_bus.subscribe(start_evt, self._on_start_requested, weak=False)
        self.event_bus.subscribe(stop_evt, self._on_stop_requested, weak=False)

    # ---------------- settings / status ----------------
    def _on_telegram_settings_loaded(self, event: Event):
        data = event.data or {}
        self.api_id = data.get("api_id", "") or ""
        self.api_hash = data.get("api_hash", "") or ""
        self.phone = data.get("phone", "") or ""
        self.settings = data.get("settings", None)

        if self.settings:
            try:
                self._min_request_interval = float(self.settings.get("TG_MIN_REQUEST_INTERVAL", 0) or 0)
            except Exception:
                self._min_request_interval = 0.0

        logger.info(
            f"Telegram настройки загружены: api_id={SH(self.api_id)}, api_hash={SH(self.api_hash)}, phone={SH(self.phone)}"
        )

        # После загрузки настроек попробуем автоподключиться (без спама — есть кулдаун)
        self._maybe_autoconnect(reason="telegram_settings_loaded")

    def _on_setting_changed(self, event: Event):
        data = event.data or {}
        key = data.get("key")
        value = data.get("value")

        if key == "SILERO_TIME" and self.bot_handler:
            try:
                self.bot_handler.silero_time_limit = int(value)
            except Exception:
                pass

        elif key == "TG_MIN_REQUEST_INTERVAL":
            try:
                self._min_request_interval = float(value)
            except Exception:
                pass

        elif key == "AUDIO_BOT" and self.bot_handler:
            try:
                self.bot_handler.tg_bot = value
            except Exception:
                pass

        # Любое изменение, влияющее на TG автоконнект
        if key in ("USE_VOICEOVER", "VOICEOVER_METHOD", "TG_AUTOCONNECT", "NM_TELEGRAM_API_ID", "NM_TELEGRAM_API_HASH", "NM_TELEGRAM_PHONE"):
            self._maybe_autoconnect(reason=f"setting_changed:{key}")

    def _on_set_silero_connected(self, event: Event):
        val = bool((event.data or {}).get("connected", False))
        self.silero_connected = val
        if val:
            self._connecting = False
        logger.info(f"Статус подключения Silero установлен: {self.silero_connected}")

    def _on_get_silero_status(self, event: Event):
        return self.silero_connected

    # ---------------- loop lifecycle ----------------
    def _on_loop_ready(self, event: Event):
        self._loop = (event.data or {}).get("loop")
        logger.info("TelegramController получил уведомление о готовности loop")

        self.event_bus.emit(Events.Core.RUN_IN_LOOP, {'coroutine': self._init_queue_and_start_worker()})

        if self._waiting_for_loop:
            self._waiting_for_loop = False
            self._start_silero_with_loop()

    # ---------------- start/stop orchestration ----------------
    def _tg_settings_snapshot(self) -> dict:
        s = self.settings
        if s is not None and hasattr(s, "get"):
            try:
                return {
                    "USE_VOICEOVER": bool(s.get("USE_VOICEOVER", False)),
                    "VOICEOVER_METHOD": str(s.get("VOICEOVER_METHOD", "TG") or "TG"),
                    "TG_AUTOCONNECT": bool(s.get("TG_AUTOCONNECT", True)),
                }
            except Exception:
                pass

        # fallback: спросим у SettingsController “сырые” settings
        try:
            res = self.event_bus.emit_and_wait(Events.Settings.GET_SETTINGS, timeout=0.4)
            raw = res[0] if res else {}
            if isinstance(raw, dict):
                return {
                    "USE_VOICEOVER": bool(raw.get("USE_VOICEOVER", False)),
                    "VOICEOVER_METHOD": str(raw.get("VOICEOVER_METHOD", "TG") or "TG"),
                    "TG_AUTOCONNECT": bool(raw.get("TG_AUTOCONNECT", True)),
                }
        except Exception:
            pass

        return {"USE_VOICEOVER": False, "VOICEOVER_METHOD": "TG", "TG_AUTOCONNECT": True}

    def _maybe_autoconnect(self, *, reason: str):
        snap = self._tg_settings_snapshot()
        if not snap.get("TG_AUTOCONNECT", True):
            return
        if not snap.get("USE_VOICEOVER", False):
            return
        if snap.get("VOICEOVER_METHOD") != "TG":
            return

        # Уже подключены или в процессе
        if self.silero_connected or self._connecting:
            return

        # Кулдаун, чтобы не спамить
        now = time.time()
        if (now - float(self._last_start_attempt_ts or 0.0)) < float(self._start_cooldown_sec or 20.0):
            return

        logger.info(f"Telegram autoconnect triggered ({reason})")
        self.request_start(force=False, source=f"autoconnect:{reason}")

    def _on_start_requested(self, event: Event):
        data = event.data or {}
        force = bool(data.get("force", False))
        source = str(data.get("source") or "event")
        self.request_start(force=force, source=source)

    def _on_stop_requested(self, event: Event):
        source = str((event.data or {}).get("source") or "event")
        self.stop_silero_async(source=source)

    def request_start(self, *, force: bool, source: str = "api") -> bool:
        # Не стартуем, если уже подключены/в процессе
        if self.silero_connected:
            return True
        if self._connecting:
            return False

        snap = self._tg_settings_snapshot()
        if not force:
            if not snap.get("USE_VOICEOVER", False) or snap.get("VOICEOVER_METHOD") != "TG":
                return False

        # Кулдаун
        now = time.time()
        if (now - float(self._last_start_attempt_ts or 0.0)) < float(self._start_cooldown_sec or 20.0):
            return False

        self._last_start_attempt_ts = now
        self._connecting = True
        logger.info(f"Запрос на запуск Silero ({source}, force={force})")
        self.start_silero_async()
        return True

    # ---------------- start/stop implementation ----------------
    def start_silero_async(self):
        # Проверяем loop
        if not self._loop:
            loops = self.event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=0.1)
            if loops and loops[0]:
                self._loop = loops[0]

        if self._loop and self._loop.is_running():
            self._start_silero_with_loop()
        else:
            logger.info("Loop ещё не готов, ожидаем события LOOP_READY...")
            self._waiting_for_loop = True

    def _start_silero_with_loop(self):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.start_silero(), self._loop)
        else:
            logger.error("Ошибка: Loop не готов для запуска Silero")
            self._connecting = False

    async def start_silero(self):
        logger.info("Telegram Bot запускается!")
        try:
            if not self.api_id or not self.api_hash or not self.phone:
                logger.info("Ошибка: отсутствуют необходимые данные для Telegram бота")
                self._connecting = False
                self.silero_connected = False
                self.event_bus.emit(Events.Telegram.SET_SILERO_CONNECTED, {'connected': False})
                return

            audio_bot = "@silero_voice_bot"
            try:
                if self.settings:
                    audio_bot = self.settings.get("AUDIO_BOT", "@silero_voice_bot")
                else:
                    res = self.event_bus.emit_and_wait(Events.Settings.GET_SETTINGS, timeout=0.5)
                    raw = res[0] if res else {}
                    if isinstance(raw, dict):
                        audio_bot = raw.get("AUDIO_BOT", "@silero_voice_bot")
            except Exception:
                pass

            self.bot_handler = TelegramBotHandler(self.api_id, self.api_hash, self.phone, audio_bot)

            try:
                await self.bot_handler.start()
                self.bot_handler_ready = True

                # фиксируем статус сразу (handler тоже эмитит SET_SILERO_CONNECTED)
                self.silero_connected = True
                self._connecting = False
                self.event_bus.emit(Events.Telegram.SET_SILERO_CONNECTED, {'connected': True})
                self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
                logger.info("ТГ успешно подключен")

            except Exception as e:
                logger.info(f"Ошибка при запуске Telegram бота: {e}")
                self.bot_handler_ready = False
                self._connecting = False
                self.silero_connected = False
                self.event_bus.emit(Events.Telegram.SET_SILERO_CONNECTED, {'connected': False})

        except Exception as e:
            logger.info(f"Критическая ошибка при инициализации Telegram Bot: {e}")
            self._connecting = False
            self.silero_connected = False
            self.bot_handler_ready = False
            self.event_bus.emit(Events.Telegram.SET_SILERO_CONNECTED, {'connected': False})

    def stop_silero_async(self, *, source: str = "api") -> bool:
        logger.info(f"Запрос на остановку Telegram клиента ({source})")

        self._connecting = False

        if not self._loop:
            loops = self.event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=0.1)
            if loops and loops[0]:
                self._loop = loops[0]

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.stop_silero(), self._loop)
            return True

        # fallback: без loop просто сбросим флаги
        self._hard_reset_state()
        return True

    async def stop_silero(self):
        try:
            bh = self.bot_handler
            if bh and getattr(bh, "client", None):
                try:
                    await bh.client.disconnect()
                except Exception:
                    try:
                        bh.client.disconnect()
                    except Exception:
                        pass
        finally:
            self._hard_reset_state()

    def _hard_reset_state(self):
        self.bot_handler_ready = False
        self.silero_connected = False
        self.bot_handler = None
        self.event_bus.emit(Events.Telegram.SET_SILERO_CONNECTED, {'connected': False})
        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

    # ---------------- voice requests ----------------
    def _on_send_voice_request(self, event: Event):
        data = event.data or {}
        text = data.get('text', '')
        speaker_command = data.get('speaker_command', '')
        mid = data.get('id', 0)
        future = data.get('future')

        if not self._voice_queue or not self._loop:
            logger.error("Очередь голосовых запросов не инициализирована")
            if future and not future.done():
                future.set_exception(Exception("Voice queue not initialized"))
            return

        item = {
            'text': text,
            'speaker_command': speaker_command,
            'mid': mid,
            'future': future,
        }
        self._loop.call_soon_threadsafe(self._voice_queue.put_nowait, item)
        logger.debug(f"TG voice request добавлен в очередь (размер: {self._voice_queue.qsize() + 1})")

    async def _init_queue_and_start_worker(self):
        self._voice_queue = asyncio.Queue()
        logger.info("TG voice queue создана, запускаем worker")
        asyncio.ensure_future(self._queue_worker())

    async def _queue_worker(self):
        logger.info("TG voice queue worker запущен")
        while True:
            item = await self._voice_queue.get()
            future = item.get('future')
            try:
                if not self.bot_handler or not self.bot_handler_ready:
                    logger.warning("TG queue worker: bot handler не готов, пропускаем запрос")
                    if future and not future.done():
                        future.set_exception(Exception("Bot handler not ready"))
                    continue

                # Enforce minimum interval between requests
                if self._last_tg_request_ts > 0 and self._min_request_interval > 0:
                    elapsed = time.time() - self._last_tg_request_ts
                    if elapsed < self._min_request_interval:
                        await asyncio.sleep(self._min_request_interval - elapsed)

                self._last_tg_request_ts = time.time()
                await self._async_send_and_receive(
                    item['text'], item['speaker_command'], item['mid'], future
                )
            except Exception as e:
                logger.error(f"TG queue worker: ошибка при обработке запроса: {e}")
                if future and not future.done():
                    future.set_exception(e)
            finally:
                self._voice_queue.task_done()

    async def _async_send_and_receive(self, text, speaker_command, mid, future):
        try:
            voice_path = await self.bot_handler.send_and_receive(text, speaker_command, mid)
            if future and not future.done():
                future.set_result(voice_path)
        except Exception as e:
            logger.error(f"Ошибка при отправке голосового запроса: {e}")
            if future and not future.done():
                future.set_exception(e)