"""Голос игрока адресуется сессии, а не «самому свежему подключению».

Пока фраза шла через ASR, активным мог стать второй запуск игры или тестовый
клиент — раньше текст уезжал туда. Теперь владелец хода фиксируется в момент
распознавания и едет вместе с фразой, а закрытая сессия честно даёт «не
доставлено», чтобы фраза вернулась в десктоп-чат.

Доставка при этом best-effort, а не exactly-once: подтверждения от мода (ACK по
utterance_id) в протоколе нет, а успешная запись в сокет ещё не значит, что мод
фразу принял и применил. Python гарантирует лишь одно: одна фраза не породит
двух ходов у себя — ни повторным «не доставлено», ни возвратом в десктоп-чат
поверх уже отданного игре хода.
"""
import asyncio
import json
import threading

from core.events import Event


class _FakeWriter:
    def __init__(self):
        self.chunks = []

    def write(self, data):
        self.chunks.append(data)

    async def drain(self):
        return None

    def payloads(self):
        raw = b"".join(self.chunks).decode("utf-8")
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


class _Loop:
    """Живой asyncio-цикл в отдельном потоке — как у настоящего сервера."""

    def __enter__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        return self.loop

    def __exit__(self, *exc):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()
        return False


def _server(loop, connections):
    from game_connections.server import ChatServerNew

    srv = ChatServerNew(host="127.0.0.1", port=0)
    srv._loop = loop
    srv.active_connections.update(connections)
    return srv


def _send(srv, client_id, text="привет", utterance_id="u1"):
    return srv.schedule_send_asr_text(
        client_id=client_id, text=text, utterance_id=utterance_id
    ).result(timeout=5)


def test_text_goes_only_to_the_session_that_owned_the_turn():
    old, new = _FakeWriter(), _FakeWriter()
    with _Loop() as loop:
        srv = _server(loop, {"127.0.0.1:5000#1": old, "127.0.0.1:5001#2": new})

        assert _send(srv, "127.0.0.1:5000#1") is True

    assert [p["text"] for p in old.payloads()] == ["привет"]
    assert new.payloads() == []


def test_text_for_closed_session_is_not_delivered_to_the_new_one():
    new = _FakeWriter()
    with _Loop() as loop:
        # Старая сессия отвалилась, пока фраза шла через ASR.
        srv = _server(loop, {"127.0.0.1:5001#2": new})

        assert _send(srv, "127.0.0.1:5000#1") is False

    assert new.payloads() == []


def test_newest_game_session_owns_the_turn():
    with _Loop() as loop:
        srv = _server(loop, {"a#1": _FakeWriter(), "b#2": _FakeWriter()})
        _declare_role(srv, loop, "a#1", "game")
        _declare_role(srv, loop, "b#2", "game")

        assert srv.primary_client_id() == "b#2"


def test_two_undeclared_clients_leave_the_turn_to_nobody():
    """Кто из двух безымянных — игра, сервер не угадывает.

    Раньше ход доставался самому свежему подключению, и подключившаяся утилита
    молча перехватывала голос. Без объявленной роли фраза уходит в десктоп-чат.
    """
    with _Loop() as loop:
        srv = _server(loop, {"a#1": _FakeWriter(), "b#2": _FakeWriter()})
        assert srv.primary_client_id() == ""


def _declare_role(srv, loop, client_id, role):
    """Роль объявляется полем запроса — как это делает мод."""
    asyncio.run_coroutine_threadsafe(
        srv.process_request({"action": "unknown_action", "client_role": role}, client_id),
        loop,
    ).result(timeout=5)


def _hello(srv, loop, client_id, role):
    return asyncio.run_coroutine_threadsafe(
        srv.process_request({"action": "hello", "client_role": role}, client_id),
        loop,
    ).result(timeout=5)


