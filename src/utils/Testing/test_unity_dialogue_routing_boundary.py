from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from controllers.chat_controller import ChatController
from controllers.server_controller import ServerController
from schemas.structured_response import ResponseSegment
from ui.pages.settings.section_registry import get_settings_section_specs


SRC_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SRC_ROOT.parent
UNITY_SCRIPTS = Path(r"D:\NeuroMitaTest\NeuroMita-Unity6-Stable\Assets\Scripts\NeuroMitaScripts")


def test_python_production_tree_has_no_dialogue_turn_router() -> None:
    assert not (SRC_ROOT / "services" / "dialogue_turn_router.py").exists()
    production_roots = (SRC_ROOT / "controllers", SRC_ROOT / "services", SRC_ROOT / "game_connections")
    forbidden = ("DialogueTurnRouter", "get_dialogue_turn_router", "route_to_transport")

    for root in production_roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert not any(symbol in source for symbol in forbidden), path


def test_headless_unity_client_uses_push_updates_without_status_polling() -> None:
    simulator_root = SRC_ROOT / "utils" / "Testing" / "dialogue_turn_simulator"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in simulator_root.glob("*.py")
    )

    assert "get_task_status" not in source
    assert 'message_type != "task_update"' in source


def test_python_sends_unity_owned_dialogue_policy_settings() -> None:
    source = (SRC_ROOT / "controllers" / "server_controller.py").read_text(encoding="utf-8")
    for key in (
        "MITA_DIALOGUE_AUTO",
        "DIALOGUE_MAX_CHAIN_TURNS",
    ):
        assert f'"{key}"' in source

    for removed_key in (
        "DIALOGUE_AUTO_TURN_COUNT_MODE",
        "DIALOGUE_MAX_AUTO_TURNS",
        "DIALOGUE_AUTO_TURNS_PER_PARTICIPANT",
    ):
        assert f'"{removed_key}"' not in source


def test_automatic_dialogue_setting_defaults_to_enabled(monkeypatch) -> None:
    source = (SRC_ROOT / "ui" / "settings" / "dialogue_settings.py").read_text(
        encoding="utf-8"
    )
    key_position = source.index('"key": "MITA_DIALOGUE_AUTO"')
    default_position = source.index('"default_checkbutton": True', key_position)
    assert default_position > key_position

    controller = object.__new__(ServerController)
    controller.settings_to_send = ["MITA_DIALOGUE_AUTO"]
    controller.settings = SimpleNamespace(revision=0)
    controller._collect_characters_stats = lambda: {}
    stored_settings = {}
    controller._get_setting = lambda key, default=None: stored_settings.get(key, default)
    monkeypatch.setattr(
        "controllers.server_controller.ensure_shared_transfer_dirs",
        lambda: (_ for _ in ()).throw(RuntimeError("disabled in test")),
    )

    body = controller._prepare_loaded_settings_body()
    assert body["settings"]["MITA_DIALOGUE_AUTO"] is True
    stored_settings["MITA_DIALOGUE_AUTO"] = False
    body = controller._prepare_loaded_settings_body()
    assert body["settings"]["MITA_DIALOGUE_AUTO"] is False
    assert "DIALOGUE_SETTINGS_DEFAULTS" not in (
        SRC_ROOT / "controllers" / "server_controller.py"
    ).read_text(encoding="utf-8")


def test_dialogue_controls_live_inside_game_settings() -> None:
    assert "dialogue" not in {spec.key for spec in get_settings_section_specs()}

    game_source = (SRC_ROOT / "ui" / "settings" / "game_settings.py").read_text(
        encoding="utf-8"
    )
    assert "add_dialogue_settings_section(self, parent)" in game_source


def test_chain_limit_uses_standard_dependency_and_polished_stepper() -> None:
    source = (SRC_ROOT / "ui" / "settings" / "dialogue_settings.py").read_text(
        encoding="utf-8"
    )
    key_position = source.index('"key": "DIALOGUE_MAX_CHAIN_TURNS"')
    block = source[key_position:key_position + 420]

    assert '"type": "number_stepper"' in block
    assert '"default": 3' in block
    assert '"depends_on": "MITA_DIALOGUE_AUTO"' in block
    assert (SRC_ROOT / "ui" / "widgets" / "number_stepper.py").exists()


