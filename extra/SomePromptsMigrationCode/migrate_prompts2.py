#!/usr/bin/env python3
"""
Second migration pass:
1. Replace Common/chess_handler.script, seabattle_handler.script, Dialogue.txt in-place.
2. Create Json copies of:
   - Crazy/By_mactep_kot_  -> Crazy/By_mactep_kot_Json
   - Crazy/Lite            -> Crazy/LiteJson
   - GameMaster/default    -> GameMaster/DefaultJson
   - Kind/Lite             -> Kind/LiteJson
"""

import os
import re
import shutil

BASE = "extra/Prompts"

# ─────────────────── helpers ───────────────────

def read_file(path):
    for enc in ('utf-8-sig', 'utf-8', 'cp1251'):
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    return None

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

def copy_tree(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

# ─────────────────── XML -> JSON replacements ───────────────────

def apply_xml_replacements(content):
    # Backtick-wrapped tag references
    content = re.sub(r'`<e>`', '`emotions`', content)
    content = re.sub(r'`<a>`', '`animations`', content)
    content = re.sub(r'`<c>`', '`commands`', content)
    content = re.sub(r'`<p>`', '`variable changes`', content)
    content = re.sub(r'`<f>`', '`face_params`', content)
    content = re.sub(r'`<v>`', '`visual_effects`', content)
    content = re.sub(r'`<m>`', '`movement_modes`', content)

    # Backtick with full tag: `<e>smile</e>` -> "emotions": ["smile"]
    content = re.sub(r'`<e>([^<`]*)</e>`',         r'"emotions": ["\1"]', content)
    content = re.sub(r'`<a>([^<`]*)</a>`',         r'"animations": ["\1"]', content)
    content = re.sub(r'`<c>([^<`]*)</c>`',         r'"commands": ["\1"]', content)
    content = re.sub(r'`<f>([^<`]*)</f>`',         r'"face_params": ["\1"]', content)
    content = re.sub(r'`<interaction>([^<`]*)</interaction>`', r'"interactions": ["\1"]', content)

    # Actual tag usages
    content = re.sub(r'<e>([^<\n]+)</e>',                   r'emotions: ["\1"]', content)
    content = re.sub(r'<a>([^<\n]+)</a>',                   r'animations: ["\1"]', content)
    content = re.sub(r'<c>([^<\n]+)</c>',                   r'commands: ["\1"]', content)
    content = re.sub(r'<f>([^<\n]+)</f>',                   r'face_params: ["\1"]', content)
    content = re.sub(r'<v>([^<\n]+)</v>',                   r'visual_effects: ["\1"]', content)
    content = re.sub(r'<m>([^<\n]+)</m>',                   r'movement_modes: ["\1"]', content)
    content = re.sub(r'<music>([^<\n]+)</music>',           r'music: "\1"', content)
    content = re.sub(r'<hint>([^<\n]+)</hint>',             r'hint: "\1"', content)
    content = re.sub(r'<To>([^<\n]+)</To>',                 r'target: "\1"', content)
    content = re.sub(r'<interaction>([^<\n]+)</interaction>',r'interactions: ["\1"]', content)
    content = re.sub(r'<clothes>([^<\n]+)</clothes>',       r'clothes: ["\1"]', content)

    # Memory tags
    content = re.sub(r'<\+memory>([^<\n]+)</memory>',  r'memory_add: ["\1"]', content)
    content = re.sub(r'<#memory>([^<\n]+)</#memory>',  r'memory_update: ["\1"]', content)
    content = re.sub(r'<#memory>([^<\n]+)</memory>',   r'memory_update: ["\1"]', content)
    content = re.sub(r'<-memory>([^<\n]+)</memory>',   r'memory_delete: ["\1"]', content)

    # <p>att,bore,str</p>
    def replace_p(m):
        parts = [p.strip() for p in m.group(1).split(',')]
        if len(parts) >= 3:
            return (f'{{attitude_change: {parts[0]}, '
                    f'boredom_change: {parts[1]}, '
                    f'stress_change: {parts[2]}}}')
        return m.group(0)
    content = re.sub(r'<p>([^<\n]+)</p>', replace_p, content)

    # <love> tag
    content = re.sub(r'<love>([^<\n]+)</love>', r'love_change: \1', content)

    # Secret tag
    content = re.sub(r'<Secret!>', '"Secret!" in commands', content)

    # Unclosed <c>text at end of line
    content = re.sub(r'<c>([^<\n]*?)(?=\n|$)', lambda m: (
        f'commands: ["{m.group(1).strip()}"]' if m.group(1).strip() else m.group(0)
    ), content)

    # <StartGame id="..."/>
    content = re.sub(r'<StartGame id="([^"]+)"/>', r'"start_game": "\1"', content)
    # <EndGame id="..."/>
    content = re.sub(r'<EndGame id="([^"]+)"/>', r'"end_game": "\1"', content)

    # Inline section headers like "EMOTIONS <e>:", "Commands <c>:"
    content = re.sub(r'\bEMOTIONS\s+<e>:', 'EMOTIONS (emotions field):', content, flags=re.IGNORECASE)
    content = re.sub(r'\bANIMATIONS\s+<a>:', 'ANIMATIONS (animations field):', content, flags=re.IGNORECASE)
    content = re.sub(r'\bCOMMANDS\s+<c>:', 'COMMANDS (commands field):', content, flags=re.IGNORECASE)
    content = re.sub(r'\bIdle Anims\s+<a>:', 'Idle Anims (idle_animations field):', content, flags=re.IGNORECASE)
    content = re.sub(r'\bFace\s+<f>:', 'Face (face_params field):', content, flags=re.IGNORECASE)
    content = re.sub(r'\bVisuals\s+<v>:', 'Visuals (visual_effects field):', content, flags=re.IGNORECASE)
    content = re.sub(r'\bModes\s+<m>:', 'Modes (movement_modes field):', content, flags=re.IGNORECASE)
    content = re.sub(r'\bStats:\s+<p>', 'Stats: variable changes (attitude_change, boredom_change, stress_change)', content)
    content = re.sub(r'\bInteraction:\s+<interaction>', 'Interactions (interactions field):', content)
    content = re.sub(r'\bMusic\s+<music>:', 'Music (music field):', content, flags=re.IGNORECASE)
    content = re.sub(r'\bQuest\s+<hint>:', 'Hint (hint field):', content, flags=re.IGNORECASE)
    content = re.sub(r'\bClothes\s+<clothes>:', 'Clothes (clothes field):', content, flags=re.IGNORECASE)

    # Remaining bare inline references like "(<e>)" "(emotions <e>)"
    content = re.sub(r'\(<e>\)', '(emotions)', content)
    content = re.sub(r'\(<a>\)', '(animations)', content)
    content = re.sub(r'\(<c>\)', '(commands)', content)
    content = re.sub(r'\(<f>\)', '(face_params)', content)
    content = re.sub(r'\(<m>\)', '(movement_modes)', content)
    content = re.sub(r'\(<v>\)', '(visual_effects)', content)
    content = re.sub(r'\s<e>\s', ' emotions field ', content)
    content = re.sub(r'\s<a>\s', ' animations field ', content)
    content = re.sub(r'\s<c>\s', ' commands field ', content)
    content = re.sub(r'Use <p>', 'Use variable changes', content)
    content = re.sub(r'блоки <>', 'поля JSON', content)
    content = re.sub(r'в какие-либо блоки <>', 'в поля JSON', content)
    content = re.sub(r'служебных сообщений помещенных в какие-либо блоки <>!',
                     'служебных полей JSON!', content)

    return content


def fix_files_in_tree(dir_path, skip_files=None):
    skip_files = skip_files or []
    changed = []
    for root, dirs, files in os.walk(dir_path):
        for fname in files:
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, dir_path)
            if rel in skip_files:
                continue
            if not any(fname.endswith(ext) for ext in
                       ['.txt', '.script', '.system', '.postscript']):
                continue
            content = read_file(fpath)
            if content is None:
                continue
            new_content = apply_xml_replacements(content)
            if new_content != content:
                write_file(fpath, new_content)
                changed.append(rel)
    return changed


