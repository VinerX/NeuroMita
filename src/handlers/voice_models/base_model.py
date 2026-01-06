import abc
from typing import Optional, Any, Dict, List


class IVoiceModel(abc.ABC):
    """
    Абстрактный базовый класс (интерфейс) для всех моделей озвучки.
    Определяет контракт, которому должны следовать все классы моделей.
    """

    def __init__(self, parent: "LocalVoice", model_id: str):
        self.parent = parent
        self.model_id = model_id
        self.initialized = False
        self.initialized_for: Optional[str] = None

    @abc.abstractmethod
    def get_display_name(self) -> str:
        """Возвращает имя модели для отображения пользователю."""
        raise NotImplementedError

    @abc.abstractmethod
    def initialize(self, init: bool = False) -> bool:
        """
        Инициализирует модель, загружая ее в память и подготавливая к работе.
        :param init: Выполнить ли тестовый "прогревочный" прогон.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def voiceover(self, text: str, character: Optional[Any] = None, **kwargs) -> Optional[str]:
        """
        Выполняет озвучку текста.
        :param text: Текст для озвучки.
        :param character: Объект персонажа с информацией о голосе.
        :param kwargs: Дополнительные параметры.
        :return: Путь к сгенерированному аудиофайлу или None в случае ошибки.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_model_configs(self) -> List[Dict[str, Any]]:
        """Возвращает конфигурации моделей, которые обрабатывает данный класс."""
        raise NotImplementedError

    def cleanup_state(self) -> None:
        """Сбрасывает состояние инциализации модели."""
        self.initialized = False
        self.initialized_for = None

    def load_model_settings(self) -> Dict[str, Any]:
        """Загружает настройки для этой конкретной модели из общего файла настроек."""
        return self.parent.load_model_settings(self.model_id)