from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from controllers.install_controller import (
    InstallController,
    _get_installed_constraints,
    _merge_requirement_specs,
)
from core.backends import BackendKind
from core.install_log import classify_install_log
from core.install_requirements import InstallRequirement, check_requirements
from core.install_types import InstallAction, InstallPlan
from handlers.voice_models.edge_tts_rvc_model import (
    EDGE_TTS_RVC_ONNX_ID,
    EdgeTTSRVCOnnxModel,
)
from utils.pip_installer import PipInstaller


def _write_dist(root: Path, name: str, version: str) -> None:
    info = root / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )


def test_requirement_checker_reads_python_module_from_explicit_target(tmp_path: Path) -> None:
    package = tmp_path / "target_only_package"
    package.mkdir()
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = check_requirements(
        [InstallRequirement(id="module", kind="python_module", module="target_only_package")],
        ctx={"libs_dir": str(tmp_path)},
    )

    assert result["ok"] is True


def test_requirement_checker_reads_distribution_from_explicit_target(tmp_path: Path) -> None:
    _write_dist(tmp_path, "target-only-dist", "1.2.3")

    result = check_requirements(
        [InstallRequirement(id="dist", kind="python_dist", spec="target-only-dist>=1")],
        ctx={"target_dir": str(tmp_path)},
    )

    assert result["ok"] is True
    assert result["details"][0]["extra"]["version"] == "1.2.3"


def test_requirement_checker_rejects_unsatisfied_target_version(tmp_path: Path) -> None:
    _write_dist(tmp_path, "target-only-dist", "1.2.3")

    result = check_requirements(
        [InstallRequirement(id="dist", kind="python_dist", spec="target-only-dist>=2")],
        ctx={"target_dir": str(tmp_path)},
    )

    assert result["ok"] is False
    assert result["missing_required"] == ["dist"]


def test_distribution_metadata_is_authoritative_when_import_name_differs(tmp_path: Path) -> None:
    # The published tts-with-rvc-onnx wheel has used a top-level import package
    # name different from its distribution name. A valid dist-info entry must
    # not be rejected by a stale/wrong module-name checker.
    _write_dist(tmp_path, "tts-with-rvc-onnx", "0.1.9.4")
    (tmp_path / "tts_with_rvc").mkdir()

    result = check_requirements(
        [InstallRequirement(id="dist", kind="python_dist", spec="tts-with-rvc-onnx[dml]")],
        ctx={"target_dir": str(tmp_path)},
    )

    assert result["ok"] is True


def test_install_controller_propagates_exact_pip_target_to_plan_context(tmp_path: Path) -> None:
    class _FakePipInstaller:
        libs_path_abs = str(tmp_path)
        script_path = os.fspath(tmp_path / "python.exe")

    class _FakeEventBus:
        def emit(self, *_args, **_kwargs):
            return None

    class _Controller(InstallController):
        def __init__(self):
            self.event_bus = _FakeEventBus()

        def _make_pip_installer(self, _callbacks):
            return _FakePipInstaller()

    seen: dict = {}

    def runner(*, ctx, **_kwargs):
        seen.update(ctx)
        return True

    assert _Controller().run_task(task_id="probe", runner=runner) is True
    assert seen["libs_dir"] == str(tmp_path)
    assert seen["lib_dir"] == str(tmp_path)
    assert seen["target_dir"] == str(tmp_path)
    assert seen["python_executable"].endswith("python.exe")


def test_edge_onnx_final_check_logs_every_missing_requirement(tmp_path: Path) -> None:
    plan = EdgeTTSRVCOnnxModel.build_install_plan_for_model(
        EDGE_TTS_RVC_ONNX_ID,
        {"libs_dir": str(tmp_path), "gpu_vendor": "INTEL"},
    )
    verify = plan.actions[-1].fn
    logs: list[str] = []
    callbacks = SimpleNamespace(log=logs.append)
    backend_status = SimpleNamespace(
        ok=False,
        as_dict=lambda: {
            "reason": "ONNX backend is missing",
            "provider": "missing",
            "target_dir": str(tmp_path),
        },
    )

    with patch("core.install_requirements.get_backend_service") as backend:
        backend.return_value.get_status.return_value = backend_status
        assert verify(callbacks=callbacks, ctx={"libs_dir": str(tmp_path)}) is False

    rendered = "\n".join(logs)
    assert "backend_onnx" in rendered
    assert "tts_rvc_pkg" in rendered
    assert str(tmp_path) in rendered


