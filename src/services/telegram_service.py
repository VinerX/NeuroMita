from services.contracts import TelegramService


class UnavailableTelegramService(TelegramService):
    def __init__(self, reason: str = ""):
        self.reason = str(reason or "")

    def is_silero_connected(self) -> bool:
        return False

    async def send_voice(
        self, text: str, speaker_command: str, message_id: int = 0
    ) -> str:
        raise RuntimeError(self.reason or "Telegram feature is disabled")
