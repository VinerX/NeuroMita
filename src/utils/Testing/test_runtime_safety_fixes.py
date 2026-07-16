from __future__ import annotations

import io
import os
import sys
import types
import zipfile
from pathlib import Path
from unittest.mock import patch


PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from handlers.voice_models.install_plan_helpers import installer_python_version
from managers.database_manager import DatabaseManager
from managers.history_manager import HistoryManager
from utils.prompt_downloader import PromptDownloader


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        for index in range(0, len(self.payload), chunk_size):
            yield self.payload[index : index + chunk_size]


def _prompt_zip(content: str = "new") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("repo-root/Prompts/System/prompt.txt", content)
    return output.getvalue()


def test_python_probe_always_has_timeout() -> None:
    installer_python_version.cache_clear()
    with patch("handlers.voice_models.install_plan_helpers.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "3.11.9\n"
        assert installer_python_version("/different/python") == (3, 11, 9)

    assert run.call_args.kwargs["timeout"] > 0


def test_prompt_update_is_streamed_and_keeps_backup(tmp_path: Path) -> None:
    prompts = tmp_path / "Prompts"
    prompts.mkdir()
    (prompts / "old.txt").write_text("old", encoding="utf-8")
    downloader = PromptDownloader()
    downloader.base_path = prompts
    downloader.backup_path = tmp_path / "Prompts_backup"

    captured = {}

    def fake_get(_url, **kwargs):
        captured.update(kwargs)
        return _Response(_prompt_zip())

    with patch("utils.prompt_downloader.requests.get", side_effect=fake_get):
        assert downloader.download_and_replace_prompts() is True

    assert captured["stream"] is True
    assert captured["timeout"][0] > 0
    assert captured["timeout"][1] > 0
    assert (prompts / "System" / "prompt.txt").read_text(encoding="utf-8") == "new"
    assert (downloader.backup_path / "old.txt").read_text(encoding="utf-8") == "old"


def test_prompt_update_restores_original_directory_on_swap_failure(tmp_path: Path) -> None:
    prompts = tmp_path / "Prompts"
    prompts.mkdir()
    (prompts / "old.txt").write_text("old", encoding="utf-8")
    downloader = PromptDownloader()
    downloader.base_path = prompts
    downloader.backup_path = tmp_path / "Prompts_backup"

    real_replace = os.replace
    calls = {"count": 0}

    def flaky_replace(source, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("swap failed")
        return real_replace(source, target)

    with patch("utils.prompt_downloader.requests.get", return_value=_Response(_prompt_zip())), patch(
        "utils.prompt_downloader.os.replace", side_effect=flaky_replace
    ):
        assert downloader.download_and_replace_prompts() is False

    assert (prompts / "old.txt").read_text(encoding="utf-8") == "old"


def test_history_read_path_does_not_refresh_schema(tmp_path: Path) -> None:
    DatabaseManager._instance = None
    DatabaseManager._path_override = str(tmp_path / "world.db")
    try:
        history = HistoryManager(character_name="Test", character_id="char:test")
        history.add_message({"role": "user", "content": "hello"})
        with patch.object(history.db, "get_history_columns", side_effect=AssertionError("hot schema refresh")):
            assert history.load_history()["messages"][0]["content"] == "hello"
            assert history.get_recent_messages(limit=10)[0]["content"] == "hello"
    finally:
        DatabaseManager._instance = None
        DatabaseManager._path_override = None


def test_rag_initialization_retries_after_transient_failure(tmp_path: Path) -> None:
    DatabaseManager._instance = None
    DatabaseManager._path_override = str(tmp_path / "world.db")
    calls = {"count": 0}
    expected = object()

    class _RAGManager:
        @classmethod
        def for_character(cls, _key):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("worker not ready")
            return expected

    fake_module = types.ModuleType("managers.rag.rag_manager")
    fake_module.RAGManager = _RAGManager

    try:
        history = HistoryManager(character_name="Test", character_id="char:test")
        history._RAG_RETRY_BASE_SECONDS = 0.0
        history._RAG_RETRY_MAX_SECONDS = 0.0
        with patch.dict(sys.modules, {"managers.rag.rag_manager": fake_module}):
            assert history.rag is None
            assert history.rag is expected
        assert calls["count"] == 2
    finally:
        DatabaseManager._instance = None
        DatabaseManager._path_override = None


def test_task_supervisor_submit_has_no_import_order_dependency() -> None:
    from core.executor_registry import Pools
    from core.task_supervisor import TaskSupervisor

    supervisor = TaskSupervisor()
    try:
        future = supervisor.submit(object(), "probe", lambda: 42, pool=Pools.IO)
        assert future.result(timeout=2.0) == 42
    finally:
        supervisor.shutdown()
