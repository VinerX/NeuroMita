from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.events import Events, get_event_bus, shutdown_event_bus
from core.request_policy import RequestPolicy
from core.services import use
from services.contracts import CharacterRegistry, ChatGenerationRequest, GenerationService, ModelStateService
from core.request_policy import resolve_policy
from main_logger import logger


@dataclass
class GenerationTurn:
    user_input: str = ""
    system_input: str = ""
    event_type: str = "chat"
    sender: str = "Player"
    participants: List[str] = field(default_factory=list)
    preset: int | str | None = None
    character_id: str | None = None
    image_source: str = ""
    disable_history_compression: bool = False

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "GenerationTurn":
        if not isinstance(raw, dict):
            raise TypeError("turn must be a dict")
        participants = raw.get("participants") or []
        if isinstance(participants, str):
            participants = [p.strip() for p in participants.split(",") if p.strip()]
        if not isinstance(participants, list):
            participants = []
        return GenerationTurn(
            user_input=str(raw.get("user_input") or ""),
            system_input=str(raw.get("system_input") or ""),
            event_type=str(raw.get("event_type") or "chat"),
            sender=str(raw.get("sender") or "Player"),
            participants=[str(p) for p in participants if str(p).strip()],
            preset=raw.get("preset"),
            character_id=str(raw.get("character_id") or "").strip() or None,
            image_source=str(raw.get("image_source") or ""),
            disable_history_compression=bool(raw.get("disable_history_compression", False)),
        )

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "user_input": self.user_input,
            "system_input": self.system_input,
            "event_type": self.event_type,
            "sender": self.sender,
            "participants": list(self.participants),
            "image_source": self.image_source,
            "disable_history_compression": self.disable_history_compression,
        }
        if self.preset is not None:
            payload["preset_id"] = self.preset
        if self.character_id:
            payload["character_id"] = self.character_id
        return payload


@dataclass
class GenerationScenario:
    name: str = "generation-debug"
    character_id: str = "Crazy"
    preset: int | str | None = None
    turns: List[GenerationTurn] = field(default_factory=list)

    @staticmethod
    def from_dict(raw: Dict[str, Any]) -> "GenerationScenario":
        if not isinstance(raw, dict):
            raise TypeError("scenario must be a dict")
        turns_raw = raw.get("turns") or []
        if not isinstance(turns_raw, list):
            raise TypeError("scenario.turns must be a list")
        return GenerationScenario(
            name=str(raw.get("name") or "generation-debug"),
            character_id=str(raw.get("character_id") or "Crazy"),
            preset=raw.get("preset"),
            turns=[GenerationTurn.from_dict(item) for item in turns_raw],
        )

    @staticmethod
    def template() -> "GenerationScenario":
        return GenerationScenario(
            name="deepseek-cache-debug",
            character_id="Crazy",
            preset="Current",
            turns=[
                GenerationTurn(
                    user_input="Привет. Скажи кратко, что ты сейчас чувствуешь.",
                    event_type="chat",
                ),
                GenerationTurn(
                    user_input="А теперь ответь чуть подробнее, но не меняй тон.",
                    event_type="chat",
                ),
                GenerationTurn(
                    user_input="Повтори ключевую мысль одной фразой.",
                    event_type="chat",
                    disable_history_compression=True,
                ),
            ],
        )

    def to_pretty_json(self) -> str:
        return json.dumps(
            {
                "name": self.name,
                "character_id": self.character_id,
                "preset": self.preset,
                "turns": [asdict(turn) for turn in self.turns],
            },
            ensure_ascii=False,
            indent=2,
        )


def _safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _copy_tree_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        raise TypeError(f"Expected JSON object in {path}")
    return loaded


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    _safe_mkdir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _usage_from_response(response) -> Dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "reasoning_tokens": int(getattr(usage, "reasoning_tokens", 0) or 0),
        "cached_prompt_tokens": int(getattr(usage, "cached_prompt_tokens", 0) or 0),
        "cache_write_tokens": int(getattr(usage, "cache_write_tokens", 0) or 0),
        "cost": getattr(usage, "cost", None),
        "cost_currency": getattr(usage, "cost_currency", None),
        "cost_source": getattr(usage, "cost_source", None),
        "raw": getattr(usage, "raw", {}) or {},
    }


