import asyncio
import importlib
import queue
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from handlers.asr_models.google_recognizer import GoogleRecognizer
from handlers.asr_models.whisper_recognizer import WhisperRecognizer
from handlers.asr_models.whisper_onnx_recognizer import WhisperOnnxRecognizer
from handlers.asr_models.gigaam_recognizer import GigaAMRecognizer
from handlers.asr_models.gigaam_onnx_recognizer import GigaAMOnnxRecognizer
from handlers.asr_models.speech_recognizer_base import validate_asr_model_settings

ADAPTERS = [GoogleRecognizer, WhisperRecognizer, WhisperOnnxRecognizer, GigaAMRecognizer, GigaAMOnnxRecognizer]


def catalogue():
    return importlib.import_module('handlers.asr_models.asr_languages')


@pytest.mark.parametrize('adapter_type', ADAPTERS)
def test_schema_and_metadata_share_language_capabilities(adapter_type):
    adapter = adapter_type(None, Mock())
    field = next(row for row in adapter.settings_spec() if row['key'] == 'language')
    assert field == catalogue().asr_language_field(adapter.item_id)
    assert adapter.MODEL_CONFIGS[0]['languages'] == catalogue().asr_language_names(adapter.item_id)
    assert field['default'] == adapter.get_default_settings()['language']
    assert set(field['option_labels']) == set(field['options'])
    assert all(code in field['option_labels'][code] for code in field['options'])
    assert field['help_ru'] and field['help_en']


def test_whisper_full_catalogue_and_google_existing_choices():
    cat = catalogue()
    options = cat.asr_language_field('whisper')['options']
    assert len(options) == len(set(options)) == 101
    assert {'uk', 'yue', 'auto'} <= set(options)
    assert len(cat.asr_language_names('whisper')) == 100
    assert 'Ukrainian' in cat.asr_language_names('whisper')
    assert 'Cantonese' in cat.asr_language_names('whisper')
    assert cat.asr_language_field('whisper_onnx')['options'] == options
    assert options[:12] == ['auto', 'ru', 'uk', 'en', 'de', 'fr', 'es', 'it', 'pt', 'ja', 'zh', 'ko']
    for engine in ('whisper', 'whisper_onnx'):
        whisper_labels = cat.asr_language_field(engine)['option_labels']
        assert all(not label.startswith('★ ') for label in whisper_labels.values())
    google_options = cat.asr_language_field('google')['options']
    assert {'ru-RU', 'uk-UA', 'en-US', 'en-GB', 'de-DE', 'fr-FR', 'es-ES', 'ja-JP', 'zh-CN'} <= set(google_options)
    assert google_options[:11] == ['ru-RU', 'uk-UA', 'en-US', 'de-DE', 'fr-FR', 'es-ES', 'it-IT', 'pt-BR', 'ja-JP', 'zh-CN', 'ko-KR']
    labels = cat.asr_language_field('google')['option_labels']
    assert all(not label.startswith('★ ') for label in labels.values())
    assert {'it-IT', 'pt-BR', 'pl-PL', 'ko-KR', 'hi-IN', 'yue-Hant-HK'} <= set(google_options)
    assert len(google_options) == len(set(google_options))
    assert 'auto' not in google_options
    assert cat.asr_language_names('google') == list(GoogleRecognizer.LANGUAGES.values())


def test_catalogue_returns_independent_schema_containers():
    first = catalogue().asr_language_field('whisper')
    first['options'].clear()
    first['option_labels'].clear()
    assert len(catalogue().asr_language_field('whisper')['options']) == 101


@pytest.mark.parametrize('adapter_type', ADAPTERS)
@pytest.mark.parametrize('language', ['xx', '', None, ['ru'], 'Russian'])
def test_invalid_language_is_rejected_on_save(adapter_type, language, monkeypatch):
    adapter = adapter_type(None, Mock())
    save = Mock()
    monkeypatch.setattr('handlers.asr_models.speech_recognizer_base.save_asr_model_settings', save)
    with pytest.raises(ValueError, match='language'):
        adapter.save_settings({'language': language})
    save.assert_not_called()


@pytest.mark.parametrize('adapter_type', [GoogleRecognizer, WhisperRecognizer, WhisperOnnxRecognizer])
@pytest.mark.parametrize('language', ['xx', '', None])
def test_invalid_runtime_language_raises_without_changing_state(adapter_type, language):
    adapter = adapter_type(None, Mock())
    before = adapter.language
    with pytest.raises(ValueError, match='language'):
        adapter.apply_settings({'language': language})
    assert adapter.language == before


@pytest.mark.parametrize('adapter_type', [GigaAMRecognizer, GigaAMOnnxRecognizer])
def test_gigaam_fixed_language(adapter_type):
    adapter = adapter_type(None, Mock())
    field = next(row for row in adapter.settings_spec() if row['key'] == 'language')
    assert field['options'] == ['ru'] and field['enabled'] is False
    assert not adapter.validate_settings({'language': 'auto'}).ok
    assert not adapter.validate_settings({'language': 'uk'}).ok
    adapter.apply_settings({'language': 'uk'})
    assert adapter.get_default_settings()['language'] == 'ru'


def test_validation_does_not_tighten_other_fields():
    schema = [{'key': 'language', 'options': ['ru']}, {'key': 'device', 'options': ['cpu']}]
    assert validate_asr_model_settings(schema, {'device': 'cuda:3'}).ok
    assert validate_asr_model_settings(schema, {}).ok
    assert not validate_asr_model_settings(schema, {'unknown': 'value'}).ok


