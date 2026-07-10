from services.contracts import TelegramService


class UnavailableTelegramService(TelegramService):
    def __init__(self, reason: str = ""):
        self.reason = str(reason or "")

    def is_silero_connected(self) -> bool:
        return False
