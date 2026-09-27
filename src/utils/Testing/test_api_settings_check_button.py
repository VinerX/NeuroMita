from types import SimpleNamespace

from controllers.gui.api_settings.editor_mixin import EditorMixin


class _Label:
    def __init__(self):
        self.visible = None
        self.text = None

    def setVisible(self, visible):
        self.visible = bool(visible)

    def setText(self, text):
        self.text = text


class _Button(_Label):
    pass


def _editor():
    view = SimpleNamespace(
        test_button=_Button(),
        url_help_label=_Label(),
        model_help_label=_Label(),
        key_help_label=_Label(),
    )
    return SimpleNamespace(
        view=view,
        _help_links_lang_hook_bound=True,
    )


def test_check_button_is_hidden_without_model_test_url():
    editor = _editor()

    EditorMixin._apply_help_links(editor, {"models_url": "https://provider.example/models"})

    assert editor.view.test_button.visible is False


def test_check_button_is_shown_only_with_nonblank_model_test_url():
    editor = _editor()

    EditorMixin._apply_help_links(editor, {"test_url": "  https://provider.example/v1/models  "})
    assert editor.view.test_button.visible is True

    EditorMixin._apply_help_links(editor, {})
    assert editor.view.test_button.visible is False