class GenerationTestRuntime:
    def __init__(
        self,
        *,
        source_base_dir: str,
        live_mode: bool = False,
        sandbox_dir: Optional[str] = None,
        prompts_dir: Optional[str] = None,
        histories_dir: Optional[str] = None,
        character_id: Optional[str] = None,
    ) -> None:
        self.source_base_dir = Path(source_base_dir).resolve()
        self.live_mode = bool(live_mode)
        self._sandbox_dir_arg = sandbox_dir
        self._prompts_dir_arg = prompts_dir
        self._histories_dir_arg = histories_dir
        self.runtime_base_dir = self._prepare_runtime_base_dir()
        self.prompts_dir = Path(prompts_dir).resolve() if prompts_dir else (self.source_base_dir / "Prompts")
        self.histories_dir = Path(histories_dir).resolve() if histories_dir else (self.runtime_base_dir / "Histories")
        self.settings_path = self.runtime_base_dir / "Settings" / "settings.json"
        self._original_cwd = Path.cwd()
        self._set_runtime_env()
        os.chdir(self.runtime_base_dir)

        shutdown_event_bus()
        self.event_bus = get_event_bus()

        from controllers.settings_controller import SettingsController
        from controllers.protocols_controller import ProtocolsController
        from controllers.api_presets_controller import ApiPresetsController
        from controllers.embedding_presets_controller import EmbeddingPresetsController
        from controllers.history_controller import HistoryController
        from controllers.prompt_controller import PromptController
        from controllers.character_controller import CharacterController
        from controllers.model_controller import ModelController

        self.settings_controller = SettingsController(str(self.settings_path))
        self.settings = self.settings_controller.settings
        self.protocols_controller = ProtocolsController()
        self.api_presets_controller = ApiPresetsController()
        self.embedding_presets_controller = EmbeddingPresetsController()
        self.history_controller = HistoryController()
        self.prompt_controller = PromptController()
        self.character_controller = CharacterController(self.settings)
        self.model_controller = ModelController(self.settings)

        if character_id:
            self.set_current_character(character_id)

    def close(self) -> None:
        shutdown_event_bus()
        try:
            os.chdir(self._original_cwd)
        except Exception:
            pass

    def _prepare_runtime_base_dir(self) -> Path:
        if self.live_mode:
            return self.source_base_dir

        if self._sandbox_dir_arg:
            sandbox_root = Path(self._sandbox_dir_arg).resolve()
            sandbox_dir = sandbox_root
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            sandbox_dir = (
                Path.cwd()
                / ".generation_tester_sandboxes"
                / self.source_base_dir.name
                / "sandboxes"
                / stamp
            ).resolve()

        _safe_mkdir(sandbox_dir)
        _copy_tree_if_exists(self.source_base_dir / "Settings", sandbox_dir / "Settings")
        _copy_tree_if_exists(self.source_base_dir / "Histories", sandbox_dir / "Histories")
        _safe_mkdir(sandbox_dir / "SavedMessages")
        src_last_ctx = self.source_base_dir / "SavedMessages" / "last_request_context.json"
        if src_last_ctx.exists():
            shutil.copy2(src_last_ctx, sandbox_dir / "SavedMessages" / "last_request_context.json")
        src_last_gen = self.source_base_dir / "SavedMessages" / "last_generation_input.json"
        if src_last_gen.exists():
            shutil.copy2(src_last_gen, sandbox_dir / "SavedMessages" / "last_generation_input.json")
        return sandbox_dir

    def _set_runtime_env(self) -> None:
        os.environ["NEUROMITA_BASE_DIR"] = str(self.runtime_base_dir)
        os.environ["NEUROMITA_PROMPTS_DIR"] = str(self.prompts_dir)
        os.environ["NEUROMITA_HISTORIES_DIR"] = str(self.histories_dir)

    @property
    def last_request_context_path(self) -> Path:
        return self.runtime_base_dir / "SavedMessages" / "last_request_context.json"

    @property
    def last_generation_input_path(self) -> Path:
        return self.runtime_base_dir / "SavedMessages" / "last_generation_input.json"

    def get_current_character_profile(self) -> Dict[str, Any]:
        return use(CharacterRegistry).current_profile()

    def get_character_ref(self, character_id: str):
        if not character_id:
            return None
        return use(CharacterRegistry).get(str(character_id))

    @staticmethod
    def _generate_from_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Тестовый прогон одного chat-запроса через GenerationService."""
        request = ChatGenerationRequest(
            character_id=payload.get("character_id") or payload.get("char_id") or None,
            user_input=payload.get("user_input", "") or "",
            system_input=payload.get("system_input", "") or "",
            image_data=list(payload.get("image_data") or []),
            image_source=payload.get("image_source", "") or "",
            event_type=payload.get("event_type", "chat") or "chat",
            sender=payload.get("sender", "Player") or "Player",
            participants=list(payload.get("participants") or []),
            req_id=payload.get("req_id"),
            origin_message_id=payload.get("origin_message_id"),
            task_uid=payload.get("message_id"),
            policy=RequestPolicy.from_dict(payload["policy"]) if isinstance(payload.get("policy"), dict) else None,
        )
        result = use(GenerationService).generate_chat(request)
        return asdict(result) if result is not None else None

    def set_current_character(self, character_id: str) -> None:
        if not character_id:
            return
        self.event_bus.emit(
            Events.Character.SET_CURRENT,
            {"character_id": str(character_id)},
            sync=True,
        )

    def resolve_preset_id(self, preset: int | str | None) -> Optional[int]:
        if preset is None:
            return None
        if isinstance(preset, int):
            return preset
        raw = str(preset).strip()
        if not raw or raw.lower() == "current":
            return None
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return self.model_controller.preset_resolver.resolve_preset_id_by_name(raw)
        except Exception:
            return None

    def read_last_request_context(self) -> Dict[str, Any]:
        if not self.last_request_context_path.exists():
            return {}
        try:
            return _read_json(self.last_request_context_path)
        except Exception as e:
            logger.warning(f"[GenerationTester] Failed to read last request context: {e}")
            return {}

    def snapshot_last_request_context(self, dst_path: Path) -> None:
        if not self.last_request_context_path.exists():
            return
        _safe_mkdir(dst_path.parent)
        shutil.copy2(self.last_request_context_path, dst_path)

    def read_last_generation_input(self) -> Dict[str, Any]:
        if not self.last_generation_input_path.exists():
            return {}
        try:
            return _read_json(self.last_generation_input_path)
        except Exception as e:
            logger.warning(f"[GenerationTester] Failed to read last generation input: {e}")
            return {}

    def snapshot_last_generation_input(self, dst_path: Path) -> None:
        if not self.last_generation_input_path.exists():
            return
        _safe_mkdir(dst_path.parent)
        shutil.copy2(self.last_generation_input_path, dst_path)

    def generate_turn(
        self,
        turn: GenerationTurn,
        *,
        default_character_id: Optional[str] = None,
        default_preset: int | str | None = None,
        timeout: float = 600.0,
    ) -> Dict[str, Any]:
        char_id = turn.character_id or default_character_id or self.get_current_character_profile().get("character_id") or ""
        if char_id:
            self.set_current_character(char_id)
        preset_id = self.resolve_preset_id(turn.preset if turn.preset is not None else default_preset)

        payload = turn.to_payload()
        if preset_id is not None:
            payload["preset_id"] = preset_id
        if char_id:
            payload["character_id"] = char_id

        started_at = datetime.utcnow().isoformat() + "Z"
        result = self._generate_from_payload(payload)
        token_stats = use(ModelStateService).token_stats()
        context = self.read_last_request_context()
        return {
            "started_at": started_at,
            "input": asdict(turn),
            "character_id": char_id,
            "preset_id": preset_id,
            "result": result,
            "token_stats": token_stats if isinstance(token_stats, dict) else {},
            "last_request_context": context,
        }

    def replay_last_request(
        self,
        *,
        preset: int | str | None = None,
        character_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        saved = self.read_last_request_context()
        messages = saved.get("messages") or []
        if not isinstance(messages, list):
            raise RuntimeError("last_request_context.json has no valid messages array")

        char_id = character_id or self.get_current_character_profile().get("character_id") or ""
        if char_id:
            self.set_current_character(char_id)
        preset_id = self.resolve_preset_id(preset)

        response = self.model_controller.model.generate(
            messages,
            preset_id=preset_id,
        )
        if response is None:
            raise RuntimeError("ChatModel.generate returned None during replay")

        replay_context = self.read_last_request_context()
        return {
            "character_id": char_id or None,
            "preset_id": preset_id,
            "message_count": len(messages),
            "response_text": getattr(response, "text", "") or "",
            "response_model": getattr(response, "model", None),
            "response_provider": getattr(response, "provider_name", None),
            "usage": _usage_from_response(response),
            "last_request_context": replay_context,
        }

    def replay_last_generation_input(
        self,
        *,
        timeout: float = 600.0,
    ) -> Dict[str, Any]:
        saved = self.read_last_generation_input()
        incoming_event = saved.get("incoming_event")
        if not isinstance(incoming_event, dict):
            raise RuntimeError("last_generation_input.json has no valid incoming_event object")

        payload = dict(incoming_event)
        payload.pop("stream_callback", None)

        char_id = str(payload.get("character_id") or payload.get("char_id") or payload.get("character") or "")
        if char_id:
            self.set_current_character(char_id)

        started_at = datetime.utcnow().isoformat() + "Z"
        result = self._generate_from_payload(payload)
        token_stats = use(ModelStateService).token_stats()
        last_ctx = self.read_last_request_context()
        latest_input = self.read_last_generation_input()
        return {
            "started_at": started_at,
            "input": payload,
            "character_id": char_id or None,
            "preset_id": payload.get("preset_id"),
            "result": result,
            "token_stats": token_stats if isinstance(token_stats, dict) else {},
            "last_request_context": last_ctx,
            "last_generation_input": latest_input,
        }


def save_run_artifacts(
    *,
    output_dir: Path,
    summary: Dict[str, Any],
    turn_results: List[Dict[str, Any]],
) -> None:
    _safe_mkdir(output_dir)
    _write_json(output_dir / "summary.json", summary)
    for idx, item in enumerate(turn_results, start=1):
        _write_json(output_dir / f"turn_{idx:03d}.json", item)