def test_handshake_answers_with_protocol_and_session():
    writer = _FakeWriter()
    with _Loop() as loop:
        srv = _server(loop, {"game#1": writer})
        _hello(srv, loop, "game#1", "game")

    ack = writer.payloads()[0]
    assert ack["type"] == "hello_ack"
    assert ack["protocol_version"] == 1
    assert ack["session_id"] == "game#1"
    assert ack["client_role"] == "game"
    assert ack["owns_player_input"] is True


def test_role_cannot_be_changed_until_reconnect():
    """Объявленная роль неизменна: иначе диагностический клиент уводил бы ход."""
    with _Loop() as loop:
        srv = _server(loop, {"game#1": _FakeWriter(), "tool#2": _FakeWriter()})
        _declare_role(srv, loop, "game#1", "game")
        _declare_role(srv, loop, "tool#2", "diagnostic")

        _declare_role(srv, loop, "tool#2", "game")

        assert srv.owns_player_input("tool#2") is False
        assert srv.primary_client_id() == "game#1"


def test_diagnostic_client_does_not_take_over_player_input():
    """Самое свежее подключение — не обязательно игра.

    Тестовый клиент или внешняя утилита подключаются последними и раньше
    перехватывали голос игрока: фраза уезжала туда, а игра её не получала.
    """
    with _Loop() as loop:
        srv = _server(loop, {"game#1": _FakeWriter(), "tool#2": _FakeWriter()})
        _declare_role(srv, loop, "game#1", "game")
        _declare_role(srv, loop, "tool#2", "diagnostic")

        assert srv.primary_client_id() == "game#1"
        assert srv.owns_player_input("tool#2") is False


def test_client_without_declared_role_is_still_treated_as_game():
    """Старый мод роли не шлёт — связь с ним обязана работать по-прежнему."""
    with _Loop() as loop:
        srv = _server(loop, {"old#1": _FakeWriter()})
        assert srv.primary_client_id() == "old#1"


def test_no_owner_when_only_diagnostic_clients_are_connected():
    with _Loop() as loop:
        srv = _server(loop, {"tool#1": _FakeWriter()})
        _declare_role(srv, loop, "tool#1", "diagnostic")

        assert srv.primary_client_id() == ""


def test_game_connection_status_ignores_diagnostic_client():
    with _Loop() as loop:
        srv = _server(loop, {"tool#1": _FakeWriter()})
        _declare_role(srv, loop, "tool#1", "diagnostic")

        assert srv.has_game_connection() is False


def test_game_connection_status_ignores_closing_writer():
    class _ClosingWriter(_FakeWriter):
        @staticmethod
        def is_closing():
            return True

    with _Loop() as loop:
        srv = _server(loop, {"game#1": _ClosingWriter()})
        srv.client_roles["game#1"] = "game"

        assert srv.has_game_connection() is False


def test_partially_written_message_is_not_reported_as_delivered():
    """Оборванная на drain() запись — это «не доставлено», а не успех.

    Часть строки уже в сокете, но мод её не применит: подтверждения в протоколе
    нет, поэтому единственный честный ответ — False, и фраза вернётся в
    десктоп-чат. Ровно поэтому маршрутизация называется best-effort.
    """

    class _HalfWriter(_FakeWriter):
        async def drain(self):
            raise ConnectionResetError("broken pipe")

    writer = _HalfWriter()
    with _Loop() as loop:
        srv = _server(loop, {"c#1": writer})
        assert _send(srv, "c#1") is False

    assert writer.chunks  # часть байтов ушла в сокет — доставкой это не считается


def test_payload_carries_utterance_id_without_unity_ui_policy():
    writer = _FakeWriter()
    with _Loop() as loop:
        srv = _server(loop, {"c#1": writer})
        srv.schedule_send_asr_text(
            client_id="c#1", text="раз", utterance_id="utt-42",
        ).result(timeout=5)

    payload = writer.payloads()[0]
    assert payload["type"] == "asr_text"
    assert payload["id"] == "utt-42"
    assert "instant_enabled" not in payload
    assert "autosend" not in payload
    assert "delay_sec" not in payload
    assert "merge_input" not in payload