def test_edge_onnx_final_check_succeeds_from_target_without_restart(tmp_path: Path) -> None:
    (tmp_path / "omegaconf").mkdir()
    (tmp_path / "tts_with_rvc").mkdir()
    (tmp_path / "edge_tts").mkdir()
    _write_dist(tmp_path, "omegaconf", "2.3.0")
    _write_dist(tmp_path, "tts-with-rvc-onnx", "0.1.0")
    _write_dist(tmp_path, "edge-tts", "6.1.9")

    plan = EdgeTTSRVCOnnxModel.build_install_plan_for_model(
        EDGE_TTS_RVC_ONNX_ID,
        {"libs_dir": str(tmp_path), "gpu_vendor": "INTEL"},
    )
    verify = plan.actions[-1].fn
    backend_status = SimpleNamespace(ok=True, as_dict=lambda: {"reason": "ready"})

    with patch("core.install_requirements.get_backend_service") as backend:
        backend.return_value.get_status.return_value = backend_status
        assert verify(callbacks=SimpleNamespace(log=lambda _line: None), ctx={"libs_dir": str(tmp_path)}) is True


def test_edge_final_check_prefers_runtime_install_target_over_plan_snapshot(tmp_path: Path) -> None:
    stale_target = tmp_path / "stale"
    runtime_target = tmp_path / "runtime"
    stale_target.mkdir()
    runtime_target.mkdir()
    (runtime_target / "omegaconf").mkdir()
    (runtime_target / "tts_with_rvc").mkdir()
    (runtime_target / "edge_tts").mkdir()
    _write_dist(runtime_target, "omegaconf", "2.3.0")
    _write_dist(runtime_target, "tts-with-rvc-onnx", "0.1.0")
    _write_dist(runtime_target, "edge-tts", "6.1.9")

    plan = EdgeTTSRVCOnnxModel.build_install_plan_for_model(
        EDGE_TTS_RVC_ONNX_ID,
        {"libs_dir": str(stale_target), "gpu_vendor": "INTEL"},
    )
    verify = plan.actions[-1].fn
    backend_status = SimpleNamespace(ok=True, as_dict=lambda: {"reason": "ready"})

    with patch("core.install_requirements.get_backend_service") as backend:
        backend.return_value.get_status.return_value = backend_status
        assert verify(
            callbacks=SimpleNamespace(log=lambda _line: None),
            ctx={"libs_dir": str(runtime_target)},
        ) is True


def test_pip_installer_uses_private_uv_executable(tmp_path: Path) -> None:
    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(tmp_path / "Lib"), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ), patch("utils.pip_installer.base_dir", return_value=tmp_path):
        installer = PipInstaller(protected_packages=[])
        path = installer._uv_executable_path()

    assert path.parent == tmp_path / ".bootstrap" / "uv" / "bin"
    assert path.name in {"uv", "uv.exe"}


def test_pip_installer_selects_uv_executable_not_python_module(tmp_path: Path) -> None:
    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(tmp_path / "Lib"), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ), patch("utils.pip_installer.base_dir", return_value=tmp_path):
        installer = PipInstaller(protected_packages=[])
        with patch.object(installer, "_ensure_uv_available", return_value=True):
            command = installer._resolve_installer_base_cmd()

    assert command[0] == str(tmp_path / ".bootstrap" / "uv" / "bin" / installer._uv_executable_path().name)
    assert command[1:] == ["pip"]
    assert "-m" not in command


def test_installed_constraints_collapse_stale_dist_info_versions(tmp_path: Path) -> None:
    _write_dist(tmp_path, "torchaudio", "2.6.0")
    _write_dist(tmp_path, "torchaudio", "2.7.1")

    constraints = _get_installed_constraints(str(tmp_path), [])

    assert constraints.count("torchaudio==2.7.1") == 1
    assert not any(item == "torchaudio==2.6.0" for item in constraints)


def test_backend_overrides_win_over_stale_discovered_constraints() -> None:
    merged = _merge_requirement_specs(
        ["torch==2.7.1", "torchaudio==2.7.1"],
        ["torch==2.6.0", "torchaudio==2.6.0", "numpy==1.26.0"],
    )

    assert merged == ["torch==2.7.1", "torchaudio==2.7.1", "numpy==1.26.0"]


