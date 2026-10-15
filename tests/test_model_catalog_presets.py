from copy import deepcopy

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout

from controllers.api_presets_controller import ApiPresetsController
from controllers.gui.api_settings.editor_mixin import EditorMixin
from controllers.gui.api_settings.model_settings_controller import PresetModelSettingsController
from controllers.gui.api_settings.presets_mixin import PresetsMixin
from controllers.gui.api_settings.protocols_mixin import ProtocolsMixin
from controllers.gui.api_settings.test_mixin import TestMixin
from model_settings.repository import SchemaRepository
from model_settings.service import ModelSettingsService
from presets.api_templates import API_TEMPLATES_DATA
from ui.settings.api_settings.ui import build_api_settings_ui
from ui.settings.api_settings.widgets import CustomPresetListItem


_APP = None


class Editor(EditorMixin, PresetsMixin, ProtocolsMixin, TestMixin):
    def _bus_call_async(self, worker, applied, failed=None, **kwargs):
        applied(worker())


@pytest.fixture
def catalog_editor(tmp_path, monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    service = ModelSettingsService(SchemaRepository(tmp_path / 'schemas'))
    with monkeypatch.context() as scope:
        scope.setattr('core.app_paths.base_dir', lambda: tmp_path)
        scope.setattr(ApiPresetsController, '_migrate_old_api_keys', lambda self: None)
        backend = ApiPresetsController(model_settings_service=service)
    for module in ('editor_mixin', 'presets_mixin'):
        monkeypatch.setattr('controllers.gui.api_settings.' + module + '.use', lambda _contract: backend)
    monkeypatch.setattr('controllers.gui.api_settings.test_mixin.get_provider_account_status', lambda _pid: {})
    view = QWidget()
    view.settings = {}
    build_api_settings_ui(view, QVBoxLayout(view))
    view.template_combo.addItem('No template', None)
    for template in API_TEMPLATES_DATA:
        view.template_combo.addItem(template['name'], template['id'])
    editor = Editor()
    editor.view = view
    editor.model_settings_controller = PresetModelSettingsController(view.model_settings_form, service=service)
    editor._protocols = editor._load_protocol_catalog()
    editor._protocol_default_id = editor._pick_default_protocol_id()
    editor._protocol_overrides = {}
    editor._snapshot = None
    editor._pending_select_id = None
    editor._is_loading_ui = False
    editor._help_links_lang_hook_bound = True
    editor._state_save_timer = QTimer(view)
    editor.custom_presets_list_items = {}
    editor._populate_protocol_combo()
    yield backend, editor
    backend.close()
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()


def add_preset(backend, editor, name, models):
    identifier = backend.save_custom({'name': name, 'base': 9, 'default_model': name + '-manual'})
    assert backend._update_preset_models(identifier, models)
    editor.custom_presets_list_items[identifier] = CustomPresetListItem(identifier, name)
    return identifier


def test_catalogs_belong_to_presets_and_survive_reload(catalog_editor):
    backend, editor = catalog_editor
    template_models = deepcopy(backend.templates[9].known_models)
    first = add_preset(backend, editor, 'first', ['llama', 'llama', ' qwen ', ''])
    second = add_preset(backend, editor, 'second', ['gemini'])
    backend._load_presets_only()
    assert backend.get_full(first)['known_models'] == ['llama', 'qwen']
    assert backend.get_full(second)['known_models'] == ['gemini']
    assert backend.templates[9].known_models == template_models


def test_switching_presets_replaces_and_clears_shared_completer(catalog_editor):
    backend, editor = catalog_editor
    first = add_preset(backend, editor, 'first', ['llama'])
    second = add_preset(backend, editor, 'second', ['gemini'])
    empty = add_preset(backend, editor, 'empty', [])
    for identifier, models, selected in [(first, ['llama'], 'first-manual'),
                                         (second, ['gemini'], 'second-manual'),
                                         (empty, [], 'empty-manual'),
                                         (first, ['llama'], 'first-manual')]:
        editor.load_preset_async(identifier)
        assert editor.view.api_model_list_model.stringList() == models
        assert editor.view.api_model_row.text() == selected


def test_stale_preset_load_cannot_replace_latest_catalog(catalog_editor):
    backend, editor = catalog_editor
    first = add_preset(backend, editor, 'first', ['llama'])
    second = add_preset(backend, editor, 'second', ['gemini'])
    pending = []
    editor._bus_call_async = lambda worker, applied, **kwargs: pending.append((worker, applied))
    editor.load_preset_async(first)
    editor.load_preset_async(second)
    pending[1][1](pending[1][0]())
    pending[0][1](pending[0][0]())
    assert editor.current_preset_id == second
    assert editor.view.api_model_list_model.stringList() == ['gemini']


def test_empty_catalog_overrides_template_defaults(catalog_editor):
    backend, editor = catalog_editor
    backend.templates[9].known_models = ['template-default']
    identifier = add_preset(backend, editor, 'empty', [])
    assert backend.get_full(identifier)['known_models'] == []
    backend._load_presets_only()
    assert backend.get_full(identifier)['known_models'] == []


def test_account_catalog_is_saved_to_request_preset(catalog_editor, monkeypatch):
    backend, editor = catalog_editor
    identifier = add_preset(backend, editor, 'first', ['old'])
    monkeypatch.setattr('controllers.api_presets_controller.run_account_action',
                        lambda *args: {'success': True, 'models': ['account-model']})
    backend._sync_account_action(identifier, 'chatgpt_plan_default', 'list_models', '')
    backend._load_presets_only()
    assert backend.get_full(identifier)['known_models'] == ['account-model']


def test_unsuccessful_catalog_save_preserves_previous_list(catalog_editor, monkeypatch):
    backend, editor = catalog_editor
    identifier = add_preset(backend, editor, 'first', ['old'])
    monkeypatch.setattr(backend, '_save_presets', lambda: False)
    assert not backend._update_preset_models(identifier, ['new'])
    assert backend.get_full(identifier)['known_models'] == ['old']


def test_template_change_discards_catalog_from_old_provider(catalog_editor):
    backend, editor = catalog_editor
    identifier = add_preset(backend, editor, 'first', ['old-provider'])
    document = backend.model_settings_service.create('google-level')
    backend.save_custom({'id': identifier, 'name': 'first', 'base': 3, 'model_settings': document})
    assert backend.get_full(identifier)['known_models'] == backend._known_models_for_template(backend.templates[3])
