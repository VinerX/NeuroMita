"""Small developer-only prompt linter.

Emits *warnings* about prompt-set problems — it never blocks startup and makes
no attempt to find semantic contradictions with an LLM. Each warning names the
file, a line number or include chain, a warning kind, and a short explanation.

Checks:
  * missing-include      — an included file that does not exist
  * cyclic-include       — an include cycle (reports the chain)
  * duplicate-paragraph  — the same normalized paragraph in multiple files
  * conflicting-length   — several different word-count rules in one file
  * deprecated-item      — the old ``item|...`` tag format in Structural files
  * intents-mention      — "intents" mentioned by a prompt set without support_intents=True
  * none-txt-include     — the removed Common/None.txt included again

Usage::

    python -m utils.prompt_linter [prompts_root]
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple


PROMPT_EXTS = (".txt", ".script", ".system", ".postscript")

_INCLUDE_RE = re.compile(r"\[<([^>]+\.(?:script|txt|system|postscript))>\]")
_RUN_RE = re.compile(r"^\s*RUN\s+(\S+)", re.MULTILINE)
_LOAD_RE = re.compile(r'\bLOAD\s+"([^"]+)"')
_WORDS_RULE_RE = re.compile(r"(\d{1,3})\s*[-–]\s*(\d{1,3})\s*words", re.IGNORECASE)
_SUPPORT_INTENTS_RE = re.compile(
    r"^\s*support_intents\s*=\s*true\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)

# Legacy syntaxes that drift from the runtime contract (see improvement plans 01/02).
# The Unity runtime parses light as ``light:color:R,G,B`` / ``light:set:...`` (colon),
# and movement points as ``walkto,PointName`` (no space). The old comma-light form and
# the ``walkto, ...`` / ``PositionMita`` point naming no longer match the runtime.
_LEGACY_SYNTAX_RES = (
    (re.compile(r"light:color,"), "old light syntax 'light:color,' — canon is 'light:color:R,G,B'"),
    (re.compile(r"light:set,"), "old light syntax 'light:set,' — canon is 'light:set:...'"),
    (re.compile(r"walkto,\s"), "old movement syntax 'walkto, ' with a space — canon is 'walkto,PointName'"),
    (re.compile(r"PositionMita\b"), "legacy point naming 'PositionMita ...' — point names now come from runtime"),
)

# Rough size guard. ~4 chars/token heuristic; a single main prompt file above this
# many estimated tokens is a candidate for normalization (plan 02).
_OVERSIZED_TOKEN_THRESHOLD = 8000
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class LintWarning:
    file: str
    location: str
    kind: str
    message: str

    def format(self) -> str:
        return f"[{self.kind}] {self.file} ({self.location}): {self.message}"


def _prompt_set_root(path: Path, root: Path) -> Path:
    """Nearest ancestor containing main_template.txt / config.json (else file dir)."""
    cur = path.parent
    while cur != root and cur != cur.parent:
        if (cur / "main_template.txt").exists() or (cur / "config.json").exists():
            return cur
        cur = cur.parent
    return path.parent


def _resolve_include(raw: str, including_file: Path, set_root: Path, root: Path) -> Path | None:
    """Resolve an include/RUN/LOAD target with best-effort fallbacks.

    Рантайм резолвит относительные пути общих шаблонов (Common/*) от базы
    ПЕРСОНАЖА-потребителя (<Char>/<Variant>/), а не от папки самого файла.
    Третий кандидат моделирует это псевдо-базой той же глубины под root —
    иначе `../../Common/x` из Common/ даёт ложный missing-include.
    """
    candidates = [
        including_file.parent / raw,
        set_root / raw,
        root / "_char" / "_variant" / raw,
    ]
    for cand in candidates:
        norm = Path(os.path.normpath(str(cand)))
        if norm.exists():
            return norm
    # Return the primary (non-existent) candidate for reporting.
    return None


def _iter_prompt_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in PROMPT_EXTS:
            # Skip archived/legacy and worktrees.
            parts = set(path.parts)
            if ".claude" in parts or "worktrees" in parts or "Legacy" in parts:
                continue
            yield path


def _line_of(text: str, needle: str) -> int:
    idx = text.find(needle)
    if idx < 0:
        return 1
    return text.count("\n", 0, idx) + 1


def lint_prompts(root: Path) -> List[LintWarning]:
    root = Path(root)
    warnings: List[LintWarning] = []

    files = list(_iter_prompt_files(root))
    include_graph: Dict[Path, List[Path]] = {}
    paragraph_index: Dict[Tuple[str, str], List[str]] = {}

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        rel = str(path.relative_to(root))
        set_root = _prompt_set_root(path, root)

        # Include/RUN/LOAD directives inside // comments are documentation, not
        # real includes — blank comments out before scanning for them.
        code_text = re.sub(r"//[^\n]*", "", text)

        raw_includes: List[Tuple[str, str]] = []
        for m in _INCLUDE_RE.finditer(code_text):
            raw_includes.append((m.group(1), "include"))
        for m in _RUN_RE.finditer(code_text):
            raw_includes.append((m.group(1), "RUN"))
        for m in _LOAD_RE.finditer(code_text):
            raw_includes.append((m.group(1), "LOAD"))

        resolved_children: List[Path] = []
        for raw, kind in raw_includes:
            # none-txt re-inclusion
            if "None.txt" in raw:
                warnings.append(LintWarning(
                    rel, f"line {_line_of(text, raw)}", "none-txt-include",
                    "the removed Common/None.txt is included again",
                ))
            resolved = _resolve_include(raw, path, set_root, root)
            if resolved is None:
                warnings.append(LintWarning(
                    rel, f"line {_line_of(text, raw)}", "missing-include",
                    f"{kind} target not found: {raw}",
                ))
            else:
                resolved_children.append(resolved)
        include_graph[path] = resolved_children

        # deprecated item| format in Structural files
        if "Structural" in path.parts and re.search(r"(?<![A-Za-z])item\|", text):
            warnings.append(LintWarning(
                rel, f"line {_line_of(text, 'item|')}", "deprecated-item",
                "old 'item|...' tag format used in a Structural file",
            ))

        # Intent rules are valid only for prompt sets that explicitly opt in.
        main_template = set_root / "main_template.txt"
        if main_template.exists() and re.search(r"\bintents\b", text, re.IGNORECASE):
            try:
                main_text = main_template.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                main_text = ""
            if not _SUPPORT_INTENTS_RE.search(main_text):
                warnings.append(LintWarning(
                    rel, f"line {_line_of(text.lower(), 'intents')}", "intents-mention",
                    "'intents' is mentioned but this prompt set does not declare support_intents=True",
                ))

        # legacy syntaxes that no longer match the Unity runtime contract
        for rx, msg in _LEGACY_SYNTAX_RES:
            m = rx.search(text)
            if m:
                warnings.append(LintWarning(
                    rel, f"line {text.count(chr(10), 0, m.start()) + 1}",
                    "legacy-syntax", msg,
                ))

        # oversized main prompt file (estimated tokens)
        if path.name in ("main.txt", "mainCrazy.txt") or path.parent.name == "Main":
            est_tokens = len(text) // _CHARS_PER_TOKEN
            if est_tokens > _OVERSIZED_TOKEN_THRESHOLD:
                warnings.append(LintWarning(
                    rel, "whole file", "oversized-prompt",
                    f"~{est_tokens} estimated tokens (> {_OVERSIZED_TOKEN_THRESHOLD}); "
                    "consider normalizing to the character skeleton",
                ))

        # conflicting numeric length rules within one file
        rules = {(a, b) for a, b in _WORDS_RULE_RE.findall(text)}
        if len(rules) > 1:
            warnings.append(LintWarning(
                rel, "multiple lines", "conflicting-length",
                f"several different word-count rules: {sorted(rules)}",
            ))

        # Collect paragraphs for duplicate detection, scoped to the prompt set.
        # Files shared across characters (Common/, per-character room maps) are
        # duplicated by design, so only flag repeats *within the same set*.
        set_key = _safe_rel(set_root, root)
        for para in re.split(r"\n\s*\n", text):
            norm = " ".join(para.split()).lower()
            if len(norm) >= 60:
                bucket = paragraph_index.setdefault((set_key, norm), [])
                if rel not in bucket:
                    bucket.append(rel)

    # duplicate paragraphs within a single prompt set
    for (set_key, norm), locs in paragraph_index.items():
        if len(locs) > 1:
            warnings.append(LintWarning(
                locs[0], f"+{len(locs) - 1} file(s) in {set_key}", "duplicate-paragraph",
                f"identical paragraph also in: {', '.join(locs[1:])} — '{norm[:50]}...'",
            ))

    # cyclic includes
    warnings.extend(_detect_cycles(include_graph, root))
    return warnings


def _detect_cycles(graph: Dict[Path, List[Path]], root: Path) -> List[LintWarning]:
    warnings: List[LintWarning] = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[Path, int] = {}
    seen_cycles: Set[Tuple[str, ...]] = set()

    def dfs(node: Path, stack: List[Path]):
        color[node] = GRAY
        stack.append(node)
        for child in graph.get(node, []):
            if color.get(child, WHITE) == GRAY:
                cycle = stack[stack.index(child):] + [child]
                key = tuple(sorted(str(p) for p in cycle))
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    chain = " -> ".join(_safe_rel(p, root) for p in cycle)
                    warnings.append(LintWarning(
                        _safe_rel(node, root), "include chain", "cyclic-include",
                        f"include cycle: {chain}",
                    ))
            elif color.get(child, WHITE) == WHITE:
                dfs(child, stack)
        stack.pop()
        color[node] = BLACK

    for node in list(graph.keys()):
        if color.get(node, WHITE) == WHITE:
            dfs(node, [])
    return warnings


def _safe_rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root))
    except Exception:
        return str(p)


def main(argv: List[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[2] / "extra" / "Prompts"
    warnings = lint_prompts(root)
    if not warnings:
        print(f"prompt-linter: no warnings ({root})")
        return 0
    print(f"prompt-linter: {len(warnings)} warning(s) in {root}\n")
    for w in warnings:
        print("  " + w.format())
    return 0  # warnings never fail the build


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