# --------------------------- одна фраза = один ход ---------------------------


class _Settings(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


class _AsrSettings:
    @staticmethod
    def snapshot():
        return {"engine": "vosk"}


class _Bus:
    def __init__(self):
        self.sent = []

    def emit(self, name, data=None):
        self.sent.append((name, data or {}))


class _Speech:
    """Владелец хода из SpeechController без Qt, аудио и настроек."""

    def __init__(self, *, turn_owner=""):
        from controllers.speech_controller import SpeechController

        self.ctrl = object.__new__(SpeechController)
        self.ctrl._turns_lock = threading.Lock()
        self.ctrl._turns_in_game = {}
        self.ctrl.settings = _Settings(MIC_ACTIVE=True, MIC_MUTE_WHILE_SPEAKING=False)
        self.ctrl.asr_settings = _AsrSettings()
        self.ctrl.events_bus = self.bus = _Bus()
        self.desktop = []
        self.ctrl._route_to_desktop = lambda text, autosend, delay, trace_id=None: self.desktop.append(text)
        self.ctrl._is_asr_duplicate = lambda text, now: False
        self.ctrl._instant_send_policy = lambda: (True, 0.0)
        self.ctrl._player_turn_owner = lambda: turn_owner

    def recognized(self, text="привет"):
        self.ctrl._on_speech_text_recognized(Event("speech.text_recognized", {"text": text}))

    def sent_to_game(self):
        from core.events import Events

        return [d for name, d in self.bus.sent if name == Events.Server.SEND_ASR_TEXT]

    def undelivered(self, utterance_id, text="привет"):
        self.ctrl._on_asr_text_undelivered(
            Event("server.asr_text_undelivered", {"id": utterance_id, "text": text})
        )


def test_recognized_phrase_goes_to_the_game_owner_only():
    speech = _Speech(turn_owner="127.0.0.1:5000#1")
    speech.recognized("привет")

    sent = speech.sent_to_game()
    assert len(sent) == 1
    assert sent[0]["client_id"] == "127.0.0.1:5000#1"
    assert sent[0]["text"] == "привет"
    # Ход отдан игре — в десктоп-чат та же фраза попасть не должна.
    assert speech.desktop == []


def test_recognized_phrase_without_game_goes_to_desktop_only():
    speech = _Speech(turn_owner="")
    speech.recognized("привет")

    assert speech.sent_to_game() == []
    assert speech.desktop == ["привет"]
    assert speech.ctrl._turns_in_game == {}


def test_undelivered_after_recognition_gives_exactly_one_desktop_turn():
    speech = _Speech(turn_owner="127.0.0.1:5000#1")
    speech.recognized("привет")
    utterance_id = speech.sent_to_game()[0]["id"]

    speech.undelivered(utterance_id)
    speech.undelivered(utterance_id)

    assert speech.desktop == ["привет"]


def test_undelivered_returns_the_phrase_to_desktop_once():
    speech = _Speech()
    speech.ctrl._claim_game_turn("utt-1")

    speech.undelivered("utt-1")
    assert speech.desktop == ["привет"]

    # Повторное «не доставлено» по той же фразе не должно дать второй ход.
    speech.undelivered("utt-1")
    assert speech.desktop == ["привет"]


def test_undelivered_for_unknown_utterance_is_ignored():
    speech = _Speech()
    speech.undelivered("utt-чужой")
    assert speech.desktop == []


def test_turn_ledger_does_not_grow_without_bound():
    from controllers.speech_controller import SpeechController

    speech = _Speech()
    for i in range(SpeechController._MAX_TURNS_IN_GAME * 3):
        speech.ctrl._claim_game_turn(f"utt-{i}")

    assert len(speech.ctrl._turns_in_game) <= SpeechController._MAX_TURNS_IN_GAME
