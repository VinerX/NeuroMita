from __future__ import annotations

import hashlib
import os
import threading
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
from services.release_catalog import ReleaseCatalogError
from services.update_contour import UpdateTarget
from updater import (
    UpdateCancelled,
    _archive_meta_path,
    _download,
    _install_unity_asset,
    _legacy_python_download_dir,
    _legacy_python_journal_path,
    _legacy_python_staging_path,
    _begin_python_operation,
    _python_download_dir,
    _python_journal_path,
    _python_stage_marker,
    _python_staging_path,
    _python_installation_id,
    _python_workspace,
    _install_full_archive,
    get_unity_update_info,
    note_locked_restart_attempt,
    resume_pending_python_update,
)
from services.update_activation import (
    activation_marker_path,
    pending_zipapp_path,
)
from utils.archive_utils import extract_archive
from utils.release_assets import ReleaseAsset


@pytest.fixture(autouse=True)
def _isolated_python_update_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NEUROMITA_UPDATE_CACHE_DIR", str(tmp_path / "update-cache"))


def test_python_update_workspace_stays_outside_install_parent(tmp_path: Path) -> None:
    base = tmp_path / "Desktop" / "NeuroMitaBuild"
    other = tmp_path / "Desktop" / "OtherNeuroMitaBuild"
    base.mkdir(parents=True)
    other.mkdir(parents=True)

    workspace = _python_workspace(base)
    assert workspace != _python_workspace(other)
    assert workspace.is_relative_to(tmp_path / "update-cache")
    assert not workspace.is_relative_to(base.parent)
    assert _python_installation_id(base) != _python_installation_id(other)


def test_unity_check_distinguishes_catalog_failure_from_missing_asset(tmp_path: Path) -> None:
    target = UpdateTarget("release", "VinerX/NeuroMita", "stable")
    with (
        patch("updater._get_update_target", return_value=target),
        patch("updater._find_unity_executable", return_value=None),
        patch(
            "updater._fetch_latest_unity_release_asset",
            side_effect=ReleaseCatalogError("manifest and API unavailable"),
        ),
    ):
        unavailable = get_unity_update_info(base_dir=str(tmp_path))

    assert unavailable["ok"] is False
    assert "Could not load release catalog" in unavailable["error"]
    assert "Could not find a Unity release asset" not in unavailable["error"]

    with (
        patch("updater._get_update_target", return_value=target),
        patch("updater._find_unity_executable", return_value=None),
        patch("updater._fetch_latest_unity_release_asset", return_value=(None, None)),
    ):
        missing = get_unity_update_info(base_dir=str(tmp_path))

    assert missing["ok"] is False
    assert "Could not find a Unity release asset" in missing["error"]


def test_new_python_operation_records_cache_paths(tmp_path: Path) -> None:
    base = tmp_path / "Desktop" / "NeuroMitaBuild"
    base.mkdir(parents=True)
    asset = ReleaseAsset(
        name="PythonBuild-v2.zip",
        url="https://example/PythonBuild-v2.zip",
        size=123,
        digest="sha256:" + "a" * 64,
    )

    state = _begin_python_operation(
        base,
        version="v2",
        asset=asset,
        mode="diff",
        preserve_prompts=True,
        is_patch=False,
    )

    assert Path(state["archive_path"]).parent == _python_download_dir(base)
    assert Path(state["staging"]) == _python_staging_path(base)
    assert Path(state["archive_path"]).is_relative_to(tmp_path / "update-cache")
    assert not list(base.parent.glob(f".{base.name}.*"))


