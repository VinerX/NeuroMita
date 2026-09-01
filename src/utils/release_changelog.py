"""Helpers for building GitHub release changelog bodies from git history."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

RELEASE_TAG_PATTERN = re.compile(r"^v[0-9]{4}\.[0-9]{2}\.[0-9]{2}(\.[0-9]+)?$")
_GIT_TIMEOUT_SECONDS = 30.0

IGNORED_SUBJECT_RE = re.compile(
    r"(_version|\bbump\b|version bump|\[skip ci\]|tester code|release workflow|github actions?)",
    re.IGNORECASE,
)


def _version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", tag or ""))


def _is_release_tag(tag: str) -> bool:
    return bool(RELEASE_TAG_PATTERN.fullmatch(tag))


@dataclass(frozen=True)
class ChangelogData:
    current_tag: str
    previous_tag: str
    excluded_tags: tuple[str, ...]
    commits: tuple[str, ...]

    def render(self) -> str:
        lines = [
            "Установка: распакуйте архив поверх установленной версии.",
            "",
            f"Изменения с {self.previous_tag}" if self.previous_tag else "Изменения",
        ]
        if self.commits:
            lines.extend(self.commits)
        else:
            lines.append("- Технические улучшения и исправления.")
        return "\n".join(lines) + "\n"


class GitRepo:
    def __init__(self, repo: str | Path = ".") -> None:
        self.repo = Path(repo)

    def git(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=check,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        return proc.stdout.strip()

    def list_release_tags(self) -> list[str]:
        tags = self.git("tag", "--list", "v*", "--sort=-version:refname")
        return [tag for tag in tags.splitlines() if _is_release_tag(tag)]

    def commit_subjects_not_reachable_from(self, excluded_tags: Sequence[str]) -> list[str]:
        if not excluded_tags:
            return []
        output = self.git(
            "log",
            "HEAD",
            "--no-merges",
            "--pretty=format:- %s (%h)",
            "--not",
            *excluded_tags,
        )
        subjects = []
        for line in output.splitlines():
            if not line:
                continue
            if IGNORED_SUBJECT_RE.search(line):
                continue
            subjects.append(line)
        return subjects


def find_excluded_release_tags(repo: GitRepo, current_tag: str) -> list[str]:
    current_key = _version_key(current_tag)
    excluded = []
    for tag in repo.list_release_tags():
        if tag == current_tag:
            continue
        if _version_key(tag) < current_key:
            excluded.append(tag)
    return excluded


def find_previous_release_tag(excluded_tags: Sequence[str]) -> str:
    """Return the immediately preceding release by version, regardless of branch."""
    return excluded_tags[0] if excluded_tags else ""


def build_changelog_data(current_tag: str, repo: str | Path = ".") -> ChangelogData:
    git_repo = GitRepo(repo)
    excluded_tags = find_excluded_release_tags(git_repo, current_tag)
    previous_tag = find_previous_release_tag(excluded_tags)
    commits = git_repo.commit_subjects_not_reachable_from(excluded_tags)
    return ChangelogData(
        current_tag=current_tag,
        previous_tag=previous_tag,
        excluded_tags=tuple(excluded_tags),
        commits=tuple(commits),
    )


def build_changelog(current_tag: str, repo: str | Path = ".") -> str:
    return build_changelog_data(current_tag=current_tag, repo=repo).render()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build release changelog body from git history.")
    parser.add_argument("--current-tag", required=True, help="Current release tag, e.g. v2026.07.04")
    parser.add_argument("--repo", default=".", help="Path to the git repository")
    parser.add_argument("--output", default="CHANGELOG_BODY.md", help="Output markdown file")
    args = parser.parse_args()

    body = build_changelog(current_tag=args.current_tag, repo=args.repo)
    Path(args.output).write_text(body, encoding="utf-8")
    print(body, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
