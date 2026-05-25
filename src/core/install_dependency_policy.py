from __future__ import annotations

from typing import Iterable


MANAGED_RUNTIME_DISTS: tuple[str, ...] = (
    "torch",
    "torchaudio",
    "torchvision",
    "torchtext",
    "torchdata",
    "numpy",
)


def managed_runtime_dists(extra: Iterable[str] | None = None) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for dist_name in (*MANAGED_RUNTIME_DISTS, *(extra or ())):
        value = str(dist_name or "").strip()
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        names.append(value)
    return tuple(names)
