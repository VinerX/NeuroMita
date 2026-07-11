from __future__ import annotations

import json
import os
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from core.backends import BackendKind
from core.install_requirements import is_pip_spec_satisfied
from core.runtime_environments import CoreLayerSpec, RuntimeEnvironmentManager


class _FakeInstaller:
    def __init__(self, target: str | Path) -> None:
        self.target = Path(target)
        self.target.mkdir(parents=True, exist_ok=True)
        self.calls: list[tuple[str, ...]] = []

    def install_package_with_overrides(
        self,
        packages,
        description=None,
        extra_args=None,
        uv_overrides=None,
    ) -> bool:
        specs = tuple(str(item) for item in packages)
        self.calls.append(specs)
        for spec in specs:
            requirement = Requirement(spec)
            version = next(
                (item.version for item in requirement.specifier if item.operator == "=="),
                "1.0.0",
            )
            name = canonicalize_name(requirement.name)
            dist = self.target / f"{name.replace('-', '_')}-{version}.dist-info"
            dist.mkdir(parents=True, exist_ok=True)
            (dist / "METADATA").write_text(
                f"Name: {requirement.name}\nVersion: {version}\n",
                encoding="utf-8",
            )
            module_name = "onnxruntime" if name == "onnxruntime-directml" else name.replace("-", "_")
            module = self.target / module_name
            module.mkdir(exist_ok=True)
            (module / "__init__.py").write_text("", encoding="utf-8")
            if name == "torch":
                transitive = self.target / "sympy-1.13.1.dist-info"
                transitive.mkdir(exist_ok=True)
                (transitive / "METADATA").write_text(
                    "Name: sympy\nVersion: 1.13.1\n",
                    encoding="utf-8",
                )
                sympy_module = self.target / "sympy"
                sympy_module.mkdir(exist_ok=True)
                (sympy_module / "__init__.py").write_text("", encoding="utf-8")
        return True


def _factory(created: list[_FakeInstaller]):
    def create(target: str):
        installer = _FakeInstaller(target)
        created.append(installer)
        return installer

    return create


