# Settings migrations

This package currently contains only the microphone endpoint-ID migration.
Existing model, history and other migrations are deliberately unchanged.

`settings/microphone_endpoint_id.py` resolves the old name/index selection
against a supplied audio catalog. It does not enumerate hardware, import Qt,
initialize PortAudio, or decide when application services start. Persistence
is supplied through the `MicrophonePreferences` port.

`MicrophoneSelectionService` runs this migration when a catalog is available.
An existing endpoint binding is never migrated again. Missing or ambiguous
legacy devices are left unchanged, and a changed selection is not overwritten.

Related responsibilities:

- `domain/audio_input.py`: immutable device, selection and catalog values.
- `services/microphone_selection.py`: application selection policy and lifecycle.
- `infrastructure/settings/microphone_preferences.py`: settings schema and writes.
- `infrastructure/audio/portaudio_catalog.py`: hardware enumeration and formats.
- `infrastructure/audio/windows_endpoint_identity.py`: Windows COM/endpoint IDs.
- `infrastructure/audio/selection_wire.py`: legacy events and IPC serialization.

The sounddevice-specific native-library path is isolated in the PortAudio adapter;
Windows identity reading takes an explicit library path and knows no sounddevice API.