def test_legacy_python_recovery_uses_original_reserve_and_cleans_it(tmp_path: Path) -> None:
    base = tmp_path / "Desktop" / "NeuroMitaBuild"
    base.mkdir(parents=True)
    (base / "payload.txt").write_text("old", encoding="utf-8")
    staging = _legacy_python_staging_path(base)
    staging.mkdir()
    (staging / "payload.txt").write_text("new", encoding="utf-8")
    archive_hash = "d" * 64
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
    archive = _legacy_python_download_dir(base) / "PythonBuild-v2.zip"
    atomic_write_json(
        _legacy_python_journal_path(base),
        {
            "schema": 1,
            "component": "python",
            "target": str(base),
            "phase": "applying",
            "authorized": True,
            "version": "v2",
            "archive_name": archive.name,
            "archive_url": "https://example/PythonBuild-v2.zip",
            "archive_path": str(archive),
            "archive_size": 0,
            "archive_digest": "",
            "archive_sha256": archive_hash,
            "staging": str(staging),
            "mode": "diff",
            "preserve_prompts": True,
        },
    )

    result = resume_pending_python_update(base_dir=str(base))

    assert result.ok and result.changed and result.recovered
    assert (base / "payload.txt").read_text(encoding="utf-8") == "new"
    assert not _legacy_python_staging_path(base).exists()
    assert not _legacy_python_download_dir(base).exists()
    assert not _legacy_python_journal_path(base).exists()
    assert not list(base.parent.glob(f".{base.name}.*"))


def test_waiting_for_credentials_keeps_new_cache_for_retry(tmp_path: Path) -> None:
    base = tmp_path / "NeuroMitaBuild"
    base.mkdir()
    archive = _python_download_dir(base) / "PythonBuild-v2.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"encrypted")
    staging = _python_staging_path(base)
    staging.mkdir()
    atomic_write_json(
        _python_journal_path(base),
        {
            "schema": 1,
            "component": "python",
            "target": str(base),
            "phase": "waiting_for_credentials",
            "authorized": True,
            "version": "v2",
            "archive_name": archive.name,
            "archive_url": "https://example/PythonBuild-v2.zip",
            "archive_path": str(archive),
            "archive_sha256": "e" * 64,
            "staging": str(staging),
        },
    )

    result = resume_pending_python_update(base_dir=str(base))

    assert result.status == "waiting_for_credentials"
    assert archive.exists()
    assert _python_journal_path(base).exists()


def test_successful_recovery_survives_cleanup_failure(tmp_path: Path) -> None:
    base = tmp_path / "NeuroMitaBuild"
    base.mkdir()
    (base / "payload.txt").write_text("old", encoding="utf-8")
    staging = _python_staging_path(base)
    staging.mkdir(parents=True)
    (staging / "payload.txt").write_text("new", encoding="utf-8")
    archive_hash = "f" * 64
    write_install_manifest(
        staging,
        build_install_manifest(
            staging,
            component="python",
            version="v2",
            archive_sha256=archive_hash,
        ),
    )
    atomic_write_json(
        _python_stage_marker(staging),
        {"schema": 1, "archive_sha256": archive_hash},
    )
    archive = _python_download_dir(base) / "PythonBuild-v2.zip"
    atomic_write_json(
        _python_journal_path(base),
        {
            "schema": 1,
            "component": "python",
            "target": str(base),
            "phase": "applying",
            "version": "v2",
            "archive_name": archive.name,
            "archive_url": "https://example/PythonBuild-v2.zip",
            "archive_path": str(archive),
            "archive_sha256": archive_hash,
            "staging": str(staging),
            "mode": "diff",
        },
    )

    with patch("updater.shutil.rmtree", side_effect=OSError("locked")):
        result = resume_pending_python_update(base_dir=str(base))

    assert result.ok and result.changed
    assert read_json(_python_journal_path(base))["phase"] == "completed"
    assert staging.exists()


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

    def iter_bytes(self, chunk_size: int):
        _ = chunk_size
        for index, piece in enumerate(self._pieces):
            if self._before_piece is not None:
                self._before_piece(index)
            yield piece


class _HttpClient:
    def __init__(self, stream_factory):
        self._stream_factory = stream_factory

    def stream(self, *args, **kwargs):
        return self._stream_factory(*args, **kwargs)

    @staticmethod
    def raise_for_status(response):
        return response.raise_for_status()


