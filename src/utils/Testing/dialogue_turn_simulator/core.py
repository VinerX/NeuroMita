from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MitaMode(str, Enum):
    NORMAL = "normal"
    HUNT = "hunt"
    INTERACTION = "interaction"


class SimulationError(RuntimeError):
    pass


UNITY_DIALOGUE_CHARACTER_IDS = (
    "Crazy",
    "Cappie",
    "Kind",
    "ShortHair",
    "Mila",
    "Sleepy",
    "Creepy",
    "Ghost",
)


@dataclass(slots=True)
class DialoguePolicy:
    auto_dialogue_enabled: bool = True
    max_chain_turns: int = 3
    max_continues: int = 3
    game_master_enabled: bool = False
    game_master_repeat: int = 2
    settings_revision: int = 0

    def apply_server_payload(self, payload: dict[str, Any]) -> None:
        body = payload.get("body") if isinstance(payload.get("body"), dict) else payload
        settings = body.get("settings") if isinstance(body.get("settings"), dict) else body
        self.auto_dialogue_enabled = _as_bool(
            settings.get("MITA_DIALOGUE_AUTO"),
            self.auto_dialogue_enabled,
        )
        self.max_chain_turns = _bounded_int(
            settings.get("DIALOGUE_MAX_CHAIN_TURNS"),
            self.max_chain_turns,
            1,
            24,
        )
        self.max_continues = _bounded_int(
            settings.get("DIALOGUE_MAX_CONTINUES"),
            self.max_continues,
            0,
            12,
        )
        self.game_master_enabled = _as_bool(settings.get("GM_ON"), self.game_master_enabled)
        self.game_master_repeat = _bounded_int(
            settings.get("GM_REPEAT"),
            self.game_master_repeat,
            1,
            100,
        )
        self.settings_revision = _bounded_int(
            body.get("settings_revision"),
            self.settings_revision,
            0,
            2**31 - 1,
        )

    def chain_turn_limit(self) -> int:
        return self.max_chain_turns


@dataclass(slots=True)
class SimulatedMita:
    character_id: str
    display_name: str
    enabled: bool = True
    distance: float = 5.0
    mode: MitaMode = MitaMode.NORMAL
    order_points: int = 0

    @property
    def is_available(self) -> bool:
        return self.enabled and self.distance <= 25.0

    def runtime_context(self) -> dict[str, Any]:
        contexts = {
            MitaMode.NORMAL: {
                "world_state": "The simulated Unity character is in a normal dialogue state.",
                "runtime_rules": "Normal dialogue behavior is active.",
                "runtime_capabilities": "The character can hear nearby speakers and participate in dialogue.",
                "intent_rules": "Use structured dialogue intents only when an explicit action is needed.",
                "runtime_events": ["Simulator character mode: normal."],
            },
            MitaMode.HUNT: {
                "world_state": "The simulated Unity character is actively hunting the player.",
                "runtime_rules": "Hunt behavior is active; dialogue should remain consistent with pursuit.",
                "runtime_capabilities": "The character can pursue the player and speak while in range.",
                "intent_rules": "Do not claim that hunt mode ended unless the scene context says so.",
                "runtime_events": ["Simulator character mode: hunt."],
            },
            MitaMode.INTERACTION: {
                "world_state": "The simulated Unity character is engaged in an interaction state.",
                "runtime_rules": "Interaction behavior is active; dialogue should acknowledge the current interaction.",
                "runtime_capabilities": "The character can speak and react to the ongoing interaction.",
                "intent_rules": "Keep requested actions compatible with the active interaction.",
                "runtime_events": ["Simulator character mode: interaction."],
            },
        }
        context = dict(contexts[self.mode])
        context["runtime_static_catalog"] = ""
        return context


@dataclass(frozen=True, slots=True)
class PreparedTurn:
    speaker_id: str
    speaker_name: str
    prompt: str
    event_type: str
    sender: str
    from_player: bool
    automatic: bool
    participant_ids: tuple[str, ...] = ()
    addressed_source_id: str = ""
    addressed_message: str = ""
    full_response: str = ""
    address_map: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class TurnResult:
    turn_index: int
    speaker_id: str
    speaker_name: str
    mode: MitaMode
    response: str
    automatic: bool
    active_order: tuple[str, ...]
    chain_turn_count: int
    chain_turn_limit: int


@dataclass(frozen=True, slots=True)
class AddressedTurn:
    source_id: str
    target_id: str
    message: str
    full_response: str
    address_map: tuple[tuple[str, str], ...]


