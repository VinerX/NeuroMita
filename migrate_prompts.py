#!/usr/bin/env python3
"""
Migrates extra/Prompts from XML <> command format to structured JSON output.

Strategy:
- Crazy: DefaultJson -> _old/DefaultJson, DefaultJsonFull -> DefaultJson
- Others with DefaultJson:
    - DefaultJson -> _old/DefaultJson (backup)
    - common.txt: keep character header, replace format section with Crazy's JSON section
    - All other files: regex-replace XML tags with JSON field equivalents
- GameMaster (only Default, no DefaultJson): create DefaultJson from scratch (skip for now, handle separately)
"""

import os
import shutil
import re

BASE = "extra/Prompts"
# DefaultJsonFull is the source - if already migrated it becomes DefaultJson
CRAZY_FULL = (f"{BASE}/Crazy/DefaultJsonFull"
              if os.path.exists(f"{BASE}/Crazy/DefaultJsonFull")
              else f"{BASE}/Crazy/DefaultJson")

NEW_FORMAT_NOTE = (
    '**[FORMAT NOTE: This prompt uses JSON structured output. '
    'Emotions go to segments[].emotions, one-shot animations to segments[].animations, '
    'face parameters to segments[].face_params, and variable changes go to top-level '
    'attitude_change / boredom_change / stress_change. Use JSON fields, not XML-like tags.]**'
)

def read_file(path):
    for enc in ('utf-8-sig', 'utf-8', 'cp1251'):
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    return None

def write_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

def get_crazy_json_section():
    """Generic JSON format section from Crazy/DefaultJsonFull/Main/common.txt (from line with 'Отвечай не более')"""
    content = read_file(f"{CRAZY_FULL}/Main/common.txt")
    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if 'Отвечай не более в' in line:
            return ''.join(lines[i:])
    # fallback
    return ''.join(lines[5:])

