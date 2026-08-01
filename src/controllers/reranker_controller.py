from __future__ import annotations

import time

from core.events import Event, Events, get_event_bus
from core.services import use
from core.task_supervisor import task_supervisor
from main_logger import logger
from services.contracts import SettingsService


class RerankerController:
    """Фоновый прогрев cross-encoder'а.

    Реранкер поднимался лениво — внутри первого же запроса, где загрузка весов
    (десятки секунд) шла одновременно с «горячим» эмбеддингом запроса и валила
    его по таймауту. Модель нужна ровно тогда, когда её использует текущая
    конфигурация, поэтому решение берётся из ``required_model_targets`` — того
    же места, что и у установщика.
    """

    _RERANK_SETTING_KEYS = frozenset({
        "RAG_ENABLED",
        "RAG_CROSS_ENCODER_ENABLED",
        "RAG_CROSS_ENCODER_MODEL",
        "RAG_CROSS_ENCODER_MODEL_CUSTOM",
    })

    def __init__(self) -> None:
        self.event_bus = get_event_bus()
        self.settings = use(SettingsService)
        self._settings_subscription = self.settings.subscribe(
            self._on_setting_changed, keys=self._RERANK_SETTING_KEYS
        )
        self.event_bus.subscribe(
            Events.Install.TASK_FINISHED, self._on_install_task_finished, weak=False
        )
        self.event_bus.subscribe(
            Events.AI.SERVICE_RESTARTED, self._on_ai_service_restarted, weak=False
        )

        self._maybe_start_warmup(reason="startup")

    def _should_warmup(self) -> bool:
        from managers.rag.install_spec import TARGET_RERANKER, required_model_targets

        return TARGET_RERANKER in required_model_targets(settings=self.settings)

    def _maybe_start_warmup(self, *, reason: str) -> None:
        if not self._should_warmup():
            return
        task_supervisor().start_thread(
            self,
            f"reranker-warmup-{reason}",
            self._warmup,
            replace=True,
        )

    def _warmup(self) -> None:
        from managers.rag.pipeline.config import resolve_ce_model
        from managers.rag.pipeline.cross_encoder import CrossEncoderReranker

        # AI engine поднимается позже контроллеров, а первый запуск модели тянет
        # веса с HF — ретраим до готовности движка, но только пока модель нужна.
        for _ in range(150):  # ~5 минут ожидания движка
            if not self._should_warmup():
                return
            model = resolve_ce_model()
            if not model:
                return
            reranker = CrossEncoderReranker.get(model)
            try:
                if reranker.ensure_loaded():
                    logger.info(f"RerankerController: реранкер '{model}' прогрет")
                    return
            except Exception as e:
                logger.debug(f"RerankerController: прогрев отложен: {e}")
            time.sleep(2.0)

    def _on_setting_changed(self, change) -> None:
        if change.key not in self._RERANK_SETTING_KEYS:
            return
        # Индикатор RAG считает готовность по прогретой модели: сменили модель —
        # состояние снова «не готово», пока новая не поднимется.
        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
        self._maybe_start_warmup(reason=f"setting:{change.key}")

    def _on_install_task_finished(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        task_id = str(data.get("task_id") or "")
        if meta.get("kind") != "rag" and not task_id.startswith("rag:"):
            return
        self._maybe_start_warmup(reason="install_finished")

    def _on_ai_service_restarted(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        if str(data.get("service") or "").strip().lower() != "rag":
            return

        # Процесс движка сменился — модели в нём нет, чем бы ни закончился
        # рестарт. Иначе плашка светит зелёным по прошлому прогреву.
        from managers.rag.pipeline.cross_encoder import CrossEncoderReranker

        ok = data.get("ok") is True
        CrossEncoderReranker.forget_runtime(
            reason="AI-воркер RAG перезапущен" if ok else "рестарт AI-воркера RAG не удался",
            clear_failed=ok,
        )
        self._maybe_start_warmup(reason="service_restarted")

    def shutdown(self) -> None:
        subscription = self._settings_subscription
        self._settings_subscription = None
        if subscription is not None:
            subscription.close()
        # Подписки weak=False держат сильную ссылку на bound method: без снятия
        # выключенный контроллер продолжит греть модель параллельно новому.
        self.event_bus.unsubscribe_owner(self)
        task_supervisor().cancel_owner(self, timeout=1.0)
