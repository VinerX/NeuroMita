from __future__ import annotations

import hashlib
import os
import sys
import threading
import types
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from services.update_transaction import (
    DirectoryInstallTransaction,
    atomic_write_json,
    build_install_manifest,
    read_json,
    verify_install_manifest,
    write_install_manifest,
)
from updater import (
    UpdateCancelled,
    _archive_meta_path,
    _download,
    _install_unity_asset,
    _python_journal_path,
    _python_stage_marker,
    _python_staging_path,
    resume_pending_python_update,
)
from utils.archive_utils import extract_archive
from utils.release_assets import ReleaseAsset


def _make_verified_tree(root: Path, text: str, version: str = "v1") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "NeuroMita.exe").write_text(text, encoding="utf-8")
    (root / "_version.txt").write_text(version, encoding="utf-8")
    manifest = build_install_manifest(
        root,
        component="unity",
        version=version,
        archive_sha256="a" * 64,
    )
    write_install_manifest(root, manifest)


def test_manifest_detects_installed_file_tampering(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    _make_verified_tree(root, "good")
    verify_install_manifest(root)

    (root / "NeuroMita.exe").write_text("tampered", encoding="utf-8")

    with pytest.raises(RuntimeError, match="mismatch"):
        verify_install_manifest(root)


def test_directory_commit_replaces_target_and_removes_backup(tmp_path: Path) -> None:
    target = tmp_path / "Unity"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    transaction = DirectoryInstallTransaction(
        component="unity",
        target=target,
        state_root=tmp_path / "state",
    )
    transaction.begin({"version": "v1", "archive_url": "https://example/update.zip"})
    _make_verified_tree(transaction.reset_stage(), "new")
    transaction.mark_stage_ready(tree_sha256="unused")

    transaction.commit(verify_install_manifest)

    assert (target / "NeuroMita.exe").read_text(encoding="utf-8") == "new"
    assert not (target / "old.txt").exists()
    assert not transaction.paths.backup.exists()
    assert transaction.phase == "completed"


def test_failed_verification_rolls_back_original_target(tmp_path: Path) -> None:
    target = tmp_path / "Unity"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    transaction = DirectoryInstallTransaction(
        component="unity",
        target=target,
        state_root=tmp_path / "state",
    )
    transaction.begin({"version": "v1", "archive_url": "https://example/update.zip"})
    _make_verified_tree(transaction.reset_stage(), "new")
    transaction.mark_stage_ready(tree_sha256="unused")

    with pytest.raises(RuntimeError, match="reject"):
        transaction.commit(lambda _path: (_ for _ in ()).throw(RuntimeError("reject")))

    assert (target / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (target / "NeuroMita.exe").exists()
    assert transaction.phase == "rolled_back"


def test_recovery_finishes_interrupted_directory_swap(tmp_path: Path) -> None:
    target = tmp_path / "Unity"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    transaction = DirectoryInstallTransaction(
        component="unity",
        target=target,
        state_root=tmp_path / "state",
    )
    transaction.begin({"version": "v1", "archive_url": "https://example/update.zip"})
    _make_verified_tree(transaction.reset_stage(), "new")
    transaction.mark_stage_ready(tree_sha256="unused")
    transaction.set_phase("commit_prepared", had_target=True)
    os.replace(target, transaction.paths.backup)
    transaction.set_phase("target_backed_up")

    assert transaction.recover_commit(verify_install_manifest)
    assert (target / "NeuroMita.exe").read_text(encoding="utf-8") == "new"
    assert transaction.phase == "completed"


class _Response:
    def __init__(self, pieces: list[bytes], *, status: int, headers: dict[str, str], before_piece=None):
        self._pieces = pieces
        self.status_code = status
        self.headers = headers
        self._before_piece = before_piece

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int):
        _ = chunk_size
        for index, piece in enumerate(self._pieces):
            if self._before_piece is not None:
                self._before_piece(index)
            yield piece


def test_download_resumes_existing_partial_file(tmp_path: Path) -> None:
    destination = tmp_path / "archive.zip"
    partial = destination.with_suffix(".zip.part")
    partial.write_bytes(b"abc")
    _archive_meta_path(partial).write_text(
        '{"url":"https://example/archive.zip","etag":"tag"}',
        encoding="utf-8",
    )
    captured_headers: dict[str, str] = {}

    def get(_url, *, stream, timeout, headers):
        assert stream and timeout == 30
        captured_headers.update(headers)
        return _Response(
            [b"def"],
            status=206,
            headers={"Content-Range": "bytes 3-5/6", "ETag": "tag"},
        )

    fake_requests = types.SimpleNamespace(get=get)
    with patch.dict(sys.modules, {"requests": fake_requests}):
        digest = _download(
            "https://example/archive.zip",
            destination,
            expected_size=6,
            expected_sha256=hashlib.sha256(b"abcdef").hexdigest(),
        )

    assert captured_headers["Range"] == "bytes=3-"
    assert captured_headers["If-Range"] == "tag"
    assert destination.read_bytes() == b"abcdef"
    assert digest == hashlib.sha256(b"abcdef").hexdigest()


def test_cancelled_download_keeps_partial_for_next_resume(tmp_path: Path) -> None:
    destination = tmp_path / "archive.zip"
    stop = threading.Event()

    def before_piece(index: int) -> None:
        if index == 1:
            stop.set()

    fake_requests = types.SimpleNamespace(
        get=lambda *_args, **_kwargs: _Response(
            [b"abc", b"def"],
            status=200,
            headers={"Content-Length": "6", "ETag": "tag"},
            before_piece=before_piece,
        )
    )
    with patch.dict(sys.modules, {"requests": fake_requests}):
        with pytest.raises(UpdateCancelled):
            _download(
                "https://example/archive.zip",
                destination,
                expected_size=6,
                stop_event=stop,
            )

    assert destination.with_suffix(".zip.part").read_bytes() == b"abc"


def _unity_asset(base: Path, files: dict[str, bytes]) -> ReleaseAsset:
    archive = base / "_update_download" / "UnityBuild-v1.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as output:
        for name, content in files.items():
            output.writestr(name, content)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return ReleaseAsset(
        name=archive.name,
        url="https://example/UnityBuild-v1.zip",
        size=archive.stat().st_size,
        digest=f"sha256:{digest}",
    )


def test_unity_install_activates_only_a_verified_staging_tree(tmp_path: Path) -> None:
    target = tmp_path / "NeuroMita-Unity"
    target.mkdir()
    (target / "old.txt").write_text("old", encoding="utf-8")
    asset = _unity_asset(
        tmp_path,
        {
            "Build/Unity.exe": b"binary",
            "Build/Data/data.bin": b"data",
        },
    )

    result = _install_unity_asset(
        base_path=tmp_path,
        unity_path=target,
        version="v1",
        asset=asset,
        tester_code=None,
        logger=None,
        on_progress=None,
        on_extract_progress=None,
        on_verify_progress=None,
        on_stage=None,
        stop_event=None,
    )

    assert result.ok and result.changed
    assert (target / "Unity.exe").read_bytes() == b"binary"
    assert not (target / "old.txt").exists()
    verify_install_manifest(target)


def test_invalid_unity_stage_never_replaces_working_target(tmp_path: Path) -> None:
    target = tmp_path / "NeuroMita-Unity"
    target.mkdir()
    (target / "Unity.exe").write_bytes(b"old-binary")
    asset = _unity_asset(tmp_path, {"Build/readme.txt": b"missing executable"})

    result = _install_unity_asset(
        base_path=tmp_path,
        unity_path=target,
        version="v1",
        asset=asset,
        tester_code=None,
        logger=None,
        on_progress=None,
        on_extract_progress=None,
        on_verify_progress=None,
        on_stage=None,
        stop_event=None,
    )

    assert not result.ok
    assert (target / "Unity.exe").read_bytes() == b"old-binary"


def test_python_apply_resumes_from_verified_stage_without_redownload(tmp_path: Path) -> None:
    base = tmp_path / "NeuroMita"
    base.mkdir()
    (base / "payload.txt").write_text("old", encoding="utf-8")
    staging = _python_staging_path(base)
    staging.mkdir()
    (staging / "payload.txt").write_text("new", encoding="utf-8")
    archive_hash = "b" * 64
    manifest = build_install_manifest(
        staging,
        component="python",
        version="v2",
        archive_sha256=archive_hash,
    )
    write_install_manifest(staging, manifest)
    atomic_write_json(
        _python_stage_marker(staging),
        {"schema": 1, "archive_sha256": archive_hash},
    )
    archive = tmp_path / "missing.zip"
    atomic_write_json(
        _python_journal_path(base),
        {
            "schema": 1,
            "component": "python",
            "target": str(base),
            "phase": "applying",
            "authorized": True,
            "version": "v2",
            "archive_name": archive.name,
            "archive_url": "https://example/missing.zip",
            "archive_path": str(archive),
            "archive_size": 0,
            "archive_digest": "",
            "archive_sha256": archive_hash,
            "mode": "diff",
            "preserve_prompts": True,
        },
    )

    result = resume_pending_python_update(base_dir=str(base))

    assert result.ok and result.changed and result.recovered
    assert (base / "payload.txt").read_text(encoding="utf-8") == "new"
    assert not staging.exists()
    assert not _python_stage_marker(staging).exists()
    assert read_json(_python_journal_path(base))["phase"] == "completed"


def test_locked_python_update_waits_for_explicit_detached_handoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    base = tmp_path / "NeuroMita"
    base.mkdir()
    (base / "Launcher.exe").write_bytes(b"old")
    staging = _python_staging_path(base)
    staging.mkdir()
    (staging / "Launcher.exe").write_bytes(b"new")
    archive_hash = "c" * 64
    manifest = build_install_manifest(
        staging,
        component="python",
        version="v2",
        archive_sha256=archive_hash,
    )
    write_install_manifest(staging, manifest)
    atomic_write_json(
        _python_stage_marker(staging),
        {"schema": 1, "archive_sha256": archive_hash},
    )
    archive = tmp_path / "missing.zip"
    atomic_write_json(
        _python_journal_path(base),
        {
            "schema": 1,
            "component": "python",
            "target": str(base),
            "phase": "waiting_for_restart",
            "authorized": True,
            "version": "v2",
            "archive_name": archive.name,
            "archive_url": "https://example/missing.zip",
            "archive_path": str(archive),
            "archive_sha256": archive_hash,
            "mode": "diff",
            "error": "Could not apply locked Launcher.exe",
        },
    )
    monkeypatch.delenv("NEUROMITA_DETACHED_RESTART", raising=False)

    waiting = resume_pending_python_update(base_dir=str(base))

    assert waiting.status == "waiting_for_restart"
    assert (base / "Launcher.exe").read_bytes() == b"old"
    monkeypatch.setenv("NEUROMITA_DETACHED_RESTART", "1")

    recovered = resume_pending_python_update(base_dir=str(base))

    assert recovered.ok and recovered.changed
    assert (base / "Launcher.exe").read_bytes() == b"new"


def test_archive_member_cannot_escape_staging_directory(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escaped.txt", "bad")

    with pytest.raises(ValueError, match="Unsafe archive member"):
        extract_archive(archive, tmp_path / "stage")

    assert not (tmp_path / "escaped.txt").exists()


def test_password_protected_7z_with_zip_name_is_detected_by_signature(tmp_path: Path) -> None:
    py7zr = pytest.importorskip("py7zr")
    source = tmp_path / "payload.txt"
    source.write_text("secret payload", encoding="utf-8")
    archive = tmp_path / "release.zip"
    with py7zr.SevenZipFile(archive, mode="w", password="tester-code") as output:
        output.write(source, arcname="payload.txt")

    destination = tmp_path / "stage"
    extract_archive(archive, destination, password="tester-code")

    assert (destination / "payload.txt").read_text(encoding="utf-8") == "secret payload"