def apply_xml_replacements(content):
    """Replace XML-style command tags with JSON-style equivalents throughout content."""
    # FORMAT NOTE line
    content = re.sub(
        r'\*\*\[FORMAT NOTE:[^\]]+\]\*\*',
        NEW_FORMAT_NOTE,
        content
    )

    # Text descriptions mentioning <> blocks
    content = content.replace(
        'служебных сообщений помещенных в какие-либо блоки <>!',
        'служебных полей JSON!'
    )
    content = content.replace(
        '(это не касается служебных сообщений помещенных в какие-либо блоки <>!)',
        '(это не касается служебных полей JSON!)'
    )
    content = content.replace('блоки <>', 'поля JSON')
    content = content.replace('в какие-либо блоки <>', 'в поля JSON')

    # Backtick shorthand references: `<e>` -> `emotions`
    content = re.sub(r'`<e>`', '`emotions`', content)
    content = re.sub(r'`<a>`', '`animations`', content)
    content = re.sub(r'`<c>`', '`commands`', content)
    content = re.sub(r'`<p>`', '`variable changes`', content)
    content = re.sub(r'`<f>`', '`face_params`', content)
    content = re.sub(r'`<v>`', '`commands`', content)

    # Backtick with full tag: `<e>smile</e>` -> "emotions": ["smile"]
    content = re.sub(r'`<e>([^<`]*)</e>`', r'"emotions": ["\1"]', content)
    content = re.sub(r'`<a>([^<`]*)</a>`', r'"animations": ["\1"]', content)
    content = re.sub(r'`<c>([^<`]*)</c>`', r'"commands": ["\1"]', content)
    content = re.sub(r'`<f>([^<`]*)</f>`', r'"face_params": ["\1"]', content)

    # Parenthetical references: (<e>...</e>, <a>...</a>)
    content = re.sub(r'\(<e>[^)]*</e>[^)]*\)', lambda m: m.group(0), content)  # handled below

    # Actual tag usages: <e>X</e>
    content = re.sub(r'<e>([^<\n]+)</e>', r'emotions: ["\1"]', content)
    content = re.sub(r'<a>([^<\n]+)</a>', r'animations: ["\1"]', content)
    content = re.sub(r'<c>([^<\n]+)</c>', r'commands: ["\1"]', content)
    content = re.sub(r'<f>([^<\n]+)</f>', r'face_params: ["\1"]', content)
    content = re.sub(r'<v>([^<\n]+)</v>', r'commands: ["\1"]', content)
    content = re.sub(r'<music>([^<\n]+)</music>', r'music: "\1"', content)
    content = re.sub(r'<hint>([^<\n]+)</hint>', r'hint: "\1"', content)
    content = re.sub(r'<To>([^<\n]+)</To>', r'to: "\1"', content)
    content = re.sub(r'<interaction>([^<\n]+)</interaction>', r'interaction: "\1"', content)
    content = re.sub(r'<clothes>([^<\n]+)</clothes>', r'clothes: "\1"', content)

    # Memory tags
    content = re.sub(r'<\+memory>([^<\n]+)</memory>', r'memory_add: ["\1"]', content)
    content = re.sub(r'<#memory>([^<\n]+)</memory>', r'memory_update: ["\1"]', content)
    content = re.sub(r'<-memory>([^<\n]+)</memory>', r'memory_delete: ["\1"]', content)

    # Secret tag
    content = re.sub(r'<Secret!>', 'secret_exposed: true', content)

    # <p>att,bore,str</p>
    def replace_p(m):
        parts = [p.strip() for p in m.group(1).split(',')]
        if len(parts) >= 3:
            return (f'{{attitude_change: {parts[0]}, '
                    f'boredom_change: {parts[1]}, '
                    f'stress_change: {parts[2]}}}')
        return m.group(0)
    content = re.sub(r'<p>([^<\n]+)</p>', replace_p, content)

    # Movement command <m>
    content = re.sub(r'<m>([^<\n]+)</m>', r'commands: ["\1"]', content)

    # Leftovers: <PlaceShip>, <MakeMove>, <MakeChessMoveAsLLM>, <ChangeChessDifficulty>, etc.
    content = re.sub(r'<PlaceShip>', 'PlaceShip:', content)
    content = re.sub(r'<MakeMove>', 'MakeMove:', content)
    content = re.sub(r'<MakeChessMoveAsLLM>', 'MakeChessMoveAsLLM:', content)
    content = re.sub(r'<ChangeChessDifficulty>', 'ChangeChessDifficulty:', content)

    # Bare section header tags: "EMOTIONS <e>:" -> "EMOTIONS (emotions field):"
    content = re.sub(r'\bEMOTIONS <e>:', 'EMOTIONS (emotions field):', content)
    content = re.sub(r'\bANIMATIONS <a>:', 'ANIMATIONS (animations field):', content)
    content = re.sub(r'\bCOMMANDS <c>:', 'COMMANDS (commands field):', content)

    # Bare tags used as field references: (<f> tag required) -> (face_params field required)
    content = re.sub(r'\(<f> tag required\)', '(face_params field required)', content)
    content = re.sub(r'\(<f>\)', '(face_params)', content)
    content = re.sub(r'\(<e>\)', '(emotions)', content)
    content = re.sub(r'\(<a>\)', '(animations)', content)
    content = re.sub(r'\(<c>\)', '(commands)', content)

    # Inline bare references: "A simple look <e> is often enough" -> "...emotions field..."
    content = re.sub(r'\s<e>\s', ' emotions field ', content)
    content = re.sub(r'\s<a>\s', ' animations field ', content)
    content = re.sub(r'\s<c>\s', ' commands field ', content)

    # Unclosed command tags: <c>text (end of string/line without </c>)
    content = re.sub(r'<c>([^<\n]*?)(?=\n|$)', lambda m: (
        f'commands: ["{m.group(1)}"]' if m.group(1).strip() else m.group(0)
    ), content)

    # Malformed <p=X,Y,Z</p> or stray <p>
    content = re.sub(r'<p=[^>]*>', 'variable changes', content)
    content = re.sub(r'`<p>`', '`variable changes`', content)

    # Malformed <v>text> (extra >)
    content = re.sub(r'<v>([^<\n]+)>', r'commands: ["\1"]', content)

    # Bare <memory> reference
    content = re.sub(r'\bCheck <memory>', 'Check memory field', content)
    content = re.sub(r'\bthe same <hint>', 'the same hint', content)

    # Parenthetical tag refs in angle brackets like "(Animations <a>)" or "(available <e>)"
    content = re.sub(r'\(([^()]*?)<([aepcfvm])>([^()]*?)\)',
                     lambda m: f'({m.group(1)}{m.group(2)} field{m.group(3)})',
                     content)

    return content

