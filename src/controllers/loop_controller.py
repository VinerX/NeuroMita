# src/controllers/loop_controller.py

import asyncio
import threading
from main_logger import logger
from core.events import get_event_bus, Events, Event


class LoopController:
    def __init__(self):
        self.event_bus = get_event_bus()

        self.loop_ready_event = threading.Event()
        self.loop = None
        self.asyncio_thread = threading.Thread(target=self.start_asyncio_loop, daemon=True)
        self.asyncio_thread.start()

        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Core.GET_EVENT_LOOP, self._on_get_event_loop, weak=False)
        self.event_bus.subscribe(Events.Core.RUN_IN_LOOP, self._on_run_in_loop, weak=False)

    def start_asyncio_loop(self):
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            logger.success("Цикл событий asyncio успешно запущен.")
            self.loop_ready_event.set()

            self.event_bus.emit(Events.Core.LOOP_READY, {'loop': self.loop})

            try:
                self.loop.run_forever()
            except Exception as e:
                logger.info(f"Ошибка в цикле событий asyncio: {e}")
            finally:
                logger.info("Начинаем shutdown asyncio loop...")
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                try:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception as e:
                    logger.error(f"Ошибка при завершении pending tasks: {e}")
                try:
                    self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                except Exception as e:
                    logger.error(f"Ошибка при shutdown async generators: {e}")
                try:
                    self.loop.run_until_complete(self.loop.shutdown_default_executor())
                except Exception as e:
                    logger.error(f"Ошибка при shutdown default executor: {e}")
                self.loop.close()
                logger.info("Цикл событий asyncio закрыт.")
        except Exception as e:
            logger.info(f"Ошибка при запуске цикла событий asyncio: {e}")
            self.loop_ready_event.set()

    def stop_loop(self):
        loop = self.loop
        if loop and not loop.is_closed():
            logger.info("Остановка asyncio loop...")
            try:
                if loop.is_running():
                    loop.call_soon_threadsafe(loop.stop)
            except Exception as e:
                logger.error(f"Ошибка при остановке loop: {e}")

        if self.asyncio_thread.is_alive():
            self.asyncio_thread.join(timeout=5)
            if self.asyncio_thread.is_alive():
                logger.warning("Asyncio thread didn't stop in time.")
        elif loop and not loop.is_closed():
            try:
                loop.close()
            except Exception as e:
                logger.error(f"Ошибка при закрытии loop: {e}")

    def _on_get_event_loop(self, event: Event):
        if hasattr(self, 'loop') and self.loop and not self.loop.is_closed():
            return self.loop
        return None

    def _on_run_in_loop(self, event: Event):
        """Универсальный обработчик для запуска корутин в loop"""
        coro = event.data.get('coroutine')
        callback = event.data.get('callback')

        if not coro:
            logger.error("Не передана корутина для запуска")
            return

        if self.loop and self.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            if callback:
                def handle_result():
                    try:
                        result = future.result()
                        callback(result, None)
                    except Exception as e:
                        callback(None, e)
                threading.Thread(target=handle_result, daemon=True).start()
        else:
            logger.error("Loop не готов для выполнения корутины")
            if callback:
                callback(None, Exception("Loop not ready"))