@pytest.mark.parametrize('adapter_type,language', [(GoogleRecognizer, 'uk-UA'), (WhisperRecognizer, 'uk'), (WhisperRecognizer, 'auto'), (WhisperOnnxRecognizer, 'uk'), (WhisperOnnxRecognizer, 'auto'), (GigaAMRecognizer, 'ru'), (GigaAMOnnxRecognizer, 'ru')])
def test_language_settings_roundtrip(adapter_type, language, tmp_path, monkeypatch):
    from services.asr_settings_service import FileASRSettingsService
    path = str(tmp_path / 'asr_settings.json')
    monkeypatch.setattr('handlers.asr_models.speech_recognizer_base.ensure_asr_settings_service', lambda: FileASRSettingsService(path))
    adapter = adapter_type(None, Mock())
    adapter.save_settings({'language': language})
    restarted = adapter_type(None, Mock())
    assert restarted.load_settings() == {'language': language}
    restarted.apply_settings(restarted.load_settings())
    if adapter_type in [GoogleRecognizer, WhisperRecognizer, WhisperOnnxRecognizer]:
        assert restarted.language == language


@pytest.mark.parametrize('language,expected', [('uk', 'uk'), ('auto', None)])
def test_whisper_language_reaches_transcribe(language, expected):
    adapter = WhisperRecognizer(None, Mock())
    adapter.apply_settings({'language': language})
    adapter._is_initialized = True
    adapter._model = Mock()
    adapter._model.transcribe.return_value = ([SimpleNamespace(text='Привіт світе')], None)
    assert asyncio.run(adapter.transcribe(np.zeros(32), 16000)) == 'Привіт світе'
    assert adapter._model.transcribe.call_args.kwargs['language'] == expected


@pytest.mark.parametrize('language', ['uk', 'auto'])
def test_onnx_language_reaches_worker_and_generation_config(language, monkeypatch):
    import handlers.asr_models.whisper_onnx_recognizer as adapter_module
    from handlers.asr_models.whisper_onnx_process import WhisperOnnxProcessWorker
    adapter = WhisperOnnxRecognizer(None, Mock())
    adapter.apply_settings({'language': language})
    monkeypatch.setattr(adapter_module.mp, 'Queue', queue.Queue)
    monkeypatch.setattr(adapter_module.mp, 'Process', lambda **kwargs: Mock())
    monkeypatch.setattr(adapter_module, 'task_supervisor', lambda: SimpleNamespace(start_thread=lambda *args, **kwargs: setattr(adapter, '_process_initialized', True)))
    monkeypatch.setattr(adapter, '_runtime_device', lambda: 'cpu')
    assert adapter._start_process()
    command, options = adapter._command_queue.get_nowait()
    assert command == 'init' and options['language'] == language
    worker = WhisperOnnxProcessWorker(queue.Queue(), queue.Queue(), queue.Queue())
    config = SimpleNamespace(forced_decoder_ids=[[1, 50259]], lang_to_id={'<|uk|>': 50280})
    processor = Mock()
    processor.get_decoder_prompt_ids.return_value = [[1, 50280], [2, 50359]]
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(GenerationConfig=SimpleNamespace(from_pretrained=lambda *args, **kwargs: config), WhisperProcessor=SimpleNamespace(from_pretrained=lambda *args, **kwargs: processor)))
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'torchaudio', SimpleNamespace(functional=SimpleNamespace()))
    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace())
    monkeypatch.setattr(worker, '_build_pipeline', lambda: object())
    monkeypatch.setattr(worker, '_select_provider', lambda: ('CPUExecutionProvider', None))
    asyncio.run(worker.init_recognizer(options))
    assert worker.result_queue.get_nowait()[0] == 'init_success'
    assert worker.language == language
    if language == 'auto':
        assert worker._generation_config.forced_decoder_ids is None
        processor.get_decoder_prompt_ids.assert_not_called()
    else:
        assert worker._generation_config.forced_decoder_ids == [[1, 50280], [2, 50359]]
        assert processor.get_decoder_prompt_ids.call_args.kwargs['language'] == 'uk'


def test_whisper_catalogue_has_exact_verified_codes():
    expected = set("en zh de es ru ko fr ja pt tr pl ca nl ar sv it id hi fi vi he uk el ms cs ro da hu ta no th ur hr bg lt la mi ml cy sk te fa lv bn sr az sl kn et mk br eu is hy ne mn bs kk sq sw gl mr pa si km sn yo so af oc ka be tg sd gu am yi lo uz fo ht ps tk nn mt sa lb my bo tl mg as tt haw ln ha ba jw su yue".split())
    assert set(catalogue().asr_language_field('whisper')['options']) == expected | {'auto'}


@pytest.mark.parametrize('adapter_type', ADAPTERS)
def test_every_advertised_language_passes_validation(adapter_type):
    adapter = adapter_type(None, Mock())
    for language in catalogue().asr_language_field(adapter.item_id)['options']:
        assert adapter.validate_settings({'language': language}).ok


def test_catalogue_import_requires_no_ml_or_app_modules():
    import subprocess
    script = """
import importlib.util
import sys
spec = importlib.util.spec_from_file_location('asr_languages', 'src/handlers/asr_models/asr_languages.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert len(module.asr_language_field('whisper')['options']) == 101
assert not any(name.split('.')[0] in {'torch', 'numpy', 'transformers', 'faster_whisper', 'utils', 'handlers', 'services', 'PyQt6'} for name in sys.modules)
"""
    subprocess.run([sys.executable, '-I', '-c', script], check=True)


@pytest.mark.parametrize('helper', ['asr_language_field', 'asr_language_names'])
def test_unknown_engine_is_rejected(helper):
    with pytest.raises(ValueError, match='Unknown ASR engine'):
        getattr(catalogue(), helper)('unknown')