def test_download_resumes_existing_partial_file(tmp_path: Path) -> None:
    destination = tmp_path / "archive.zip"
    partial = destination.with_suffix(".zip.part")
    partial.write_bytes(b"abc")
    _archive_meta_path(partial).write_text(
        '{"url":"https://example/archive.zip","etag":"tag"}',
        encoding="utf-8",
    )
    captured_headers: dict[str, str] = {}

    def stream(method, _url, *, timeout, headers):
        assert method == "GET"
        assert timeout.connect == 30.0
        assert timeout.read == 30.0
        captured_headers.update(headers)
        return _Response(
            [b"def"],
            status=206,
            headers={"Content-Range": "bytes 3-5/6", "ETag": "tag"},
        )

    fake_http_client = _HttpClient(stream)
    with patch("updater._UPDATE_HTTP_CLIENT", fake_http_client):
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

    fake_http_client = _HttpClient(
        lambda *_args, **_kwargs: _Response(
            [b"abc", b"def"],
            status=200,
            headers={"Content-Length": "6", "ETag": "tag"},
            before_piece=before_piece,
        )
    )
    with patch("updater._UPDATE_HTTP_CLIENT", fake_http_client):
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
    staging.mkdir(parents=True)
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
    assert not _python_journal_path(base).exists()
    assert not _python_workspace(base).exists()


