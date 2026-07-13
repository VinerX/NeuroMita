from __future__ import annotations

import base64
import os
import uuid
from typing import Any, Callable

from core.events import Events, get_event_bus
from core.services import services, use
from main_logger import logger
from services.contracts import (
    CaptureService,
    CharacterRegistry,
    GameLinkService,
    LocalVoiceService,
    ModelStateService,
    SettingsService,
    SpeechService,
    TelegramService,
)
from utils import getTranslationVariant as _

from .async_runner import run_async


class AppShellController:
    """Application coordinator for the main Qt shell.

    The shell view owns widgets and rendering only. This controller owns every
    backend request that used to leak through ``AppWindowBase``.
    """

    def __init__(
        self,
        view: Any,
        presentation: Any,
        *,
        close_pages: Callable[[], None] | None = None,
    ) -> None:
        self._view = view
        self._presentation = presentation
        self._close_pages = close_pages
        self._event_bus = get_event_bus()
        self._main_controller = None
        self._backend_error = ""
        self._closed = False

    @property
    def backend_ready(self) -> bool:
        return not self._closed and self._main_controller is not None and not self.is_closing

    @property
    def backend_error(self) -> str:
        return self._backend_error

    @property
    def is_closing(self) -> bool:
        return bool(getattr(self._main_controller, "_closing_started", False))

    def attach_backend(self, controller: Any) -> None:
        if self._closed:
            raise RuntimeError("GUI shell is already closed")
        self._main_controller = controller
        self._backend_error = ""
        self._presentation.app.attach_backend(controller)

    def detach_backend(self) -> None:
        self._main_controller = None
        self._presentation.app.detach_backend()

    def backend_failed(self, error: BaseException | str) -> None:
        message = str(error)
        if not isinstance(error, str):
            message = f"Backend startup failed: {type(error).__name__}: {error}"
        self._main_controller = None
        self._backend_error = message
        self._presentation.app.mark_failed(message)

    def close_application(self) -> None:
        if self._closed:
            return
        self._closed = True
        controller = self._main_controller
        try:
            close_pages = self._close_pages
            self._close_pages = None
            if close_pages is not None:
                try:
                    close_pages()
                except Exception:
                    logger.exception("Failed to close page presentation models")
            if controller is not None:
                controller.close_app()
            else:
                self._event_bus.emit(Events.Capture.STOP_SCREEN_CAPTURE)
                self._event_bus.emit(Events.Capture.STOP_CAMERA_CAPTURE)
                self._event_bus.emit(Events.Audio.DELETE_SOUND_FILES)
                self._event_bus.emit(Events.Server.STOP_SERVER)
        finally:
            self._main_controller = None
            self._presentation.app.detach_backend()

    def load_history(self) -> None:
        self._event_bus.emit(Events.Model.LOAD_HISTORY)

    def load_more_history(self) -> None:
        self._event_bus.emit(Events.Model.LOAD_MORE_HISTORY)

    def clear_chat(self) -> None:
        self._view.render_chat_cleared()
        self._event_bus.emit(Events.Chat.CLEAR_CHAT)

    @staticmethod
    def _dedupe_images(image_list):
        seen = set()
        result = []
        for image in image_list or []:
            if isinstance(image, (bytes, bytearray)):
                key = bytes(image)
                if key in seen:
                    continue
                seen.add(key)
            result.append(image)
        return result

    @staticmethod
    def _merge_text(explicit_text: str, entry_text: str, *, merge_with_entry: bool) -> tuple[str, bool]:
        explicit = str(explicit_text or "").strip()
        draft = str(entry_text or "").strip()
        if not merge_with_entry or not draft:
            return explicit, False
        if not explicit:
            return draft, True
        return f"{explicit}\n{draft}", True

    def send_message(
        self,
        *,
        system_input: str = "",
        image_data: list[bytes] | None = None,
        user_input: str | None = None,
        merge_input_from_entry: bool = False,
    ) -> bool:
        if not self.backend_ready:
            self._view.show_send_error(
                self._backend_error
                or _(
                    "Backend ещё запускается. Повторите отправку после завершения инициализации.",
                    "The backend is still starting. Retry after initialization completes.",
                )
            )
            return False

        from_entry = user_input is None
        clear_entry_after_send = False
        entry_text = self._view.user_input_text()
        if from_entry:
            user_input = entry_text
            clear_entry_after_send = bool(user_input)
        else:
            user_input, clear_entry_after_send = self._merge_text(
                user_input,
                entry_text,
                merge_with_entry=merge_input_from_entry,
            )

        settings = use(SettingsService)
        staged_images = self._view.staged_images_snapshot()
        character_id = self.current_character_id()
        auto_screen = bool(settings.get("AUTO_ATTACH_IMAGES", False))
        auto_camera = bool(settings.get("ENABLE_CAMERA_CAPTURE", False))

        def finish(frames: tuple[list[Any], list[Any]]) -> None:
            screen_frames, camera_frames = frames
            self._finish_send_message(
                user_input=str(user_input or ""),
                system_input=str(system_input or ""),
                explicit_image_data=list(image_data or []),
                screen_frames=screen_frames,
                camera_frames=camera_frames,
                staged_image_data=staged_images,
                character_id=character_id,
                from_entry=from_entry,
                clear_entry_after_send=clear_entry_after_send,
            )

        if not (auto_screen or auto_camera):
            finish(([], []))
            return True

        self.capture_frames(
            auto_screen=auto_screen,
            auto_camera=auto_camera,
            screen_limit=int(settings.get("SCREEN_CAPTURE_HISTORY_LIMIT", 1) or 1),
            camera_limit=int(settings.get("CAMERA_CAPTURE_HISTORY_LIMIT", 1) or 1),
            on_ready=finish,
        )
        return True

    def _finish_send_message(
        self,
        *,
        user_input: str,
        system_input: str,
        explicit_image_data: list[Any],
        screen_frames: list[Any],
        camera_frames: list[Any],
        staged_image_data: list[Any],
        character_id: str,
        from_entry: bool,
        clear_entry_after_send: bool,
    ) -> None:
        settings = use(SettingsService)
        current_image_data = list(screen_frames)
        all_image_data = (
            list(explicit_image_data)
            + current_image_data
            + list(staged_image_data)
            + list(camera_frames)
        )
        if not bool(settings.get("ENABLE_IMAGE_ANALYSIS", True)):
            all_image_data = []
        all_image_data = self._dedupe_images(all_image_data)
        if not user_input and not system_input and not all_image_data:
            return

        req_id = uuid.uuid4().hex
        user_message_id = f"in:{req_id}"
        image_content = []
        if all_image_data:
            image_content = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64.b64encode(image).decode('utf-8')}"
                    },
                }
                for image in all_image_data
            ]
            if not user_input:
                label = _("<Изображения>", "<Images>")
                if staged_image_data and not current_image_data and not explicit_image_data:
                    label = _("<Прикрепленные изображения>", "<Attached Images>")
                elif (current_image_data or explicit_image_data) and not staged_image_data:
                    label = _("<Изображение экрана>", "<Screen Image>")
                image_content.insert(0, {"type": "text", "content": label + "\n"})

        self._view.render_outgoing_message(
            user_input=user_input,
            image_content=image_content,
            message_id=user_message_id,
            clear_entry=bool(from_entry or clear_entry_after_send),
        )
        self._event_bus.emit(
            Events.Chat.SEND_MESSAGE,
            {
                "user_input": user_input,
                "system_input": system_input,
                "image_data": all_image_data,
                "character_id": character_id,
                "sender": "Player",
                "req_id": req_id,
                "images_shown": bool(all_image_data),
            },
        )
        self._view.show_thinking_now()
        if staged_image_data:
            self._event_bus.emit(Events.Chat.CLEAR_STAGED_IMAGES)
            self._view.clear_staged_images_view()

    def current_character_id(self) -> str:
        return str(use(CharacterRegistry).current_id() or "")

    def save_setting(self, key: str, value: Any) -> None:
        use(SettingsService).update(str(key), value)

    def capture_frames(
        self,
        *,
        auto_screen: bool,
        auto_camera: bool,
        screen_limit: int,
        camera_limit: int,
        on_ready: Callable[[tuple[list[Any], list[Any]]], None],
    ) -> None:
        def worker() -> tuple[list[Any], list[Any]]:
            capture = services().get_optional(CaptureService)
            if capture is None:
                return [], []
            screen_frames = list(capture.capture_screen(screen_limit) or []) if auto_screen else []
            camera_frames = list(capture.camera_frames(camera_limit) or []) if auto_camera else []
            return screen_frames, camera_frames

        run_async(self._view, worker, on_ready, name="app-send-capture")

    def request_debug_info(self, on_ready: Callable[[str], None]) -> None:
        def worker() -> str:
            model = services().get_optional(ModelStateService)
            return str(model.debug_info() if model is not None else "Debug info not available")

        run_async(self._view, worker, on_ready, name="app-debug-info")

    def request_token_stats(self, on_ready: Callable[[dict[str, Any]], None]) -> None:
        def worker() -> dict[str, Any]:
            model = services().get_optional(ModelStateService)
            return dict(model.token_stats() or {}) if model is not None else {}

        run_async(self._view, worker, on_ready, name="app-token-stats")

    def request_status(self, on_ready: Callable[[dict[str, Any]], None]) -> None:
        def worker() -> dict[str, Any]:
            settings = use(SettingsService)
            use_voice = bool(settings.get("USE_VOICEOVER", False))
            method = str(settings.get("VOICEOVER_METHOD", "Local") or "Local")
            model_id = str(settings.get("NM_CURRENT_VOICEOVER", "") or "")
            local_voice = services().get_optional(LocalVoiceService)
            telegram = services().get_optional(TelegramService)
            speech = services().get_optional(SpeechService)
            capture = services().get_optional(CaptureService)
            voice_initialized = bool(
                local_voice is not None
                and use_voice
                and method == "Local"
                and model_id
                and local_voice.check_initialized(model_id)
            )
            return {
                "game_connected": bool(use(GameLinkService).is_connected()),
                "silero_connected": bool(telegram and telegram.is_silero_connected()),
                "mic_active": bool(speech and speech.mic_active()),
                "screen_capture_active": bool(capture and capture.screen_capture_active()),
                "camera_capture_active": bool(capture and capture.camera_capture_active()),
                "rag_enabled": bool(settings.get("RAG_ENABLED", False)),
                "use_voice": use_voice,
                "method": method,
                "voice_initialized": voice_initialized,
            }

        run_async(self._view, worker, on_ready, name="app-status-colors")

    def insert_debug_message(self, *, text: str, character_id: str, as_user: bool) -> None:
        self._event_bus.emit(
            Events.Chat.INSERT_SYSTEM_MESSAGE,
            {"text": str(text), "character_id": str(character_id), "as_user": bool(as_user)},
        )

    def save_snapshot(self, character_id: str) -> None:
        self._event_bus.emit(Events.Chat.SAVE_SNAPSHOT, {"character_id": str(character_id)})

    def load_snapshot(self, *, file_path: str, character_id: str) -> None:
        self._event_bus.emit(
            Events.Chat.LOAD_SNAPSHOT,
            {"file_path": str(file_path), "character_id": str(character_id)},
        )

    @staticmethod
    def snapshot_start_directory(character_id: str) -> str:
        histories_root = os.environ.get(
            "NEUROMITA_HISTORIES_DIR",
            os.path.join(os.getcwd(), "Histories"),
        )
        candidate = (
            os.path.join(histories_root, str(character_id), "Saved")
            if str(character_id or "").strip()
            else histories_root
        )
        if os.path.isdir(candidate):
            return candidate
        if os.path.isdir(histories_root):
            return histories_root
        return "."

    def voice_model_state(self, model_id: str) -> tuple[bool, bool]:
        local_voice = services().get_optional(LocalVoiceService)
        if local_voice is None:
            return False, False
        normalized = str(model_id or "")
        return bool(local_voice.is_installed(normalized)), bool(local_voice.check_initialized(normalized))
