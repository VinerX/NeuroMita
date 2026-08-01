"""AI-engine proxy for the optional RAG cross-encoder reranker."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from handlers.ai_engine.rag_client import rerank_candidates
from main_logger import logger


@dataclass(frozen=True, slots=True)
class RerankerReadiness:
    """Состояние реранкера для статуса RAG: без RPC и без загрузки модели."""

    model_loaded: bool = False
    failed: bool = False


class CrossEncoderReranker:
    """Singleton per model_name. Call CrossEncoderReranker.get(name)."""

    _instances: dict[str, "CrossEncoderReranker"] = {}
    _cls_lock: Lock = Lock()

    def __init__(self, model_name: str) -> None:
        self.model_name = str(model_name or "")
        self._model = None
        self._failed = False
        self._runtime_ready = False
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
        return RerankerReadiness(
            model_loaded=bool(inst._runtime_ready or inst._model),
            failed=bool(inst._failed),
        )

    @classmethod
    def forget_runtime(cls, *, reason: str = "", clear_failed: bool = True) -> None:
        """Движок перезапустился — модели в нём больше нет. Сбрасываем признаки
        прогрева, иначе статус остаётся зелёным на пустом рантайме.

        clear_failed=False — рестарт не удался: прошлую ошибку затирать нельзя,
        иначе красный статус подменяется бесконечным «загружается»."""
        for inst in list(cls._instances.values()):
            with inst._load_lock:
                inst._runtime_ready = False
                inst._model = None
                if clear_failed:
                    inst._failed = False
        if reason:
            logger.info(f"[CrossEncoder] прогрев сброшен: {reason}")
        cls._notify_status_changed()

    def ensure_loaded(self) -> bool:
        """Поднять реранкер заранее (фоновый прогрев на старте). Без этого модель
        грузится внутри первого запроса и отъедает у него до минуты."""
        return self._ensure_runtime()

    def _ensure_runtime(self) -> bool:
        if self._runtime_ready:
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
                self._runtime_ready = bool(
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
                if self._runtime_ready:
                    self._failed = False
                    self._notify_status_changed()
                return self._runtime_ready
            except Exception as exc:
                logger.warning(
                    f"[CrossEncoder] RAG runtime activation failed: {exc}"
                )
                self._runtime_ready = False
                return False

    def _set_failed(self, failed: bool) -> None:
        # Статус RAG считается по этим флагам, поэтому смена состояния обязана
        # доехать до индикатора; одинаковое значение шину не дёргает.
        if bool(self._failed) == bool(failed):
            return
        self._failed = bool(failed)
        self._notify_status_changed()

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

        if not self._ensure_runtime():
            logger.warning("[CrossEncoder] RAG reranker runtime is unavailable")
            self._set_failed(True)
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
            logger.warning(f"[CrossEncoder] AI engine rerank failed (ignored): {exc}")
            self._set_failed(True)
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
            with self._load_lock:
                self._model = True
            self._set_failed(False)