# ─────────────────── GameMaster JSON response structure ───────────────────

GAMEMASTER_JSON_RESPONSE_STRUCTURE = """\
Response Format (Structured JSON):

You MUST respond with a single JSON object. No extra text before or after the JSON.

Schema:
{
  "segments": [
    {
      "text": "narration or instruction text (optional)",
      "commands": ["Speaker,CharacterName"]
    }
  ]
}

Field descriptions:
- "commands": ["Speaker,CharacterName"] — selects the next speaker.
  Replaces the old <c>Speaker,CharacterName</c> syntax.
- "text": narrator text in asterisk style (*...*), or an instruction line for the selected character.
  Omit if nothing to narrate.

Rules:
- Keep each "text" entry short (≤15 words, no commas inside narrator text).
- Do NOT use XML tags anywhere in the response.
- To both narrate AND select a speaker, put both in the same segment.
- If no action is needed, return: {"segments": [{"text": " "}]}

Example:
{
  "segments": [
    {
      "text": "*Crazy Mita hesitated, reflecting on her behavior.*",
      "commands": ["Speaker,Crazy"]
    }
  ]
}
"""


# ─────────────────── Part 1: Common files ───────────────────

def update_common_files():
    common = f"{BASE}/Common"
    crazy_dj_scripts = f"{BASE}/Crazy/DefaultJson/Scripts"

    # chess_handler.script -> copy JSON version
    src_chess = f"{crazy_dj_scripts}/chess_handler.script"
    dst_chess = f"{common}/chess_handler.script"
    content = read_file(src_chess)
    if content:
        write_file(dst_chess, content)
        print(f"  Common/chess_handler.script: replaced with JSON version")
    else:
        print(f"  WARN: could not read {src_chess}")

    # seabattle_handler.script -> copy JSON version
    src_sb = f"{crazy_dj_scripts}/seabattle_handler.script"
    dst_sb = f"{common}/seabattle_handler.script"
    content = read_file(src_sb)
    if content:
        write_file(dst_sb, content)
        print(f"  Common/seabattle_handler.script: replaced with JSON version")
    else:
        print(f"  WARN: could not read {src_sb}")

    # Dialogue.txt -> apply xml replacements
    dlg_path = f"{common}/Dialogue.txt"
    content = read_file(dlg_path)
    if content:
        new_content = apply_xml_replacements(content)
        if new_content != content:
            write_file(dlg_path, new_content)
            print(f"  Common/Dialogue.txt: updated (XML tags removed)")
        else:
            print(f"  Common/Dialogue.txt: no changes needed")
    else:
        print(f"  WARN: could not read {dlg_path}")


