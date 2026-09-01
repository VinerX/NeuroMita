"""AI-engine proxy for the optional RAG cross-encoder reranker."""
from __future__ import annotations
from core.error_utils import format_exception

from dataclasses import dataclass
from threading import Lock

from handlers.ai_engine.rag_client import rerank_candidates
from main_logger import logger
from services.contracts import ModelState


@dataclass(frozen=True, slots=True)
class RerankerReadiness:
    """Состояние реранкера для статуса RAG: без RPC и без загрузки модели."""

    state: ModelState = ModelState.LOADING
    error: str = ""

    @property
    def model_loaded(self) -> bool:
        return self.state is ModelState.READY

    @property
    def failed(self) -> bool:
        return self.state is ModelState.ERROR


class CrossEncoderReranker:
    """Singleton per model_name. Call CrossEncoderReranker.get(name)."""

    _instances: dict[str, "CrossEncoderReranker"] = {}
    _cls_lock: Lock = Lock()
    # Поколение рантайма. Рантайм у всех экземпляров общий (один процесс движка),
    # поэтому счётчик классовый: рестарт делает недействительными все ответы,
    # начатые до него.
    _runtime_epoch: int = 0

    def __init__(self, model_name: str) -> None:
        self.model_name = str(model_name or "")
        self._state = ModelState.LOADING
        self._error = ""
        # Лок состояния отдельно от лока загрузки: активация модели длится
        # минутами, и сброс рантайма не должен её дожидаться, чтобы записать
        # ERROR — иначе индикатор врёт ровно столько, сколько грузится модель.
        self._state_lock = Lock()
        self._load_lock = Lock()

    @classmethod
    def get(cls, model_name: str) -> "CrossEncoderReranker":
        model_name = str(model_name or "")
        if model_name not in cls._instances:
            with cls._cls_lock:
                if model_name not in cls._instances:
                    cls._instances[model_name] = cls(model_name)
        return cls._instances[model_name]

    @classmethod
    def readiness(cls, model_name: str) -> RerankerReadiness:
        """Прогрет ли реранкер в движке — без RPC и без загрузки модели.
        Модель поднимается лениво при первом реранке, поэтому статус RAG обязан
        различать «включён», «готов отвечать без минутной паузы» и «сломан»:
        иначе упавший реранкер вечно висит как «загружается»."""
        inst = cls._instances.get(str(model_name or ""))
        if inst is None:
            return RerankerReadiness()
        state, error = inst._snapshot()
        return RerankerReadiness(state=state, error=error)

    @classmethod
    def reset_runtime(cls, *, failed: bool, error: str = "", reason: str = "") -> None:
        """Движок перезапустился — модели в нём больше нет.

        failed=True означает, что воркер не поднялся: это ошибка, а не «грузится».
        Прогрев в таком состоянии бессмысленен — модель поднимет только явный
        успешный рестарт, он же вернёт состояние в LOADING.

        Смена поколения обязательна: реранк, начатый в прошлом процессе, может
        вернуться уже после рестарта и выставить READY по мёртвому рантайму."""
        state = ModelState.ERROR if failed else ModelState.LOADING
        with cls._cls_lock:
            cls._runtime_epoch += 1
            instances = list(cls._instances.values())
        for inst in instances:
            with inst._state_lock:
                inst._state = state
                inst._error = str(error or "") if failed else ""
        if reason:
            logger.info(f"[CrossEncoder] прогрев сброшен: {reason}")
        cls._notify_status_changed()

    def ensure_loaded(self) -> bool:
        """Поднять реранкер заранее (фоновый прогрев на старте). Без этого модель
        грузится внутри первого запроса и отъедает у него до минуты.

        Фоновый прогрев — единственный путь выхода из ошибки: запрос пользователя
        в состоянии ERROR модель не поднимает, иначе каждый rerank упирался бы в
        30-секундную активацию мёртвого рантайма."""
        return self._ensure_runtime(force=True)

    def _ensure_runtime(self, *, force: bool = False) -> bool:
        epoch = self.runtime_epoch()
        state, _ = self._snapshot()
        if state is ModelState.ERROR and not force:
            return False
        if state is ModelState.READY:
            try:
                from core.services import use
                from services.contracts import AIEngineService

                engine = use(AIEngineService).get_engine()
                is_active = getattr(engine, "is_environment_active", None)
                if callable(is_active) and is_active(
                    "rag",
                    "reranker",
                    category="rag",
                    runtime_slot="rag:reranker",
                ):
                    return True
            except Exception:
                pass

        with self._load_lock:
            try:
                from core.services import use
                from services.contracts import AIEngineService

                engine = use(AIEngineService).get_engine()
                activate = getattr(engine, "activate_environment", None)
                if not callable(activate):
                    return False
                activated = bool(
                    activate(
                        "rag",
                        "reranker",
                        category="rag",
                        runtime_slot="rag:reranker",
                        timeout=30.0,
                        validation_method="warmup_reranker",
                        validation_payload={"model_name": self.model_name},
                        validation_timeout=3600.0,
                    )
                )
                if activated:
                    return self._set_state(ModelState.READY, epoch=epoch)
                return activated
            except Exception as exc:
                logger.warning(
                    f"[CrossEncoder] RAG runtime activation failed: {format_exception(exc)}"
                )
                return False

    @classmethod
    def runtime_epoch(cls) -> int:
        with cls._cls_lock:
            return cls._runtime_epoch

    def _snapshot(self) -> tuple[ModelState, str]:
        with self._state_lock:
            return self._state, self._error

    def _set_state(self, state: ModelState, error: str = "", *, epoch: int | None = None) -> bool:
        # Статус RAG считается по этому состоянию, поэтому смена обязана доехать
        # до индикатора; одинаковое значение шину не дёргает.
        # False — результат отброшен как устаревший.
        with self._state_lock:
            if epoch is not None and epoch != self.runtime_epoch():
                logger.debug(
                    f"[CrossEncoder] результат поколения {epoch} отброшен: рантайм с тех пор сменился"
                )
                return False
            if self._state is state and self._error == error:
                return True
            self._state = state
            self._error = str(error or "")
        self._notify_status_changed()
        return True

    @staticmethod
    def _notify_status_changed() -> None:
        try:
            from core.events import Events, get_event_bus

            get_event_bus().emit(Events.GUI.UPDATE_STATUS_COLORS)
        except Exception:
            pass

    def rerank(
        self,
        query: str,
        cands: list,
        top_k: int = 20,
        alpha: float = 1.0,
        early_exit_score: float = 1.1,
    ) -> None:
        if not cands or not query:
            return

        top_k = min(len(cands), max(1, int(top_k or 1)))
        payload_candidates = []
        for candidate in cands[:top_k]:
            payload_candidates.append(
                {
                    "source": getattr(candidate, "source", ""),
                    "id": getattr(candidate, "id", 0),
                    "content": getattr(candidate, "content", ""),
                    "score": float(getattr(candidate, "score", 0.0) or 0.0),
                    "debug": dict(getattr(candidate, "debug", {}) or {}),
                }
            )

        # Поколение фиксируем до RPC: ответ мёртвого процесса не должен ни
        # зажигать зелёный, ни красить в красный уже перезапущенный рантайм.
        epoch = self.runtime_epoch()

        if not self._ensure_runtime():
            logger.warning("[CrossEncoder] RAG reranker runtime is unavailable")
            self._set_state(ModelState.ERROR, "рантайм реранкера недоступен", epoch=epoch)
            return

        try:
            result = rerank_candidates(
                model_name=self.model_name,
                query=str(query or ""),
                candidates=payload_candidates,
                top_k=top_k,
                alpha=float(alpha or 0.0),
                early_exit_score=float(early_exit_score or 0.0),
                total_candidates=len(cands),
            )
        except Exception as exc:
            logger.warning(f"[CrossEncoder] AI engine rerank failed (ignored): {format_exception(exc)}")
            self._set_state(ModelState.ERROR, format_exception(exc), epoch=epoch)
            return

        updates = result.get("updates") if isinstance(result, dict) else None
        if not isinstance(updates, list):
            updates = []

        for update in updates:
            try:
                idx = int(update.get("index", -1))
            except Exception:
                idx = -1
            if idx < 0 or idx >= top_k:
                continue

            candidate = cands[idx]
            try:
                candidate.score = float(update.get("score", candidate.score) or 0.0)
            except Exception:
                pass
            try:
                ce_score = float(update.get("cross_encoder"))
                if getattr(candidate, "debug", None) is None:
                    candidate.debug = {}
                candidate.debug["cross_encoder"] = ce_score
            except Exception:
                pass

        if bool(result.get("loaded", False)):
            self._set_state(ModelState.READY, epoch=epoch)
