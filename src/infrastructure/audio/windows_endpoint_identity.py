"""Read opaque Windows endpoint IDs from the same PortAudio device catalog."""

import ctypes
import sys
from functools import lru_cache
from dataclasses import dataclass
from domain.audio_input import EndpointIdentityStatus


@dataclass(frozen=True, slots=True)
class EndpointIdentityRead:
    values: tuple[tuple[int, str], ...] = ()
    status: EndpointIdentityStatus = EndpointIdentityStatus.AVAILABLE
    detail: str = ""


_RPC_E_CHANGED_MODE = -2147417850
_IMMDEVICE_GET_ID_SLOT = 5


@lru_cache(maxsize=4)
def _portaudio_library(path):
    library = ctypes.CDLL(path)
    library.PaWasapi_GetIMMDevice.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    library.PaWasapi_GetIMMDevice.restype = ctypes.c_int
    return library


@lru_cache(maxsize=1)
def _com_library():
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None
    return ole32


def read_windows_endpoint_ids(library_path, indices):
    """Borrow PortAudio IMMDevice pointers and free only the allocated ID strings."""
    if sys.platform != "win32":
        return EndpointIdentityRead(
            status=EndpointIdentityStatus.UNSUPPORTED, detail="Not a Windows backend"
        )
    if not library_path:
        return EndpointIdentityRead(
            status=EndpointIdentityStatus.UNSUPPORTED,
            detail="PortAudio library path is unavailable",
        )
    try:
        library = _portaudio_library(library_path)
        ole32 = _com_library()
        initialized = ole32.CoInitializeEx(None, 0)
        if initialized < 0 and initialized != _RPC_E_CHANGED_MODE:
            return EndpointIdentityRead(
                status=EndpointIdentityStatus.UNAVAILABLE,
                detail=f"COM initialization failed: {initialized}",
            )
        try:
            result = {}
            failures = []
            for index in indices:
                device = ctypes.c_void_p()
                code = library.PaWasapi_GetIMMDevice(index, ctypes.byref(device))
                if code < 0 or not device.value:
                    failures.append(f"PortAudio endpoint {index}: {code}")
                    continue
                table = ctypes.cast(
                    device, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
                ).contents
                get_id = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
                )(table[_IMMDEVICE_GET_ID_SLOT])
                value = ctypes.c_void_p()
                code = get_id(device, ctypes.byref(value))
                if code >= 0 and value.value:
                    try:
                        result[index] = ctypes.wstring_at(value)
                    finally:
                        ole32.CoTaskMemFree(value)
                else:
                    failures.append(f"Windows endpoint {index}: {code}")
            status = EndpointIdentityStatus.AVAILABLE
            if failures:
                status = (
                    EndpointIdentityStatus.PARTIAL
                    if result
                    else EndpointIdentityStatus.UNAVAILABLE
                )
            return EndpointIdentityRead(
                tuple(result.items()), status, "; ".join(failures)
            )
        finally:
            if initialized >= 0:
                ole32.CoUninitialize()
    except AttributeError as error:
        return EndpointIdentityRead(
            status=EndpointIdentityStatus.UNSUPPORTED, detail=str(error)
        )
    except (OSError, ValueError) as error:
        return EndpointIdentityRead(
            status=EndpointIdentityStatus.UNAVAILABLE, detail=str(error)
        )
