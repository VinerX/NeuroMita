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
    cuda_devices = []
    try:
        import torch
        if torch.cuda.is_available():
            device_count = torch.cuda.device_count()
            for i in range(int(device_count or 0)):
                cuda_devices.append(f"cuda:{i}")
    except ImportError:
        logger.info("PyTorch не найден. Невозможно определить CUDA устройства через PyTorch.")
    except Exception as e:
        logger.info(f"Неожиданная ошибка при проверке CUDA устройств через PyTorch: {e}")

    return cuda_devices


def get_gpu_name_by_id(device_id):
    if not isinstance(device_id, str) or not device_id.startswith("cuda:"):
        return None

    try:
        match = re.match(r"cuda:(\d+)", device_id)
        if not match:
            return None
        index = int(match.group(1))

        import torch
        if torch.cuda.is_available() and index < torch.cuda.device_count():
            return torch.cuda.get_device_name(index)
        return None
    except ImportError:
        logger.info("PyTorch не найден. Невозможно получить имя GPU.")
        return None
    except Exception as e:
        logger.info(f"Ошибка при получении имени GPU для {device_id}: {e}")
        return None