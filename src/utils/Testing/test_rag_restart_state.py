"""Рестарт AI-воркера RAG обязан честно доезжать до индикатора.

Раньше неудачный рестарт (`ok=False`) только «не очищал» прошлую ошибку: если
до этого ошибки не было, индикатор оставался жёлтым «грузится» до перезапуска
приложения, хотя воркер уже не поднимут — `call()` мёртвый процесс не оживляет.
Здесь проверяется обе стороны: провал даёт ERROR, а последующий удачный рестарт
возвращает LOADING и запускает прогрев, который доводит состояние до READY.
"""
import threading
from threading import Lock

from core.events import Event
from services.contracts import ModelState


class _Bus:
    def __init__(self):
        self.emitted = []

    def emit(self, name, data=None):
        self.emitted.append(name)


def _controller():
    """Контроллер без конструктора: нам нужна только машина состояний."""
    from controllers.embedding_controller import EmbeddingController

    ctrl = object.__new__(EmbeddingController)
    ctrl.event_bus = _Bus()
    ctrl._state = ModelState.LOADING
    ctrl._error = ""
    ctrl._state_lock = Lock()
    ctrl._activation_lock = Lock()
    ctrl._runtime_epoch = 0
    ctrl.warmups = []
    ctrl._maybe_start_warmup = lambda *, reason: ctrl.warmups.append(reason)
    return ctrl


def _restarted(ok: bool, error: str = "") -> Event:
    return Event("ai.service_restarted", {"service": "rag", "ok": ok, "error": error})


def test_failed_restart_without_previous_error_becomes_error():
    ctrl = _controller()
    assert ctrl.readiness().failed is False

    ctrl._on_ai_service_restarted(_restarted(False, "worker exited"))

    readiness = ctrl.readiness()
    assert readiness.state is ModelState.ERROR
    assert readiness.failed is True
    assert "worker exited" in readiness.error
    # Прогрев по мёртвому воркеру не запускаем — восстановление придёт рестартом.
    assert ctrl.warmups == []


def test_failed_restart_without_reason_still_reports_error():
    ctrl = _controller()
    ctrl._on_ai_service_restarted(_restarted(False))
    assert ctrl.readiness().state is ModelState.ERROR
    assert ctrl.readiness().error


def test_successful_restart_after_error_returns_to_loading_then_ready():
    ctrl = _controller()
    ctrl._on_ai_service_restarted(_restarted(False, "worker exited"))
    assert ctrl.readiness().state is ModelState.ERROR

    ctrl._on_ai_service_restarted(_restarted(True))

    assert ctrl.readiness().state is ModelState.LOADING
    assert ctrl.readiness().error == ""
    assert ctrl.warmups == ["service_restarted"]

    # Прогрев в фоне завершился успехом — состояние становится READY.
    ctrl._set_state(ModelState.READY)
    assert ctrl.readiness().model_loaded is True
    assert ctrl.readiness().failed is False


def test_restart_of_another_service_is_ignored():
    ctrl = _controller()
    ctrl._on_ai_service_restarted(Event("ai.service_restarted", {"service": "asr", "ok": False}))
    assert ctrl.readiness().state is ModelState.LOADING


def test_reranker_failed_restart_becomes_error_and_recovers():
    from managers.rag.pipeline.cross_encoder import CrossEncoderReranker

    model = "owner/reranker-test"
    CrossEncoderReranker.get(model)

    CrossEncoderReranker.reset_runtime(failed=True, error="worker exited", reason="тест")
    readiness = CrossEncoderReranker.readiness(model)
    assert readiness.state is ModelState.ERROR
    assert readiness.failed is True
    assert "worker exited" in readiness.error

    CrossEncoderReranker.reset_runtime(failed=False, reason="тест")
    readiness = CrossEncoderReranker.readiness(model)
    assert readiness.state is ModelState.LOADING
    assert readiness.error == ""


