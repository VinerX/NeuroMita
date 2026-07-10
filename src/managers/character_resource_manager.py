from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from main_logger import logger


@dataclass
class _CharacterDescriptor:
    character_id: str
    character_name: str
    prompt_set_path: str = ""


class CharacterResourceManager:
    """Единый владелец runtime-хранилищ всех персонажей.

    Character остаётся доменным объектом и лишь предоставляет совместимые
    свойства ``history_manager``, ``memory_system`` и ``reminder_system``.
    Реальные менеджеры создаются лениво и не дублируются для одного char_id.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._descriptors: dict[str, _CharacterDescriptor] = {}
        self._histories: dict[str, object] = {}
        self._memories: dict[str, object] = {}
        self._reminders: dict[str, object] = {}

    @staticmethod
    def _key(character_id: str) -> str:
        key = str(character_id or "").strip()
        if not key:
            raise ValueError("character_id is required")
        return key

    def register_character(
        self,
        character_id: str,
        character_name: str,
        prompt_set_path: str = "",
    ) -> None:
        key = self._key(character_id)
        with self._lock:
            descriptor = self._descriptors.get(key)
            if descriptor is None:
                self._descriptors[key] = _CharacterDescriptor(
                    character_id=key,
                    character_name=str(character_name or key),
                    prompt_set_path=str(prompt_set_path or ""),
                )
            else:
                descriptor.character_name = str(character_name or descriptor.character_name or key)
                descriptor.prompt_set_path = str(prompt_set_path or descriptor.prompt_set_path or "")

            memory = self._memories.get(key)
            if memory is not None:
                memory.prompt_set_path = descriptor.prompt_set_path

    def update_prompt_set_path(self, character_id: str, prompt_set_path: str) -> None:
        key = self._key(character_id)
        with self._lock:
            descriptor = self._descriptors.get(key)
            if descriptor is None:
                descriptor = _CharacterDescriptor(key, key)
                self._descriptors[key] = descriptor
            descriptor.prompt_set_path = str(prompt_set_path or "")
            memory = self._memories.get(key)
            if memory is not None:
                memory.prompt_set_path = descriptor.prompt_set_path

    def _descriptor(self, character_id: str, character_name: str = "") -> _CharacterDescriptor:
        key = self._key(character_id)
        descriptor = self._descriptors.get(key)
        if descriptor is None:
            descriptor = _CharacterDescriptor(key, str(character_name or key))
            self._descriptors[key] = descriptor
        return descriptor

    def history_for(self, character_id: str, character_name: str = ""):
        key = self._key(character_id)
        with self._lock:
            manager = self._histories.get(key)
            if manager is None:
                from managers.history_manager import HistoryManager

                descriptor = self._descriptor(key, character_name)
                manager = HistoryManager(
                    character_name=descriptor.character_name,
                    character_id=key,
                )
                self._histories[key] = manager
                logger.debug(f"[CharacterResources] HistoryManager created for {key}")
            return manager

    def memory_for(self, character_id: str, character_name: str = ""):
        key = self._key(character_id)
        with self._lock:
            manager = self._memories.get(key)
            if manager is None:
                from managers.memory_manager import MemoryManager

                descriptor = self._descriptor(key, character_name)
                manager = MemoryManager(key)
                manager.prompt_set_path = descriptor.prompt_set_path
                self._memories[key] = manager
                logger.debug(f"[CharacterResources] MemoryManager created for {key}")
            return manager

    def reminders_for(self, character_id: str, character_name: str = ""):
        key = self._key(character_id)
        with self._lock:
            manager = self._reminders.get(key)
            if manager is None:
                from managers.reminder_manager import ReminderManager

                self._descriptor(key, character_name)
                manager = ReminderManager(key)
                self._reminders[key] = manager
                logger.debug(f"[CharacterResources] ReminderManager created for {key}")
            return manager

    def shutdown(self) -> None:
        """Останавливает process-wide фоновые executors менеджеров."""
        for manager_type in ("history", "memory", "rag"):
            try:
                if manager_type == "history":
                    from managers.history_manager import HistoryManager

                    HistoryManager.shutdown_executor()
                elif manager_type == "memory":
                    from managers.memory_manager import MemoryManager

                    MemoryManager.shutdown_executor()
                else:
                    from managers.rag.rag_manager import RAGManager

                    RAGManager.shutdown_executor()
            except Exception as exc:
                logger.warning(
                    f"[CharacterResources] Failed to shutdown {manager_type} executor: {exc}"
                )


_global_resources: Optional[CharacterResourceManager] = None
_global_resources_lock = threading.Lock()


def get_character_resource_manager() -> CharacterResourceManager:
    global _global_resources
    manager = _global_resources
    if manager is not None:
        return manager
    with _global_resources_lock:
        manager = _global_resources
        if manager is None:
            manager = CharacterResourceManager()
            _global_resources = manager
        return manager
