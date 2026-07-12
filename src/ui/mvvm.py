from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar


@dataclass(frozen=True, slots=True)
class UiIntent:
    """Marker base for user intents emitted by passive views."""


@dataclass(frozen=True, slots=True)
class UiEffect:
    """Marker base for one-shot presentation effects."""


StateT = TypeVar("StateT")
IntentT = TypeVar("IntentT", bound=UiIntent)
EffectT = TypeVar("EffectT", bound=UiEffect)
KeyT = TypeVar("KeyT")
ValueT = TypeVar("ValueT")


@dataclass(frozen=True, slots=True)
class FrozenMapping(Mapping[KeyT, ValueT], Generic[KeyT, ValueT]):
    """Immutable mapping used inside presentation state snapshots.

    A dedicated type is required here. Encoding mappings as tuples of pairs is
    ambiguous because a legitimate list of pairs has exactly the same shape.
    """

    _items: tuple[tuple[KeyT, ValueT], ...] = ()

    def __iter__(self) -> Iterator[KeyT]:
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, key: KeyT) -> ValueT:
        for current_key, value in self._items:
            if current_key == key:
                return value
        raise KeyError(key)

    def items(self):
        return self._items


class IntentView(Protocol[StateT, IntentT, EffectT]):
    def render(self, state: StateT) -> None: ...

    def handle_effect(self, effect: EffectT) -> None: ...

    def dispatch_intent(self, intent: IntentT) -> None: ...


def immutable_payload(value: Any) -> Any:
    """Convert common mutable containers to immutable presentation values."""

    if isinstance(value, Mapping):
        return FrozenMapping(
            tuple(
            (immutable_payload(key), immutable_payload(item))
            for key, item in value.items()
            )
        )
    if isinstance(value, list):
        return tuple(immutable_payload(item) for item in value)
    if isinstance(value, set):
        return frozenset(immutable_payload(item) for item in value)
    if isinstance(value, tuple):
        return tuple(immutable_payload(item) for item in value)
    return value


def mutable_payload(value: Any) -> Any:
    """Restore containers frozen by :func:`immutable_payload` for rendering."""

    if isinstance(value, FrozenMapping):
        return {
            mutable_payload(key): mutable_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [mutable_payload(item) for item in value]
    if isinstance(value, frozenset):
        return {mutable_payload(item) for item in value}
    return value