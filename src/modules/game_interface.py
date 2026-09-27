from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol


class GameHost(Protocol):
    def request_character_reaction(
        self,
        game: "GameInterface",
        instruction: str,
        *,
        visible: bool = True,
    ) -> bool: ...


class GameInterface(ABC):
    """Абстрактный базовый класс для всех игр."""

    def __init__(self, character, game_id: str, host: Optional[GameHost] = None):
        self.character = character
        self.game_id = game_id
        self.host = host

    def request_character_reaction(self, instruction: str, *, visible: bool = True) -> bool:
        """Ask the owning game host to initiate a character reaction."""
        if self.host is None:
            return False
        return bool(self.host.request_character_reaction(self, instruction, visible=visible))

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
        """Формирует системный промпт с текущим состоянием игры."""
        pass

    def process_structured_commands(self, commands: List[str]):
        """Обрабатывает команды из structured response. По умолчанию — no-op."""
        pass