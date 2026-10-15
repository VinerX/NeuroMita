TELEGRAM_CREDENTIAL_KEYS = (
    "NM_TELEGRAM_API_ID",
    "NM_TELEGRAM_API_HASH",
    "NM_TELEGRAM_PHONE",
)


def telegram_credentials_complete(settings):
    return all(
        str(settings.get(key, "") or "").strip() for key in TELEGRAM_CREDENTIAL_KEYS
    )
