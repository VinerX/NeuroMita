from core.remote_voice import RemoteVoiceTemplate

REMOTE_VOICE_TEMPLATES = (
    RemoteVoiceTemplate(
        id="fish_audio",
        name="Fish Audio",
        endpoint="https://api.fish.audio/v1/tts",
        models=("s1", "s2-pro", "s2.1-pro", "s2.1-pro-free"),
        default_model="s1",
        voices_url="https://fish.audio/discovery/",
        keys_url="https://fish.audio/app/api-keys",
    ),
)


def remote_voice_template(template_id: str) -> RemoteVoiceTemplate:
    for template in REMOTE_VOICE_TEMPLATES:
        if template.id == template_id:
            return template
    raise ValueError("Неизвестный провайдер API озвучки.")
