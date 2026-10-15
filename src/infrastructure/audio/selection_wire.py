from domain.audio_input import MicrophoneSelection


def as_microphone_selection(value: MicrophoneSelection | int) -> MicrophoneSelection:
    return (
        value
        if isinstance(value, MicrophoneSelection)
        else MicrophoneSelection(index=int(value or 0))
    )


def capture_selection_payload(selection: MicrophoneSelection) -> dict:
    payload = {"microphone_index": int(selection.index or 0)}
    if selection.backend:
        payload["microphone_backend"] = selection.backend
        payload["microphone_name"] = selection.name
    if selection.uid:
        payload["microphone_uid"] = selection.uid
    return payload


def capture_selection_from_payload(payload: dict) -> MicrophoneSelection:
    return MicrophoneSelection(
        uid=payload.get("microphone_uid") or None,
        name=str(payload.get("microphone_name") or ""),
        index=int(payload.get("microphone_index") or 0),
        backend=str(payload.get("microphone_backend") or ""),
    )


def selection_from_event(data, current: MicrophoneSelection) -> MicrophoneSelection:
    if isinstance(data, MicrophoneSelection):
        return data
    uid = data.get("device_uid")
    name = str(data.get("name") or "")
    index = data.get("device_id")
    if "device_uid" not in data and name == current.name and index == current.index:
        uid = current.uid
    return MicrophoneSelection(uid, index, name, current.backend)