def _write_zipapp(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as output:
        output.writestr("__main__.py", f"MARKER = {marker!r}\n")
        output.writestr("package/data.txt", marker)


def test_python_zipapp_is_staged_without_overwriting_running_archive(tmp_path: Path) -> None:
    base = tmp_path / "NeuroMita"
    base.mkdir()
    active = base / "NeuroMita.pyz"
    _write_zipapp(active, "old")
    old_bytes = active.read_bytes()

    source = tmp_path / "source"
    source.mkdir()
    _write_zipapp(source / "NeuroMita.pyz", "new")
    (source / "payload.txt").write_text("new-payload", encoding="utf-8")
    archive = tmp_path / "PythonBuild-v2.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for file in source.rglob("*"):
            if file.is_file():
                output.write(file, file.relative_to(source).as_posix())

    deferred = _install_full_archive(
        archive,
        base,
        None,
        lambda *_args: None,
        mode="diff",
        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
    )

    assert active.read_bytes() == old_bytes
    assert (base / "payload.txt").read_text(encoding="utf-8") == "new-payload"
    assert deferred["NeuroMita.pyz"] == str(pending_zipapp_path(base))
    assert pending_zipapp_path(base).is_file()
    assert activation_marker_path(base).is_file()
    with zipfile.ZipFile(pending_zipapp_path(base)) as staged:
        assert "new" in staged.read("__main__.py").decode("utf-8")


def test_pending_zipapp_activation_is_confirmed_after_launcher_promotion(tmp_path: Path) -> None:
    base = tmp_path / "NeuroMita"
    base.mkdir()
    active = base / "NeuroMita.pyz"
    pending = pending_zipapp_path(base)
    _write_zipapp(active, "old")
    _write_zipapp(pending, "new")
    pending_hash = hashlib.sha256(pending.read_bytes()).hexdigest()
    activation_marker_path(base).parent.mkdir(parents=True, exist_ok=True)
    activation_marker_path(base).write_text("{}", encoding="utf-8")

    atomic_write_json(
        _python_journal_path(base),
        {
            "schema": 1,
            "component": "python",
            "target": str(base),
            "phase": "waiting_for_activation",
            "version": "v2",
            "archive_name": "PythonBuild-v2.zip",
            "archive_url": "https://example/PythonBuild-v2.zip",
            "archive_sha256": "a" * 64,
            "pending_zipapp": str(pending),
            "pending_zipapp_sha256": pending_hash,
            "staging": str(_python_staging_path(base)),
        },
    )

    waiting = resume_pending_python_update(base_dir=str(base))
    assert waiting.ok
    assert waiting.status == "waiting_for_activation"
    assert waiting.restart_required

    os.replace(pending, active)
    activation_marker_path(base).unlink(missing_ok=True)

    activated = resume_pending_python_update(base_dir=str(base))
    assert activated.ok and activated.recovered
    assert activated.status == "activated"
    assert not activated.changed
    assert not _python_journal_path(base).exists()
    with zipfile.ZipFile(active) as archive:
        assert "new" in archive.read("__main__.py").decode("utf-8")


def test_corrupt_zipapp_is_rejected_before_active_archive_is_touched(tmp_path: Path) -> None:
    base = tmp_path / "NeuroMita"
    base.mkdir()
    active = base / "NeuroMita.pyz"
    _write_zipapp(active, "old")
    old_bytes = active.read_bytes()

    source = tmp_path / "source"
    source.mkdir()
    (source / "NeuroMita.pyz").write_bytes(b"not-a-zipapp")
    archive = tmp_path / "PythonBuild-v2.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.write(source / "NeuroMita.pyz", "NeuroMita.pyz")

    with pytest.raises(RuntimeError, match="valid ZIP application"):
        _install_full_archive(
            archive,
            base,
            None,
            lambda *_args: None,
            mode="diff",
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        )

    assert active.read_bytes() == old_bytes
    assert not pending_zipapp_path(base).exists()


def test_failed_overlay_discards_staged_zipapp_activation(tmp_path: Path) -> None:
    base = tmp_path / "NeuroMita"
    base.mkdir()
    active = base / "NeuroMita.pyz"
    _write_zipapp(active, "old")
    old_bytes = active.read_bytes()

    source = tmp_path / "source"
    source.mkdir()
    _write_zipapp(source / "NeuroMita.pyz", "new")
    (source / "payload.txt").write_text("new payload", encoding="utf-8")
    archive = tmp_path / "PythonBuild-v2.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.write(source / "NeuroMita.pyz", "NeuroMita.pyz")
        output.write(source / "payload.txt", "payload.txt")

    with patch("updater._overlay_dir", side_effect=RuntimeError("overlay failed")):
        with pytest.raises(RuntimeError, match="overlay failed"):
            _install_full_archive(
                archive,
                base,
                None,
                lambda *_args: None,
                mode="diff",
                archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            )

    assert active.read_bytes() == old_bytes
    assert not pending_zipapp_path(base).exists()
    assert not activation_marker_path(base).exists()


def test_locked_python_update_waits_for_explicit_detached_handoff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    base = tmp_path / "NeuroMita"
    base.mkdir()
    (base / "Launcher.exe").write_bytes(b"old")
    staging = _python_staging_path(base)
    staging.mkdir(parents=True)
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


def test_locked_restart_attempts_stop_the_detached_relaunch_loop(
    tmp_path: Path,
) -> None:
    base = tmp_path / "NeuroMita"
    base.mkdir()
    atomic_write_json(
        _python_journal_path(base),
        {
            "schema": 1,
            "component": "python",
            "target": str(base),
            "phase": "waiting_for_restart",
            "version": "v2",
            "archive_name": "x.zip",
            "archive_url": "https://example/x.zip",
            "error": "Could not apply locked python.exe",
        },
    )

    # Первые попытки просят ещё один detached-перезапуск, но не роняют операцию.
    attempt1, exhausted1 = note_locked_restart_attempt(base, limit=3)
    attempt2, exhausted2 = note_locked_restart_attempt(base, limit=3)
    assert (attempt1, exhausted1) == (1, False)
    assert (attempt2, exhausted2) == (2, False)
    assert read_json(_python_journal_path(base))["phase"] == "waiting_for_restart"

    # На лимите операция переводится в терминальный failed без «locked»-текста,
    # чтобы resume больше не сигналил waiting_for_restart и цикл остановился.
    attempt3, exhausted3 = note_locked_restart_attempt(base, limit=3)
    assert (attempt3, exhausted3) == (3, True)
    journal = read_json(_python_journal_path(base))
    assert journal["phase"] == "failed"
    assert "Could not apply" not in journal["error"]
    assert journal["restart_attempts"] == 3

    # После исчерпания лимита resume считает операцию завершённой (без петли).
    result = resume_pending_python_update(base_dir=str(base))
    assert result.status == "no_pending_operation"


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
