
from DSL.dsl_engine import DslInterpreter
from DSL.path_resolver import LocalPathResolver

def create_dsl_interpreter(character) -> DslInterpreter:
    resolver = LocalPathResolver(
        global_prompts_root=character.prompts_root,
        character_base_data_path=character.base_data_path
    )
    return DslInterpreter(character, resolver)