def test_task_result_preserves_only_per_segment_addressees() -> None:
    result = ChatController._build_task_result(
        "Ответ",
        {"segments": [
            {"text": "Добрая, что думаешь?", "target": "Kind", "intents": []},
            {"text": "Кепочка, а ты?", "target": "Cappie", "intents": []},
        ]},
        structured_parse_level="direct",
        control_plane_trusted=True,
    )

    assert [segment["target"] for segment in result["segments"]] == ["Kind", "Cappie"]
    assert not {"target", "targets", "next_turns"}.intersection(result)


def test_python_generation_contract_has_no_flat_addressee_state() -> None:
    contracts = (SRC_ROOT / "services" / "contracts.py").read_text(encoding="utf-8")
    character = (SRC_ROOT / "characters" / "character.py").read_text(encoding="utf-8")
    model = (SRC_ROOT / "controllers" / "model_controller.py").read_text(encoding="utf-8")

    generation_result = contracts.split("class ChatGenerationResult:", 1)[1].split(
        "class GenerationService", 1
    )[0]
    assert "target:" not in generation_result
    assert "targets:" not in generation_result
    assert "consume_pending_targets" not in character
    assert "_pending_targets" not in character
    assert "consume_pending_targets" not in model


def test_unity_groups_each_v3_response_by_unique_target_and_has_no_fallback() -> None:
    processor = (
        UNITY_SCRIPTS / "Network" / "Handlers" / "DialogueTaskResultProcessor.cs"
    ).read_text(encoding="utf-8")
    order = (
        UNITY_SCRIPTS / "Dialogue" / "Application" / "DialogueSpeakerOrder.cs"
    ).read_text(encoding="utf-8")

    assert "accepting the response as legacy protocol" not in processor
    assert "Missing response_protocol_version" in processor
    assert "return false;" in processor
    assert "Segment {index + 1} to {label}" in processor
    assert "Dictionary<CharacterType, List<string>> textsByTarget" in processor
    assert "List<CharacterType> targetOrder" in processor
    assert 'Text = string.Join(" ", textsByTarget[target])' in processor
    assert "ClearAddressedMessages" in processor
    assert "if (addressedMessage == null)" in order
    assert "nextSpeaker = active[0]" not in order
    assert "dialogueTurnCount++" in order


def test_game_master_semantic_intent_survives_without_python_routing() -> None:
    intent = {
        "type": "dialogue.broadcast_system_message",
        "payload": {"message": "Смените тему разговора."},
    }
    result = ChatController._build_task_result(
        " ",
        {"segments": [{"text": " ", "target": "Player", "intents": [intent]}]},
        structured_parse_level="direct",
        control_plane_trusted=True,
    )

    assert result["segments"][0]["intents"] == [intent]
    assert not {"target", "targets", "next_turns"}.intersection(result)


def test_dialogue_prompt_defines_per_segment_addressing_contract() -> None:
    prompt = (PROJECT_ROOT / "extra" / "Prompts" / "Common" / "Dialogue.txt").read_text(
        encoding="utf-8"
    )

    assert '"target" belongs to one segment' in prompt
    assert 'Never emit top-level "target" or "targets" fields' in prompt
    assert '"target":"Kind"' in prompt
    assert '"target":"Cappie"' in prompt

    target_schema = ResponseSegment.model_json_schema()["properties"]["target"]
    description = str(target_schema.get("description") or "")
    assert "addressee of this segment's spoken text" in description
    assert "omit it when speaking to the Player" in description


def test_all_active_response_prompts_reject_python_turn_routing() -> None:
    prompts = PROJECT_ROOT / "extra" / "Prompts"
    response_format = (prompts / "Structural" / "response_format_json.script").read_text(
        encoding="utf-8"
    )
    assert "Python chooses the next participant" not in response_format
    assert '"next_turns": [' not in response_format
    assert 'Never emit top-level "target", "targets" or "next_turns" fields' in response_format

    for relative in (
        "GameMaster/Default/Structural/response_structure.txt",
        "GameMaster/Lite/Structural/response_structure.txt",
    ):
        assert '"next_turns"' not in (prompts / relative).read_text(encoding="utf-8")


def test_build_copies_runtime_prompt_source_by_default() -> None:
    source = (PROJECT_ROOT / "build.py").read_text(encoding="utf-8")
    assert 'env.get("BUILD_COPY_DIRS", "extra/Prompts")' in source
    assert 'env.get("BUILD_FAST_COPY_DIRS", "extra/Prompts")' in source
