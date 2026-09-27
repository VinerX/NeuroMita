from managers.protocol_registry import ProtocolRegistry
from managers.api_preset_resolver import ApiPresetResolver
from presets.api_protocols import API_PROTOCOLS_DATA
from types import SimpleNamespace


def test_openrouter_keeps_common_as_transport_but_exposes_service_name():
    registry = ProtocolRegistry(API_PROTOCOLS_DATA)

    protocol = registry.get("openrouter_default")

    assert protocol is not None
    assert protocol.provider == "common"
    assert protocol.display_name == "OpenRouter"


def test_custom_preset_name_overrides_generic_protocol_label():
    label = ApiPresetResolver._resolve_provider_display_name(
        {"base": None, "name": "My Gemini Proxy"},
        SimpleNamespace(display_name="OpenAI-compatible API", name="Generic"),
        "My Gemini Proxy",
    )

    assert label == "My Gemini Proxy"
