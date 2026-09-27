from __future__ import annotations
from core.error_utils import format_exception

import ctypes
import os
import platform
import struct
import threading
import time
import uuid
from typing import Any

from services.contracts import HardwareInventoryService


_VENDORS = {
    0x10DE: "NVIDIA",
    0x1002: "AMD",
    0x8086: "INTEL",
}
_DXGI_ERROR_NOT_FOUND = 0x887A0002
_DXGI_ADAPTER_FLAG_SOFTWARE = 2


class _GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    )

    @classmethod
    def from_text(cls, value: str) -> "_GUID":
        raw = uuid.UUID(value).bytes_le
        return cls.from_buffer_copy(raw)


class _LUID(ctypes.Structure):
    _fields_ = (("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32))

    def as_bytes(self) -> bytes:
        return struct.pack("<Ii", int(self.LowPart), int(self.HighPart))


class _DXGIAdapterDesc1(ctypes.Structure):
    _fields_ = (
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", ctypes.c_uint32),
        ("DeviceId", ctypes.c_uint32),
        ("SubSysId", ctypes.c_uint32),
        ("Revision", ctypes.c_uint32),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _LUID),
        ("Flags", ctypes.c_uint32),
    )


def _com_method(pointer: ctypes.c_void_p, index: int, restype, *argtypes):
    vtable = ctypes.cast(
        pointer,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents
    address = vtable[index]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(address)


def _release(pointer: ctypes.c_void_p) -> None:
    if pointer:
        _com_method(pointer, 2, ctypes.c_ulong)(pointer)


def _dxgi_adapters() -> list[dict[str, Any]]:
    if platform.system() != "Windows":
        return []

    dxgi = ctypes.WinDLL("dxgi.dll")
    create_factory = dxgi.CreateDXGIFactory1
    create_factory.argtypes = (ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
    create_factory.restype = ctypes.c_long

    iid = _GUID.from_text("770aae78-f26f-4dba-a829-253c83d1b387")
    factory = ctypes.c_void_p()
    hr = int(create_factory(ctypes.byref(iid), ctypes.byref(factory)))
    if hr < 0 or not factory:
        raise OSError(f"CreateDXGIFactory1 failed: 0x{hr & 0xFFFFFFFF:08X}")

    adapters: list[dict[str, Any]] = []
    try:
        enum_adapters = _com_method(
            factory,
            12,
            ctypes.c_long,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        )
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            hr = int(enum_adapters(factory, index, ctypes.byref(adapter)))
            if (hr & 0xFFFFFFFF) == _DXGI_ERROR_NOT_FOUND:
                break
            if hr < 0:
                raise OSError(f"EnumAdapters1 failed: 0x{hr & 0xFFFFFFFF:08X}")
            try:
                desc = _DXGIAdapterDesc1()
                get_desc = _com_method(
                    adapter,
                    10,
                    ctypes.c_long,
                    ctypes.POINTER(_DXGIAdapterDesc1),
                )
                desc_hr = int(get_desc(adapter, ctypes.byref(desc)))
                if desc_hr >= 0 and not (int(desc.Flags) & _DXGI_ADAPTER_FLAG_SOFTWARE):
                    vendor_id = int(desc.VendorId)
                    adapters.append(
                        {
                            "index": index,
                            "name": str(desc.Description).strip(),
                            "vendor": _VENDORS.get(vendor_id, "UNKNOWN"),
                            "vendor_id": f"{vendor_id:04x}",
                            "device_id": f"{int(desc.DeviceId):04x}",
                            "subsystem_id": f"{int(desc.SubSysId):08x}",
                            "revision": int(desc.Revision),
                            "dedicated_vram_bytes": int(desc.DedicatedVideoMemory),
                            "shared_memory_bytes": int(desc.SharedSystemMemory),
                            "luid": desc.AdapterLuid.as_bytes().hex(),
                            "source": "dxgi",
                        }
                    )
            finally:
                _release(adapter)
            index += 1
    finally:
        _release(factory)
    return adapters


def _nvidia_driver_inventory() -> dict[str, Any]:
    result: dict[str, Any] = {"available": False, "devices": []}
    if platform.system() != "Windows":
        return result
    try:
        cuda = ctypes.WinDLL("nvcuda.dll")
    except OSError as exc:
        result["error"] = format_exception(exc)
        return result

    def bind(name: str, argtypes, restype=ctypes.c_int):
        fn = getattr(cuda, name)
        fn.argtypes = argtypes
        fn.restype = restype
        return fn

    try:
        cu_init = bind("cuInit", (ctypes.c_uint,))
        cu_count = bind("cuDeviceGetCount", (ctypes.POINTER(ctypes.c_int),))
        cu_get = bind("cuDeviceGet", (ctypes.POINTER(ctypes.c_int), ctypes.c_int))
        cu_attr = bind(
            "cuDeviceGetAttribute",
            (ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int),
        )
        cu_name = bind("cuDeviceGetName", (ctypes.c_void_p, ctypes.c_int, ctypes.c_int))
        cu_driver = bind("cuDriverGetVersion", (ctypes.POINTER(ctypes.c_int),))
    except (AttributeError, OSError) as exc:
        result["error"] = format_exception(exc)
        return result

    # LUID is useful for joining the CUDA-driver enumeration with DXGI, but it
    # is not required to discover CUDA ordinals.  Keep it optional so an older
    # driver/API surface cannot hide otherwise usable cuda:N devices.
    try:
        cu_luid = bind(
            "cuDeviceGetLuid",
            (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.c_int),
        )
    except (AttributeError, OSError):
        cu_luid = None

    code = int(cu_init(0))
    if code != 0:
        result["error"] = f"cuInit failed with code {code}"
        return result

    driver_version = ctypes.c_int()
    if int(cu_driver(ctypes.byref(driver_version))) == 0:
        raw = int(driver_version.value)
        result["driver_version"] = f"{raw // 1000}.{(raw % 1000) // 10}"

    count = ctypes.c_int()
    if int(cu_count(ctypes.byref(count))) != 0:
        result["error"] = "cuDeviceGetCount failed"
        return result

    devices: list[dict[str, Any]] = []
    for ordinal in range(max(0, int(count.value))):
        device = ctypes.c_int()
        if int(cu_get(ctypes.byref(device), ordinal)) != 0:
            continue
        major = ctypes.c_int()
        minor = ctypes.c_int()
        name = ctypes.create_string_buffer(256)
        luid = ctypes.create_string_buffer(8)
        node_mask = ctypes.c_uint()
        cu_attr(ctypes.byref(major), 75, device.value)
        cu_attr(ctypes.byref(minor), 76, device.value)
        cu_name(name, len(name), device.value)
        luid_hex = ""
        if cu_luid is not None and int(cu_luid(luid, ctypes.byref(node_mask), device.value)) == 0:
            luid_hex = bytes(luid.raw).hex()
        devices.append(
            {
                "ordinal": ordinal,
                "device": f"cuda:{ordinal}",
                "name": name.value.decode("utf-8", errors="replace"),
                "compute_capability": f"sm_{major.value}{minor.value}",
                "compute_major": int(major.value),
                "compute_minor": int(minor.value),
                "luid": luid_hex,
                "node_mask": int(node_mask.value),
            }
        )
    result["available"] = True
    result["devices"] = devices
    return result


def _normalized_adapter_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _attach_cuda_devices_to_adapters(
    adapters: list[dict[str, Any]],
    cuda_devices: list[dict[str, Any]],
) -> None:
    """Attach CUDA metadata to DXGI adapters without making the join fatal.

    LUID is the authoritative Windows identity when available.  A unique
    normalized-name match is only a fallback for drivers where cuDeviceGetLuid
    is unavailable; ambiguous duplicate names are deliberately left unmatched.
    """

    by_luid = {
        str(item.get("luid") or "").lower(): item
        for item in cuda_devices
        if str(item.get("luid") or "").strip()
    }
    unmatched = {int(item.get("ordinal", index)): item for index, item in enumerate(cuda_devices)}

    for adapter in adapters:
        luid = str(adapter.get("luid") or "").lower()
        match = by_luid.get(luid) if luid else None
        if match is None:
            continue
        adapter["cuda"] = dict(match)
        try:
            unmatched.pop(int(match.get("ordinal")), None)
        except (TypeError, ValueError):
            pass

    if not unmatched:
        return

    # Name fallback is safe only when both sides have exactly one candidate
    # with that name.  This avoids pairing the wrong board in homogeneous
    # multi-GPU systems.
    adapter_names: dict[str, list[dict[str, Any]]] = {}
    for adapter in adapters:
        if adapter.get("cuda") or str(adapter.get("vendor") or "").upper() != "NVIDIA":
            continue
        key = _normalized_adapter_name(adapter.get("name"))
        if key:
            adapter_names.setdefault(key, []).append(adapter)

    cuda_names: dict[str, list[dict[str, Any]]] = {}
    for item in unmatched.values():
        key = _normalized_adapter_name(item.get("name"))
        if key:
            cuda_names.setdefault(key, []).append(item)

    for name, matching_adapters in adapter_names.items():
        matching_cuda = cuda_names.get(name, [])
        if len(matching_adapters) != 1 or len(matching_cuda) != 1:
            continue
        matching_adapters[0]["cuda"] = dict(matching_cuda[0])


def _build_accelerator_descriptors(
    adapters: list[dict[str, Any]],
    cuda_devices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build an additive, backend-neutral view of physical accelerators.

    This is intentionally a snapshot schema rather than a runtime routing
    abstraction.  Consumers can show all physical GPUs while CUDA-capable
    NVIDIA adapters additionally expose their exact cuda:N address.
    """

    result: list[dict[str, Any]] = []
    matched_cuda_ordinals: set[int] = set()
    for adapter in adapters:
        cuda = adapter.get("cuda") if isinstance(adapter.get("cuda"), dict) else {}
        ordinal: int | None = None
        if cuda:
            try:
                ordinal = int(cuda.get("ordinal"))
                matched_cuda_ordinals.add(ordinal)
            except (TypeError, ValueError):
                ordinal = None
        result.append(
            {
                "id": (
                    f"dxgi-luid:{adapter.get('luid')}"
                    if adapter.get("luid")
                    else f"dxgi:{adapter.get('index', len(result))}"
                ),
                "name": str(adapter.get("name") or "GPU"),
                "vendor": str(adapter.get("vendor") or "UNKNOWN"),
                "dedicated_vram_bytes": int(adapter.get("dedicated_vram_bytes") or 0),
                "dxgi_index": adapter.get("index"),
                "cuda_device": f"cuda:{ordinal}" if ordinal is not None else None,
                "compute_capability": cuda.get("compute_capability") if cuda else None,
                "source": str(adapter.get("source") or "dxgi"),
            }
        )

    # If DXGI failed, or LUID/name association was impossible, CUDA discovery
    # is still valuable.  Add those devices rather than hiding them.
    for index, cuda in enumerate(cuda_devices):
        try:
            ordinal = int(cuda.get("ordinal", index))
        except (TypeError, ValueError):
            continue
        if ordinal in matched_cuda_ordinals:
            continue
        result.append(
            {
                "id": f"cuda:{ordinal}",
                "name": str(cuda.get("name") or f"CUDA {ordinal}"),
                "vendor": "NVIDIA",
                "dedicated_vram_bytes": 0,
                "dxgi_index": None,
                "cuda_device": f"cuda:{ordinal}",
                "compute_capability": cuda.get("compute_capability"),
                "source": "cuda_driver",
            }
        )
    return result


class WindowsHardwareInventoryService(HardwareInventoryService):
    def __init__(self, *, ttl_seconds: float = 120.0) -> None:
        self._ttl_seconds = max(1.0, float(ttl_seconds))
        self._lock = threading.RLock()
        self._cached: dict[str, Any] | None = None
        self._cached_at = 0.0

    def snapshot(self, *, refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if (
                not refresh
                and self._cached is not None
                and now - self._cached_at < self._ttl_seconds
            ):
                return self._copy(self._cached)

            snapshot = self._probe()
            self._cached = snapshot
            self._cached_at = now
            return self._copy(snapshot)

    @staticmethod
    def _copy(snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            **snapshot,
            "adapters": [
                {
                    **dict(item),
                    **(
                        {"cuda": dict(item["cuda"])}
                        if isinstance(item.get("cuda"), dict)
                        else {}
                    ),
                }
                for item in snapshot.get("adapters", [])
            ],
            "accelerators": [dict(item) for item in snapshot.get("accelerators", [])],
            "cuda": {
                **dict(snapshot.get("cuda") or {}),
                "devices": [
                    dict(item)
                    for item in (snapshot.get("cuda") or {}).get("devices", [])
                ],
            },
        }

    def _probe(self) -> dict[str, Any]:
        error = ""
        if os.environ.get("TEST_AS_AMD", "").upper() == "TRUE":
            adapters = [{"index": 0, "name": "AMD (TEST)", "vendor": "AMD", "vendor_id": "1002", "source": "env"}]
            cuda = {"available": False, "devices": []}
        elif os.environ.get("TEST_AS_NVIDIA", "").upper() == "TRUE":
            adapters = [{"index": 0, "name": "NVIDIA (TEST)", "vendor": "NVIDIA", "vendor_id": "10de", "source": "env"}]
            cuda = {"available": True, "devices": []}
        else:
            try:
                adapters = _dxgi_adapters()
            except Exception as exc:
                adapters = []
                error = format_exception(exc)
            try:
                # CUDA Driver API enumeration does not import torch and gives
                # the actual CUDA ordinal namespace (cuda:0, cuda:1, ...).
                # Probe independently from DXGI so a DXGI failure does not also
                # erase CUDA information from the hardware snapshot.
                cuda = _nvidia_driver_inventory()
            except Exception as exc:
                cuda = {"available": False, "devices": [], "error": format_exception(exc)}

        _attach_cuda_devices_to_adapters(adapters, list(cuda.get("devices") or []))
        accelerators = _build_accelerator_descriptors(
            adapters,
            list(cuda.get("devices") or []),
        )

        primary = next(
            (item for vendor in ("NVIDIA", "AMD", "INTEL") for item in adapters if item.get("vendor") == vendor),
            None,
        )
        return {
            "platform": platform.system(),
            "source": "dxgi+ctypes" if platform.system() == "Windows" else "unsupported",
            "adapters": adapters,
            "accelerators": accelerators,
            "primary": dict(primary) if primary is not None else None,
            "vendor": str((primary or {}).get("vendor") or "CPU"),
            "cuda": cuda,
            "error": error or ("" if adapters or platform.system() != "Windows" else "DXGI did not return a hardware adapter"),
        }
