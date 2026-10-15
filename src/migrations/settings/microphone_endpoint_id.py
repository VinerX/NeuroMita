from dataclasses import replace
from domain.audio_input import (
    ASRInputDevice,
    AudioInputCatalog,
    MicrophoneSelection,
    EndpointIdentityStatus,
)
from services.audio_input_contracts import MicrophonePreferences


def _name_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _preferred(catalog: AudioInputCatalog, representation: ASRInputDevice):
    if representation.uid:
        return next(
            (device for device in catalog.devices if device.uid == representation.uid),
            None,
        )
    index = dict(catalog.preferred_indices).get(
        representation.index, representation.index
    )
    return next((device for device in catalog.devices if device.index == index), None)


def resolve_legacy_microphone(
    catalog: AudioInputCatalog, selection: MicrophoneSelection
):
    """Resolve the old name/index format without guessing an ambiguous device."""
    representations = catalog.representations or catalog.devices
    if selection.name:
        matching = [
            device
            for device in representations
            if _name_key(device.name) == _name_key(selection.name)
        ]
        indexed = next(
            (device for device in matching if device.index == selection.index), None
        )
        if indexed is not None:
            return _preferred(catalog, indexed)
        preferred = {
            device.index: device
            for item in matching
            if (device := _preferred(catalog, item)) is not None
        }
        return next(iter(preferred.values())) if len(preferred) == 1 else None
    if selection.index is not None:
        indexed = next(
            (device for device in representations if device.index == selection.index),
            None,
        )
        if indexed is not None:
            return _preferred(catalog, indexed)
    default = next(
        (device for device in representations if device.index == catalog.default_index),
        None,
    )
    if default is not None:
        return _preferred(catalog, default)
    return catalog.devices[0] if catalog.devices else None


def migrate_microphone_endpoint_id(
    preferences: MicrophonePreferences, catalog: AudioInputCatalog
) -> bool:
    """Upgrade one unmodified legacy selection when its endpoint is identifiable."""
    before = preferences.read()
    if before.uid or catalog.identity_status != EndpointIdentityStatus.AVAILABLE:
        return False
    device = resolve_legacy_microphone(catalog, before)
    if device is None or not device.uid or preferences.read() != before:
        return False
    return preferences.write(replace(device.selection, backend=before.backend))