def fix_common_txt(char_dj_dir, json_section):
    """Replace format section in common.txt, keep character header."""
    path = os.path.join(char_dj_dir, 'Main', 'common.txt')
    if not os.path.exists(path):
        return
    content = read_file(path)
    lines = content.splitlines(keepends=True)

    # Find split: first line containing an actual <tag> pattern
    split_idx = len(lines)
    for i, line in enumerate(lines):
        # Look for "Отвечай не более" or "You must generate messages" as format section start
        if ('Отвечай не более в' in line or
                'You must generate messages' in line):
            split_idx = i
            break

    # If we didn't find a known marker, fall back to first <tag> line
    if split_idx == len(lines):
        for i, line in enumerate(lines):
            if re.search(r'<[a-z]>', line):
                split_idx = i
                break

    header_lines = lines[:split_idx]
    # Trim trailing blank lines from header
    while header_lines and header_lines[-1].strip() == '':
        header_lines.pop()
    header_lines.append('\n')  # one blank separator

    new_content = ''.join(header_lines) + json_section
    write_file(path, new_content)
    print(f"    common.txt: header kept ({split_idx} lines), format replaced")

def fix_files_with_regex(dir_path, skip_files=None):
    """Apply XML->JSON replacements to all text files in directory tree."""
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


def handle_crazy():
    crazy_dir = f"{BASE}/Crazy"
    dj = f"{crazy_dir}/DefaultJson"
    djf = f"{crazy_dir}/DefaultJsonFull"
    old_dir = f"{crazy_dir}/_old"
    old_dj = f"{old_dir}/DefaultJson"

    if not os.path.exists(djf):
        print("  Crazy: DefaultJsonFull already migrated, skipping")
        return

    os.makedirs(old_dir, exist_ok=True)

    # Backup DefaultJson -> _old/DefaultJson
    if os.path.exists(old_dj):
        shutil.rmtree(old_dj)
    shutil.copytree(dj, old_dj)
    print("  Crazy: DefaultJson -> _old/DefaultJson")

    # DefaultJsonFull -> DefaultJson (replace)
    shutil.rmtree(dj)
    shutil.copytree(djf, dj)
    print("  Crazy: DefaultJsonFull -> DefaultJson")
    # Remove DefaultJsonFull (now redundant)
    shutil.rmtree(djf)
    print("  Crazy: DefaultJsonFull removed (now is DefaultJson)")


def handle_character(char_name, json_section):
    char_dir = f"{BASE}/{char_name}"
    dj = f"{char_dir}/DefaultJson"
    old_dir = f"{char_dir}/_old"
    old_dj = f"{old_dir}/DefaultJson"

    if not os.path.exists(dj):
        print(f"  {char_name}: No DefaultJson found, skipping")
        return

    os.makedirs(old_dir, exist_ok=True)

    # Backup
    if os.path.exists(old_dj):
        shutil.rmtree(old_dj)
    shutil.copytree(dj, old_dj)
    print(f"  {char_name}: DefaultJson -> _old/DefaultJson")

    # Fix common.txt (replace format section)
    fix_common_txt(dj, json_section)

    # Fix all other files with regex (skip common.txt already handled)
    changed = fix_files_with_regex(dj, skip_files=[os.path.join('Main', 'common.txt')])
    if changed:
        print(f"    regex-fixed: {', '.join(changed)}")
    print(f"  {char_name}: Done")


def refix_remaining(chars):
    """Re-apply regex replacements to files that still have <> after initial pass."""
    for char_name in chars:
        char_dj = f"{BASE}/{char_name}/DefaultJson"
        if not os.path.exists(char_dj):
            continue
        changed = fix_files_with_regex(char_dj)
        if changed:
            print(f"  {char_name} refix: {', '.join(changed)}")

if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Cache JSON section BEFORE handling Crazy (which removes DefaultJsonFull)
    CACHED_JSON_SECTION = get_crazy_json_section()

    print("=== Crazy ===")
    handle_crazy()

    for char in ['Cappie', 'Kind', 'Mila', 'ShortHair', 'Sleepy', 'Creepy', 'Ghost']:
        print(f"=== {char} ===")
        handle_character(char, CACHED_JSON_SECTION)

    # Second pass to catch remaining edge cases
    print("\n=== Second pass: fixing remaining edge cases ===")
    refix_remaining(['Cappie', 'Kind', 'Mila', 'ShortHair', 'Sleepy', 'Creepy', 'Ghost', 'Crazy'])

    print("\nDone. GameMaster skipped (only has 'default', needs separate handling).")
