from __future__ import annotations

from typing import Iterable

from core.installables.types import ComponentCategory, InstallableComponent


class InstallableRegistry:
    def __init__(self) -> None:
        self._items: dict[str, InstallableComponent] = {}

    def register(self, component: InstallableComponent) -> InstallableComponent:
        component_id = str(component.id or "").strip()
        if not component_id:
            raise ValueError("Installable component id is empty")
        if component_id in self._items:
            raise ValueError(f"Duplicate installable component id: {component_id}")
        self._items[component_id] = component
        return component

    def register_many(self, components: Iterable[InstallableComponent]) -> None:
        for component in components or ():
            self.register(component)

    def get(self, component_id: str) -> InstallableComponent | None:
        return self._items.get(str(component_id or "").strip())

    def require(self, component_id: str) -> InstallableComponent:
        component = self.get(component_id)
        if component is None:
            raise KeyError(f"Unknown installable component: {component_id}")
        return component

    def all(self) -> list[InstallableComponent]:
        return list(self._items.values())

    def by_category(self, category: ComponentCategory | str) -> list[InstallableComponent]:
        value = category.value if isinstance(category, ComponentCategory) else str(category or "").strip().lower()
        return [item for item in self._items.values() if item.category.value == value]


__all__ = ["InstallableRegistry"]
