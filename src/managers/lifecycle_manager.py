import asyncio
import threading
from core.task_supervisor import task_supervisor
from typing import Optional, List, Callable
from main_logger import logger

class LifecycleManager:
    """Управляет жизненным циклом приложения, потоками и asyncio"""
    
    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.loop_thread: Optional[threading.Thread] = None
        self.loop_ready_event = threading.Event()
        self._cleanup_callbacks: List[Callable] = []
        
    def start_event_loop(self):
        """Запуск asyncio event loop в отдельном потоке"""
        self.loop_thread = task_supervisor().start_thread(
            self, "lifecycle-event-loop", self._run_event_loop, replace=True
        )
        self.loop_ready_event.wait()
        
    def _run_event_loop(self):
        """Запуск event loop"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            logger.info("Asyncio event loop started")
            self.loop_ready_event.set()
            self.loop.run_forever()
        except Exception as e:
            logger.error(f"Error in event loop: {e}", exc_info=True)
        finally:
            self._cleanup_loop()
            
    def _cleanup_loop(self):
        """Очистка event loop"""
        if self.loop and not self.loop.is_closed():
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()
            logger.info("Event loop closed")
            
    def register_cleanup(self, callback: Callable):
        """Регистрация callback для cleanup"""
        self._cleanup_callbacks.append(callback)
        
    def shutdown(self):
        """Завершение работы"""
        logger.info("Lifecycle manager shutting down...")
        
        # Вызываем все cleanup callbacks
        for callback in self._cleanup_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in cleanup callback: {e}", exc_info=True)
                
        # Останавливаем event loop
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.loop.stop)
            
        if self.loop_thread and self.loop_thread.is_alive():
            self.loop_thread.join(timeout=5)