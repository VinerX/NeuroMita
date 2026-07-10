from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from main_logger import logger
from managers.history_manager import HistoryManager
from managers.memory_manager import MemoryManager
from managers.reminder_manager import ReminderManager


@dataclass
class _CharacterDescriptor:
    character_id: str
    character_name: str
    prompt_set_path: str = ""


class CharacterResourceManager:
    """Application-scoped owner of one history, memory and reminder service."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._descriptors: dict[str, _CharacterDescriptor] = {}
        self._history_views: dict[str, object] = {}
        self._memory_views: dict[str, object] = {}
        self._reminder_views: dict[str, object] = {}

        self.history_manager = HistoryManager()
        self.memory_manager = MemoryManager()
        self.reminder_manager = ReminderManager()

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
                descriptor = _CharacterDescriptor(
                    character_id=key,
                    character_name=str(character_name or key),
                    prompt_set_path=str(prompt_set_path or ""),
                )
                self._descriptors[key] = descriptor
            else:
                descriptor.character_name = str(
                    character_name or descriptor.character_name or key
                )
                descriptor.prompt_set_path = str(
                    prompt_set_path or descriptor.prompt_set_path or ""
                )

            self.history_manager.register_scope(
                key,
                descriptor.character_name,
                descriptor.prompt_set_path,
            )
            self.memory_manager.register_scope(
                key,
                descriptor.character_name,
                descriptor.prompt_set_path,
            )
            self.reminder_manager.register_scope(
                key,
                descriptor.character_name,
                descriptor.prompt_set_path,
            )

    def update_prompt_set_path(self, character_id: str, prompt_set_path: str) -> None:
        key = self._key(character_id)
        with self._lock:
            descriptor = self._descriptors.get(key)
            if descriptor is None:
                descriptor = _CharacterDescriptor(key, key)
                self._descriptors[key] = descriptor
            descriptor.prompt_set_path = str(prompt_set_path or "")
            self.register_character(
                key,
                descriptor.character_name,
                descriptor.prompt_set_path,
            )

    def _descriptor(
        self,
        character_id: str,
        character_name: str = "",
    ) -> _CharacterDescriptor:
        key = self._key(character_id)
        descriptor = self._descriptors.get(key)
        if descriptor is None:
            descriptor = _CharacterDescriptor(key, str(character_name or key))
            self._descriptors[key] = descriptor
            self.register_character(key, descriptor.character_name, "")
        return descriptor

    def history_for(self, character_id: str, character_name: str = ""):
        with self._lock:
            descriptor = self._descriptor(character_id, character_name)
            view = self._history_views.get(descriptor.character_id)
            if view is None:
                view = self.history_manager.bind(
                    descriptor.character_id,
                    descriptor.character_name,
                    descriptor.prompt_set_path,
                )
                self._history_views[descriptor.character_id] = view
            return view

    def memory_for(self, character_id: str, character_name: str = ""):
        with self._lock:
            descriptor = self._descriptor(character_id, character_name)
            view = self._memory_views.get(descriptor.character_id)
            if view is None:
                view = self.memory_manager.bind(
                    descriptor.character_id,
                    descriptor.character_name,
                    descriptor.prompt_set_path,
                )
                self._memory_views[descriptor.character_id] = view
            return view

    def reminders_for(self, character_id: str, character_name: str = ""):
        with self._lock:
            descriptor = self._descriptor(character_id, character_name)
            view = self._reminder_views.get(descriptor.character_id)
            if view is None:
                view = self.reminder_manager.bind(
                    descriptor.character_id,
                    descriptor.character_name,
                    descriptor.prompt_set_path,
                )
                self._reminder_views[descriptor.character_id] = view
            return view

    def shutdown(self) -> None:
        for name, callback in (
            ("history", self.history_manager.shutdown_executor),
            ("memory", self.memory_manager.shutdown_executor),
        ):
            try:
                callback()
            except Exception as exc:
                logger.warning(
                    f"[CharacterResources] Failed to shutdown {name} executor: {exc}"
                )

        try:
            from managers.rag.rag_manager import RAGManager

            RAGManager.shutdown_executor()
        except Exception as exc:
            logger.warning(
                f"[CharacterResources] Failed to shutdown rag executor: {exc}"
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
