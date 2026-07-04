import os
import glob
import asyncio
from typing import Optional

from handlers.audio_handler import AudioHandler
from main_logger import logger
from ui.settings.voiceover_settings import LOCAL_VOICE_MODELS
from core.events import get_event_bus, Events, Event
from managers.task_manager import TaskStatus
from utils import process_text_to_voice


class AudioController:
    """
    Агрегатор озвучки.
    Получает на вход уже определённый speaker и voice_profile (если есть),
    не делает повторных запросов персонажа в рамках одного запроса.
    """

    def __init__(self, main_controller):
        self.main_controller = main_controller
        self.settings = main_controller.settings
        self.event_bus = get_event_bus()

        self.voiceover_method = self.settings.get("VOICEOVER_METHOD", "Local")
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

    def _set_mita_speaking(self, active: bool):
        """Сообщить, что Мита начала/закончила говорить (открытое окно)."""
        try:
            self.event_bus.emit(Events.Audio.MITA_SPEAKING_WINDOW, {"active": bool(active)})
        except Exception:
            pass

    @staticmethod
    def _audio_duration(path) -> float:
        """Длительность аудиофайла в секундах (0.0 — определить не удалось)."""
        try:
            import soundfile as sf
            info = sf.info(path)
            if info.frames and info.samplerate:
                return float(info.frames) / float(info.samplerate)
        except Exception:
            pass
        try:
            import wave
            with wave.open(path, "rb") as w:
                fr = w.getframerate()
                if fr:
                    return float(w.getnframes()) / float(fr)
        except Exception:
            pass
        return 0.0

    def _on_get_waiting_answer(self, event: Event):
        return self.waiting_answer

    def _on_set_waiting_answer(self, event: Event):
        self.waiting_answer = (event.data or {}).get("waiting", False)

    def get_speaker_text(self):
        if self.settings.get("AUDIO_BOT") == "@CrazyMitaAIbot":
            return self.textSpeakerMiku
        return self.textSpeaker

    def _update_task_failed_voiceover(self, task_uid: str, error: str):
        self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
            "uid": task_uid,
            "status": TaskStatus.FAILED_ON_VOICEOVER,
            "error": error
        })

    @staticmethod
    def _voice_status_name(voice_profile, speaker: str) -> str:
        if isinstance(voice_profile, dict):
            for key in ("name", "short_name", "character_id"):
                value = str(voice_profile.get(key) or "").strip()
                if value:
                    return value
        speaker = str(speaker or "").strip()
        return speaker.lstrip("/") if speaker else ""

    def _on_voiceover_requested(self, event: Event):
        data = event.data or {}
        text = data.get("text", "")
        task_uid = data.get("task_uid")

        character_id = data.get("character_id")
        voice_profile = data.get("voice_profile")

        speaker = data.get("speaker")
        if not speaker:
            if isinstance(voice_profile, dict):
                if self.settings.get("AUDIO_BOT") == "@CrazyMitaAIbot":
                    speaker = voice_profile.get("miku_tts_name")
                else:
                    speaker = voice_profile.get("silero_command")
            speaker = speaker or self.get_speaker_text()

        if not text:
            return

        original_text = text
        text_for_voice = process_text_to_voice(text)

        loops = self.event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
        loop = loops[0] if loops else None
        if not (loop and loop.is_running()):
            logger.error("Ошибка: Цикл событий не готов.")
            if task_uid:
                self._update_task_failed_voiceover(task_uid, "Event loop not ready")
            self.waiting_answer = False
            return

        self.waiting_answer = True
        self.voiceover_method = self.settings.get("VOICEOVER_METHOD", "Local")

        try:
            if self.voiceover_method == "TG":
                logger.info(f"Используем Telegram (Silero/Miku) для озвучки: {speaker}")
                self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
                    "coroutine": self.run_send_and_receive(
                        text_for_voice,
                        original_text,
                        speaker,
                        task_uid
                    )
                })

            elif self.voiceover_method == "Local":
                self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
                    "coroutine": self._await_local_voiceover_and_postprocess(
                        text_for_voice,
                        original_text,
                        task_uid,
                        character_id=character_id,
                        voice_profile=voice_profile,
                    )
                })

            else:
                logger.warning(f"Неизвестный метод озвучки: {self.voiceover_method}")
                if task_uid:
                    self._update_task_failed_voiceover(task_uid, "Unknown voiceover method")
                self.waiting_answer = False
                return

            logger.info("Запрос озвучки принят")
            # #11: индикатор «Озвучивает…» на время синтеза/воспроизведения.
            self.event_bus.emit(Events.GUI.SHOW_MITA_VOICING, {
                "character_name": self._voice_status_name(voice_profile, speaker),
                "icon_names": ["fa6s.volume-high"],
            })
        except Exception as e:
            logger.error(f"Ошибка при отправке текста на озвучку: {e}")
            if task_uid:
                self._update_task_failed_voiceover(task_uid, str(e))
            self.waiting_answer = False

    async def run_send_and_receive(self, voice_text, original_text, speaker_command, task_uid=None):
        logger.info("Попытка получить фразу (Telegram)")

        future = asyncio.Future()
        logger.notify(f"Отправка на озвучку в Telegram текста: {voice_text[:50]}...")

        self.event_bus.emit(Events.Telegram.TELEGRAM_SEND_VOICE_REQUEST, {
            "text": voice_text,
            "speaker_command": speaker_command,
            "id": 0,
            "future": future,
            "task_uid": task_uid
        })

        try:
            await future
            voiceover_path = future.result()
            logger.notify(voiceover_path)

            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    "uid": task_uid,
                    "status": TaskStatus.SUCCESS,
                    "result": {
                        "voiceover_path": voiceover_path
                    }
                })
        except Exception as e:
            logger.error(f"Ошибка при получении озвучки через Telegram: {e}")
            if task_uid:
                self._update_task_failed_voiceover(task_uid, str(e))
        finally:
            self.waiting_answer = False
            self.event_bus.emit(Events.GUI.HIDE_MITA_VOICING)

        logger.info("Завершение получения фразы (Telegram)")

    async def _await_local_voiceover_and_postprocess(
        self,
        voice_text: str,
        original_text: str,
        task_uid: Optional[str],
        character_id: Optional[str] = None,
        voice_profile: Optional[dict] = None,
    ):
        future = asyncio.Future()
        self.event_bus.emit(Events.Audio.LOCAL_SEND_VOICE_REQUEST, {
            "text": voice_text,
            "future": future,
            "task_uid": task_uid,
            "character_id": character_id,
            "voice_profile": voice_profile,
        })

        try:
            await future
            result_path = future.result()

            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    "uid": task_uid,
                    "status": TaskStatus.SUCCESS,
                    "result": {
                        "voiceover_path": result_path
                    }
                })

            server_res = self.event_bus.emit_and_wait(Events.Server.GET_GAME_CONNECTION, timeout=1.0)
            is_connected = server_res[0] if server_res else False

            if not is_connected and self.settings.get("VOICEOVER_LOCAL_CHAT"):
                # Воспроизведение идёт в нашем процессе — точно знаем начало и
                # конец, поэтому держим окно «Мита говорит» открытым на всю
                # длительность play (см. SpeechController: ASR в это время
                # не засчитывает распознанное).
                self._set_mita_speaking(True)
                try:
                    await AudioHandler.handle_voice_file(
                        result_path,
                        self.settings.get("LOCAL_VOICE_DELETE_AUDIO", True)
                        if os.environ.get("ENABLE_VOICE_DELETE_CHECKBOX", "0") == "1" else True,
                        volume=self._local_playback_volume(),
                    )
                finally:
                    self._set_mita_speaking(False)
            elif is_connected:
                # Аудио проигрывает мод в игре — конец воспроизведения нам не
                # виден. Прикидываем окно по длительности самого файла.
                dur = self._audio_duration(result_path)
                if dur > 0:
                    self.event_bus.emit(Events.Audio.MITA_SPEAKING_WINDOW, {"duration": dur})
                self.event_bus.emit(Events.Server.SET_PATCH_TO_SOUND_FILE, result_path)
            else:
                logger.info("Озвучка в локальном чате отключена.")

        except Exception as e:
            logger.error(f"Ошибка при выполнении локальной озвучки: {e}")
            if task_uid:
                self._update_task_failed_voiceover(task_uid, str(e))
        finally:
            self.waiting_answer = False
            self.event_bus.emit(Events.GUI.HIDE_MITA_VOICING)

    def _local_playback_volume(self) -> int:
        """Громкость воспроизведения озвучки в питоне (в процентах, 0..200)."""
        try:
            vol = int(self.settings.get("VOICEOVER_LOCAL_VOLUME", 100))
        except (TypeError, ValueError):
            vol = 100
        return max(0, min(200, vol))

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
