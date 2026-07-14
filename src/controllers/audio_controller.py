import os
import glob
from typing import Optional

from handlers.audio_handler import AudioHandler
from main_logger import logger
from presets.local_voice_models import LOCAL_VOICE_MODELS
from core.events import get_event_bus, Events, Event
from core.services import use
from services.contracts import (
    AudioStateService,
    GameLinkService,
    LocalVoiceService,
    LoopService,
    TelegramService,
)
from managers.task_manager import TaskStatus
from utils import process_text_to_voice


class AudioController(AudioStateService):
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

    def is_waiting_answer(self) -> bool:
        return bool(getattr(self, "waiting_answer", False))

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

    def _emit_show_voicing(self, voice_profile, speaker, message_id=None):
        """Показывает статус «Озвучивает…». Вызывать в момент фактического
        старта воспроизведения, а не при приёме запроса на синтез. message_id —
        чтобы подсветить конкретный пузырь, который сейчас озвучивается."""
        self.event_bus.emit(Events.GUI.SHOW_MITA_VOICING, {
            "character_name": self._voice_status_name(voice_profile, speaker),
            "icon_names": ["fa6s.volume-high"],
            "message_id": message_id,
        })

    def _on_voiceover_requested(self, event: Event):
        data = event.data or {}
        text = data.get("text", "")
        task_uid = data.get("task_uid")
        message_id = data.get("message_id")

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

        loop_service = use(LoopService)
        if not loop_service.is_running():
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
                loop_service.run(self.run_send_and_receive(
                    text_for_voice,
                    original_text,
                    speaker,
                    task_uid,
                    message_id=message_id,
                ))

            elif self.voiceover_method == "Local":
                loop_service.run(self._await_local_voiceover_and_postprocess(
                    text_for_voice,
                    original_text,
                    task_uid,
                    character_id=character_id,
                    voice_profile=voice_profile,
                    message_id=message_id,
                ))

            else:
                logger.warning(f"Неизвестный метод озвучки: {self.voiceover_method}")
                if task_uid:
                    self._update_task_failed_voiceover(task_uid, "Unknown voiceover method")
                self.waiting_answer = False
                return

            logger.info("Запрос озвучки принят")
            # #11: индикатор «Озвучивает…». Раньше показывался прямо здесь —
            # то есть на время СИНТЕЗА (а он не мгновенный), из-за чего статус и
            # блокировка ASR срабатывали раньше фактической озвучки. Теперь
            # показ переехал к моменту старта воспроизведения (см. корутины ниже).
        except Exception as e:
            logger.error(f"Ошибка при отправке текста на озвучку: {e}")
            if task_uid:
                self._update_task_failed_voiceover(task_uid, str(e))
            self.waiting_answer = False

    async def run_send_and_receive(self, voice_text, original_text, speaker_command, task_uid=None, message_id=None):
        logger.info("Попытка получить фразу (Telegram)")

        logger.notify(f"Отправка на озвучку в Telegram текста: {voice_text[:50]}...")

        try:
            voiceover_path = await use(TelegramService).send_voice(
                voice_text, speaker_command, 0
            )
            logger.notify(voiceover_path)

            # Синтез завершён, файл получен — только теперь показываем «Озвучивает…».
            self._emit_show_voicing(None, speaker_command, message_id)

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
        message_id: Optional[str] = None,
    ):
        try:
            result_path = await use(LocalVoiceService).synthesize(
                voice_text,
                character_id=character_id,
                voice_profile=voice_profile,
            )

            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    "uid": task_uid,
                    "status": TaskStatus.SUCCESS,
                    "result": {
                        "voiceover_path": result_path
                    }
                })

            is_connected = use(GameLinkService).is_connected()

            if not is_connected and self.settings.get("VOICEOVER_LOCAL_CHAT"):
                # Воспроизведение идёт в нашем процессе — точно знаем начало и
                # конец, поэтому держим окно «Мита говорит» открытым на всю
                # длительность play (см. SpeechController: ASR в это время
                # не засчитывает распознанное). Статус и блокировку ASR включаем
                # ровно перед стартом play, а не после синтеза.
                self._emit_show_voicing(voice_profile, character_id, message_id)
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
                # Точный момент старта у мода тоже не виден (передача файла по
                # TCP + запуск play), поэтому окно ASR и статус здесь —
                # оценочные, но выставляются не раньше готовности файла.
                self._emit_show_voicing(voice_profile, character_id, message_id)
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
