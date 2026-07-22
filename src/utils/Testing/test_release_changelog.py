"""Tests for src/utils/release_changelog.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.release_changelog import build_changelog_data  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.stdout.strip()


def _commit(repo: Path, filename: str, message: str, content: str) -> str:
    path = repo / filename
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def release_history_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Codex Test")
    _git(repo, "config", "user.email", "codex@example.com")
    default_branch = _git(repo, "branch", "--show-current")

    _commit(repo, "notes.txt", "Релизный фундамент: распаковка поверх установленной версии", "base\n")
    _git(repo, "tag", "v2026.06.12_Full")

    _commit(repo, "notes.txt", "Исправлен bootstrap встроенного Python для полного релиза", "bootstrap\n")
    _git(repo, "tag", "v2026.06.20")

    _commit(repo, "notes.txt", "Обновлена карточка новостей: changelog и ссылки на полные заметки", "news\n")
    _git(repo, "tag", "v2026.06.22")

    _commit(repo, "notes.txt", "Горячий фикс релиза: восстановлен выбор предыдущего тега", "hotfix\n")
    _git(repo, "tag", "v2026.06.22.1")

    _commit(repo, "notes.txt", "build: убран служебный шум из changelog релиза", "noise-filter\n")
    _git(repo, "tag", "v2026.07.04")

    _commit(repo, "notes.txt", "Исправлен расчёт changelog при наличии будущего тестового тега", "current\n")

    _git(repo, "branch", "future-tag-base", "v2026.06.20")
    _git(repo, "checkout", "future-tag-base")
    _commit(repo, "future.txt", "Тестовый будущий релиз с реальным текстом заметок", "future branch\n")
    _git(repo, "tag", "v2026.12.01.1")
    _git(repo, "checkout", default_branch)

    return repo


def test_build_changelog_ignores_future_release_tag_and_old_release_history(release_history_repo: Path):
    data = build_changelog_data("v2026.07.05", repo=release_history_repo)
    expected_sha = _git(release_history_repo, "rev-parse", "--short", "HEAD")

    assert data.previous_tag == "v2026.07.04"
    assert "v2026.12.01.1" not in data.excluded_tags
    assert data.commits == (f"- Исправлен расчёт changelog при наличии будущего тестового тега ({expected_sha})",)


def test_build_changelog_uses_previous_version_even_when_tag_is_on_another_branch(release_history_repo: Path):
    default_branch = _git(release_history_repo, "branch", "--show-current")
    _git(release_history_repo, "branch", "released-from-default", "v2026.06.20")
    _git(release_history_repo, "checkout", "released-from-default")
    _commit(release_history_repo, "release.txt", "Release created from another branch", "release\n")
    _git(release_history_repo, "tag", "v2026.07.14")
    _git(release_history_repo, "checkout", default_branch)

    data = build_changelog_data("v2026.07.22", repo=release_history_repo)

    assert data.previous_tag == "v2026.07.14"


def test_build_changelog_renders_real_release_style_header_and_fallback_text(release_history_repo: Path):
    _commit(release_history_repo, "noise.txt", "github actions: tweak release workflow filters", "noise\n")
    _git(release_history_repo, "tag", "v2026.07.05")
    _commit(release_history_repo, "noise.txt", "release workflow: bump ci helper only", "noise 2\n")

    body = build_changelog_data("v2026.07.06", repo=release_history_repo).render()

    assert body.startswith("Установка: распакуйте архив поверх установленной версии.\n\nИзменения с v2026.07.05\n")
    assert body.endswith("- Технические улучшения и исправления.\n")
