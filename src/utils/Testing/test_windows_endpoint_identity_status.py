from types import SimpleNamespace
from unittest.mock import Mock

from domain.audio_input import EndpointIdentityStatus
from infrastructure.audio import windows_endpoint_identity as reader


def test_native_library_failure_is_reported_as_identity_failure(monkeypatch):
    monkeypatch.setattr(reader.sys, "platform", "win32")

    def fail(path):
        raise OSError("library unavailable")

    monkeypatch.setattr(reader, "_portaudio_library", fail)
    result = reader.read_windows_endpoint_ids("portaudio.dll", [1])
    assert result.status == EndpointIdentityStatus.UNAVAILABLE
    assert "library unavailable" in result.detail


def test_missing_endpoint_extension_is_reported_as_unsupported(monkeypatch):
    monkeypatch.setattr(reader.sys, "platform", "win32")

    def fail(path):
        raise AttributeError("PaWasapi_GetIMMDevice")

    monkeypatch.setattr(reader, "_portaudio_library", fail)
    assert (
        reader.read_windows_endpoint_ids("portaudio.dll", [1]).status
        == EndpointIdentityStatus.UNSUPPORTED
    )


def test_failed_queries_are_not_reported_as_successful_empty_catalog(monkeypatch):
    monkeypatch.setattr(reader.sys, "platform", "win32")
    monkeypatch.setattr(
        reader,
        "_portaudio_library",
        lambda path: SimpleNamespace(PaWasapi_GetIMMDevice=lambda *args: -1),
    )
    com = SimpleNamespace(CoInitializeEx=Mock(return_value=0), CoUninitialize=Mock())
    monkeypatch.setattr(reader, "_com_library", lambda: com)
    result = reader.read_windows_endpoint_ids("portaudio.dll", [1, 2])
    assert result.status == EndpointIdentityStatus.UNAVAILABLE
    assert len(result.values) == 0
    assert "1" in result.detail and "2" in result.detail
    com.CoUninitialize.assert_called_once()


def test_successful_empty_device_list_can_mean_no_devices(monkeypatch):
    monkeypatch.setattr(reader.sys, "platform", "win32")
    monkeypatch.setattr(reader, "_portaudio_library", lambda path: object())
    com = SimpleNamespace(CoInitializeEx=Mock(return_value=0), CoUninitialize=Mock())
    monkeypatch.setattr(reader, "_com_library", lambda: com)
    result = reader.read_windows_endpoint_ids("portaudio.dll", [])
    assert result.status == EndpointIdentityStatus.AVAILABLE
    assert result.values == ()
