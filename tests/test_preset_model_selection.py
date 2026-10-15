import json
from threading import RLock

import pytest

from controllers.api_presets_controller import ApiPresetsController, ApiTemplate
from presets.model_selection import select_catalog_model


@pytest.mark.parametrize('current, models, preferred, expected', [
    ('chosen', ['other', 'chosen'], 'other', 'chosen'),
    ('missing', ['first', 'preferred'], 'preferred', 'preferred'),
    ('', ['first', 'preferred'], 'unavailable', 'first'),
    ('chosen', [], 'preferred', 'chosen'),
])
def test_catalog_selection_respects_available_user_choice(current, models, preferred, expected):
    assert select_catalog_model(current, models, preferred) == expected


@pytest.mark.parametrize('preference, expected', [(None, 'template-model'), ('custom-model', 'custom-model'), ('', '')])
def test_preset_preference_survives_storage_and_overrides_template(tmp_path, preference, expected):
    controller = ApiPresetsController.__new__(ApiPresetsController)
    controller._io_lock = RLock()
    controller.templates = {12: ApiTemplate(id=12, name='Provider', preferred_model='template-model',
                                           protocol_id='openai_compatible_default')}
    controller.presets = {1001: controller._user_preset_from_dict({
        'id': 1001, 'name': 'Preset', 'base': 12, 'preferred_model': preference,
    })}
    controller.presets_order = [1001]
    controller.presets_path = tmp_path / 'presets.json'
    assert controller._save_presets()
    saved = json.loads(controller.presets_path.read_text(encoding='utf-8'))['presets']['1001']
    controller.presets[1001] = controller._user_preset_from_dict(saved)
    assert controller._build_effective_preset_dict(1001)['preferred_model'] == expected
    assert saved['preferred_model'] == preference


def test_chatgpt_template_declares_luna_preference():
    from presets.api_templates import API_TEMPLATES_DATA
    template = next(item for item in API_TEMPLATES_DATA if item['protocol_id'] == 'chatgpt_plan_default')
    assert template['preferred_model'] == 'gpt-6-luna'