def test_pip_installer_deduplicates_overrides_by_distribution_name(tmp_path: Path) -> None:
    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(tmp_path / "Lib"), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ):
        installer = PipInstaller(protected_packages=[])

    assert installer._dedupe_overrides(
        ["torch==2.7.1", "Torch==2.6.0", "numpy==1.26.0"]
    ) == ["torch==2.7.1", "numpy==1.26.0"]


def test_compatibility_sensitive_stack_tries_uv_first_with_overrides(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(tmp_path / "Lib"), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ):
        installer = PipInstaller(protected_packages=[])
        installer._preferred_installer_cmd = [str(tmp_path / "uv.exe"), "pip"]

        def fake_run(cmd, _description):
            commands.append(list(cmd))
            installer._last_run_returncode = 0
            return True

        with patch.object(installer, "_run_pip_process", side_effect=fake_run):
            ok = installer.install_package_with_overrides(
                ["tts-with-rvc-onnx[dml]"],
                uv_overrides=["torch==2.7.1", "torchaudio==2.7.1"],
            )

    assert ok is True
    assert len(commands) == 1
    assert commands[0][0].endswith("uv.exe")
    assert commands[0][1] == "pip"
    assert "--overrides" in commands[0]
    assert "--constraint" not in commands[0]


def test_runtime_install_command_is_uv_only(tmp_path: Path) -> None:
    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(tmp_path / "Lib"), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ):
        installer = PipInstaller(protected_packages=[])

    uv = tmp_path / "uv.exe"
    with patch.object(installer, "_resolve_installer_base_cmd", return_value=[str(uv), "pip"]):
        command = installer._build_install_command()

    assert command[:2] == [str(uv), "pip"]
    assert "--python" in command
    assert [os.sys.executable, "-m", "pip"] != command[:3]


def test_target_module_detection_uses_wheel_top_level_metadata(tmp_path: Path) -> None:
    lib = tmp_path / "Lib"
    lib.mkdir()
    _write_dist(lib, "tts-with-rvc-onnx", "0.1.9.4")
    dist_info = next(lib.glob("tts_with_rvc_onnx-*.dist-info"))
    (dist_info / "top_level.txt").write_text("tts_with_rvc\n", encoding="utf-8")
    (lib / "tts_with_rvc").mkdir()

    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(lib), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ):
        installer = PipInstaller(protected_packages=[])

    assert installer.is_spec_satisfied_in_target("tts-with-rvc-onnx[dml]") is True


def test_uv_resolver_failure_does_not_fall_back_to_pip(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(tmp_path / "Lib"), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ):
        installer = PipInstaller(protected_packages=[])
        installer._preferred_installer_cmd = [str(tmp_path / "uv.exe"), "pip"]

        def fake_run(cmd, _description):
            commands.append(list(cmd))
            installer._last_run_returncode = 1
            installer._last_run_recent_lines = ["No solution found when resolving dependencies"]
            return False

        with patch.object(installer, "_run_pip_process", side_effect=fake_run):
            ok = installer.install_package_with_overrides(
                ["tts-with-rvc-onnx[dml]"],
                uv_overrides=["torch==2.7.1", "torchaudio==2.7.1"],
            )

    assert ok is False
    assert len(commands) == 1
    assert commands[0][0].endswith("uv.exe")
    assert "--overrides" in commands[0]


def test_uv_progress_parser_ignores_dependency_solver_prose(tmp_path: Path) -> None:
    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(tmp_path / "Lib"), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ):
        installer = PipInstaller(protected_packages=[])
    aggregate = installer._UvProgressAggregator()

    for line in (
        "Because tts-with-rvc-onnx depends on torchaudio",
        "torchaudio cannot be used",
        "we can conclude that your requirements are unsatisfiable",
    ):
        aggregate.update(line)

    assert aggregate.tasks == {}


def test_carriage_return_resolver_diagnostics_are_preserved(tmp_path: Path) -> None:
    logs: list[str] = []
    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(tmp_path / "Lib"), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ):
        installer = PipInstaller(update_log=logs.append, protected_packages=[])
    state = installer._RunState("resolve", ["uv", "pip", "install"])
    state.uv_progress = installer._UvProgressAggregator()

    installer._process_line(
        state,
        "No solution found when resolving dependencies",
        transient=True,
    )
    installer._process_line(
        state,
        "Because torchaudio cannot be used",
        transient=True,
    )

    assert list(state.recent_lines) == [
        "No solution found when resolving dependencies",
        "Because torchaudio cannot be used",
    ]
    assert any("No solution found" in line for line in logs)


