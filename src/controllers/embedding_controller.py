from __future__ import annotations

import time
from threading import Lock
from typing import List, Optional

import numpy as np

from core.events import Event, Events, get_event_bus
from core.services import use
from core.task_supervisor import task_supervisor
from handlers.ai_engine.rag_client import get_embeddings as rag_get_embeddings
from handlers.embedding_presets import (
    invalidate_embedding_config_cache,
    resolve_full_config,
    resolve_model_settings,
)
from main_logger import logger
from services.contracts import (
    AIEngineService,
    AIRuntimeUnavailable,
    EmbeddingReadiness,
    EmbeddingService,
    ModelState,
    SettingsService,
)


class EmbeddingController(EmbeddingService):
    """
    Typed RAG embedding service backed by ``ai_engine`` service='rag'.
    """

    # Раньше стояло 3600с: «вечное» ожидание маскировало зависший worker.
    # Эмбеддинг запроса пользователя не имеет смысла ждать дольше самой генерации.
    _HOT_TIMEOUT_SEC = 60.0

    _EMBED_SETTING_KEYS = frozenset({
        "RAG_EMBED_MODEL",
        "RAG_EMBED_MODEL_CUSTOM",
        "RAG_EMBED_QUERY_PREFIX",
        "HF_TOKEN",
        "RAG_VECTOR_SEARCH_ENABLED",
        "RAG_EMBED_PRESET_ID",
        "RAG_ENABLED",
    })

    def __init__(self) -> None:
        self.event_bus = get_event_bus()
        self.settings = use(SettingsService)
        self._settings_subscription = self.settings.subscribe(
            self._on_setting_changed, keys=self._EMBED_SETTING_KEYS
        )
        self._state: ModelState = ModelState.LOADING
        self._error: str = ""
        # Два разных лока, и это принципиально. Состояние (_state/_error/эпоха)
        # читают и меняют из GUI, из шины и из shutdown — этот лок обязан
        # отпускаться мгновенно. Активация же тянет веса с HuggingFace и живёт
        # минутами; будь она под тем же локом, сменить поколение или погасить
        # контроллер во время загрузки стало бы невозможно — а вся защита по
        # поколениям ровно на этом и держится.
        self._state_lock = Lock()
        self._activation_lock = Lock()
        # Поколение рантайма: рестарт движка и смена модели делают недействительным
        # прогрев, начатый до них, иначе запоздавший успех зажигает зелёный по
        # уже несуществующей модели.
        self._runtime_epoch = 0

        self._subscribe_to_events()

        if not self.settings.get("RAG_ENABLED", False):
            logger.info("RAG is disabled in settings. Embedding backend warmup skipped.")
            return

        self._maybe_start_warmup(reason="startup")

    def _should_warmup(self) -> bool:
        """Грузим модель ровно тогда, когда текущая конфигурация её использует —
        то же решение, что у установщика (``required_model_targets``). Прогрев
        обязан быть фоновым: иначе первый RAG-запрос упирается в таймаут на
        «холодной» загрузке/скачивании весов с HuggingFace."""
        from managers.rag.install_spec import TARGET_EMBEDDINGS, required_model_targets

        return TARGET_EMBEDDINGS in required_model_targets(settings=self.settings)

    def _set_state(self, state: ModelState, error: str = "", *, epoch: int | None = None) -> bool:
        """Единственная точка смены состояния: индикатор RAG читает его же.

        False — результат отброшен как устаревший: рантайм сменился, пока шла
        активация.
        """
        with self._state_lock:
            if epoch is not None and epoch != self._runtime_epoch:
                logger.debug(
                    f"EmbeddingController: результат поколения {epoch} отброшен — "
                    "рантайм с тех пор сменился"
                )
                return False
            if self._state is state and self._error == error:
                return True
            self._state = state
            self._error = error
        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)
        return True

    def _bump_runtime_epoch(self) -> None:
        with self._state_lock:
            self._runtime_epoch += 1

    def _snapshot(self) -> tuple[ModelState, str, int]:
        """Согласованный срез состояния: читать поля по отдельности нельзя —
        между чтениями рантайм успевает смениться."""
        with self._state_lock:
            return self._state, self._error, self._runtime_epoch

    def _maybe_start_warmup(self, *, reason: str) -> None:
        if not self._should_warmup():
            return
        if self._snapshot()[0] in (ModelState.READY, ModelState.DISABLED):
            return
        # Имя без причины — чтобы replace=True действительно заменял прогрев, а
        # не плодил по потоку на каждый повод.
        logger.debug(f"EmbeddingController: прогрев эмбеддингов, причина — {reason}")
        task_supervisor().start_thread(
            self,
            "embed-warmup",
            self._warmup_local_backend,
            replace=True,
        )

    def readiness(self) -> EmbeddingReadiness:
        # Нужна ли модель вообще — решает конфигурация (required_model_targets),
        # здесь только факт: прогрета она или нет.
        state, error, _ = self._snapshot()
        return EmbeddingReadiness(
            provider=self._provider_name(),
            state=state,
            error=error,
        )

    def _provider_name(self) -> str:
        try:
            cfg = resolve_full_config()
            return str(cfg.get("provider_name") or "local").strip().lower()
        except Exception:
            return "local"

    def _subscribe_to_events(self) -> None:
        self.event_bus.subscribe(Events.RAG.MODEL_CHANGED, self._on_model_changed, weak=False)
        self.event_bus.subscribe(Events.Install.TASK_FINISHED, self._on_install_task_finished, weak=False)
        # Содержимое пресета могло измениться при том же id — сигнатура настроек
        # этого не поймает, поэтому сбрасываем кэш конфига явно.
        self.event_bus.subscribe(Events.EmbeddingPresets.PRESET_SAVED, self._on_preset_mutated, weak=False)
        self.event_bus.subscribe(Events.EmbeddingPresets.PRESET_DELETED, self._on_preset_mutated, weak=False)
        self.event_bus.subscribe(Events.AI.SERVICE_RESTARTED, self._on_ai_service_restarted, weak=False)
        logger.notify("EmbeddingController subscribed to RAG lifecycle facts")

    def _on_ai_service_restarted(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        if str(data.get("service") or "").strip().lower() != "rag":
            return

        # Процесс движка сменился — прогретой модели в нём больше нет. Неудачный
        # рестарт означает, что воркер уже не поднимут автоматически: это ошибка,
        # а не «грузится», иначе индикатор висит жёлтым до перезапуска приложения.
        self._bump_runtime_epoch()

        if data.get("ok") is True:
            self._set_state(ModelState.LOADING)
            self._maybe_start_warmup(reason="service_restarted")
            return

        reason = str(data.get("error") or "").strip() or "AI-воркер RAG не поднялся"
        logger.error(f"EmbeddingController: эмбеддинги недоступны — {reason}")
        self._set_state(ModelState.ERROR, reason)

    def _warmup_local_backend(self) -> None:
        # AI engine может подняться позже контроллера, а первый запуск модели —
        # тянуть веса с HF (~минуты). Поэтому ретраим до готовности движка, чтобы
        # прогрев состоялся в фоне, а не сорвался из-за стартовой гонки.
        for _ in range(150):  # ~5 минут ожидания движка (загрузка идёт уже в нём)
            if self._snapshot()[0] in (ModelState.READY, ModelState.DISABLED):
                return
            if not self._should_warmup():
                return
            try:
                # force: фоновый прогрев — единственный путь выхода из ошибки,
                # запросу пользователя ждать мёртвый рантайм нельзя.
                if self._ensure_local_backend(force=True):
                    return
            except Exception:
                pass
            time.sleep(2.0)

    def _ensure_local_backend(self, *, force: bool = False) -> bool:
        state, _, _ = self._snapshot()
        if state is ModelState.DISABLED:
            return False
        if state is ModelState.ERROR and not force:
            return False
        if not self.settings.get("RAG_ENABLED", False):
            return False
        if not self.settings.get("RAG_VECTOR_SEARCH_ENABLED", False):
            return False
        if self._provider_name() != "local":
            self._set_state(ModelState.LOADING)
            logger.debug("EmbeddingController: non-local provider, AI engine warmup skipped")
            return False
        if state is ModelState.READY:
            return True

        # Singleflight: активацию делает один поток, остальные ждут его исхода.
        # Состояние при этом не заперто — эпоху можно сменить прямо во время
        # загрузки, и её результат будет отброшен как чужой.
        with self._activation_lock:
            state, _, epoch = self._snapshot()
            if state is ModelState.READY:
                return True
            if state is ModelState.DISABLED:
                return False
            try:
                self._activate_embeddings()
            except Exception as e:
                if "AI engine not available" in str(e):
                    # Движок ещё не поднялся — не окончательный провал, фоновый
                    # прогрев повторит попытку позже.
                    logger.debug(
                        "EmbeddingController: AI engine ещё не готов для прогрева эмбеддингов, повторю позже"
                    )
                    return False
                logger.error(
                    f"EmbeddingController: не удалось прогреть local embedding backend: {e}",
                    exc_info=True,
                )
                self._set_state(ModelState.ERROR, str(e), epoch=epoch)
                return False

        # Индикатор RAG показывает «готово» только когда модель реально в памяти,
        # и только если она всё ещё та самая — это решает проверка поколения.
        return self._set_state(ModelState.READY, epoch=epoch)

    def _activate_embeddings(self) -> None:
        """Поднять окружение эмбеддингов в AI-движке. Долгая операция."""
        ms = resolve_model_settings()
        engine = use(AIEngineService).get_engine()
        activate = getattr(engine, "activate_environment", None) if engine is not None else None
        if not callable(activate):
            raise RuntimeError("AI engine not available")
        if not activate(
            "rag",
            "embeddings",
            category="rag",
            runtime_slot="rag:embeddings",
            timeout=30.0,
            validation_method="warmup_embeddings",
            validation_payload={
                "model_name": ms["hf_name"],
                "query_prefix": ms["query_prefix"],
            },
            validation_timeout=3600.0,
        ):
            raise RuntimeError("RAG embeddings environment could not be initialized")

    def _invalidate_runtime(self, *, reason: str) -> None:
        """Конфигурация эмбеддингов изменилась — прогретая модель больше не та.

        Одного сброса кэша конфига мало: состояние осталось бы READY, и
        индикатор горел бы зелёным по модели, которой в памяти нет. Сохранённый
        под тем же id пресет с другой моделью — ровно этот случай.
        """
        invalidate_embedding_config_cache()
        self._bump_runtime_epoch()
        self._set_state(ModelState.LOADING)
        self._maybe_start_warmup(reason=reason)

    def _on_preset_mutated(self, _event: Event) -> None:
        self._invalidate_runtime(reason="preset_mutated")

    def _on_model_changed(self, event: Event) -> None:
        logger.info(f"EmbeddingController: MODEL_CHANGED event received: {event.data or {}}")
        self._invalidate_runtime(reason="model_changed")

    def _on_setting_changed(self, change) -> None:
        key = change.key
        if key not in self._EMBED_SETTING_KEYS:
            return

        logger.info(f"EmbeddingController: настройка '{key}' изменилась, сбрасываю local backend cache")

        if key in ("RAG_EMBED_MODEL", "RAG_EMBED_MODEL_CUSTOM"):
            # Сброс рантайма сделает обработчик MODEL_CHANGED — тот же, что и для
            # смены модели снаружи. Дублировать его здесь незачем.
            self.event_bus.emit(Events.RAG.MODEL_CHANGED, {
                "key": key,
                "value": change.value,
            })
        else:
            # Прогрев прошлой конфигурации больше не относится к делу — новое
            # поколение, LOADING и фоновый прогрев новой.
            self._invalidate_runtime(reason=f"setting:{key}")

        # Сброшенный backend — это «не готово»: индикатор RAG должен об этом узнать.
        self.event_bus.emit(Events.GUI.UPDATE_STATUS_COLORS)

    def shutdown(self) -> None:
        subscription = self._settings_subscription
        self._settings_subscription = None
        if subscription is not None:
            subscription.close()
        # Подписки weak=False держат сильную ссылку на bound method — иначе
        # выключенный контроллер остаётся жив и реагирует на события.
        self.event_bus.unsubscribe_owner(self)
        # Гасим сразу и вместе с поколением: активация может идти прямо сейчас,
        # и ждать её здесь нельзя — её результат просто не будет применён.
        with self._state_lock:
            self._runtime_epoch += 1
            self._state = ModelState.DISABLED
            self._error = ""
        task_supervisor().cancel_owner(self, timeout=1.0)

    def _on_install_task_finished(self, event: Event) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        task_id = str(data.get("task_id") or "")
        if meta.get("kind") != "rag" and not task_id.startswith("rag:"):
            return

        invalidate_embedding_config_cache()
        self._set_state(ModelState.LOADING)

        # Модель эмбеддингов только что доустановлена — прогреем в фоне.
        self._maybe_start_warmup(reason="install_finished")

    def embed_one(self, text: str, prefix: str = "") -> Optional[np.ndarray]:
        if not text or self._provider_name() != "local":
            return None
        try:
            self._ensure_local_backend()
            ms = resolve_model_settings()
            # Никакого _infer_lock: конкуренцию за устройство разруливает
            # приоритетный планировщик внутри AI-worker'а. Локальный лок здесь
            # просто заставлял эмбеддинг запроса ждать фоновую индексацию.
            results = rag_get_embeddings(
                [str(text)],
                model_name=ms["hf_name"],
                query_prefix=ms["query_prefix"],
                prefix=str(prefix or ""),
                batch_size=1,
                timeout_sec=self._HOT_TIMEOUT_SEC,
                priority="hot",
            )
            return results[0] if results else None
        except AIRuntimeUnavailable as e:
            # Временная недоступность рантайма — не дефект, трейсбек только шумит.
            logger.warning(f"EmbeddingController: embed_one отложен, {e}")
            return None
        except Exception as e:
            logger.error(f"EmbeddingController: ошибка embed_one via AI engine: {e}", exc_info=True)
            return None

    def embed_many(
        self,
        texts: List[str],
        prefix: str = "",
        batch_size: Optional[int] = None,
        priority: str = "hot",
    ) -> List[Optional[np.ndarray]]:
        if not texts or self._provider_name() != "local":
            return []
        try:
            self._ensure_local_backend()
            ms = resolve_model_settings()
            bs = int(batch_size) if batch_size is not None else 32
            if bs <= 0:
                bs = 32

            return rag_get_embeddings(
                list(texts),
                model_name=ms["hf_name"],
                query_prefix=ms["query_prefix"],
                prefix=str(prefix or ""),
                batch_size=bs,
                timeout_sec=(None if priority == "bulk" else self._HOT_TIMEOUT_SEC),
                priority=priority,
            )
        except AIRuntimeUnavailable as e:
            logger.warning(f"EmbeddingController: embed_many отложен, {e}")
            return []
        except Exception as e:
            logger.error(f"EmbeddingController: ошибка embed_many via AI engine: {e}", exc_info=True)
            return []
