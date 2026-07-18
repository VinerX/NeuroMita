import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2] / "ui" / "windows" / "app_window_base.py"


def _load_method(name: str, globals_dict: dict | None = None):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    class_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AppWindowBase")
    method = next(node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name == name)
    module = ast.Module(
        body=[ast.ClassDef(name="Probe", bases=[], keywords=[], body=[method], decorator_list=[])],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = dict(globals_dict or {})
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return getattr(namespace["Probe"], name)


class _Label:
    def __init__(self):
        self.visible = None
        self.text = None

    def setVisible(self, value):
        self.visible = value

    def setText(self, value):
        self.text = value


def test_token_refresh_is_deferred_until_lazy_chat_ui_exists():
    update_token_count = _load_method("update_token_count")
    probe = type("ProbeInstance", (), {})()
    probe.token_count_label = None
    probe._token_refresh_pending = False

    assert update_token_count(probe) is False
    assert probe._token_refresh_pending is True


def test_hidden_token_stats_are_applied_after_label_exists():
    update_token_count = _load_method("update_token_count", {"_": lambda ru, en: en})
    probe = type("ProbeInstance", (), {})()
    probe.token_count_label = _Label()
    probe._token_refresh_pending = True
    probe._get_setting = lambda key, default=None: False
    probe.update_debug_info = lambda: None

    assert update_token_count(probe) is True
    assert probe.token_count_label.visible is False
    assert probe.token_count_label.text == "Tokens: Tokenizer not available"


def _render_stats(stats: dict, max_fallback: int = 32000):
    tr = {"_": lambda ru, en: ru}  # русские подписи
    fmt = _load_method("_fmt_tokens", tr)
    render = _load_method("_render_token_stats_html", tr)
    probe = type("ProbeInstance", (), {})()
    probe._fmt_tokens = fmt
    return render(probe, stats, max_fallback)


def test_stats_free_tier_hides_money_and_shows_only_context():
    html, _tip = _render_stats(
        {"estimated_context_tokens": 14100, "max_context_tokens": 1_000_000}
    )
    assert "Контекст" in html
    assert "n/a" not in html            # никакого «n/a»
    assert "₽" not in html and "USD" not in html and "RUB" not in html
    assert "Прошлый запрос" not in html  # запроса ещё не было


def test_stats_free_tier_after_request_shows_facts_without_money():
    html, _tip = _render_stats({
        "estimated_context_tokens": 14100, "max_context_tokens": 1_000_000,
        "actual_prompt_tokens": 15000, "actual_completion_tokens": 146,
        "actual_total_tokens": 15200,
    })
    assert "Прошлый запрос" in html
    assert "▸" in html and "Σ" in html   # запрос ▸ ответ (Σ всего)
    assert "n/a" not in html
    assert "USD" not in html and "RUB" not in html


def test_stats_paid_shows_costs():
    html, _tip = _render_stats({
        "estimated_context_tokens": 5000, "max_context_tokens": 128000,
        "estimated_input_cost": 0.0021, "estimated_input_cost_currency": "USD",
        "actual_prompt_tokens": 5100, "actual_completion_tokens": 200,
        "actual_total_tokens": 5300, "actual_cost": 0.0025, "actual_cost_currency": "USD",
    })
    assert "USD" in html
    assert "0.0021" in html and "0.0025" in html


def test_stats_near_limit_uses_warning_color():
    html, _tip = _render_stats(
        {"estimated_context_tokens": 900000, "max_context_tokens": 1_000_000}
    )
    assert "#ff6b61" in html  # красный при заполнении >85%


def test_live_chat_projection_is_skipped_until_lazy_chat_ui_exists():
    update_chat = _load_method("_on_update_chat_signal")
    probe = type("ProbeInstance", (), {})()
    probe._chat_render_context = type("RenderContext", (), {"is_bound": False})()
    probe._pending_structured_data = {"segments": [{"text": "reply"}]}
    probe._pending_message_id = "message-id"

    assert update_chat(probe, "assistant", "reply", False, "") is False
    assert probe._pending_structured_data is None
    assert probe._pending_message_id is None


def test_stream_projection_is_skipped_until_lazy_chat_ui_exists():
    probe = type("ProbeInstance", (), {})()
    probe._chat_render_context = type("RenderContext", (), {"is_bound": False})()

    for method_name, payload in (
        ("_on_prepare_stream_signal", {}),
        ("_append_stream_chunk_slot", {"chunk": "reply"}),
        ("_finish_stream_slot", {}),
    ):
        method = _load_method(method_name)
        assert method(probe, payload) is False
