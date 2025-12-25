import uuid
import os
import glob
import asyncio

from handlers.audio_handler import AudioHandler
from main_logger import logger
from ui.settings.voiceover_settings import LOCAL_VOICE_MODELS
from core.events import get_event_bus, Events, Event
from managers.task_manager import TaskStatus
from typing import Optional
from utils import process_text_to_voice


class AudioController:
    """
    Агрегатор озвучки:
    - TG → TelegramController
    - Local → LocalVoiceController
    Вся «локальная» логика вынесена в LocalVoiceController.
    """

    def __init__(self, main_controller):
        self.main_controller = main_controller
        self.settings = main_controller.settings
        self.event_bus = get_event_bus()

        self.voiceover_method = self.settings.get("VOICEOVER_METHOD", "TG")
        self.current_local_voice_id = self.settings.get("NM_CURRENT_VOICEOVER", None)
        self.last_voice_model_selected = None
        if self.current_local_voice_id:
            for model_info in LOCAL_VOICE_MODELS:
                if model_info["id"] == self.current_local_voice_id:
                    self.last_voice_model_selected = model_info
                    break

        self.textSpeaker = "/speaker Mita"
        self.textSpeakerMiku = "/set_person CrazyMita"

        self.id_sound = -1
        self.waiting_answer = False

        self._subscribe_to_events()

    def _subscribe_to_events(self):
        eb = self.event_bus
        eb.subscribe(Events.Audio.VOICEOVER_REQUESTED, self._on_voiceover_requested, weak=False)
        eb.subscribe(Events.Audio.DELETE_SOUND_FILES, self._on_delete_sound_files, weak=False)
        eb.subscribe(Events.Audio.GET_WAITING_ANSWER, self._on_get_waiting_answer, weak=False)
        eb.subscribe(Events.Audio.SET_WAITING_ANSWER, self._on_set_waiting_answer, weak=False)

    def _on_get_waiting_answer(self, event: Event):
        return self.waiting_answer

    def _on_set_waiting_answer(self, event: Event):
        self.waiting_answer = event.data.get('waiting', False)

    def get_speaker_text(self):
        if self.settings.get("AUDIO_BOT") == "@CrazyMitaAIbot":
            return self.textSpeakerMiku
        else:
            return self.textSpeaker

    def _update_task_failed_voiceover(self, task_uid: str, error: str):
        self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
            'uid': task_uid,
            'status': TaskStatus.FAILED_ON_VOICEOVER,
            'error': error
        })

    def _on_voiceover_requested(self, event: Event):
        data = event.data or {}
        text = data.get('text', '')
        speaker = data.get('speaker', self.get_speaker_text())
        task_uid = data.get('task_uid')

        if not text:
            return

        # Сохраняем оригинальный текст (с командами) для логики
        original_text = text
        # Создаем очищенный текст для TTS (без команд)
        text_for_voice = process_text_to_voice(text)

        loops = self.event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
        loop = loops[0] if loops else None
        if not (loop and loop.is_running()):
            logger.error("Ошибка: Цикл событий не готов.")
            if task_uid:
                self._update_task_failed_voiceover(task_uid, "Event loop not ready")
            return

        try:
            self.waiting_answer = True
            self.voiceover_method = self.settings.get("VOICEOVER_METHOD", "TG")

            if self.voiceover_method == "TG":
                logger.info(f"Используем Telegram (Silero/Miku) для озвучки: {speaker}")
                self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
                    # Передаем и очищенный текст (для звука), и оригинальный (для результата задачи)
                    'coroutine': self.run_send_and_receive(text_for_voice, original_text, speaker, task_uid)
                })

            elif self.voiceover_method == "Local":
                # Схема с Future по аналогии с TG
                self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
                    # Передаем и очищенный текст (для звука), и оригинальный (для результата задачи)
                    'coroutine': self._await_local_voiceover_and_postprocess(text_for_voice, original_text, task_uid)
                })

            else:
                logger.warning(f"Неизвестный метод озвучки: {self.voiceover_method}")
                if task_uid:
                    self._update_task_failed_voiceover(task_uid, "Unknown voiceover method")

            logger.info("Запрос озвучки принят")
        except Exception as e:
            logger.error(f"Ошибка при отправке текста на озвучку: {e}")
            if task_uid:
                self._update_task_failed_voiceover(task_uid, str(e))
        finally:
            self.waiting_answer = False

    async def run_send_and_receive(self, voice_text, original_text, speaker_command, task_uid=None):
        """TG-озвучка (как было)."""
        import asyncio
        logger.info("Попытка получить фразу (Telegram)")

        future = asyncio.Future()
        logger.notify(f"Отправка на озвучку в Telegram текста: {voice_text[:50]}...")

        self.event_bus.emit(Events.Telegram.TELEGRAM_SEND_VOICE_REQUEST, {
            'text': voice_text,  # Telegram сам преобразует
            'speaker_command': speaker_command,
            'id': 0,
            'future': future,
            'task_uid': task_uid
        })

        try:
            await future
            voiceover_path = future.result()
            logger.notify(voiceover_path)

            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    'uid': task_uid,
                    'status': TaskStatus.SUCCESS,
                    'result': {
                        'response': original_text,  # ВАЖНО: возвращаем оригинальный текст с командами
                        'voiceover_path': voiceover_path
                    }
                })
        except Exception as e:
            logger.error(f"Ошибка при получении озвучки через Telegram: {e}")
            if task_uid:
                self._update_task_failed_voiceover(task_uid, str(e))

        logger.info("Завершение получения фразы (Telegram)")

    async def _await_local_voiceover_and_postprocess(self, voice_text: str, original_text: str,
                                                     task_uid: Optional[str]):
        """Локальная озвучка через LocalVoiceController (через Future) + пост-обработка."""
        import asyncio

        future = asyncio.Future()
        self.event_bus.emit(Events.Audio.LOCAL_SEND_VOICE_REQUEST, {
            'text': voice_text,  # Отправляем очищенный текст в TTS
            'future': future,
            'task_uid': task_uid
        })

        try:
            await future
            result_path = future.result()

            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    'uid': task_uid,
                    'status': TaskStatus.SUCCESS,
                    'result': {
                        'response': original_text,  # ВАЖНО: возвращаем оригинальный текст с командами
                        'voiceover_path': result_path
                    }
                })

            # Остальная логика как раньше
            server_res = self.event_bus.emit_and_wait(Events.Server.GET_GAME_CONNECTION, timeout=1.0)
            is_connected = server_res[0] if server_res else False

            if not is_connected and self.settings.get("VOICEOVER_LOCAL_CHAT"):
                await AudioHandler.handle_voice_file(
                    result_path,
                    self.settings.get("LOCAL_VOICE_DELETE_AUDIO", True) if os.environ.get(
                        "ENABLE_VOICE_DELETE_CHECKBOX", "0") == "1" else True
                )
            elif is_connected:
                self.event_bus.emit(Events.Server.SET_PATCH_TO_SOUND_FILE, result_path)
            else:
                logger.info("Озвучка в локальном чате отключена.")

        except Exception as e:
            logger.error(f"Ошибка при выполнении локальной озвучки: {e}")
            if task_uid:
                self._update_task_failed_voiceover(task_uid, str(e))

    @staticmethod
    def delete_all_sound_files():
        for pattern in ["*.wav", "*.mp3"]:
            files = glob.glob(pattern)
            for file in files:
                try:
                    os.remove(file)
                    logger.info(f"Удален файл: {file}")
                except Exception as e:
                    logger.info(f"Ошибка при удалении файла {file}: {e}")

    def _on_delete_sound_files(self, event: Event):
        self.delete_all_sound_files()