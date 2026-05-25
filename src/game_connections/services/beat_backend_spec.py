from __future__ import annotations

import os
import platform
import subprocess
from typing import Any

from core.backends import BACKEND_NUMPY_SPEC, BackendKind, get_backend_service
from core.install_requirements import InstallRequirement, check_requirements


def _(ru_text: str, en_text: str = "") -> str:
    language = str(os.environ.get("NEUROMITA_LANGUAGE") or "").strip().upper()
    if language == "EN" and en_text:
        return en_text
    return ru_text


def _detect_gpu_vendor() -> str:
    forced_amd = str(os.environ.get("TEST_AS_AMD") or "").strip().upper() == "TRUE"
    if forced_amd:
        return "AMD"

    forced_nvidia = str(os.environ.get("TEST_AS_NVIDIA") or "").strip().upper() == "TRUE"
    if forced_nvidia:
        return "NVIDIA"

    if platform.system() != "Windows":
        return "CPU"

    def _parse_vendor(output: str) -> str | None:
        upper = str(output or "").upper()
        if "NVIDIA" in upper:
            return "NVIDIA"
        if "AMD" in upper or "RADEON" in upper:
            return "AMD"
        return None

    commands = (
        "wmic path win32_VideoController get name",
        [
            "powershell",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ],
    )
    for command in commands:
        try:
            output = subprocess.check_output(
                command,
                shell=isinstance(command, str),
                stdin=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2.5,
            ).strip()
        except Exception:
            continue

        vendor = _parse_vendor(output)
        if vendor:
            return vendor

    return "CPU"


BACKEND_AUTO = "auto"
BACKEND_BEAT_THIS = "beat_this"
BACKEND_LIBROSA = "librosa"
BACKEND_DSP = "dsp_fallback"

BEAT_NUMPY_SPEC = BACKEND_NUMPY_SPEC
BEAT_LIBROSA_SPEC = "librosa==0.9.1"
BEAT_JOBLIB_SPEC = "joblib"
BEAT_NUMBA_SPEC = "numba==0.60.0"
BEAT_SCIPY_SPEC = "scipy>=1.10,<1.14"
BEAT_SKLEARN_SPEC = "scikit-learn>=1.1,<1.6"
BEAT_POOCH_SPEC = "pooch>=1.6,<2"
BEAT_LLVMLITE_SPEC = "llvmlite==0.43.0"
BEAT_THIS_SPEC = "beat-this"

BEAT_SHARED_PACKAGES = [
    BEAT_NUMPY_SPEC,
    "soxr",
    BEAT_LIBROSA_SPEC,
    "audioread",
    "decorator",
    BEAT_JOBLIB_SPEC,
    BEAT_NUMBA_SPEC,
    BEAT_LLVMLITE_SPEC,
    BEAT_SCIPY_SPEC,
    BEAT_SKLEARN_SPEC,
    "threadpoolctl",
    BEAT_POOCH_SPEC,
    "packaging",
    "platformdirs",
    "requests",
    "certifi",
    "charset-normalizer",
    "idna",
    "urllib3",
    "resampy",
    "soundfile",
    "cffi",
    "pycparser",
]

BEAT_SHARED_PACKAGES_NO_NUMPY = [
    pkg for pkg in BEAT_SHARED_PACKAGES
    if str(pkg).strip().lower() != str(BEAT_NUMPY_SPEC).strip().lower()
]

BEAT_THIS_PACKAGES = [
    BEAT_THIS_SPEC,
    "tqdm",
    "einops",
    "rotary-embedding-torch",
]

BEAT_BACKEND_CHOICES = (
    BACKEND_AUTO,
    BACKEND_BEAT_THIS,
    BACKEND_LIBROSA,
    BACKEND_DSP,
)


def normalize_backend_choice(choice: str | None) -> str:
    value = str(choice or "").strip().lower()
    if value not in BEAT_BACKEND_CHOICES:
        return BACKEND_AUTO
    return value


def backend_display_name(backend_id: str) -> str:
    mapping = {
        BACKEND_AUTO: _("Авто", "Auto"),
        BACKEND_BEAT_THIS: "Beat This",
        BACKEND_LIBROSA: "Librosa",
        BACKEND_DSP: _("DSP fallback", "DSP fallback"),
    }
    return mapping.get(normalize_backend_choice(backend_id), str(backend_id or BACKEND_AUTO))


def backend_attempt_order(preferred_backend: str | None) -> tuple[str, ...]:
    backend_id = normalize_backend_choice(preferred_backend)
    if backend_id == BACKEND_BEAT_THIS:
        return (BACKEND_BEAT_THIS, BACKEND_LIBROSA, BACKEND_DSP)
    if backend_id == BACKEND_LIBROSA:
        return (BACKEND_LIBROSA, BACKEND_DSP)
    if backend_id == BACKEND_DSP:
        return (BACKEND_DSP,)
    return (BACKEND_BEAT_THIS, BACKEND_LIBROSA, BACKEND_DSP)


def resolve_backend_choice(preferred_backend: str | None, availability: dict[str, bool]) -> str:
    for backend_id in backend_attempt_order(preferred_backend):
        if availability.get(backend_id, False):
            return backend_id
    return BACKEND_DSP


