from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from model_settings.builtins import BUILTIN_SCHEMAS
from model_settings.bundled_json_compat import is_bundled_json_copy
from model_settings.repository import SchemaRepository
from model_settings.schema import SchemaError, SettingsSchema
from model_settings.service import ModelSettingsService


ROOT = Path(__file__).resolve().parents[1]


def test_all_definitions_match_pre_migration_snapshot():
    expected = json.loads(Path(__file__).with_name('model_settings_builtin_snapshot.json').read_text())
    actual = {
        identifier: sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        for identifier, data in BUILTIN_SCHEMAS.items()
    }
    assert actual == expected
    assert not list((ROOT / 'src/model_settings/defaults').glob('*.json'))
    for identifier, data in BUILTIN_SCHEMAS.items():
        assert identifier == SettingsSchema.from_dict(data).data['id']
        assert is_bundled_json_copy(data)


def test_cold_catalog_does_not_read_or_write_json(tmp_path):
    with patch('json.loads', side_effect=AssertionError('Reading built-in JSON')), \
            patch.object(SchemaRepository, '_write', side_effect=AssertionError('Writing built-in JSON')):
        service = ModelSettingsService(SchemaRepository(tmp_path / 'schemas'))
        for identifier, schema in service.repository.catalog().items():
            document = service.create(identifier)
            dialect = schema.data['dialect']
            assert service.resolve(document, dialect)[0].data == schema.data
            assert service.for_preset({'model_settings': document}, dialect) == document
            assert service.compile(document, dialect) == schema.compile(document['values'], document['enabled'])
            assert service.capabilities(document, dialect, {'tools_native': True, 'streaming': True})
    assert not list((tmp_path / 'schemas').glob('*.json'))


def test_returned_catalog_cannot_mutate_builtin_or_next_read(tmp_path):
    repository = SchemaRepository(tmp_path)
    original = deepcopy(BUILTIN_SCHEMAS)
    first = repository.catalog()
    first['openai-compatible'].fields[0]['default'] = 0.2
    second = repository.catalog()
    assert second['openai-compatible'].data == original['openai-compatible']
    second['openai-compatible'].fields[0]['default'] = 0.3
    assert repository.get('openai-compatible').data == original['openai-compatible']
    assert BUILTIN_SCHEMAS == original


def test_factory_copy_does_not_hide_corrected_builtin_at_same_revision(tmp_path, monkeypatch):
    identifier = 'openai-compatible'
    old = deepcopy(BUILTIN_SCHEMAS[identifier])
    path = tmp_path / 'renamed-factory-copy.json'
    path.write_text(json.dumps(old, indent=4), encoding='utf-8-sig')
    saved = path.read_bytes()
    corrected = deepcopy(old)
    corrected['fields'][0]['maximum'] = 1.5
    monkeypatch.setitem(BUILTIN_SCHEMAS, identifier, corrected)
    assert SchemaRepository(tmp_path).get(identifier).data == corrected
    assert path.read_bytes() == saved


@pytest.mark.parametrize('revision', [1, 2])
def test_historical_plan_copy_uses_current_builtin_without_rewriting_file(tmp_path, revision):
    legacy = deepcopy(BUILTIN_SCHEMAS['chatgpt-plan'])
    legacy['revision'] = revision
    legacy['dialect'] = 'openai_chat_completions'
    if revision == 1:
        legacy['supports']['structured_output'] = False
    path = tmp_path / 'chatgpt-plan.json'
    path.write_text(json.dumps(legacy), encoding='utf-8')
    assert is_bundled_json_copy(legacy)
    assert SchemaRepository(tmp_path).get('chatgpt-plan').data == BUILTIN_SCHEMAS['chatgpt-plan']
    assert json.loads(path.read_text()) == legacy


@pytest.mark.parametrize('revision_delta', [-1, 0, 1])
def test_user_edits_retain_revision_priority_and_file_contents(tmp_path, revision_delta):
    original = deepcopy(BUILTIN_SCHEMAS['chatgpt-plan'])
    custom = deepcopy(original)
    custom['revision'] += revision_delta
    custom['fields'][0]['default'] = 'high'
    assert not is_bundled_json_copy(custom)
    path = tmp_path / 'personal.json'
    path.write_text(json.dumps(custom), encoding='utf-8')
    saved = path.read_bytes()
    expected = original if revision_delta < 0 else custom
    assert SchemaRepository(tmp_path).get('chatgpt-plan').data == expected
    assert path.read_bytes() == saved


def test_import_export_and_inline_override_remain_json_contracts(tmp_path):
    service = ModelSettingsService(SchemaRepository(tmp_path / 'schemas'))
    custom = deepcopy(BUILTIN_SCHEMAS['openai-responses'])
    custom['id'] = 'personal-responses'
    custom['fields'][0]['default'] = 0.5
    source = tmp_path / 'import.json'
    source.write_text(json.dumps(custom), encoding='utf-8-sig')
    service.import_definition(source, 'openai_responses')
    document = service.create(custom['id'])
    document['enabled'] = ['temperature']
    document['values']['unknown_disabled_field'] = {'preserve': True}
    exported = tmp_path / 'export.json'
    service.export_definition(document, 'openai_responses', exported)
    assert json.loads(exported.read_text(encoding='utf-8')) == custom
    document['schema_override'] = custom
    service.repository = SchemaRepository(tmp_path / 'empty')
    assert service.compile(document, 'openai_responses') == {'temperature': 0.5}
    assert service.for_preset({'model_settings': document}, 'openai_responses') == document


def test_external_dialect_changes_and_duplicate_ids_are_rejected(tmp_path):
    custom = deepcopy(BUILTIN_SCHEMAS['openai-compatible'])
    custom['dialect'] = 'openai_responses'
    path = tmp_path / 'custom.json'
    path.write_text(json.dumps(custom), encoding='utf-8')
    with pytest.raises(SchemaError, match='cannot change its dialect'):
        SchemaRepository(tmp_path).catalog()
    custom['dialect'] = 'openai_chat_completions'
    path.write_text(json.dumps(custom), encoding='utf-8')
    (tmp_path / 'duplicate.json').write_text(json.dumps(custom), encoding='utf-8')
    with pytest.raises(SchemaError, match='Duplicate external schema id'):
        SchemaRepository(tmp_path).catalog()


def test_archive_catalog_starts_without_source_tree(tmp_path):
    archive = tmp_path / 'NeuroMita.pyz'
    with ZipFile(archive, 'w') as bundle:
        for directory in ['model_settings', 'core', 'presets']:
            for path in (ROOT / 'src' / directory).glob('*.py'):
                bundle.write(path, path.relative_to(ROOT / 'src').as_posix())
    script = '''
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from model_settings import builtins
from model_settings.repository import SchemaRepository
from model_settings.service import ModelSettingsService
assert builtins.__file__.startswith(sys.argv[1])
with patch('json.loads', side_effect=AssertionError('Unexpected JSON read')):
    service = ModelSettingsService(SchemaRepository(Path('schemas')))
    assert set(service.repository.catalog()) == set(builtins.BUILTIN_SCHEMAS)
    for identifier, data in builtins.BUILTIN_SCHEMAS.items():
        service.compile(service.create(identifier), data['dialect'])
assert not list(Path('schemas').glob('*.json'))
'''
    subprocess.run([sys.executable, '-I', '-c', script, str(archive)], cwd=tmp_path, check=True)
