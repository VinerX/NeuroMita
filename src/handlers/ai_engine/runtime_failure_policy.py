from __future__ import annotations

import os
import sys
from typing import Any


CUDA_CONTEXT_POISONED_EXIT_CODE = 70

_FATAL_CUDA_MARKERS = (
    "device-side assert triggered",
    "an illegal memory access was encountered",
    "misaligned address",
    "illegal instruction",
    "invalid program counter",
    "unspecified launch failure",
    "context is destroyed",
    "context has been destroyed",
)


def _exception_text(exc: BaseException | None) -> str:
    if exc is None:
        return ""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(str(current))
        current = current.__cause__ or current.__context__
    return "\n".join(parts).lower()


def is_cuda_context_poisoned(exc: BaseException | None) -> bool:
    text = _exception_text(exc)
    return any(marker in text for marker in _FATAL_CUDA_MARKERS)


def probe_cuda_context() -> BaseException | None:
    """Probe an already-loaded CUDA runtime without importing/initializing it.

    A poisoned context often survives behind a vendor/library exception that
    swallowed the original CUDA error. Synchronizing only on an error path
    surfaces that sticky failure without imposing a sync on successful calls.
    """

    torch = sys.modules.get("torch")
    cuda = getattr(torch, "cuda", None) if torch is not None else None
    if cuda is None:
        return None
    try:
        if not bool(cuda.is_available()):
            return None
    except Exception:
        return None

    try:
        cuda.synchronize()
    except BaseException as exc:
        return exc if is_cuda_context_poisoned(exc) else None
    return None


def should_probe_after_result(result: Any) -> bool:
    # Service wrappers in this codebase sometimes convert native/runtime
    # failures into False/None. Probe only these failure-shaped results, never
    # the successful hot path.
    return result is None or result is False


def terminate_poisoned_worker() -> None:
    # CUDA fatal errors invalidate process-owned runtime state. Do not run
    # graceful model cleanup in that process; the parent supervisor will spawn
    # a fresh worker and replay registered runtime validations.
    os._exit(CUDA_CONTEXT_POISONED_EXIT_CODE)
