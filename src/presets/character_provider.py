CURRENT_PRESET_ID = -1


def provider_preset_id(value):
    """Return an explicit preset ID, or None for the current preset."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        preset_id = int(value)
    except (ValueError, TypeError):
        return None
    return preset_id if preset_id >= 0 else None


def migrate_character_provider_settings(settings, meta):
    """Convert old provider names once, outside the request path."""
    names = {}
    for bucket in ("custom", "builtin"):
        for preset in (meta or {}).get(bucket, []):
            name = preset.get("name") if isinstance(preset, dict) else preset.name
            identifier = preset.get("id") if isinstance(preset, dict) else preset.id
            names.setdefault(name, set()).add(identifier)
    for key, value in settings.snapshot().items():
        if not key.startswith("CHAR_PROVIDER_") or isinstance(value, int):
            continue
        identifier = provider_preset_id(value)
        if identifier is None:
            if str(value or "").strip() in ("", "Current", "Текущий", "-1"):
                identifier = CURRENT_PRESET_ID
            else:
                matches = names.get(str(value).strip(), set())
                if len(matches) != 1:
                    continue
                identifier = next(iter(matches))
        settings.set(key, int(identifier))


def character_provider_choices(meta):
    choices = []
    for preset in (meta or {}).get("custom", []):
        def field(key, default=""):
            return preset.get(key, default) if isinstance(preset, dict) else getattr(preset, key, default)
        choices.append({"id": int(field("id")), "name": str(field("name")),
                        "model": str(field("default_model")), "provider": str(field("provider_name")),
                        "template": str(field("template_name")), "protocol": str(field("protocol_id"))})
    return choices
