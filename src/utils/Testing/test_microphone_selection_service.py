from domain.audio_input import ASRInputDevice, AudioInputCatalog, MicrophoneSelection
from infrastructure.settings.microphone_preferences import SettingsMicrophonePreferences
from migrations.settings.microphone_endpoint_id import migrate_microphone_endpoint_id
from services.microphone_selection import MicrophoneSelectionService
from threading import Event, Thread
from domain.audio_input import EndpointIdentityStatus
from services.audio_input_contracts import MicrophoneIdentityUnavailable
import pytest


class Settings(dict):
    saves = 0

    def set(self, key, value):
        self[key] = value

    def save_settings(self):
        self.saves += 1


class CatalogProvider:
    def __init__(self, catalog):
        self.catalog = catalog
        self.calls = []

    def read(self, *, refresh=False):
        self.calls.append(refresh)
        return self.catalog


def legacy_catalog():
    old = ASRInputDevice(1, "Microphone (FIFINE K670 Microph", "MME", uid="endpoint-A")
    current = ASRInputDevice(
        38, "Microphone (FIFINE K670 Microphone)", "WASAPI", uid="endpoint-A"
    )
    return AudioInputCatalog((current,), (old, current), ((1, 38), (38, 38)), 1)


def test_migration_preserves_physical_endpoint_without_enabling_microphone():
    settings = Settings(
        NM_MICROPHONE_ID=1,
        NM_MICROPHONE_NAME="Microphone (FIFINE K670 Microph",
        MIC_ACTIVE=False,
    )
    preferences = SettingsMicrophonePreferences(settings)
    assert migrate_microphone_endpoint_id(preferences, legacy_catalog())
    assert preferences.read() == legacy_catalog().devices[0].selection
    assert settings["MIC_DEVICE"] == "Microphone (FIFINE K670 Microphone) (38)"
    assert settings.saves == 1
    assert not settings["MIC_ACTIVE"]
    assert not migrate_microphone_endpoint_id(preferences, legacy_catalog())
    assert settings.saves == 1


def test_service_initializes_migration_once_and_owns_selection_storage():
    settings = Settings(
        NM_MICROPHONE_ID=1, NM_MICROPHONE_NAME="Microphone (FIFINE K670 Microph"
    )
    provider = CatalogProvider(legacy_catalog())
    service = MicrophoneSelectionService(
        SettingsMicrophonePreferences(settings), provider
    )
    assert service.initialize().uid == "endpoint-A"
    service.initialize()
    assert provider.calls == [False]
    assert service.selection.index == 38
    assert settings.saves == 1
    service.select(MicrophoneSelection("endpoint-B", 39, "Another microphone"))
    assert settings["NM_MICROPHONE_UID"] == "endpoint-B"


def test_stored_endpoint_is_not_replaced_when_unavailable():
    settings = Settings(
        NM_MICROPHONE_UID="missing", NM_MICROPHONE_ID=38, NM_MICROPHONE_NAME="Same name"
    )
    device = ASRInputDevice(38, "Same name", "WASAPI", uid="another")
    service = MicrophoneSelectionService(
        SettingsMicrophonePreferences(settings),
        CatalogProvider(AudioInputCatalog((device,))),
    )
    assert service.resolve_current() is None
    assert settings["NM_MICROPHONE_UID"] == "missing"
    assert settings.saves == 0


def test_runtime_resolution_updates_only_metadata_after_rename_and_reordering():
    settings = Settings(
        NM_MICROPHONE_UID="endpoint-A",
        NM_MICROPHONE_ID=1,
        NM_MICROPHONE_NAME="Old name",
    )
    device = ASRInputDevice(44, "Renamed microphone", "WASAPI", uid="endpoint-A")
    service = MicrophoneSelectionService(
        SettingsMicrophonePreferences(settings),
        CatalogProvider(AudioInputCatalog((device,))),
    )
    assert service.resolve_current() == device
    assert service.selection == MicrophoneSelection(
        "endpoint-A", 44, "Renamed microphone"
    )
    assert settings["NM_MICROPHONE_UID"] == "endpoint-A"


