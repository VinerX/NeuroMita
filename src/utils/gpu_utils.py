# src/utils/gpu_utils.py
import subprocess
import platform
import os
import re
import threading
import time
from main_logger import logger

_GPU_VENDOR_LOCK = threading.Lock()
_GPU_VENDOR_CACHE: str | None = None
_GPU_VENDOR_TS = 0.0
_GPU_VENDOR_TTL_SEC = 120.0
_CUDA_INFO_LOCK = threading.Lock()
_CUDA_INFO_CACHE: list[tuple[str, str]] = []
_CUDA_INFO_TS = 0.0
_CUDA_INFO_TTL_SEC = 30.0


def check_gpu_provider() -> str:
    """
    Возвращает вендора GPU как строку: "NVIDIA", "AMD" или "CPU".
    Никогда не возвращает None.

    На Windows пытается определить NVIDIA/AMD через WMIC, затем через PowerShell.
    Если определить не удалось — возвращает "CPU".
    """

    global _GPU_VENDOR_CACHE, _GPU_VENDOR_TS

    now = time.time()
    with _GPU_VENDOR_LOCK:
        if (now - float(_GPU_VENDOR_TS or 0.0)) < float(_GPU_VENDOR_TTL_SEC or 120.0) and _GPU_VENDOR_CACHE:
            return _GPU_VENDOR_CACHE

    # тестовые принудительные режимы
    if os.environ.get('TEST_AS_AMD', '').upper() == 'TRUE':
        with _GPU_VENDOR_LOCK:
            _GPU_VENDOR_CACHE = "AMD"
            _GPU_VENDOR_TS = now
        return "AMD"

    if os.environ.get('TEST_AS_NVIDIA', '').upper() == 'TRUE':
        with _GPU_VENDOR_LOCK:
            _GPU_VENDOR_CACHE = "NVIDIA"
            _GPU_VENDOR_TS = now
        return "NVIDIA"

    if platform.system() != "Windows":
        with _GPU_VENDOR_LOCK:
            _GPU_VENDOR_CACHE = "CPU"
            _GPU_VENDOR_TS = now
        return "CPU"

    def parse_output(output: str) -> str | None:
        out = (output or "").upper()
        if "NVIDIA" in out:
            return "NVIDIA"
        if "AMD" in out or "RADEON" in out:
            return "AMD"
        return None

    vendor: str | None = None

    # 1) WMIC
    try:
        output = subprocess.check_output(
            "wmic path win32_VideoController get name",
            shell=True,
            text=True,
            stdin=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=2.0
        ).strip()

        vendor = parse_output(output)
        if vendor:
            with _GPU_VENDOR_LOCK:
                _GPU_VENDOR_CACHE = vendor
                _GPU_VENDOR_TS = now
            return vendor

    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        pass
    except subprocess.CalledProcessError:
        pass
    except Exception:
        pass

    # 2) PowerShell
    try:
        command = [
            "powershell",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"
        ]
        output = subprocess.check_output(
            command,
            stdin=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2.5
        ).strip()

        vendor = parse_output(output)
        if vendor:
            with _GPU_VENDOR_LOCK:
                _GPU_VENDOR_CACHE = vendor
                _GPU_VENDOR_TS = now
            return vendor

    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass

    # fallback: стабильно возвращаем CPU
    with _GPU_VENDOR_LOCK:
        _GPU_VENDOR_CACHE = "CPU"
        _GPU_VENDOR_TS = now
    return "CPU"


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