@pytest.mark.parametrize(
    "message",
    [
        '__STATS__{"errors": 0, "warnings": 0}',
        "__SNAPSHOT_START__",
        "__SNAPSHOT_END__",
    ],
)
def test_structural_install_progress_is_not_classified_as_error(message: str) -> None:
    assert classify_install_log(message) is None


@pytest.mark.parametrize(
    ("message", "explicit_level", "expected"),
    [
        ("Installation failed", "", "error"),
        ("Traceback: boom", "", "error"),
        ("ordinary text", "critical", "error"),
        ("Предупреждение: cache disabled", "", "warning"),
        ("ordinary text", "warning", "warning"),
        ("Installing package", "", None),
    ],
)
def test_human_installer_log_classification(message: str, explicit_level: str, expected: str | None) -> None:
    assert classify_install_log(message, explicit_level) == expected


def test_environment_lock_uses_uv_compile_and_omits_shared_core(tmp_path: Path) -> None:
    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(tmp_path / "Lib"), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ):
        installer = PipInstaller(protected_packages=[], target_path=tmp_path / "overlay")

    commands: list[list[str]] = []

    def fake_run(command, _description):
        commands.append(list(command))
        if "compile" in command:
            output = Path(command[command.index("--output-file") + 1])
            output.write_text("fish-speech-lib==1.0.0\n", encoding="utf-8")
        return True

    with patch.object(installer, "_resolve_installer_base_cmd", return_value=[str(tmp_path / "uv.exe"), "pip"]), patch.object(
        installer, "_run_pip_process", side_effect=fake_run
    ):
        ok = installer.install_environment_lock(
            ["fish-speech-lib", "numpy<2"],
            core_overrides=["torch==2.7.1", "numpy==1.26.0"],
            core_packages=["torch", "numpy"],
            extra_args=[
                "--extra-index-url",
                "https://download.pytorch.org/whl/cu128",
                "--index-strategy",
                "unsafe-best-match",
            ],
        )

    assert ok is True
    assert len(commands) == 2
    compile_cmd, install_cmd = commands
    assert compile_cmd[:3] == [str(tmp_path / "uv.exe"), "pip", "compile"]
    assert compile_cmd.count("--no-emit-package") == 2
    assert "torch" in compile_cmd and "numpy" in compile_cmd
    assert "--extra-index-url" in compile_cmd
    assert "https://download.pytorch.org/whl/cu128" in compile_cmd
    assert "--index-strategy" in compile_cmd
    assert "unsafe-best-match" in compile_cmd
    assert install_cmd[:2] == [str(tmp_path / "uv.exe"), "pip"]
    assert "--no-deps" in install_cmd
    assert "-r" in install_cmd
    assert [os.sys.executable, "-m", "pip"] != install_cmd[:3]


def test_managed_uninstall_cleanup_skips_environment_package_mutations() -> None:
    package_action = InstallAction(
        type="call",
        description="remove packages",
        fn=lambda **_kwargs: True,
        environment_mutation=True,
    )
    artifact_action = InstallAction(
        type="call",
        description="remove model files",
        fn=lambda **_kwargs: True,
    )
    plan = InstallPlan(actions=[package_action, artifact_action])

    cleanup = InstallController._artifact_cleanup_plan(plan)

    assert cleanup.actions == [artifact_action]
    assert cleanup.required_backend is None


def test_missing_pywinpty_does_not_install_it_with_embedded_pip(tmp_path: Path) -> None:
    with patch.dict(
        os.environ,
        {"NEUROMITA_LIB_DIR": str(tmp_path / "Lib"), "NEUROMITA_PYTHON": os.sys.executable},
        clear=False,
    ):
        installer = PipInstaller(protected_packages=[])

    with patch("utils.pip_installer.os.name", "nt"), patch.object(
        installer, "_detect_pty", return_value=(False, None)
    ), patch.object(installer, "_ensure_pip_available") as ensure_pip, patch.object(
        installer, "_run_pip_process"
    ) as run_process:
        assert installer._ensure_pty_available() is False

    ensure_pip.assert_not_called()
    run_process.assert_not_called()