# ─────────────────── Part 2: JSON copies ───────────────────

def make_json_copy(src_dir, dst_dir, json_response_structure, local_scripts_dir=None):
    """
    Copy src_dir -> dst_dir, then:
    - Replace Structural/response_structure.txt with json_response_structure
    - If local_scripts_dir is given, replace chess/seabattle scripts there with JSON versions
    - Apply xml_replacements to all remaining text files
    """
    copy_tree(src_dir, dst_dir)
    print(f"  Copied {src_dir} -> {dst_dir}")

    # Replace response_structure.txt
    rs_path = os.path.join(dst_dir, "Structural", "response_structure.txt")
    if json_response_structure:
        write_file(rs_path, json_response_structure)
        print(f"  response_structure.txt: replaced with JSON version")

    # Replace local chess/seabattle scripts if present
    if local_scripts_dir:
        crazy_dj_scripts = f"{BASE}/Crazy/DefaultJson/Scripts"
        for script_name, src_name in [
            ("chess_handler.script",     "chess_handler.script"),
            ("seabattle_handler.script", "seabattle_handler.script"),
        ]:
            dst_script = os.path.join(dst_dir, local_scripts_dir, script_name)
            if os.path.exists(dst_script):
                content = read_file(f"{crazy_dj_scripts}/{src_name}")
                if content:
                    write_file(dst_script, content)
                    print(f"  {local_scripts_dir}/{script_name}: replaced with JSON version")

    # Apply xml replacements to all remaining text files
    skip = [os.path.join("Structural", "response_structure.txt")]
    if local_scripts_dir:
        skip += [
            os.path.join(local_scripts_dir, "chess_handler.script"),
            os.path.join(local_scripts_dir, "seabattle_handler.script"),
        ]
    changed = fix_files_in_tree(dst_dir, skip_files=skip)
    if changed:
        print(f"  xml->json applied: {', '.join(changed)}")


# ─────────────────── main ───────────────────

if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Read reference JSON response structures
    crazy_rs = read_file(f"{BASE}/Crazy/DefaultJson/Structural/response_structure.txt")
    kind_rs  = read_file(f"{BASE}/Kind/DefaultJson/Structural/response_structure.txt")

    print("=== Part 1: Common files ===")
    update_common_files()

    print("\n=== Part 2: Crazy/By_mactep_kot_Json ===")
    make_json_copy(
        src_dir          = f"{BASE}/Crazy/By_mactep_kot_",
        dst_dir          = f"{BASE}/Crazy/By_mactep_kot_Json",
        json_response_structure = crazy_rs,
        local_scripts_dir= "Common",   # has Common/chess_handler.script etc.
    )

    print("\n=== Part 3: Crazy/LiteJson ===")
    make_json_copy(
        src_dir          = f"{BASE}/Crazy/Lite",
        dst_dir          = f"{BASE}/Crazy/LiteJson",
        json_response_structure = crazy_rs,
    )

    print("\n=== Part 4: Kind/LiteJson ===")
    make_json_copy(
        src_dir          = f"{BASE}/Kind/Lite",
        dst_dir          = f"{BASE}/Kind/LiteJson",
        json_response_structure = kind_rs,
    )

    print("\n=== Part 5: GameMaster/DefaultJson ===")
    make_json_copy(
        src_dir          = f"{BASE}/GameMaster/default",
        dst_dir          = f"{BASE}/GameMaster/DefaultJson",
        json_response_structure = GAMEMASTER_JSON_RESPONSE_STRUCTURE,
    )

    print("\nDone.")
