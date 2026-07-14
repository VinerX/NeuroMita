import asyncio
import time
from concurrent.futures import Future
from typing import Any, Optional

from handlers.telegram_handler import TelegramBotHandler
from main_logger import logger
from utils import SH
from core.events import get_event_bus, Events, Event
from core.services import use
from services.contracts import LoopService, SettingsService, TelegramService


class TelegramController(TelegramService):
    _SETTING_KEYS = frozenset({
        "USE_VOICEOVER", "VOICEOVER_METHOD", "TG_AUTOCONNECT",
        "NM_TELEGRAM_API_ID", "NM_TELEGRAM_API_HASH", "NM_TELEGRAM_PHONE",
        "TG_MIN_REQUEST_INTERVAL", "SILERO_TIME", "AUDIO_BOT",
    })

    def __init__(self):
        self.settings: Any = use(SettingsService)
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
        self._queue_worker_task: asyncio.Task[Any] | None = None
        self._last_tg_request_ts: float = 0.0
        self._min_request_interval: float = 0.0

        self._settings_subscription = self.settings.subscribe(
            self._on_setting_changed, keys=self._SETTING_KEYS
        )
        self._subscribe_to_events()
        self._attach_running_loop()
        self._load_settings_snapshot(reason="initial")

    def _subscribe_to_events(self):
        self.event_bus.subscribe("telegram_settings_loaded", self._on_telegram_settings_loaded, weak=False)

        self.event_bus.subscribe(Events.Telegram.SET_SILERO_CONNECTED, self._on_set_silero_connected, weak=False)

        self.event_bus.subscribe(Events.Core.LOOP_READY, self._on_loop_ready, weak=False)

        # START/STOP events (если констант нет в Events.Telegram — используем строковые фолбэки)
        start_evt = getattr(Events.Telegram, "START_SILERO", "telegram_start_silero")
        stop_evt = getattr(Events.Telegram, "STOP_SILERO", "telegram_stop_silero")
        self.event_bus.subscribe(start_evt, self._on_start_requested, weak=False)
        self.event_bus.subscribe(stop_evt, self._on_stop_requested, weak=False)

    def _attach_running_loop(self) -> None:
        try:
            loop_service = use(LoopService)
            if not loop_service.is_running():
                return
            self._loop = loop_service.loop()
            loop_service.run(self._init_queue_and_start_worker())
        except Exception:
            self._loop = None

    # ---------------- settings / status ----------------
    def _on_telegram_settings_loaded(self, event: Event):
        data = event.data or {}
        supplied = data.get("settings")
        if supplied is not None:
            self.settings = supplied
        self._load_settings_snapshot(reason="telegram_settings_loaded")

    def _load_settings_snapshot(self, *, reason: str) -> None:
        settings = self.settings or use(SettingsService)
        self.api_id = settings.get("NM_TELEGRAM_API_ID", "") or ""
        self.api_hash = settings.get("NM_TELEGRAM_API_HASH", "") or ""
        self.phone = settings.get("NM_TELEGRAM_PHONE", "") or ""
        try:
            self._min_request_interval = float(settings.get("TG_MIN_REQUEST_INTERVAL", 0) or 0)
        except Exception:
            self._min_request_interval = 0.0

        logger.info(
            f"Telegram настройки загружены: api_id={SH(self.api_id)}, api_hash={SH(self.api_hash)}, phone={SH(self.phone)}"
        )
        self._maybe_autoconnect(reason=reason)

    def _on_setting_changed(self, change):
        key = change.key
        value = change.value

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

        elif key == "NM_TELEGRAM_API_ID":
            self.api_id = value or ""
        elif key == "NM_TELEGRAM_API_HASH":
            self.api_hash = value or ""
        elif key == "NM_TELEGRAM_PHONE":
            self.phone = value or ""

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
        return self.is_silero_connected()

    def is_silero_connected(self) -> bool:
        return self.silero_connected

    # ---------------- loop lifecycle ----------------
    def _on_loop_ready(self, event: Event):
        self._loop = (event.data or {}).get("loop")
        logger.info("TelegramController получил уведомление о готовности loop")

        use(LoopService).run(self._init_queue_and_start_worker())

        if self._waiting_for_loop:
            self._waiting_for_loop = False
            self._start_silero_with_loop()

    # ---------------- start/stop orchestration ----------------
    def _tg_settings_snapshot(self) -> dict:
        s = use(SettingsService)
        return {
            "USE_VOICEOVER": bool(s.get("USE_VOICEOVER", False)),
            "VOICEOVER_METHOD": str(s.get("VOICEOVER_METHOD", "Local") or "Local"),
            "TG_AUTOCONNECT": bool(s.get("TG_AUTOCONNECT", True)),
        }

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
            loop_service = use(LoopService)
            if loop_service.is_running():
                self._loop = loop_service.loop()

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
                    audio_bot = use(SettingsService).get("AUDIO_BOT", "@silero_voice_bot")
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
        finally:
            # На случай отмены пользователем (CancelledError — BaseException, не ловится
            # except Exception): не оставляем _connecting=True, иначе повторный коннект
            # заблокирован навсегда.
            if self._connecting and not self.silero_connected:
                self._connecting = False
                self.event_bus.emit(Events.Telegram.SET_SILERO_CONNECTED, {'connected': False})

    def stop_silero_async(self, *, source: str = "api") -> bool:
        logger.info(f"Запрос на остановку Telegram клиента ({source})")

        self._connecting = False

        if not self._loop:
            loop_service = use(LoopService)
            if loop_service.is_running():
                self._loop = loop_service.loop()

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

    def shutdown(self) -> None:
        subscription = self._settings_subscription
        self._settings_subscription = None
        if subscription is not None:
            subscription.close()
        try:
            loop_service = use(LoopService)
            if loop_service.is_running():
                future = loop_service.run(self._shutdown_queue_worker())
                try:
                    future.result(timeout=5.0)
                except Exception:
                    pass
        except Exception:
            pass
        self.stop_silero_async(source="shutdown")

    # ---------------- voice requests ----------------
    async def send_voice(
        self,
        text: str,
        speaker_command: str,
        message_id: int = 0,
    ) -> str:
        owner_loop = self._loop
        current_loop = asyncio.get_running_loop()
        if owner_loop is None or not owner_loop.is_running():
            owner_loop = current_loop
            self._loop = owner_loop

        if not self._voice_queue:
            if owner_loop is current_loop:
                await self._init_queue_and_start_worker()
            else:
                init_future = asyncio.run_coroutine_threadsafe(
                    self._init_queue_and_start_worker(), owner_loop
                )
                await asyncio.wrap_future(init_future)
        if not self._loop or not self._voice_queue:
            raise RuntimeError("Telegram voice queue is not initialized")

        result: Future[str] = Future()
        item = {
            "text": str(text or ""),
            "speaker_command": str(speaker_command or ""),
            "mid": int(message_id or 0),
            "future": result,
        }
        self._loop.call_soon_threadsafe(self._voice_queue.put_nowait, item)
        return await asyncio.wrap_future(result)


    async def _init_queue_and_start_worker(self):
        if self._voice_queue is None:
            self._voice_queue = asyncio.Queue()
        task = self._queue_worker_task
        if task is not None and not task.done():
            return
        logger.info("TG voice queue создана, запускаем worker")
        task = asyncio.create_task(self._queue_worker(), name="telegram-voice-queue")
        self._queue_worker_task = task

        def log_failure(done: asyncio.Task[Any]) -> None:
            if done.cancelled():
                return
            try:
                error = done.exception()
            except Exception:
                return
            if error is not None:
                logger.error(
                    f"TG voice queue worker terminated: {error}",
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(log_failure)

    async def _shutdown_queue_worker(self) -> None:
        task = self._queue_worker_task
        self._queue_worker_task = None
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        queue = self._voice_queue
        if queue is None:
            return
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            future = item.get("future") if isinstance(item, dict) else None
            if future is not None and not future.done():
                future.set_exception(RuntimeError("Telegram controller shut down"))
            queue.task_done()

    async def _queue_worker(self):
        logger.info("TG voice queue worker запущен")
        while True:
            try:
                item = await self._voice_queue.get()
            except asyncio.CancelledError:
                logger.info("TG voice queue worker stopped")
                raise
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
