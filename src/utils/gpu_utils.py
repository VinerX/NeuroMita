from core.services import services
from services.contracts import HardwareInventoryService
from services.hardware_inventory_service import WindowsHardwareInventoryService

_FALLBACK_HARDWARE = WindowsHardwareInventoryService()

def _inventory() -> HardwareInventoryService:
    return services().get_optional(HardwareInventoryService) or _FALLBACK_HARDWARE


def get_primary_gpu_info() -> dict[str, str | list[str]]:
    snapshot = _inventory().snapshot()
    primary = snapshot.get("primary") if isinstance(snapshot, dict) else None
    adapters = snapshot.get("adapters") if isinstance(snapshot, dict) else []
    names = [
        str(item.get("name") or "")
        for item in adapters or []
        if item.get("name")
    ]
    info = {
        "vendor": str(snapshot.get("vendor") or "CPU"),
        "name": str((primary or {}).get("name") or ""),
        "names": names,
        "source": str(snapshot.get("source") or "hardware_inventory"),
    }

    return info


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

    for current_device_id, gpu_name in _get_cuda_device_info():
        if current_device_id == device_id:
            return gpu_name
    return None


def _get_cuda_device_info() -> list[tuple[str, str]]:
    snapshot = _inventory().snapshot()
    cuda = snapshot.get("cuda") if isinstance(snapshot, dict) else {}
    devices = [
        (
            f"cuda:{int(item.get('ordinal', index))}",
            str(item.get("name") or f"CUDA {index}"),
        )
        for index, item in enumerate((cuda or {}).get("devices", []))
    ]
    return list(devices)