def test_ambiguous_legacy_name_is_left_unmodified():
    settings = Settings(NM_MICROPHONE_ID=99, NM_MICROPHONE_NAME="Identical")
    devices = (
        ASRInputDevice(1, "Identical", "WASAPI", uid="A"),
        ASRInputDevice(2, "Identical", "WASAPI", uid="B"),
    )
    assert not migrate_microphone_endpoint_id(
        SettingsMicrophonePreferences(settings), AudioInputCatalog(devices)
    )
    assert "NM_MICROPHONE_UID" not in settings
    assert settings.saves == 0


def test_migration_cannot_overwrite_a_selection_changed_during_resolution():
    class ConcurrentPreferences:
        reads = 0
        writes = []

        def read(self):
            self.reads += 1
            return (
                MicrophoneSelection(index=1)
                if self.reads == 1
                else MicrophoneSelection("user-choice", 42, "User choice")
            )

        def write(self, choice):
            self.writes.append(choice)
            return True

    preferences = ConcurrentPreferences()
    assert not migrate_microphone_endpoint_id(preferences, legacy_catalog())
    assert preferences.writes == []


def test_slow_catalog_lookup_cannot_overwrite_new_user_selection():
    entered, release = Event(), Event()
    a = ASRInputDevice(1, "A", "WASAPI", uid="endpoint-A")
    b = ASRInputDevice(2, "B", "WASAPI", uid="endpoint-B")

    class SlowCatalog:
        def read(self, *, refresh=False):
            entered.set()
            assert release.wait(2)
            return AudioInputCatalog((a, b))

    settings = Settings(
        NM_MICROPHONE_UID="endpoint-A", NM_MICROPHONE_ID=1, NM_MICROPHONE_NAME="A"
    )
    service = MicrophoneSelectionService(
        SettingsMicrophonePreferences(settings), SlowCatalog()
    )
    resolved = []
    worker = Thread(target=lambda: resolved.append(service.resolve_current()))
    worker.start()
    try:
        assert entered.wait(2)
        service.select(b.selection)
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert resolved == [b]
        assert service.selection.uid == "endpoint-B"
    finally:
        release.set()
        worker.join(2)


@pytest.mark.parametrize(
    "status",
    [
        EndpointIdentityStatus.UNAVAILABLE,
        EndpointIdentityStatus.PARTIAL,
        EndpointIdentityStatus.UNSUPPORTED,
    ],
)
def test_identity_read_failure_is_distinct_from_missing_device_and_preserves_binding(
    status,
):
    settings = Settings(
        NM_MICROPHONE_UID="endpoint-A", NM_MICROPHONE_ID=1, NM_MICROPHONE_NAME="Mic"
    )
    unverified = ASRInputDevice(1, "Mic", "WASAPI")
    catalog = AudioInputCatalog(
        (unverified,), identity_status=status, identity_detail="native API failed"
    )
    service = MicrophoneSelectionService(
        SettingsMicrophonePreferences(settings), CatalogProvider(catalog)
    )
    assert service.list_devices() == [unverified]
    with pytest.raises(MicrophoneIdentityUnavailable) as error:
        service.resolve_current()
    assert error.value.detail == "native API failed"
    assert settings["NM_MICROPHONE_UID"] == "endpoint-A"
    assert settings.saves == 0


def test_identity_reading_recovers_without_reselecting_saved_microphone():
    settings = Settings(
        NM_MICROPHONE_UID="endpoint-A", NM_MICROPHONE_ID=1, NM_MICROPHONE_NAME="Mic"
    )
    provider = CatalogProvider(
        AudioInputCatalog(identity_status=EndpointIdentityStatus.UNAVAILABLE)
    )
    service = MicrophoneSelectionService(
        SettingsMicrophonePreferences(settings), provider
    )
    with pytest.raises(MicrophoneIdentityUnavailable):
        service.resolve_current()
    current = ASRInputDevice(38, "Renamed", "WASAPI", uid="endpoint-A")
    provider.catalog = AudioInputCatalog((current,))
    assert service.resolve_current() == current
    assert service.selection.uid == "endpoint-A"


