"""Рестарт AI-воркера RAG обязан честно доезжать до индикатора.

Раньше неудачный рестарт (`ok=False`) только «не очищал» прошлую ошибку: если
до этого ошибки не было, индикатор оставался жёлтым «грузится» до перезапуска
приложения, хотя воркер уже не поднимут — `call()` мёртвый процесс не оживляет.
Здесь проверяется обе стороны: провал даёт ERROR, а последующий удачный рестарт
возвращает LOADING и запускает прогрев, который доводит состояние до READY.
"""
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
    ctrl._init_lock = Lock()
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


def test_error_state_reaches_rag_indicator():
    from managers.rag.readiness import ERROR, _map_state

    assert _map_state(ModelState.ERROR) == ERROR
