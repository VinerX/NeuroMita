"""Fingerprints of unmodified JSON definitions shipped before the Python migration."""

from hashlib import sha256
import json


BUNDLED_JSON_FINGERPRINTS: dict[str, frozenset[str]] = {
    'chatgpt-plan': frozenset(['2f1ea5232f431e9eab8cb84e143baa2da1c7f9d5d01295f4418f880938a285f1',
 '5d1fbe5a685e999d38a15c6615140e71cc1b8cf236b021b89931fc6d2648ef98',
 'd42b6de1f9304fea199933e44a735b8dbdb7008a33e3bfb6755609999f726bb5']),
    'google-budget': frozenset(['3b8324b71335e993a7ab66cbd3557923d79a2c2fcd33d565edcd6fe4fd8de6ce']),
    'google-budget-lite': frozenset(['e2678aa24afce60105436911dbce6b6451890f5740d91a87eab162256d3eccb2']),
    'google-budget-pro': frozenset(['6a1fb73bb06e5a949937b3e115e1ec4d531fd6d89b912df62dddddefa8e663e1']),
    'google-level': frozenset(['2fcce5c41b254dc3abb7ba0b5b6e2fcf158d3235f222a7b31ee2503a393b6302']),
    'groq': frozenset(['4cef7da7caf01b558f2e16bccdaabd1380fb1adf24a32ad431cb9534c55adb1a']),
    'local-openai': frozenset(['7c9f403d27a8d8101ab7cc94a826e2c44d2f1ceaaf0d1d707ee042657a7027f6']),
    'mistral': frozenset(['aa8fdd5dc2468531ec27fb591ba5d1b16e5b9c74df3b4bb1bd5d2da0f03f7101']),
    'openai-compatible': frozenset(['bcfc7f099fe31cdf6276e538d49a4d25d18bc8fdcbaba4abbe92ec214e53ee86']),
    'openai-responses': frozenset(['e38f37fa1976f7d9b70f4460095d6bac5372cfc803f13a6c219b05d3226c2fec']),
    'openrouter': frozenset(['770665964274fa05ef754a638b621908ab6af9ff6d03a8c08600c88811dbd470']),
    'together': frozenset(['e0a0a9aa946c37e0692bbea4f43d64c7d9d8eb80389d26a6277296d5eaf6c1a9']),
}


def is_bundled_json_copy(data: dict) -> bool:
    """Ignore historical factory copies without mistaking edited definitions for defaults."""
    fingerprints = BUNDLED_JSON_FINGERPRINTS.get(data["id"], ())
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(serialized.encode("utf-8")).hexdigest() in fingerprints
