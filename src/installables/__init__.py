from __future__ import annotations

__all__ = [
    "build_installable_registry",
    "get_installable_registry",
    "refresh_installable_registry",
]


def __getattr__(name: str):
    if name in __all__:
        from installables import registry_builder

        return getattr(registry_builder, name)
    raise AttributeError(name)
