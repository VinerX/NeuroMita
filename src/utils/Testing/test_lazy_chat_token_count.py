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