def test_managed_install_registers_overlay_without_refreshing_shared_worker(
    tmp_path: Path,
) -> None:
    class _EventBus:
        def emit(self, *_args, **_kwargs):
            return True

    class _Installer:
        def __init__(self, target: str | Path) -> None:
            self.libs_path_abs = str(target)
            self.script_path = os.sys.executable

        def cancel(self) -> None:
            return None

    record = SimpleNamespace(
        logical_id="tts-edge",
        revision_id="revision",
        category="tts",
        item_id="edge",
        site_packages=tmp_path / "overlay",
    )

    class _Transaction:
        def __init__(self) -> None:
            self.logical_id = "tts-edge"
            self.category = "tts"
            self.item_id = "edge"
            self.site_packages = tmp_path / "staging" / "site-packages"
            self.site_packages.mkdir(parents=True)
            self.validation_paths = (str(self.site_packages),)
            self.core_resolver_args = ()
            self.core_overrides = ()
            self.core_package_names = ()
            self.core_layers = []
            self.finalized = False

        def ensure_core_layers(self, _factory, *, log):
            return True

        def commit(self, _meta):
            return record

        def finalize(self):
            self.finalized = True

        def abort(self):
            return None

        def rollback_commit(self):
            raise AssertionError("rollback must not be needed")

    transaction = _Transaction()

    class _EnvironmentManager:
        staging_root = tmp_path / "staging-root"

        def should_manage(self, _meta):
            return True

        def logical_id_from_meta(self, _meta):
            return "tts-edge", "tts", "edge"

        def active(self, _logical_id):
            return None

        def begin(self, **_kwargs):
            return transaction

        def promote_backend_profile(self, _layer_ids, *, cleanup=False):
            assert cleanup is False

        def ensure_backend_profile(self, _layer_ids, *, cleanup=False):
            assert cleanup is False

    class _Controller(InstallController):
        def __init__(self) -> None:
            self.event_bus = _EventBus()
            self.environment_manager = _EnvironmentManager()

        def _make_pip_installer(self, _callbacks, target_path=None):
            return _Installer(target_path or tmp_path / "initial")

        def _execute_plan(self, *_args, **_kwargs):
            return True

        @staticmethod
        def _refresh_ai_runtime(**_kwargs):
            raise AssertionError("installation must not refresh the shared worker")

    plan = InstallPlan(actions=[], required_backend=None)
    result = _Controller().run_task(
        task_id="tts:edge:install",
        runner=lambda **_kwargs: plan,
        meta={"category": "tts", "item_id": "edge", "op": "install"},
    )

    assert result is True
    assert transaction.finalized is True


def test_backend_install_registers_candidate_without_empty_overlay(
    tmp_path: Path,
) -> None:
    class _EventBus:
        def emit(self, *_args, **_kwargs):
            return True

    class _Installer:
        def __init__(self, target: str | Path) -> None:
            self.libs_path_abs = str(target)
            self.script_path = os.sys.executable

        def cancel(self) -> None:
            return None

    layer = SimpleNamespace(layer_id="torch-cuda")

    class _Transaction:
        logical_id = "backend-cuda"
        category = "backend"
        item_id = "cuda"
        validation_paths = ()
        core_resolver_args = ()
        core_overrides = ()
        core_package_names = ()
        core_layers = [layer]

        def __init__(self) -> None:
            self.site_packages = tmp_path / "staging" / "site-packages"
            self.site_packages.mkdir(parents=True)
            self.aborted = False

        def ensure_core_layers(self, _factory, *, log):
            return True

        def commit(self, _meta):
            raise AssertionError("backend installation must not register an overlay")

        def abort(self):
            self.aborted = True

    transaction = _Transaction()

    class _EnvironmentManager:
        staging_root = tmp_path / "staging-root"

        def __init__(self) -> None:
            self.candidates = None

        def should_manage(self, _meta):
            return True

        def logical_id_from_meta(self, _meta):
            return "backend-cuda", "backend", "cuda"

        def active(self, _logical_id):
            return None

        def begin(self, **_kwargs):
            return transaction

        def register_backend_candidates(self, layer_ids):
            self.candidates = tuple(layer_ids)

    manager = _EnvironmentManager()

    class _Controller(InstallController):
        def __init__(self) -> None:
            self.event_bus = _EventBus()
            self.environment_manager = manager

        def _make_pip_installer(self, _callbacks, target_path=None):
            return _Installer(target_path or tmp_path / "initial")

        def _execute_plan(self, *_args, **_kwargs):
            return True

    result = _Controller().run_task(
        task_id="backend:cuda:install",
        runner=lambda **_kwargs: InstallPlan(
            actions=[],
            required_backend=BackendKind.CUDA,
        ),
        meta={"category": "backend", "item_id": "cuda", "op": "install"},
    )

    assert result is True
    assert manager.candidates == ("torch-cuda",)
    assert transaction.aborted is True
