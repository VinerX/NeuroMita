"""Окно «Мита говорит»: аренды реплик вместо одного общего флага.

Раньше состояние было булевым: любой `active=False` открывал микрофон, даже если
параллельно звучала вторая реплика того же клиента, а `active=True`, обогнавший
обработку разрыва соединения, глушил микрофон до конца аренды. Здесь проверяется
и то, и другое, плюс страховка по дедлайну на случай мода, упавшего молча.
"""
from managers.speaking_window import SpeakingWindow


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _window(clock, *, tail=0.4, lease=60.0) -> SpeakingWindow:
    return SpeakingWindow(tail_sec=tail, lease_sec=lease, clock=clock)


def test_two_utterances_of_one_client_close_independently():
    clock = _Clock()
    win = _window(clock)

    win.open(source="127.0.0.1:5000#1", speech_id="a")
    win.open(source="127.0.0.1:5000#1", speech_id="b")
    assert win.is_active() is True

    # Первая реплика кончилась — вторая ещё звучит, микрофон обязан молчать.
    win.close(source="127.0.0.1:5000#1", speech_id="a")
    clock.advance(1.0)
    assert win.is_active() is True

    win.close(source="127.0.0.1:5000#1", speech_id="b")
    clock.advance(1.0)
    assert win.is_active() is False


def test_close_of_unknown_utterance_does_not_open_microphone():
    clock = _Clock()
    win = _window(clock)

    win.open(source="c1", speech_id="a")
    win.close(source="c1", speech_id="stale")
    clock.advance(1.0)
    assert win.is_active() is True


def test_tail_keeps_window_closed_right_after_last_utterance():
    clock = _Clock()
    win = _window(clock, tail=0.4)

    win.open(source="c1", speech_id="a")
    win.close(source="c1", speech_id="a")
    assert win.is_active() is True

    clock.advance(0.5)
    assert win.is_active() is False


def test_late_active_from_disconnected_client_is_ignored():
    clock = _Clock()
    win = _window(clock)

    win.open(source="c1", speech_id="a")
    win.close_source("c1")
    clock.advance(1.0)
    assert win.is_active() is False

    # Разрыв обработан раньше, чем запоздавшее «начал говорить» той же сессии.
    assert win.open(source="c1", speech_id="b") is False
    clock.advance(1.0)
    assert win.is_active() is False


def test_new_session_of_same_address_is_not_blocked_by_old_one():
    clock = _Clock()
    win = _window(clock)

    win.open(source="127.0.0.1:5000#1", speech_id="a")
    win.close_source("127.0.0.1:5000#1")
    clock.advance(1.0)

    # client_id уникален на подключение, поэтому новая сессия не наследует запрет.
    assert win.open(source="127.0.0.1:5000#2", speech_id="a") is True
    assert win.is_active() is True


def test_disconnect_releases_all_leases_of_that_client_only():
    clock = _Clock()
    win = _window(clock)

    win.open(source="c1", speech_id="a")
    win.open(source="c1", speech_id="b")
    win.open(source="c2", speech_id="a")

    win.close_source("c1")
    clock.advance(1.0)
    assert win.is_active() is True

    win.close(source="c2", speech_id="a")
    clock.advance(1.0)
    assert win.is_active() is False


def test_lease_expires_when_mod_never_reports_end():
    clock = _Clock()
    win = _window(clock, lease=60.0)

    win.open(source="c1", speech_id="a")
    clock.advance(59.0)
    assert win.is_active() is True

    clock.advance(2.0)
    assert win.is_active() is False


def test_known_duration_shortens_the_lease():
    clock = _Clock()
    win = _window(clock, lease=60.0)

    win.open(source="c1", speech_id="a", duration_sec=3.0)
    clock.advance(3.0 + SpeakingWindow.LEASE_MARGIN_SEC + 0.1)
    assert win.is_active() is False
