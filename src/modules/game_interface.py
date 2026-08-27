
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Type, List

class GameInterface(ABC):
    """Абстрактный базовый класс для всех игр."""
    def __init__(self, character, game_id: str):
        self.character = character
        self.game_id = game_id

    @abstractmethod
    def start(self, params: Dict[str, Any]):
        """Запускает игру с заданными параметрами."""
        pass

    @abstractmethod
    def stop(self, params: Dict[str, Any]):
        """Останавливает игру."""
        pass

    @abstractmethod
    def process_llm_tags(self, response: str) -> str:
        """Обрабатывает специфичные для игры теги из ответа LLM."""
        pass

    @abstractmethod
    def cleanup(self):
        """Очищает все ресурсы, связанные с игрой."""
        pass

    @abstractmethod
    def get_state_prompt(self) -> Optional[str]:
        """
        Формирует и возвращает системный промпт с текущим состоянием игры,
        используя DSL-шаблон.
        """
        pass

    def process_structured_commands(self, commands: List[str]):
        """Обрабатывает команды из structured response (commands array). По умолчанию — no-op."""
        pass