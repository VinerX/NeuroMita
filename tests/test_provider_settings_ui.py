from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from controllers.gui.api_settings.editor_mixin import EditorMixin
from controllers.gui.api_settings.presets_mixin import PresetsMixin
from controllers.gui.api_settings.test_mixin import TestMixin
from ui.settings.api_settings.ui import build_api_settings_ui


_APP = None


@pytest.fixture
def editor():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    root = QWidget()
    root.settings = {}
    build_api_settings_ui(root, QVBoxLayout(root))
    class Presenter(EditorMixin, PresetsMixin, TestMixin):
        def _current_protocol_id_ui(self):
            return self.protocol
    instance = Presenter()
    instance.view = root
    instance.protocol = 'chatgpt_plan_default'
    instance._help_links_lang_hook_bound = True
    instance._active_template = {}
    instance.current_preset_id = 42
    yield instance
    root.close()
    root.deleteLater()
    _APP.processEvents()


def test_subscription_action_stays_visible_without_test_url(editor):
    editor._apply_help_links({})
    assert not editor.view.test_button.isHidden()
    assert editor.view.api_key_row.isHidden()
    assert not editor.view.account_button.isHidden()
    assert not editor.view.models_button.isHidden()
    editor.protocol = 'openai_compatible_default'
    editor._apply_help_links({})
    assert editor.view.test_button.isHidden()
    assert not editor.view.api_key_row.isHidden()
    assert editor.view.account_button.isHidden()
    assert editor.view.models_button.isHidden()


def test_responses_generation_form_loads_and_preserves_settings(editor, tmp_path):
    from model_settings.repository import SchemaRepository
    from model_settings.service import ModelSettingsService
    from ui.settings.api_settings.model_settings_form import ModelSettingsForm
    service = ModelSettingsService(SchemaRepository(tmp_path / 'schemas'))
    document = service.create('chatgpt-plan')
    document['enabled'] = ['reasoning_effort']
    document['values']['reasoning_effort'] = 'low'
    form = ModelSettingsForm(editor.view)
    form.load(service.repository.get('chatgpt-plan'), document)
    assert 'OpenAI Responses' in form.format_label.text()
    assert service.compile(form.document(), 'openai_responses') == {'reasoning': {'effort': 'low'}}


def test_account_action_emits_application_command_without_url_validation(editor):
    emitted = []
    editor.event_bus = SimpleNamespace(emit=lambda name, data: emitted.append(data))
    editor._test_connection()
    assert emitted[0]['action'] == 'sign_in'
    assert emitted[0]['protocol_id'] == 'chatgpt_plan_default'
    assert not editor.view.test_button.isEnabled()
    assert not editor.view.account_button.isEnabled()
    assert not editor.view.models_button.isEnabled()


def test_model_refresh_emits_list_models_without_reauthorization(editor):
    emitted = []
    editor.event_bus = SimpleNamespace(emit=lambda name, data: emitted.append(data))
    editor._load_account_models()
    assert emitted[0]['action'] == 'list_models'
    assert emitted[0]['protocol_id'] == 'chatgpt_plan_default'


def test_chatgpt_template_is_paid_with_account_catalog_and_existing_openai_icon(editor):
    from presets.api_templates import API_TEMPLATES_DATA
    from ui.provider_icons import template_provider, protocol_provider, provider_icon
    template = next(t for t in API_TEMPLATES_DATA if t['id'] == 12)
    assert template['pricing'] == 'paid'
    assert template['badge_kind'] == 'subscription'
    assert template['default_model'] == ''
    assert API_TEMPLATES_DATA[-1]['id'] == 12
    assert template_provider(template['name'], template['protocol_id']) == 'openai'
    assert protocol_provider(template['protocol_id']) == 'openai'
    assert not provider_icon('openai').isNull()


def test_subscription_notice_is_provider_specific_without_placeholder_bars(editor):
    editor._apply_provider_ui('chatgpt_plan_default')
    panel = editor.view.subscription_info
    assert not panel.isHidden()
    assert 'Экспериментальный' in panel.notice.text()
    assert 'квоту ChatGPT/Codex' in panel.notice.text()
    assert '10.10.2026' not in panel.notice.text()
    from PyQt6.QtWidgets import QProgressBar
    assert not panel.findChildren(QProgressBar)
    assert 'https://chatgpt.com/settings/usage' in panel.dashboard_link.text()
    editor._apply_provider_ui('openai_compatible_default')
    assert panel.isHidden()
    assert panel.notice.text() == ''
    editor._apply_provider_ui('chatgpt_plan_default')
    assert not panel.isHidden()


@pytest.mark.parametrize('current, models, preferred, expected', [
    ('gpt-5.6-luna', ['account-model'], 'gpt-6-luna', 'account-model'),
    ('', ['first', 'gpt-6-luna'], 'gpt-6-luna', 'gpt-6-luna'),
    ('first', ['first', 'gpt-6-luna'], 'gpt-6-luna', 'first'),
    ('', ['gpt-6-luna', 'preferred-vendor-model'], 'preferred-vendor-model', 'preferred-vendor-model'),
    ('', ['first', 'gpt-6-luna'], '', 'first'),
])
def test_subscription_model_comes_from_account_catalog_even_if_dialog_cancelled(editor, monkeypatch, current, models, preferred, expected):
    class CancelledDialog:
        DialogCode = SimpleNamespace(Accepted=1)
        def __init__(self, *args, **kwargs):
            pass
        def exec(self):
            return 0
    monkeypatch.setattr('controllers.gui.api_settings.test_mixin.ModelsLoadedDialog', CancelledDialog)
    editor._on_field_changed = lambda: None
    editor.current_preset_data = {'preferred_model': preferred}
    editor.view.api_model_row.set_text(current)
    editor._process_test_result({'success': True, 'models': models})
    assert editor.view.api_model_row.text() == expected


def test_sandbox_selector_preserves_provider_labels():
    from controllers.gui.sandbox_page_view_model import SandboxPageViewModel
    updates = []
    controller = SimpleNamespace(
        character_snapshot=lambda: (['Crazy'], 'Crazy'),
        model_snapshot=lambda character: ({'custom': [
            {'id': 1, 'name': 'ChatGPT', 'protocol_id': 'chatgpt_plan_default'},
            {'id': 2, 'name': 'Other', 'protocol_id': 'openai_compatible_default'},
        ]}, 1),
        prompt_snapshot=lambda character: ('Crazy', [], ''),
    )
    view_model = SimpleNamespace(_controller=controller, _update=lambda **kwargs: updates.append(kwargs),
                                 _model_label=SandboxPageViewModel._model_label,
                                 run_coalesced=lambda name, worker, applied, failed: applied(worker()))
    SandboxPageViewModel.refresh_selectors(view_model)
    items = updates[-1]['model_items']
    assert items[0].label == 'ChatGPT'
    assert items[1].label == 'Other'


def test_sandbox_model_selector_only_updates_model_value(editor):
    from ui.pages.sandbox_page import SandboxPage
    from ui.pages.sandbox_presentation import SandboxModelItem, SandboxState
    values = []
    receiver = SimpleNamespace(_chat_model_combobox=SimpleNamespace(set_value=values.append))
    items = (SandboxModelItem(1, 'ChatGPT'),
             SandboxModelItem(2, 'Other'))
    SandboxPage._render_model_selector(receiver, SandboxState(model_items=items, current_model_id=1))
    SandboxPage._render_model_selector(receiver, SandboxState(model_items=items, current_model_id=2))
    assert values == ['ChatGPT', 'Other']
