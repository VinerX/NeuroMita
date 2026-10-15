from dataclasses import replace

from domain.audio_input import (
    ASRInputDevice,
    AudioInputCatalog,
    MicrophoneSelection,
    EndpointIdentityStatus,
)
from migrations.settings.microphone_endpoint_id import (
    migrate_microphone_endpoint_id,
    resolve_legacy_microphone,
)
from services.audio_input_contracts import (
    AudioInputCatalogProvider,
    MicrophonePreferences,
    AudioInputCatalogUnavailable,
    MicrophoneIdentityUnavailable,
    MicrophoneBackendUnavailable,
)
from main_logger import logger
from threading import RLock


def resolve_microphone(
    catalog: AudioInputCatalog, selection: MicrophoneSelection
) -> ASRInputDevice | None:
    if selection.backend:
        automatic = resolve_microphone(catalog, replace(selection, backend=""))
        if automatic is None:
            return None
        candidates = microphone_backends(catalog, automatic)
        found = next((d for d in candidates if d.host_api == selection.backend), None)
        if found is None:
            raise MicrophoneBackendUnavailable(selection.backend)
        return found
    if selection.uid:
        found = next(
            (device for device in catalog.devices if device.uid == selection.uid), None
        )
        if (
            found is None
            and catalog.identity_status != EndpointIdentityStatus.AVAILABLE
        ):
            raise MicrophoneIdentityUnavailable(catalog.identity_detail)
        return found
    return resolve_legacy_microphone(catalog, selection)


def microphone_backends(catalog: AudioInputCatalog, device: ASRInputDevice):
    compatible = catalog.compatible_representations or catalog.devices
    preferred = dict(catalog.preferred_indices)
    return tuple(
        candidate
        for candidate in compatible
        if (device.uid and candidate.uid == device.uid)
        or (
            not device.uid
            and preferred.get(candidate.index, candidate.index)
            == preferred.get(device.index, device.index)
        )
    )


def find_display_device(
    devices, selection: MicrophoneSelection
) -> ASRInputDevice | None:
    if selection.uid:
        return next((device for device in devices if device.uid == selection.uid), None)
    if selection.name:
        candidates = [device for device in devices if device.name == selection.name]
        indexed = next(
            (device for device in candidates if device.index == selection.index), None
        )
        return indexed or (candidates[0] if len(candidates) == 1 else None)
    return next((device for device in devices if device.index == selection.index), None)


class MicrophoneSelectionService:
    """Single owner of microphone preferences, migration and runtime resolution."""

    def __init__(
        self, preferences: MicrophonePreferences, catalog: AudioInputCatalogProvider
    ):
        self._preferences = preferences
        self._catalog = catalog
        self._lock = RLock()

    @property
    def selection(self) -> MicrophoneSelection:
        with self._lock:
            return self._preferences.read()

    def _read_catalog(self, *, refresh=False):
        catalog = self._catalog.read(refresh=refresh)
        with self._lock:
            if migrate_microphone_endpoint_id(self._preferences, catalog):
                logger.info(
                    "Microphone endpoint binding migrated: %s", self.selection.uid
                )
        return catalog

    def initialize(self):
        if not self.selection.uid:
            try:
                self._read_catalog()
            except AudioInputCatalogUnavailable as error:
                logger.debug("Microphone migration deferred: %s", error)
        return self.selection

    def list_devices(self, *, refresh=False):
        return list(self._read_catalog(refresh=refresh).devices)

    def catalog(self, *, refresh=False):
        return self._read_catalog(refresh=refresh)

    def resolve_current(self, *, refresh=False):
        catalog = self._read_catalog(refresh=refresh)
        with self._lock:
            current = self.selection
            device = resolve_microphone(catalog, current)
            if device is not None:
                stored = device.selection
                if (
                    not current.uid
                    and catalog.identity_status != EndpointIdentityStatus.AVAILABLE
                ):
                    stored = MicrophoneSelection(index=device.index, name=device.name)
                self._preferences.write(replace(stored, backend=current.backend))
            return device

    def select(self, selection: MicrophoneSelection):
        with self._lock:
            self._preferences.write(selection)
            return self.selection

    def set_index_hint(self, index: int):
        with self._lock:
            current = self.selection
            if current.index == int(index):
                return current
            return self.select(
                MicrophoneSelection(
                    current.uid,
                    int(index),
                    current.name if current.uid else "",
                    current.backend,
                )
            )
