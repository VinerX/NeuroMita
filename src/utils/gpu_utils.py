import os
import platform
import re
import subprocess
import threading
import time

from main_logger import logger

_GPU_VENDOR_LOCK = threading.Lock()
_GPU_VENDOR_CACHE: str | None = None
_GPU_VENDOR_TS = 0.0
_GPU_VENDOR_TTL_SEC = 120.0
_GPU_INFO_CACHE: dict[str, str | list[str]] | None = None
_GPU_INFO_TS = 0.0
_GPU_INFO_TTL_SEC = 120.0

_CUDA_INFO_LOCK = threading.Lock()
_CUDA_INFO_CACHE: list[tuple[str, str]] = []
_CUDA_INFO_TS = 0.0
_CUDA_INFO_TTL_SEC = 30.0


def _classify_gpu_vendor(name: str) -> str:
    upper_name = str(name or "").upper()
    if "NVIDIA" in upper_name:
        return "NVIDIA"
    if "AMD" in upper_name or "RADEON" in upper_name:
        return "AMD"
    if "INTEL" in upper_name:
        return "INTEL"
    return "CPU"


def _parse_gpu_names(output: str) -> list[str]:
    names: list[str] = []
    for raw_line in str(output or "").splitlines():
        line = str(raw_line or "").strip()
        if not line or line.lower() == "name":
            continue
        names.append(line)
    return names


def _choose_primary_gpu_name(names: list[str]) -> tuple[str, str]:
    preferred_order = ("NVIDIA", "AMD", "INTEL")
    for vendor in preferred_order:
        for name in names:
            if _classify_gpu_vendor(name) == vendor:
                return vendor, name
    if names:
        fallback_name = names[0]
        return _classify_gpu_vendor(fallback_name), fallback_name
    return "CPU", ""


def get_primary_gpu_info() -> dict[str, str | list[str]]:
    global _GPU_INFO_CACHE, _GPU_INFO_TS, _GPU_VENDOR_CACHE, _GPU_VENDOR_TS

    now = time.time()
    with _GPU_VENDOR_LOCK:
        if (
            _GPU_INFO_CACHE is not None
            and (now - float(_GPU_INFO_TS or 0.0)) < float(_GPU_INFO_TTL_SEC or 120.0)
        ):
            cached = dict(_GPU_INFO_CACHE)
            cached["names"] = list(cached.get("names") or [])
            return cached

    if os.environ.get("TEST_AS_AMD", "").upper() == "TRUE":
        info = {"vendor": "AMD", "name": "AMD (TEST)", "names": ["AMD (TEST)"], "source": "env"}
    elif os.environ.get("TEST_AS_NVIDIA", "").upper() == "TRUE":
        info = {"vendor": "NVIDIA", "name": "NVIDIA (TEST)", "names": ["NVIDIA (TEST)"], "source": "env"}
    elif platform.system() != "Windows":
        info = {"vendor": "CPU", "name": "", "names": [], "source": "non_windows"}
    else:
        info = {"vendor": "CPU", "name": "", "names": [], "source": "fallback"}
        probes: list[tuple[str, str | list[str]]] = [
            ("wmic", "wmic path win32_VideoController get name"),
            (
                "powershell",
                [
                    "powershell",
                    "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
                ],
            ),
        ]
        for source, command in probes:
            try:
                output = subprocess.check_output(
                    command,
                    shell=isinstance(command, str),
                    text=True,
                    stdin=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=2.5,
                ).strip()
                names = _parse_gpu_names(output)
                vendor, name = _choose_primary_gpu_name(names)
                if vendor != "CPU" or name:
                    info = {"vendor": vendor, "name": name, "names": names, "source": source}
                    break
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                continue
            except subprocess.CalledProcessError:
                continue
            except Exception:
                continue

    with _GPU_VENDOR_LOCK:
        _GPU_INFO_CACHE = dict(info)
        _GPU_INFO_TS = now
        _GPU_VENDOR_CACHE = str(info.get("vendor") or "CPU").upper()
        _GPU_VENDOR_TS = now

    cached = dict(info)
    cached["names"] = list(cached.get("names") or [])
    return cached


def get_primary_gpu_name() -> str | None:
    name = str(get_primary_gpu_info().get("name") or "").strip()
    return name or None


def format_primary_gpu_label() -> str:
    info = get_primary_gpu_info()
    vendor = str(info.get("vendor") or "CPU").strip().upper()
    name = str(info.get("name") or "").strip()
    if name:
        return name if vendor in name.upper() else f"{vendor}: {name}"
    return vendor


def check_gpu_provider() -> str:
    """
    Возвращает вендора GPU как строку: "NVIDIA", "AMD", "INTEL" или "CPU".
    Никогда не возвращает None.
    """

    vendor = str(get_primary_gpu_info().get("vendor") or "CPU").strip().upper()
    return vendor or "CPU"


def get_cuda_devices():
    return [device_id for device_id, _name in _get_cuda_device_info()]


def get_gpu_name_by_id(device_id):
    if not isinstance(device_id, str) or not device_id.startswith("cuda:"):
        return None

    try:
        match = re.match(r"cuda:(\d+)", device_id)
        if not match:
            return None
        index = int(match.group(1))
        for current_device_id, gpu_name in _get_cuda_device_info():
            if current_device_id == f"cuda:{index}":
                return gpu_name
        return None
    except Exception as e:
        logger.info(f"Ошибка при получении имени GPU для {device_id}: {e}")
        return None


def _get_cuda_device_info() -> list[tuple[str, str]]:
    global _CUDA_INFO_CACHE, _CUDA_INFO_TS

    now = time.time()
    with _CUDA_INFO_LOCK:
        if (now - float(_CUDA_INFO_TS or 0.0)) < float(_CUDA_INFO_TTL_SEC or 30.0):
            return list(_CUDA_INFO_CACHE)

    if check_gpu_provider() != "NVIDIA":
        with _CUDA_INFO_LOCK:
            _CUDA_INFO_CACHE = []
            _CUDA_INFO_TS = now
        return []

    query_cmd = [
        "nvidia-smi",
        "--query-gpu=index,name",
        "--format=csv,noheader",
    ]

    try:
        output = subprocess.check_output(
            query_cmd,
            stdin=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2.5,
        ).strip()

        devices: list[tuple[str, str]] = []
        for raw_line in output.splitlines():
            line = str(raw_line or "").strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split(",", 1)]
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            devices.append((f"cuda:{int(parts[0])}", parts[1]))

        with _CUDA_INFO_LOCK:
            _CUDA_INFO_CACHE = devices
            _CUDA_INFO_TS = now
        return list(devices)
    except FileNotFoundError:
        logger.info("nvidia-smi не найден. Список CUDA-устройств недоступен.")
    except subprocess.TimeoutExpired:
        logger.info("nvidia-smi не ответил вовремя. Список CUDA-устройств недоступен.")
    except subprocess.CalledProcessError as e:
        details = (e.stderr or "").strip()
        if details:
            logger.info(f"nvidia-smi завершился с ошибкой: {details}")
    except Exception as e:
        logger.info(f"Ошибка при получении списка CUDA-устройств через nvidia-smi: {e}")

    with _CUDA_INFO_LOCK:
        _CUDA_INFO_CACHE = []
        _CUDA_INFO_TS = now
    return []