def _write_dist(target: Path, name: str, version: str) -> None:
    normalized = canonicalize_name(name)
    dist = target / f"{normalized.replace('-', '_')}-{version}.dist-info"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "METADATA").write_text(
        f"Name: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )
    (dist / "RECORD").write_text(
        f"{normalized.replace('-', '_')}/__init__.py,,\n"
        f"{dist.name}/METADATA,,\n{dist.name}/RECORD,,\n",
        encoding="utf-8",
    )
    module = target / normalized.replace("-", "_")
    module.mkdir(exist_ok=True)
    (module / "__init__.py").write_text("", encoding="utf-8")


def test_layout_uses_versioned_core_and_environment_roots(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    spec = manager.core_layer_specs(BackendKind.CUDA, {"gpu_vendor": "NVIDIA"})[0]

    assert manager.main_core_root == (tmp_path / "Lib" / "core").resolve()
    assert manager.core_root == (tmp_path / "Lib" / "environment" / "bases").resolve()
    assert manager.overlay_root == (tmp_path / "Lib" / "environment" / "overlays").resolve()
    assert manager.environment_root == (tmp_path / "Lib" / "environment").resolve()
    assert "2.7.1" in spec.layer_id
    assert "cu128" in spec.layer_id


def test_cuda_torch_layer_satisfies_cpu_capability_without_second_copy(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    cuda_spec = manager.core_layer_specs(BackendKind.CUDA, {"gpu_vendor": "NVIDIA"})[0]
    cuda_layer = manager.ensure_core_layer(
        cuda_spec,
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    assert cuda_layer is not None
    assert "torch.cpu@2.7.1" in cuda_layer.capabilities
    assert "torch.cuda@2.7.1+cu128" in cuda_layer.capabilities
    assert "https://download.pytorch.org/whl/cu128" in cuda_layer.extra_args

    cpu_specs = manager.core_layer_specs(BackendKind.CPU, {"gpu_vendor": "CPU"})
    assert len(cpu_specs) == 1
    assert cpu_specs[0].group == "torch-reuse"
    cpu_layer = manager.ensure_core_layer(
        cpu_specs[0],
        installer_factory=_factory(created),
        log=lambda _message: None,
    )

    assert cpu_layer is not None
    assert cpu_layer.layer_id == cuda_layer.layer_id
    assert cpu_layer.extra_args == cuda_layer.extra_args
    assert len(list(manager.core_root.glob("*/manifest.json"))) == 1


def test_environment_commit_is_atomic_and_strips_only_core_owned_packages(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "fish"},
        requested_specs=("fish-speech==1.0.0",),
        required_backend=BackendKind.CPU,
        backend_context={"gpu_vendor": "CPU"},
    )
    assert manager.active(transaction.logical_id) is None
    assert transaction.ensure_core_layers(
        _factory(created),
        log=lambda _message: None,
    )
    assert transaction.site_packages is not None

    _write_dist(transaction.site_packages, "fish-speech", "1.0.0")
    _write_dist(transaction.site_packages, "torch", "2.7.1")
    _write_dist(transaction.site_packages, "sympy", "9.9.9")
    transaction.strip_core_packages()

    assert not list(transaction.site_packages.glob("torch-*.dist-info"))
    assert list(transaction.site_packages.glob("fish_speech-*.dist-info"))
    assert not list(transaction.site_packages.glob("sympy-*.dist-info"))

    record = transaction.commit({"source": "test"})
    assert manager.active(transaction.logical_id) == record
    assert record.site_packages.is_dir()
    assert not transaction.staging_root.exists()
    assert manager.runtime_paths(record)[0] == str(record.site_packages)


def test_runtime_composition_probes_direct_overlay_and_backend_imports(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "fish"},
        requested_specs=("fish-speech-lib==1.0.0",),
        required_backend=BackendKind.CPU,
        backend_context={"gpu_vendor": "CPU"},
    )
    assert transaction.ensure_core_layers(
        _factory(created),
        log=lambda _message: None,
    )
    _write_dist(transaction.site_packages, "fish-speech-lib", "1.0.0")

    record = transaction.commit()
    composition = manager.runtime_composition()

    assert record.probe_modules == ("fish_speech_lib",)
    assert "fish_speech_lib" in composition.probe_modules
    assert "torch" in composition.probe_modules
    assert "torchaudio" in composition.probe_modules
    assert "numpy" in composition.probe_modules
    reloaded = manager.active(record.logical_id)
    assert reloaded is not None
    assert reloaded.probe_modules == record.probe_modules


def test_legacy_manifest_derives_probes_and_ignores_native_lib_directories(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "legacy"},
        requested_specs=("pyarrow==20.0.0",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    dist = transaction.site_packages / "pyarrow-20.0.0.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(
        "Name: pyarrow\nVersion: 20.0.0\n",
        encoding="utf-8",
    )
    (dist / "RECORD").write_text(
        "pyarrow/__init__.py,,\n"
        "pyarrow.libs/arrow.dll,,\n"
        f"{dist.name}/METADATA,,\n"
        f"{dist.name}/RECORD,,\n",
        encoding="utf-8",
    )
    package = transaction.site_packages / "pyarrow"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    native = transaction.site_packages / "pyarrow.libs"
    native.mkdir()
    (native / "arrow.dll").write_bytes(b"dll")

    record = transaction.commit()
    manifest_path = record.root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("probe_modules", None)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    reloaded = manager.active(record.logical_id)

    assert reloaded is not None
    assert reloaded.probe_modules == ("pyarrow",)


def test_aborted_transaction_never_becomes_active(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    transaction = manager.begin(
        meta={"category": "asr", "item_id": "probe"},
        requested_specs=("example==1.0.0",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    staging = transaction.staging_root
    transaction.abort()

    assert staging is not None and not staging.exists()
    assert manager.active(transaction.logical_id) is None


def test_component_context_uses_active_environment_not_legacy_lib(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    transaction = manager.begin(
        meta={"category": "rag", "item_id": "local"},
        requested_specs=(),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    record = transaction.commit()

    context = manager.component_context(
        category="rag",
        item_id="local",
        ctx={"target_dir": str(tmp_path / "legacy")},
    )
    assert context["strict_target"] is True
    assert context["target_dir"] == str(record.site_packages)
    assert context["python_paths"][0] == str(record.site_packages)


def test_registry_contains_only_committed_revision(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    tx = manager.begin(
        meta={"category": "tts", "item_id": "edge"},
        requested_specs=(),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    record = tx.commit()
    registry = json.loads(manager.registry_path.read_text(encoding="utf-8"))

    assert registry["environments"][record.logical_id]["revision_id"] == record.revision_id


def test_dml_core_layer_substitutes_cpu_onnx_distribution_in_overlay(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "edge-dml"},
        requested_specs=("tts-with-rvc-onnx[dml]",),
        required_backend=BackendKind.ONNX,
        backend_context={"gpu_vendor": "INTEL", "device": "dml"},
    )
    assert transaction.ensure_core_layers(_factory(created), log=lambda _message: None)

    assert "onnxruntime" in transaction.core_package_names
    assert "onnxruntime-directml" in transaction.core_package_names
    assert any(spec.startswith("onnxruntime==") for spec in transaction.core_overrides)
    assert any(spec.startswith("onnxruntime-directml==") for spec in transaction.core_overrides)


def test_deactivate_can_retire_revision_without_mutating_or_deleting_it(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=(),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    marker = transaction.site_packages / "immutable.txt"
    marker.write_text("ready", encoding="utf-8")
    record = transaction.commit()

    assert manager.deactivate(record.logical_id, delete=False) is True
    assert manager.active(record.logical_id) is None
    assert record.root.is_dir()
    assert (record.site_packages / "immutable.txt").read_text(encoding="utf-8") == "ready"


def test_failed_replacement_keeps_previous_active_revision(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    first = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("demo==1",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    (first.site_packages / "version.txt").write_text("one", encoding="utf-8")
    active_before = first.commit()

    replacement = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("demo==2",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    (replacement.site_packages / "version.txt").write_text("two", encoding="utf-8")
    replacement.abort()

    active_after = manager.active(active_before.logical_id)
    assert active_after is not None
    assert active_after.revision_id == active_before.revision_id
    assert (active_after.site_packages / "version.txt").read_text(encoding="utf-8") == "one"


def test_committed_candidate_can_roll_back_to_previous_revision(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    first = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("demo==1",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    (first.site_packages / "version.txt").write_text("one", encoding="utf-8")
    previous = first.commit()

    replacement = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("demo==2",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    (replacement.site_packages / "version.txt").write_text("two", encoding="utf-8")
    candidate = replacement.commit()

    assert manager.active(previous.logical_id) == candidate
    replacement.rollback_commit()

    restored = manager.active(previous.logical_id)
    assert restored is not None
    assert restored.revision_id == previous.revision_id
    assert not candidate.root.exists()


def test_cuda_backend_profile_replaces_cpu_layer_for_all_active_environments(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []

    cpu_tx = manager.begin(
        meta={"category": "rag", "item_id": "local"},
        requested_specs=(),
        required_backend=BackendKind.CPU,
        backend_context={"gpu_vendor": "CPU"},
    )
    assert cpu_tx.ensure_core_layers(_factory(created), log=lambda _message: None)
    cpu_layer = cpu_tx.core_layers[0]
    cpu_record = cpu_tx.commit()

    cuda_tx = manager.begin(
        meta={"category": "backend", "item_id": "cuda"},
        requested_specs=(),
        required_backend=BackendKind.CUDA,
        backend_context={"gpu_vendor": "NVIDIA"},
    )
    assert cuda_tx.ensure_core_layers(_factory(created), log=lambda _message: None)
    cuda_layer = cuda_tx.core_layers[0]
    cuda_tx.commit()

    composition = manager.runtime_composition()
    assert cuda_layer.layer_id in composition.core_layer_ids
    assert cpu_layer.layer_id not in composition.core_layer_ids

    manager.promote_runtime_composition(composition)
    rebound = manager.active(cpu_record.logical_id)

    assert rebound is not None
    assert rebound.core_layer_ids == composition.core_layer_ids
    assert cuda_layer.root.exists()
    assert not cpu_layer.root.exists()



def test_new_backend_version_is_authoritative_during_candidate_validation(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []

    old_spec = CoreLayerSpec(
        group="torch-cpu",
        packages=("torch==2.7.1", "numpy==1.26.0"),
        capabilities=("torch.cpu", "torch.cpu@2.7.1"),
    )
    new_spec = CoreLayerSpec(
        group="torch-cpu",
        packages=("torch==2.7.2", "numpy==1.26.0"),
        capabilities=("torch.cpu", "torch.cpu@2.7.2"),
    )
    old_layer = manager.ensure_core_layer(
        old_spec,
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    new_layer = manager.ensure_core_layer(
        new_spec,
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    assert old_layer is not None and new_layer is not None

    old_tx = manager.begin(
        meta={"category": "rag", "item_id": "local"},
        requested_specs=(),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    old_tx.core_layers = [old_layer]
    old_record = old_tx.commit()

    candidate_tx = manager.begin(
        meta={"category": "tts", "item_id": "voice"},
        requested_specs=(),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    candidate_tx.core_layers = [new_layer]
    candidate_tx.commit()

    composition = manager.runtime_composition(
        preferred_core_layer_ids=(new_layer.layer_id,),
    )
    assert composition.core_layer_ids == (new_layer.layer_id,)
    assert str(new_layer.site_packages) in composition.paths
    assert str(old_layer.site_packages) not in composition.paths

    manager.promote_runtime_composition(composition)
    candidate_tx.finalize()

    rebound = manager.active(old_record.logical_id)
    assert rebound is not None
    assert rebound.core_layer_ids == (new_layer.layer_id,)
    assert new_layer.root.exists()
    assert not old_layer.root.exists()


def test_pip_installer_never_activates_ai_target_in_main_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sys

    from utils.pip_installer import PipInstaller

    main_core = (tmp_path / "Lib" / "core").resolve()
    ai_target = (tmp_path / "Lib" / "environment" / ".staging" / "candidate").resolve()
    monkeypatch.setenv("NEUROMITA_CORE_DIR", str(main_core))
    monkeypatch.setenv("NEUROMITA_LIB_DIR", str(main_core))

    previous_path = list(sys.path)
    try:
        PipInstaller(target_path=ai_target)
        assert str(ai_target) not in sys.path

        PipInstaller(target_path=main_core)
        assert str(main_core) in sys.path
    finally:
        sys.path[:] = previous_path


def test_strict_environment_check_does_not_fall_back_to_main_core(
    tmp_path: Path,
    monkeypatch,
) -> None:
    main_core = tmp_path / "Lib" / "core"
    staging = tmp_path / "Lib" / "environment" / ".staging" / "candidate"
    main_core.mkdir(parents=True)
    staging.mkdir(parents=True)
    _write_dist(main_core, "transformers", "4.45.2")
    monkeypatch.setenv("NEUROMITA_LIB_DIR", str(main_core))
    monkeypatch.setenv("NEUROMITA_CORE_DIR", str(main_core))

    assert not is_pip_spec_satisfied(
        "transformers>=4.45.2",
        ctx={
            "target_dir": str(staging),
            "python_paths": [str(staging)],
            "strict_target": True,
        },
    )


def test_rag_snapshot_download_uses_isolated_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sys

    from managers.rag.install_spec import _snapshot_download_action

    overlay = tmp_path / "Lib" / "environment" / "overlays" / "rag" / "site-packages"
    package = overlay / "huggingface_hub"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "from pathlib import Path\n"
        "def snapshot_download(repo_id, cache_dir, token=None):\n"
        "    marker = Path(cache_dir) / ('models--' + repo_id.replace('/', '--'))\n"
        "    marker.mkdir(parents=True, exist_ok=True)\n"
        "    (marker / 'downloaded.txt').write_text(token or 'no-token', encoding='utf-8')\n",
        encoding="utf-8",
    )
    checkpoints = tmp_path / "checkpoints"
    monkeypatch.setenv("NEUROMITA_CHECKPOINTS_DIR", str(checkpoints))

    class _Installer:
        script_path = sys.executable

        def __init__(self) -> None:
            self.active = None

        def _set_active_process(self, process, _killer) -> None:
            self.active = process

        def _clear_active_process(self, process) -> None:
            if self.active is process:
                self.active = None

        @staticmethod
        def _terminate_process(process, _reason="") -> None:
            process.kill()

    class _Callbacks:
        @staticmethod
        def log(_message: str) -> None:
            return None

    action = _snapshot_download_action(
        "owner/model",
        description="download",
        progress=50,
    )
    installer = _Installer()
    assert action.fn(
        pip_installer=installer,
        callbacks=_Callbacks(),
        ctx={
            "python_paths": [str(overlay)],
            "python_executable": sys.executable,
            "timeout_sec": 10.0,
        },
    )
    assert (
        checkpoints / "models--owner--model" / "downloaded.txt"
    ).read_text(encoding="utf-8") == "no-token"
    assert installer.active is None
    assert str(overlay) not in sys.path

def test_runtime_bootstrap_reserves_lib_core_for_main_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from startup.runtime_bootstrap import _configure_paths

    for name in (
        "NEUROMITA_RUNTIME_ROOT",
        "NEUROMITA_LIB_DIR",
        "NEUROMITA_CORE_DIR",
        "NEUROMITA_ENVIRONMENT_DIR",
    ):
        monkeypatch.delenv(name, raising=False)

    import sys

    previous_path = list(sys.path)
    try:
        configured = Path(_configure_paths(str(tmp_path))).resolve()
        assert configured == (tmp_path / "Lib" / "core").resolve()
        assert Path(os.environ["NEUROMITA_RUNTIME_ROOT"]).resolve() == (
            tmp_path / "Lib"
        ).resolve()
        assert Path(os.environ["NEUROMITA_ENVIRONMENT_DIR"]).resolve() == (
            tmp_path / "Lib" / "environment"
        ).resolve()
        assert Path(sys.path[0]).resolve() == configured
    finally:
        sys.path[:] = previous_path


def test_runtime_bootstrap_migrates_only_legacy_ai_layout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from startup.runtime_bootstrap import _configure_paths

    runtime = tmp_path / "Lib"
    legacy_main = runtime / "example_main_package"
    legacy_main.mkdir(parents=True)
    (legacy_main / "__init__.py").write_text("", encoding="utf-8")

    legacy_base = runtime / "core" / "torch-cpu-old"
    (legacy_base / "site-packages").mkdir(parents=True)
    (legacy_base / "manifest.json").write_text("{}", encoding="utf-8")

    legacy_overlay = runtime / "environment" / "tts-edge" / "revision-a"
    (legacy_overlay / "site-packages").mkdir(parents=True)
    (legacy_overlay / "manifest.json").write_text("{}", encoding="utf-8")

    for name in (
        "NEUROMITA_RUNTIME_ROOT",
        "NEUROMITA_LIB_DIR",
        "NEUROMITA_CORE_DIR",
        "NEUROMITA_ENVIRONMENT_DIR",
    ):
        monkeypatch.delenv(name, raising=False)

    import sys

    previous_path = list(sys.path)
    try:
        _configure_paths(str(tmp_path))
    finally:
        sys.path[:] = previous_path

    assert (runtime / "example_main_package" / "__init__.py").is_file()
    assert not (runtime / "core" / "example_main_package").exists()
    assert (
        runtime / "environment" / "bases" / "torch-cpu-old" / "manifest.json"
    ).is_file()
    assert (
        runtime
        / "environment"
        / "overlays"
        / "tts-edge"
        / "revision-a"
        / "manifest.json"
    ).is_file()


def test_main_dependency_is_managed_but_excluded_from_ai_composition(tmp_path: Path) -> None:
    from core.backends import BackendKind
    from core.runtime_environments import RuntimeEnvironmentManager

    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    assert manager.should_manage({"category": "dependency", "item_id": "opencv"}) is True
    assert manager.should_manage({"category": "dependency", "item_id": "ffmpeg"}) is False

    transaction = manager.begin(
        meta={"category": "dependency", "item_id": "opencv"},
        requested_specs=("opencv-python",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    assert transaction.site_packages is not None
    package = transaction.site_packages / "cv2"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    dist_info = transaction.site_packages / "opencv_python-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Name: opencv-python\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (dist_info / "top_level.txt").write_text("cv2\n", encoding="utf-8")
    (dist_info / "RECORD").write_text("", encoding="utf-8")
    record = transaction.commit({"category": "dependency", "item_id": "opencv"})
    transaction.finalize()

    assert manager.main_runtime_paths() == (str(record.site_packages),)
    composition = manager.runtime_composition()
    assert record not in composition.records
    assert str(record.site_packages) not in composition.paths