def test_reranker_failed_restart_does_not_start_warmup():
    """Провалившийся рестарт не должен запускать прогрев.

    Прогрев — это до 150 попыток `ensure_loaded(force=True)` по две секунды:
    пять минут стука в мёртвый рантайм. Поведение обязано совпадать с
    эмбеддингами: модель поднимет следующий успешный рестарт.
    """
    from controllers.reranker_controller import RerankerController

    ctrl = object.__new__(RerankerController)
    warmups = []
    ctrl._maybe_start_warmup = lambda *, reason: warmups.append(reason)

    ctrl._on_ai_service_restarted(_restarted(False, "worker exited"))
    assert warmups == []

    ctrl._on_ai_service_restarted(_restarted(True))
    assert warmups == ["service_restarted"]


def test_stale_rerank_result_cannot_light_up_a_restarted_runtime():
    """Ответ, начатый в прошлом процессе движка, не выставляет READY.

    Реранк живёт десятки секунд; за это время движок успевает перезапуститься.
    Без поколения такой ответ красил индикатор зелёным по мёртвому рантайму.
    """
    from managers.rag.pipeline.cross_encoder import CrossEncoderReranker

    model = "owner/stale-epoch-test"
    inst = CrossEncoderReranker.get(model)

    epoch = CrossEncoderReranker.runtime_epoch()  # реранк стартовал здесь
    CrossEncoderReranker.reset_runtime(failed=True, error="worker exited", reason="тест")

    inst._set_state(ModelState.READY, epoch=epoch)
    assert CrossEncoderReranker.readiness(model).state is ModelState.ERROR

    # Ответ текущего поколения проходит как обычно.
    inst._set_state(ModelState.READY, epoch=CrossEncoderReranker.runtime_epoch())
    assert CrossEncoderReranker.readiness(model).state is ModelState.READY


def test_stale_embedding_warmup_cannot_light_up_a_restarted_runtime():
    ctrl = _controller()
    epoch = ctrl._snapshot()[2]

    ctrl._on_ai_service_restarted(_restarted(False, "worker exited"))

    ctrl._set_state(ModelState.READY, epoch=epoch)
    assert ctrl.readiness().state is ModelState.ERROR

    ctrl._set_state(ModelState.READY, epoch=ctrl._snapshot()[2])
    assert ctrl.readiness().state is ModelState.READY


def test_activation_does_not_freeze_state_while_the_model_loads():
    """Загрузка модели идёт минутами — состояние на это время не запирается.

    Пока веса тянутся с HuggingFace, индикатор обязан читаться, а смена модели —
    менять поколение. Заодно проверяется главное следствие: результат активации,
    начатой в прошлом поколении, зелёный не зажигает.
    """
    ctrl = _controller()
    ctrl.settings = {"RAG_ENABLED": True, "RAG_VECTOR_SEARCH_ENABLED": True}
    ctrl._provider_name = lambda: "local"

    started, release = threading.Event(), threading.Event()

    def _slow_activation():
        started.set()
        assert release.wait(timeout=5)

    ctrl._activate_embeddings = _slow_activation

    result = []
    worker = threading.Thread(target=lambda: result.append(ctrl._ensure_local_backend()))
    worker.start()
    assert started.wait(timeout=5)

    # Активация ещё идёт, а состояние и читается, и меняется.
    assert ctrl.readiness().state is ModelState.LOADING
    ctrl._bump_runtime_epoch()

    release.set()
    worker.join(timeout=5)

    assert result == [False]
    assert ctrl.readiness().state is ModelState.LOADING


def test_saving_the_active_preset_drops_ready_and_rewarms():
    """Пересохранённый пресет с другой моделью не оставляет зелёный индикатор.

    Id пресета тот же, сигнатура настроек не изменилась — раньше сбрасывался
    только кэш конфига, и READY продолжал показывать модель, которой в памяти
    уже нет.
    """
    ctrl = _controller()
    ctrl._set_state(ModelState.READY)
    epoch = ctrl._snapshot()[2]

    ctrl._on_preset_mutated(Event("embedding_presets.preset_saved", {"preset_id": "p1"}))

    assert ctrl.readiness().state is ModelState.LOADING
    assert ctrl._snapshot()[2] != epoch
    assert ctrl.warmups == ["preset_mutated"]


def test_error_state_reaches_rag_indicator():
    from managers.rag.readiness import ERROR, _map_state

    assert _map_state(ModelState.ERROR) == ERROR
