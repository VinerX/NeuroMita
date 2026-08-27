# File: src/utils/prompt_builder.py
from typing import List, Dict

def build_system_prompts(blocks: List[str], separate: bool) -> List[Dict[str, str]]:
    blocks = [b for b in (blocks or []) if isinstance(b, str) and b.strip()]
    if not blocks:
        return []
    if separate:
        return [{"role": "system", "content": b} for b in blocks]
    return [{"role": "system", "content": "\n".join(blocks)}]