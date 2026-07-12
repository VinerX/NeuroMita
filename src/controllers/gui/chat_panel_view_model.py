from __future__ import annotations

from typing import Any, Callable

from controllers.gui.intent_view_model import IntentViewModel
from core.events import Events, get_event_bus
from core.services import services, use
from managers.prompt_catalogue_manager import list_prompt_sets
from services.contracts import (
    ApiPresetService,
    CaptureService,
    CharacterRegistry,
    SettingsService,
)
from ui.widgets.chat_panel_presentation import (
    ChatCaptureScreenRequested,
    ChatClearStagedRequested,
    ChatImagesStaged,
    ChatInputChanged,
    ChatOpenHistoryRequested,
    ChatPanelActivated,
    ChatPanelState,
    ChatShowError,
    ChatStageFilesRequested,
    ChatStageImageRequested,
    ChatStagedCleared,
)
from utils import _


class ChatPanelViewModel(IntentViewModel[ChatPanelState]):
    def __init__(self, *, host: Any, backend_ready: Callable[[], bool], parent=None) -> None:
        super().__init__(ChatPanelState(), parent)
        self._host = host
        self._backend_ready = backend_ready
        self._settings = use(SettingsService)
        self._bus = get_event_bus()
        for event_name in (
            Events.Character.CURRENT_CHANGED,
            Events.Character.RELOAD_DATA,
            Events.ApiPresets.PRESET_SAVED,
            Events.ApiPresets.PRESET_DELETED,
            Events.ApiPresets.PRESET_IMPORTED,
        ):
            self.track_subscription(
                self._bus.subscribe(event_name, self._on_dependency_changed, weak=False)
            )
        self.track_subscription(
            self._settings.subscribe(
                self._on_setting_changed,
                keys=("AUTO_ATTACH_IMAGES", "ENABLE_CAMERA_CAPTURE", "LAST_API_PRESET_ID"),
            )
        )

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, ChatPanelActivated):
            self.refresh()
            return
        if isinstance(intent, ChatInputChanged):
            self._apply_input(intent.has_text, intent.staged_count)
            return
        if isinstance(intent, ChatOpenHistoryRequested):
            self._open_history(intent.character_id)
            return
        if isinstance(intent, ChatStageFilesRequested):
            self._stage_files(intent.paths)
            return
        if isinstance(intent, ChatStageImageRequested):
            self._stage_images((bytes(intent.image_data),))
            return
        if isinstance(intent, ChatClearStagedRequested):
            self._bus.emit(Events.Chat.CLEAR_STAGED_IMAGES)
            self.update_state(staged_count=0, can_send=self._calculate_can_send(self.state.has_text, 0))
            self.emit_effect(ChatStagedCleared())
            return
        if isinstance(intent, ChatCaptureScreenRequested):
            self._capture_screen()

    def refresh(self) -> None:
        def worker() -> tuple[str, tuple[str, str] | None, bool]:
            character_id = str(use(CharacterRegistry).current_id() or "")
            return character_id, self._block_reason(character_id), bool(self._backend_ready())

        def applied(payload: tuple[str, tuple[str, str] | None, bool]) -> None:
            character_id, reason, backend_ready = payload
            warning, category = reason if reason is not None else ("", "api")
            self.update_state(
                character_id=character_id,
                blocked=reason is not None,
                warning=warning,
                settings_category=category,
                backend_ready=backend_ready,
                can_send=self._calculate_can_send(
                    self.state.has_text,
                    self.state.staged_count,
                    backend_ready=backend_ready,
                    blocked=reason is not None,
                ),
                revision=self.state.revision + 1,
            )

        self.run_coalesced("chat-composer-state", worker, applied)

    def _apply_input(self, has_text: bool, staged_count: int) -> None:
        count = max(0, int(staged_count))
        self.update_state(
            has_text=bool(has_text),
            staged_count=count,
            can_send=self._calculate_can_send(bool(has_text), count),
        )

    def _calculate_can_send(
        self,
        has_text: bool,
        staged_count: int,
        *,
        backend_ready: bool | None = None,
        blocked: bool | None = None,
    ) -> bool:
        ready = self.state.backend_ready if backend_ready is None else bool(backend_ready)
        is_blocked = self.state.blocked if blocked is None else bool(blocked)
        auto_images = bool(
            self._settings.get("AUTO_ATTACH_IMAGES", False)
            or self._settings.get("ENABLE_CAMERA_CAPTURE", False)
        )
        return bool(ready and not is_blocked and (has_text or staged_count > 0 or auto_images))

    def _block_reason(self, character_id: str) -> tuple[str, str] | None:
        try:
            presets = use(ApiPresetService)
            meta = presets.list_meta() or {}
            custom = meta.get("custom") or []
            has_selected = presets.current_id() is not None
            if not custom and not has_selected:
                return (
                    _(
                        "Нельзя отправлять сообщения: не настроен API-пресет. "
                        "Создайте или выберите пресет в настройках.",
                        "Can't send messages: no API preset configured. "
                        "Create or select a preset in settings.",
                    ),
                    "api",
                )
        except Exception:
            pass
        try:
            if character_id and not list_prompt_sets("Prompts", character_id):
                return (
                    _(
                        "Нельзя отправлять сообщения: у персонажа нет набора промптов "
                        "(папка Prompts). Восстановите промпты.",
                        "Can't send messages: character has no prompt set "
                        "(Prompts folder). Restore prompts.",
                    ),
                    "characters",
                )
        except Exception:
            pass
        return None

    def _open_history(self, character_id: str) -> None:
        cid = str(character_id or self.state.character_id).strip()
        try:
            if cid:
                self._bus.emit(Events.Character.SET_CURRENT, {"character_id": cid})
            from controllers.gui.character_settings_logic import open_db_viewer

            open_db_viewer(self._host)
        except Exception as exc:
            self.emit_effect(ChatShowError("History", str(exc)))

    _MAX_STAGED_FILE_BYTES = 32 * 1024 * 1024
    _MAX_STAGED_TOTAL_BYTES = 64 * 1024 * 1024
    _MAX_STAGED_FILES = 8
    _ALLOWED_IMAGE_SUFFIXES = frozenset(
        {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
    )

    def _stage_files(self, paths: tuple[str, ...]) -> None:
        normalized = tuple(str(path) for path in paths if str(path).strip())
        if not normalized:
            return

        def worker() -> tuple[bytes, ...]:
            import os
            from pathlib import Path

            images: list[bytes] = []
            if len(normalized) > self._MAX_STAGED_FILES:
                raise ValueError(
                    _(
                        "Слишком много вложений: {count}, максимум {limit}",
                        "Too many attachments: {count}, maximum {limit}",
                    ).format(count=len(normalized), limit=self._MAX_STAGED_FILES)
                )

            total_size = 0
            for path in normalized:
                suffix = Path(path).suffix.lower()
                if suffix not in self._ALLOWED_IMAGE_SUFFIXES:
                    raise ValueError(
                        _(
                            "Неподдерживаемый тип изображения: {name}",
                            "Unsupported image type: {name}",
                        ).format(name=os.path.basename(path))
                    )
                size = os.path.getsize(path)
                if size > self._MAX_STAGED_FILE_BYTES:
                    raise ValueError(
                        _(
                            "Файл слишком большой для вложения: {name} ({size:.1f} МБ, лимит {limit} МБ)",
                            "File is too large to attach: {name} ({size:.1f} MB, limit {limit} MB)",
                        ).format(
                            name=os.path.basename(path),
                            size=size / (1024 * 1024),
                            limit=self._MAX_STAGED_FILE_BYTES // (1024 * 1024),
                        )
                    )
                total_size += size
                if total_size > self._MAX_STAGED_TOTAL_BYTES:
                    raise ValueError(
                        _(
                            "Суммарный размер вложений превышает {limit} МБ",
                            "Total attachment size exceeds {limit} MB",
                        ).format(
                            limit=self._MAX_STAGED_TOTAL_BYTES // (1024 * 1024)
                        )
                    )
                with open(path, "rb") as stream:
                    payload = stream.read(self._MAX_STAGED_FILE_BYTES + 1)
                if len(payload) != size:
                    raise ValueError(
                        _(
                            "Файл изменился во время чтения: {name}",
                            "File changed while being read: {name}",
                        ).format(name=os.path.basename(path))
                    )
                images.append(payload)
            return tuple(images)

        self.run_exclusive(
            "chat-stage-files",
            worker,
            self._stage_images,
            lambda error: self.emit_effect(ChatShowError("Images", str(error))),
        )

    def _stage_images(self, images: tuple[bytes, ...]) -> None:
        normalized = tuple(bytes(item) for item in images if item)
        if not normalized:
            return
        for image in normalized:
            self._bus.emit(Events.Chat.STAGE_IMAGE, {"image_data": image})
        count = self.state.staged_count + len(normalized)
        self.update_state(staged_count=count, can_send=self._calculate_can_send(self.state.has_text, count))
        self.emit_effect(ChatImagesStaged(normalized))

    def _capture_screen(self) -> None:
        def worker() -> tuple[bytes, ...]:
            capture = services().get_optional(CaptureService)
            if capture is None:
                return ()
            frames = list(capture.capture_screen(1) or [])
            if not frames:
                return ()
            return tuple(bytes(item) for item in (frames[0] or []) if item)

        def applied(images: tuple[bytes, ...]) -> None:
            if not images:
                self.emit_effect(
                    ChatShowError(
                        _("Ошибка", "Error"),
                        _(
                            "Не удалось захватить экран. Убедитесь, что обработка изображений включена в настройках.",
                            "Failed to capture the screen. Make sure image analysis is enabled in settings.",
                        ),
                    )
                )
                return
            self._stage_images(images)

        self.run_exclusive("chat-screen-capture", worker, applied)

    def _on_dependency_changed(self, event: Any) -> None:
        self._post_ui(self.refresh)

    def _on_setting_changed(self, change: Any) -> None:
        self._post_ui(self.refresh)