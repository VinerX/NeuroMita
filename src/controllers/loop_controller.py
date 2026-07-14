# src/controllers/loop_controller.py

import asyncio
import threading
from main_logger import logger
from core.events import get_event_bus, Events, Event
from core.services import services
from core.task_supervisor import task_supervisor
from services.contracts import LoopService
from services.loop_service import AsyncioLoopService


class LoopController:
    """Владелец asyncio-loop. Регистрирует LoopService."""

    def __init__(self):
        self.event_bus = get_event_bus()

        self.loop_ready_event = threading.Event()
        self.loop = None

        services().register(LoopService, AsyncioLoopService(lambda: self.loop), replace=True)

        self.asyncio_thread = task_supervisor().start_thread(
            self,
            "application-asyncio-loop",
            self.start_asyncio_loop,
        )

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