def test_legacy_selection_can_still_work_when_identity_api_is_unsupported():
    settings = Settings(NM_MICROPHONE_ID=1, NM_MICROPHONE_NAME="Mic")
    device = ASRInputDevice(1, "Mic", "MME")
    catalog = AudioInputCatalog(
        (device,), identity_status=EndpointIdentityStatus.UNSUPPORTED
    )
    service = MicrophoneSelectionService(
        SettingsMicrophonePreferences(settings), CatalogProvider(catalog)
    )
    assert service.resolve_current() == device
    assert not service.selection.uid
    service.set_index_hint(1)
    assert service.selection.name == "Mic"


def test_partial_identity_results_do_not_trigger_migration():
    settings = Settings(
        NM_MICROPHONE_ID=1, NM_MICROPHONE_NAME="Microphone (FIFINE K670 Microph"
    )
    full = legacy_catalog()
    catalog = AudioInputCatalog(
        full.devices,
        full.representations,
        full.preferred_indices,
        full.default_index,
        EndpointIdentityStatus.PARTIAL,
    )
    assert not migrate_microphone_endpoint_id(
        SettingsMicrophonePreferences(settings), catalog
    )
    assert "NM_MICROPHONE_UID" not in settings


def test_verified_endpoint_can_work_with_partial_results_for_other_devices():
    settings = Settings(
        NM_MICROPHONE_UID="A", NM_MICROPHONE_ID=1, NM_MICROPHONE_NAME="Mic"
    )
    device = ASRInputDevice(1, "Mic", "WASAPI", uid="A")
    catalog = AudioInputCatalog(
        (device,), identity_status=EndpointIdentityStatus.PARTIAL
    )
    service = MicrophoneSelectionService(
        SettingsMicrophonePreferences(settings), CatalogProvider(catalog)
    )
    assert service.resolve_current() == device


def backend_catalog():
    mme = ASRInputDevice(1, "Desk", "MME", uid="endpoint-A")
    wasapi = ASRInputDevice(38, "Desk", "Windows WASAPI", uid="endpoint-A")
    other = ASRInputDevice(9, "Other", "DirectSound", uid="endpoint-B")
    return AudioInputCatalog(
        devices=(wasapi, other),
        representations=(mme, wasapi, other),
        preferred_indices=((1, 38), (38, 38), (9, 9)),
        compatible_representations=(mme, wasapi, other),
    )


def test_explicit_backend_survives_save_resolve_and_worker_transport():
    from infrastructure.audio.selection_wire import (
        capture_selection_payload,
        capture_selection_from_payload,
    )

    settings = Settings()
    service = MicrophoneSelectionService(
        SettingsMicrophonePreferences(settings), CatalogProvider(backend_catalog())
    )
    choice = MicrophoneSelection("endpoint-A", 999, "Old name", "MME")
    service.select(choice)
    assert service.resolve_current().index == 1
    assert service.selection.backend == "MME"
    assert settings["NM_MICROPHONE_BACKEND"] == "MME"
    assert (
        capture_selection_from_payload(capture_selection_payload(service.selection))
        == service.selection
    )


def test_explicit_missing_backend_does_not_fall_back_to_other_endpoint_or_auto():
    from services.microphone_selection import resolve_microphone
    from services.audio_input_contracts import MicrophoneBackendUnavailable

    with pytest.raises(MicrophoneBackendUnavailable):
        resolve_microphone(
            backend_catalog(),
            MicrophoneSelection("endpoint-A", 1, "Desk", "DirectSound"),
        )
    assert (
        resolve_microphone(backend_catalog(), MicrophoneSelection("endpoint-A")).index
        == 38
    )


def test_legacy_migration_preserves_explicit_backend():
    settings = Settings(
        NM_MICROPHONE_ID=1, NM_MICROPHONE_NAME="Desk", NM_MICROPHONE_BACKEND="MME"
    )
    service = MicrophoneSelectionService(
        SettingsMicrophonePreferences(settings), CatalogProvider(backend_catalog())
    )
    assert service.initialize().uid == "endpoint-A"
    assert service.resolve_current().index == 1
    assert service.selection.backend == "MME"