@dataclass(slots=True)
class DialogueSimulation:
    mitas: list[SimulatedMita]
    policy: DialoguePolicy = field(default_factory=DialoguePolicy)
    seed: int = 7
    history: list[TurnResult] = field(default_factory=list, init=False)
    pending_speaker_id: str = field(default="", init=False)
    pending_addressed_turn: AddressedTurn | None = field(default=None, init=False)
    last_response: str = field(default="", init=False)
    last_speaker_id: str = field(default="", init=False)
    stop_reason: str = field(default="Ожидание сообщения игрока", init=False)
    _dialogue_turn_count: int = field(default=0, init=False)
    _addressed_turns: list[AddressedTurn] = field(default_factory=list, init=False)
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    @property
    def auto_dialogue_enabled(self) -> bool:
        return self.policy.auto_dialogue_enabled

    @auto_dialogue_enabled.setter
    def auto_dialogue_enabled(self, value: bool) -> None:
        self.policy.auto_dialogue_enabled = bool(value)

    @property
    def chain_turn_count(self) -> int:
        return self._dialogue_turn_count

    def active_mitas(self) -> list[SimulatedMita]:
        return [mita for mita in self.mitas if mita.is_available]

    def ordered_active_mitas(self) -> list[SimulatedMita]:
        return sorted(self.active_mitas(), key=lambda mita: -mita.order_points)

    def get_mita(self, character_id: str) -> SimulatedMita:
        for mita in self.mitas:
            if mita.character_id == character_id:
                return mita
        raise SimulationError(f"Неизвестная Мита: {character_id}")

    def set_next_speaker(self, character_id: str) -> None:
        target = self.get_mita(character_id)
        active = self.active_mitas()
        if target not in active:
            raise SimulationError("Следующим можно назначить только доступного персонажа")
        target.order_points = max((item.order_points for item in active), default=0) + 1

    def enqueue_addressed_segments(
        self,
        addressed_segments: list[tuple[str, str]] | tuple[tuple[str, str], ...],
        *,
        source_id: str,
        full_response: str,
        address_map: tuple[tuple[str, str], ...],
        reset_pending: bool = False,
    ) -> None:
        if reset_pending:
            self._addressed_turns.clear()
            self._dialogue_turn_count = 1
        active_ids = {mita.character_id for mita in self.active_mitas()}
        texts_by_target: dict[str, list[str]] = {}
        target_order: list[str] = []
        for raw_target_id, raw_message in addressed_segments:
            target_id = str(raw_target_id or "").strip()
            message = str(raw_message or "").strip()
            if (
                target_id in active_ids
                and target_id != source_id
                and message
            ):
                if target_id not in texts_by_target:
                    texts_by_target[target_id] = []
                    target_order.append(target_id)
                texts_by_target[target_id].append(message)

        for target_id in target_order:
            self._addressed_turns.append(AddressedTurn(
                source_id=source_id,
                target_id=target_id,
                message=" ".join(texts_by_target[target_id]),
                full_response=str(full_response or "").strip(),
                address_map=tuple(address_map),
            ))

    def clear_addressed_turns(self) -> None:
        self._addressed_turns.clear()
        self.pending_addressed_turn = None

    def can_schedule_automatic_turns(self) -> bool:
        return (
            self.policy.auto_dialogue_enabled
            and self.policy.chain_turn_limit() > 1
        )

    @property
    def has_pending_addressed_turns(self) -> bool:
        return bool(self._addressed_turns or self.pending_addressed_turn)

    def reset_orders(self, *, randomize: bool = False) -> None:
        for mita in self.active_mitas():
            mita.order_points = self._rng.randrange(0, 24) if randomize else 0

    def reset(self) -> None:
        self.history.clear()
        self.pending_speaker_id = ""
        self.pending_addressed_turn = None
        self.last_response = ""
        self.last_speaker_id = ""
        self.stop_reason = "Ожидание сообщения игрока"
        self._dialogue_turn_count = 0
        self._addressed_turns.clear()
        self._rng.seed(self.seed)
        for mita in self.mitas:
            mita.order_points = 0

    def prepare_player_turn(
        self,
        message: str,
        target_character_id: str | None = None,
    ) -> PreparedTurn:
        text = str(message or "").strip()
        if not text:
            raise SimulationError("Введите реплику игрока")
        active = self.ordered_active_mitas()
        if not active:
            raise SimulationError("Нет доступных Мит в радиусе 25 метров")
        speaker = active[0]
        if target_character_id:
            speaker = next(
                (item for item in active if item.character_id == target_character_id),
                None,
            )
            if speaker is None:
                raise SimulationError("Упомянутая Мита сейчас недоступна")
        speaker.order_points -= 25
        self._dialogue_turn_count = 1
        self._addressed_turns.clear()
        self.pending_speaker_id = ""
        self.pending_addressed_turn = None
        self.stop_reason = f"Ожидание ответа: {speaker.display_name}"
        return PreparedTurn(
            speaker_id=speaker.character_id,
            speaker_name=speaker.display_name,
            prompt=text,
            event_type="answer",
            sender="Player",
            from_player=True,
            automatic=False,
            participant_ids=tuple(item.character_id for item in active),
        )

    def prepare_automatic_turn(self, prompt: str) -> PreparedTurn:
        if not self.pending_speaker_id:
            raise SimulationError("Следующий автоматический ход не запланирован")
        speaker_id = self.pending_speaker_id
        self.pending_speaker_id = ""
        addressed_turn = self.pending_addressed_turn
        self.pending_addressed_turn = None
        speaker = self.get_mita(speaker_id)
        if not speaker.is_available:
            self.stop_reason = f"{speaker.display_name} больше недоступна"
            raise SimulationError(self.stop_reason)
        self.stop_reason = f"Ожидание ответа: {speaker.display_name}"
        return PreparedTurn(
            speaker_id=speaker.character_id,
            speaker_name=speaker.display_name,
            prompt=(addressed_turn.full_response if addressed_turn else str(prompt or "")),
            event_type="react",
            sender=speaker.character_id,
            from_player=False,
            automatic=True,
            participant_ids=tuple(item.character_id for item in self.ordered_active_mitas()),
            addressed_source_id=addressed_turn.source_id if addressed_turn else "",
            addressed_message=addressed_turn.message if addressed_turn else "",
            full_response=addressed_turn.full_response if addressed_turn else "",
            address_map=addressed_turn.address_map if addressed_turn else (),
        )

    def complete_turn(
        self,
        turn: PreparedTurn,
        response: str,
        *,
        plan_follow_up: bool = True,
    ) -> TurnResult:
        speaker = self.get_mita(turn.speaker_id)
        self.last_response = str(response or "")
        self.last_speaker_id = speaker.character_id
        result = TurnResult(
            turn_index=len(self.history) + 1,
            speaker_id=speaker.character_id,
            speaker_name=speaker.display_name,
            mode=speaker.mode,
            response=self.last_response,
            automatic=turn.automatic,
            active_order=tuple(item.character_id for item in self.ordered_active_mitas()),
            chain_turn_count=self._dialogue_turn_count,
            chain_turn_limit=self.policy.chain_turn_limit(),
        )
        self.history.append(result)
        if plan_follow_up:
            self.plan_follow_up(speaker.character_id, from_player=turn.from_player)
        return result

    def record_game_master_turn(self, response: str) -> TurnResult:
        self.last_response = str(response or "")
        self.last_speaker_id = "GameMaster"
        result = TurnResult(
            turn_index=len(self.history) + 1,
            speaker_id="GameMaster",
            speaker_name="GameMaster",
            mode=MitaMode.NORMAL,
            response=self.last_response,
            automatic=True,
            active_order=tuple(item.character_id for item in self.ordered_active_mitas()),
            chain_turn_count=self._dialogue_turn_count,
            chain_turn_limit=self.policy.chain_turn_limit(),
        )
        self.history.append(result)
        return result

    def plan_follow_up(self, from_character_id: str, *, from_player: bool) -> None:
        self.pending_speaker_id = ""
        self.pending_addressed_turn = None
        if not self.policy.auto_dialogue_enabled:
            self._addressed_turns.clear()
            self.stop_reason = "Автодиалог выключен"
            return
        active = self.active_mitas()
        if not active:
            self.stop_reason = "Нет доступных Мит"
            return
        total_limit = self.policy.chain_turn_limit()
        if self._dialogue_turn_count >= total_limit:
            self._addressed_turns.clear()
            self.stop_reason = f"Достигнут максимум ходов в цепочке: {total_limit}"
            return

        next_speaker: SimulatedMita | None = None
        selected_addressed_turn: AddressedTurn | None = None
        while self._addressed_turns:
            addressed_turn = self._addressed_turns.pop(0)
            addressed = next(
                (item for item in active if item.character_id == addressed_turn.target_id),
                None,
            )
            if addressed is not None:
                next_speaker = addressed
                selected_addressed_turn = addressed_turn
                break
        if next_speaker is None:
            self.stop_reason = "Нет адресованных сегментов — цепочка завершена"
            return

        self._dialogue_turn_count += 1
        self.pending_speaker_id = next_speaker.character_id
        self.pending_addressed_turn = selected_addressed_turn
        self.stop_reason = f"Следующий ход: {next_speaker.display_name}"

    @staticmethod
    def game_master_runtime_context() -> dict[str, Any]:
        return {
            "world_state": "The simulated GameMaster is observing the active dialogue.",
            "runtime_rules": "Moderate only through supported structured dialogue intents.",
            "runtime_static_catalog": "",
            "runtime_capabilities": "Can observe the conversation and issue scene directives.",
            "intent_rules": "Use dialogue broadcast or direct system-message intents for directives.",
            "runtime_events": ["Simulator GameMaster observation requested."],
        }


def create_default_simulation() -> DialogueSimulation:
    return DialogueSimulation(
        mitas=[
            SimulatedMita("Crazy", "Безумная Мита", order_points=80),
            SimulatedMita("Cappie", "Кепочка", order_points=70),
            SimulatedMita("Kind", "Добрая Мита", order_points=60),
            SimulatedMita("ShortHair", "Коротковолосая Мита", order_points=50),
            SimulatedMita("Mila", "Мила", order_points=40),
            SimulatedMita("Sleepy", "Сонная Мита", order_points=30),
            SimulatedMita("Creepy", "Жуткая Мита", order_points=20),
            SimulatedMita("Ghost", "Призрачная Мита", order_points=10),
        ]
    )


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "да", "вкл"}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(minimum, min(parsed, maximum))
