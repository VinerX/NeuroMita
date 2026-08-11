from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum


class MitaMode(str, Enum):
    NORMAL = "normal"
    HUNT = "hunt"
    INTERACTION = "interaction"


class SimulationError(RuntimeError):
    pass


_MODE_RESPONSES: dict[MitaMode, tuple[str, ...]] = {
    MitaMode.NORMAL: (
        "Подхватываю мысль: {topic}.",
        "Мне есть что добавить про {topic}.",
        "Слушаю вас. Если коротко — {topic}.",
    ),
    MitaMode.HUNT: (
        "Я сейчас на охоте, но услышала: {topic}.",
        "Не теряю цель из виду. По теме — {topic}.",
        "Говори быстрее. Я запомнила: {topic}.",
    ),
    MitaMode.INTERACTION: (
        "Я занята взаимодействием, но отвечу: {topic}.",
        "Секунду, закончу действие. Насчёт этого: {topic}.",
        "Отвечаю, не прерывая действие: {topic}.",
    ),
}


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
class SimulatedMita:
    character_id: str
    display_name: str
    enabled: bool = True
    distance: float = 5.0
    mode: MitaMode = MitaMode.NORMAL
    order_points: int = 0
    response_index: int = 0

    @property
    def is_available(self) -> bool:
        return self.enabled and self.distance <= 25.0

    def create_response(self, prompt: str) -> str:
        templates = _MODE_RESPONSES[self.mode]
        template = templates[self.response_index % len(templates)]
        self.response_index += 1
        topic = " ".join(str(prompt or "тишина").strip().split())
        if len(topic) > 88:
            topic = topic[:85].rstrip() + "…"
        return template.format(topic=topic or "тишина")


@dataclass(frozen=True, slots=True)
class TurnResult:
    turn_index: int
    speaker_id: str
    speaker_name: str
    mode: MitaMode
    response: str
    automatic: bool
    active_order: tuple[str, ...]
    auto_turn_counter: int
    auto_turn_limit: int


@dataclass(slots=True)
class DialogueSimulation:
    mitas: list[SimulatedMita]
    auto_dialogue_enabled: bool = True
    limit_modifier_percent: float = 100.0
    seed: int = 7
    history: list[TurnResult] = field(default_factory=list, init=False)
    pending_speaker_id: str = field(default="", init=False)
    last_response: str = field(default="", init=False)
    last_speaker_id: str = field(default="", init=False)
    stop_reason: str = field(default="Ожидание сообщения игрока", init=False)
    _dialogue_auto_limit: int = field(default=1, init=False)
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    @property
    def auto_turn_counter(self) -> int:
        return self._dialogue_auto_limit

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

    def reset_orders(self, *, randomize: bool = False) -> None:
        for mita in self.active_mitas():
            mita.order_points = self._rng.randrange(0, 24) if randomize else 0

    def reset(self) -> None:
        self.history.clear()
        self.pending_speaker_id = ""
        self.last_response = ""
        self.last_speaker_id = ""
        self.stop_reason = "Ожидание сообщения игрока"
        self._dialogue_auto_limit = 1
        self._rng.seed(self.seed)
        for mita in self.mitas:
            mita.order_points = 0
            mita.response_index = 0

    def begin_player_turn(self, message: str) -> TurnResult:
        text = str(message or "").strip()
        if not text:
            raise SimulationError("Введите реплику игрока")

        active = self.ordered_active_mitas()
        if not active:
            raise SimulationError("Нет доступных Мит в радиусе 25 метров")

        speaker = active[0]
        speaker.order_points -= 25
        self._dialogue_auto_limit = 1
        result = self._emit_turn(speaker, text, automatic=False)
        self._plan_follow_up(from_player=True)
        return result

    def step(self) -> TurnResult:
        if not self.pending_speaker_id:
            raise SimulationError("Следующий автоматический ход не запланирован")

        speaker_id = self.pending_speaker_id
        self.pending_speaker_id = ""
        speaker = self.get_mita(speaker_id)
        if not speaker.is_available:
            self.stop_reason = f"{speaker.display_name} больше недоступна"
            raise SimulationError(self.stop_reason)

        result = self._emit_turn(speaker, self.last_response, automatic=True)
        self._plan_follow_up(from_player=False)
        return result

    def run_until_stop(self, max_steps: int = 64) -> list[TurnResult]:
        produced: list[TurnResult] = []
        while self.pending_speaker_id and len(produced) < max_steps:
            produced.append(self.step())
        if self.pending_speaker_id:
            raise SimulationError("Защитный лимит симуляции превышен")
        return produced

    def _emit_turn(self, speaker: SimulatedMita, prompt: str, *, automatic: bool) -> TurnResult:
        response = speaker.create_response(prompt)
        self.last_response = response
        self.last_speaker_id = speaker.character_id
        result = TurnResult(
            turn_index=len(self.history) + 1,
            speaker_id=speaker.character_id,
            speaker_name=speaker.display_name,
            mode=speaker.mode,
            response=response,
            automatic=automatic,
            active_order=tuple(item.character_id for item in self.ordered_active_mitas()),
            auto_turn_counter=self._dialogue_auto_limit,
            auto_turn_limit=self._total_limit(len(self.active_mitas()), speaker.character_id),
        )
        self.history.append(result)
        return result

    def _plan_follow_up(self, *, from_player: bool) -> None:
        self.pending_speaker_id = ""
        if not self.auto_dialogue_enabled:
            self.stop_reason = "Автодиалог выключен"
            return

        active = self.active_mitas()
        if not active:
            self.stop_reason = "Нет доступных Мит"
            return

        total_limit = self._total_limit(len(active), self.last_speaker_id)
        if self._dialogue_auto_limit >= total_limit and not from_player:
            self._dialogue_auto_limit = 1
            self.reset_orders(randomize=True)
            self.stop_reason = "Лимит автоматических ходов исчерпан"
            return

        if not from_player:
            self.get_mita(self.last_speaker_id).order_points -= 25

        if len(active) <= 1 and not from_player:
            self._dialogue_auto_limit = 1
            self.reset_orders(randomize=True)
            self.stop_reason = "Для продолжения нужна ещё одна доступная Мита"
            return

        ordered = self.ordered_active_mitas()
        next_speaker = ordered[0] if ordered else None
        if next_speaker is None or next_speaker.character_id == self.last_speaker_id:
            self._dialogue_auto_limit = 1
            self.reset_orders(randomize=True)
            self.stop_reason = "Подходящий следующий собеседник не найден"
            return

        self._dialogue_auto_limit = 1 if from_player else self._dialogue_auto_limit + 1
        self.pending_speaker_id = next_speaker.character_id
        self.stop_reason = f"Следующий ход: {next_speaker.display_name}"

    def _total_limit(self, character_count: int, from_character_id: str) -> int:
        total = math.ceil(character_count * max(0.0, self.limit_modifier_percent) / 100.0)
        if from_character_id.casefold() == "gamemaster":
            total += 5
        return total


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
