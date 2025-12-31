import asyncio
from handlers.telegram_handler import TelegramBotHandler
from main_logger import logger
from utils import SH
from core.events import get_event_bus, Events, Event

# Контроллер для работы с озвучкой в Telegram

class TelegramController:
    def __init__(self):
        self.settings = None
        self.event_bus = get_event_bus()
        self.bot_handler = None
        self.bot_handler_ready = False
        self.silero_connected = False
        
        self.api_hash = ""
        self.api_id = ""
        self.phone = ""
        
        self._loop = None
        self._waiting_for_loop = False
        
        self._subscribe_to_events()
        
    def _subscribe_to_events(self):
        self.event_bus.subscribe("telegram_settings_loaded", self._on_telegram_settings_loaded, weak=False)
        self.event_bus.subscribe(Events.Core.SETTING_CHANGED, self._on_setting_changed, weak=False)
        self.event_bus.subscribe(Events.Telegram.TELEGRAM_SEND_VOICE_REQUEST, self._on_send_voice_request, weak=False)
        self.event_bus.subscribe(Events.Telegram.SET_SILERO_CONNECTED, self._on_set_silero_connected, weak=False)
        self.event_bus.subscribe(Events.Telegram.GET_SILERO_STATUS, self._on_get_silero_status, weak=False)
        self.event_bus.subscribe(Events.Core.LOOP_READY, self._on_loop_ready, weak=False)
    
    def _on_telegram_settings_loaded(self, event: Event):
        data = event.data
        self.api_id = data.get("api_id", "")
        self.api_hash = data.get("api_hash", "")
        self.phone = data.get("phone", "")
        self.settings = data.get("settings")
        logger.info(f"Telegram настройки загружены: api_id={SH(self.api_id)}, api_hash={SH(self.api_hash)}, phone={SH(self.phone)}")
    
    def _on_setting_changed(self, event: Event):
        key = event.data.get('key')
        value = event.data.get('value')
        
        if key == "SILERO_TIME" and self.bot_handler:
            self.bot_handler.silero_time_limit = int(value)
        elif key == "AUDIO_BOT" and self.bot_handler:
            self.bot_handler.tg_bot = value
    
    def _on_set_silero_connected(self, event: Event):
        self.silero_connected = event.data.get('connected', False)
        logger.info(f"Статус подключения Silero установлен: {self.silero_connected}")
    
    def _on_get_silero_status(self, event: Event):
        return self.silero_connected
    
    def _on_loop_ready(self, event: Event):
        """Обработчик события готовности loop"""
        self._loop = event.data.get('loop')
        logger.info("TelegramController получил уведомление о готовности loop")
        
        # Если ждали loop для запуска Silero
        if self._waiting_for_loop:
            self._waiting_for_loop = False
            self._start_silero_with_loop()
        
        
    def start_silero_async(self):
        logger.info("Запрос на запуск Silero...")
        
        # Проверяем, есть ли уже loop
        if not self._loop:
            # Пробуем получить loop синхронно
            loops = self.event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=0.1)
            if loops and loops[0]:
                self._loop = loops[0]
        
        if self._loop and self._loop.is_running():
            # Loop готов, запускаем сразу
            self._start_silero_with_loop()
        else:
            # Loop ещё не готов, ждём события LOOP_READY
            logger.info("Loop ещё не готов, ожидаем события LOOP_READY...")
            self._waiting_for_loop = True
    
    def _start_silero_with_loop(self):
        """Запуск Silero когда loop точно готов"""
        if self._loop and self._loop.is_running():
            logger.info("Запускаем Silero через цикл событий.")
            asyncio.run_coroutine_threadsafe(self.start_silero(), self._loop)
        else:
            logger.error("Ошибка: Loop не готов для запуска Silero")
            
    async def start_silero(self):
        logger.info("Telegram Bot запускается!")
        try:
            if not self.api_id or not self.api_hash or not self.phone:
                logger.info("Ошибка: отсутствуют необходимые данные для Telegram бота")
                self.silero_connected = False
                return

            logger.info(f"Передаю в тг {SH(self.api_id)},{SH(self.api_hash)},{SH(self.phone)} (Должно быть не пусто)")

            audio_bot = "@silero_voice_bot"
            if self.settings:
                audio_bot = self.settings.get("AUDIO_BOT", "@silero_voice_bot")

            self.bot_handler = TelegramBotHandler(self.api_id, self.api_hash, self.phone, audio_bot)

            try:
                await self.bot_handler.start()
                self.bot_handler_ready = True
                if hasattr(self, 'silero_connected') and self.silero_connected:
                    logger.info("ТГ успешно подключен")
                    self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
                else:
                    logger.info("ТГ не подключен")
            except Exception as e:
                logger.info(f"Ошибка при запуске Telegram бота: {e}")
                self.bot_handler_ready = False
                self.silero_connected = False

        except Exception as e:
            logger.info(f"Критическая ошибка при инициализации Telegram Bot: {e}")
            self.silero_connected = False
            self.bot_handler_ready = False

    def _on_send_voice_request(self, event: Event):
        data = event.data
        text = data.get('text', '')
        speaker_command = data.get('speaker_command', '')
        id = data.get('id', 0)
        future = data.get('future')
        
        if not self.bot_handler or not self.bot_handler_ready:
            logger.error("Bot handler не готов для отправки голосового запроса")
            if future:
                future.set_exception(Exception("Bot handler not ready"))
            return
            
        # Используем универсальное событие RUN_IN_LOOP
        coro = self._async_send_and_receive(text, speaker_command, id, future)

        # callback нужен только для прокидывания исключений
        def handle_result(result, error):
            if error and future and not future.done():
                future.set_exception(error)

        self.event_bus.emit(Events.Core.RUN_IN_LOOP,
                            {'coroutine': coro, 'callback': handle_result})

    async def _async_send_and_receive(self, text, speaker_command, id, future):
        try:
            voice_path = await self.bot_handler.send_and_receive(
                text, speaker_command, id
            )
            if future and not future.done():
                future.set_result(voice_path)
        except Exception as e:
            logger.error(f"Ошибка при отправке голосового запроса: {e}")
            if future and not future.done():
                future.set_exception(e)