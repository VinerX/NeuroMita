from core.services import services
from core.cuda_precision_policy import CudaHalfPrecisionDecision, evaluate_rvc_half_precision
from services.contracts import HardwareInventoryService
from services.hardware_inventory_service import WindowsHardwareInventoryService

_FALLBACK_HARDWARE = WindowsHardwareInventoryService()

def _inventory() -> HardwareInventoryService:
    return services().get_optional(HardwareInventoryService) or _FALLBACK_HARDWARE


def get_hardware_snapshot() -> dict:
    return dict(_inventory().snapshot() or {})


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


def get_cuda_device_record(device_id: str = "cuda:0") -> dict:
    raw_device = str(device_id or "cuda:0").strip().lower()
    if raw_device == "cuda":
        ordinal = 0
    elif raw_device.startswith("cuda:"):
        try:
            ordinal = int(raw_device.split(":", 1)[1])
        except (TypeError, ValueError):
            return {}
    else:
        return {}

    snapshot = _inventory().snapshot()
    cuda = snapshot.get("cuda") if isinstance(snapshot, dict) else {}
    for index, item in enumerate((cuda or {}).get("devices", [])):
        if not isinstance(item, dict):
            continue
        current_ordinal = item.get("ordinal", index)
        try:
            if int(current_ordinal) == ordinal:
                return dict(item)
        except (TypeError, ValueError):
            continue
    return {}


def get_rvc_half_precision_decision(device_id: str = "cuda:0") -> CudaHalfPrecisionDecision:
    raw_device = str(device_id or "cuda:0").strip().lower()
    if not raw_device.startswith("cuda"):
        return evaluate_rvc_half_precision(
            vendor="CPU",
            compute_capability=None,
            gpu_name="",
        )

    snapshot = _inventory().snapshot()
    record = get_cuda_device_record(raw_device)
    primary = snapshot.get("primary") if isinstance(snapshot, dict) else {}

    compute_capability = None
    if record:
        major = record.get("compute_major")
        minor = record.get("compute_minor")
        if major is not None and minor is not None:
            compute_capability = (major, minor)
        else:
            compute_capability = record.get("compute_capability")

    gpu_name = str(record.get("name") or (primary or {}).get("name") or "")
    return evaluate_rvc_half_precision(
        vendor="NVIDIA",
        compute_capability=compute_capability,
        gpu_name=gpu_name,
    )


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