def build_beat_ctx(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(ctx or {})
    if not data.get("gpu_vendor"):
        data["gpu_vendor"] = _detect_gpu_vendor()
    data["libs_dir"] = os.environ.get("NEUROMITA_LIB_DIR")
    return data


def _beat_this_backend_kind(ctx: dict[str, Any]) -> BackendKind:
    return get_backend_service().preferred_torch_kind(ctx)


def _beat_this_requirements(ctx: dict[str, Any]) -> list[InstallRequirement]:
    backend_kind = _beat_this_backend_kind(ctx)
    return [
        InstallRequirement(
            id=f"backend_{backend_kind.value}",
            kind="backend",
            backend_kind=backend_kind,
            required=True,
        ),
        InstallRequirement(id="beat_this_module", kind="python_module", module="beat_this", required=True),
        InstallRequirement(id="tqdm", kind="python_dist", spec="tqdm", required=True),
        InstallRequirement(id="einops", kind="python_dist", spec="einops", required=True),
        InstallRequirement(
            id="rotary_embedding_torch",
            kind="python_dist",
            spec="rotary-embedding-torch",
            required=True,
        ),
        InstallRequirement(id="soxr", kind="python_dist", spec="soxr", required=True),
    ]


def _librosa_requirements() -> list[InstallRequirement]:
    return [
        InstallRequirement(id="librosa_module", kind="python_module", module="librosa", required=True),
        InstallRequirement(id="joblib_module", kind="python_module", module="joblib", required=True),
        InstallRequirement(id="sklearn_module", kind="python_module", module="sklearn", required=True),
        InstallRequirement(id="pooch_module", kind="python_module", module="pooch", required=True),
        InstallRequirement(id="scipy_module", kind="python_module", module="scipy", required=True),
        InstallRequirement(id="soundfile_module", kind="python_module", module="soundfile", required=True),
        InstallRequirement(id="soxr", kind="python_dist", spec="soxr", required=True),
        InstallRequirement(id="numpy", kind="python_dist", spec=BEAT_NUMPY_SPEC, required=True),
        InstallRequirement(id="librosa_dist", kind="python_dist", spec=BEAT_LIBROSA_SPEC, required=True),
        InstallRequirement(id="joblib_dist", kind="python_dist", spec=BEAT_JOBLIB_SPEC, required=True),
        InstallRequirement(id="numba", kind="python_dist", spec=BEAT_NUMBA_SPEC, required=True),
        InstallRequirement(id="llvmlite", kind="python_dist", spec=BEAT_LLVMLITE_SPEC, required=True),
        InstallRequirement(id="scipy_dist", kind="python_dist", spec=BEAT_SCIPY_SPEC, required=True),
        InstallRequirement(id="sklearn_dist", kind="python_dist", spec=BEAT_SKLEARN_SPEC, required=True),
        InstallRequirement(id="pooch_dist", kind="python_dist", spec=BEAT_POOCH_SPEC, required=True),
        InstallRequirement(id="soundfile_dist", kind="python_dist", spec="soundfile", required=True),
    ]


def _build_backend_entry(
    backend_id: str,
    *,
    available: bool,
    installed: bool,
    missing_required: list[str] | None = None,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": backend_id,
        "label": backend_display_name(backend_id),
        "available": bool(available),
        "installed": bool(installed),
        "ready": False,
        "missing_required": list(missing_required or []),
        "details": list(details or []),
    }


def get_backend_status_snapshot(preferred_backend: str | None, *, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    beat_ctx = build_beat_ctx(ctx)
    selected = normalize_backend_choice(preferred_backend)
    runtime_status = get_backend_service().get_status(_beat_this_backend_kind(beat_ctx), ctx=beat_ctx)
    runtime_status_detail = runtime_status.as_requirement_detail()

    beat_this_checked = check_requirements(_beat_this_requirements(beat_ctx), ctx=beat_ctx)
    beat_this_missing = list(beat_this_checked.get("missing_required") or [])
    beat_this_available = bool(beat_this_checked.get("ok"))
    beat_this_details = list(beat_this_checked.get("details") or [])

    librosa_checked = check_requirements(_librosa_requirements(), ctx=beat_ctx)
    librosa_available = bool(librosa_checked.get("ok"))

    backends = {
        BACKEND_BEAT_THIS: _build_backend_entry(
            BACKEND_BEAT_THIS,
            available=beat_this_available,
            installed=beat_this_available,
            missing_required=beat_this_missing,
            details=beat_this_details,
        ),
        BACKEND_LIBROSA: _build_backend_entry(
            BACKEND_LIBROSA,
            available=librosa_available,
            installed=librosa_available,
            missing_required=list(librosa_checked.get("missing_required") or []),
            details=list(librosa_checked.get("details") or []),
        ),
        BACKEND_DSP: _build_backend_entry(
            BACKEND_DSP,
            available=True,
            installed=True,
            missing_required=[],
            details=[],
        ),
    }

    resolved_backend = resolve_backend_choice(
        selected,
        {
            BACKEND_BEAT_THIS: backends[BACKEND_BEAT_THIS]["available"],
            BACKEND_LIBROSA: backends[BACKEND_LIBROSA]["available"],
            BACKEND_DSP: True,
        },
    )

    return {
        "preferred_backend": selected,
        "resolved_backend": resolved_backend,
        "active_backend": resolved_backend,
        "gpu_vendor": beat_ctx.get("gpu_vendor"),
        "runtime_backend": runtime_status.as_dict(),
        "torch": runtime_status_detail,
        "backends": backends,
    }


def backend_install_packages(target_backend: str | None) -> list[str]:
    normalized = normalize_backend_choice(target_backend)
    if normalized == BACKEND_DSP:
        return []
    if normalized == BACKEND_LIBROSA:
        return list(BEAT_SHARED_PACKAGES)
    packages = list(BEAT_SHARED_PACKAGES_NO_NUMPY)
    packages.extend(BEAT_THIS_PACKAGES)
    seen: set[str] = set()
    ordered: list[str] = []
    for pkg in packages:
        key = str(pkg).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(pkg)
    return ordered
