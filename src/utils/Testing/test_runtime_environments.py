from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from core.backends import BackendKind
from core.backends.installable_component import BackendInstallableComponent
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


def test_missing_registry_uses_defaults_without_warning(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")

    with patch("core.runtime_environments.logger.warning") as warning:
        registry = manager._load_registry()

    assert registry == manager._default_registry()
    warning.assert_not_called()


def test_environment_ids_preserve_plus_as_a_distinct_component_key(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    ids = [
        manager.logical_id_from_meta({"category": "tts", "item_id": item_id})[0]
        for item_id in ("medium", "medium+", "medium+low")
    ]

    assert ids == ["tts-medium", "tts-medium-plus", "tts-medium-plus-low"]


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
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "edge"},
        requested_specs=("tts-with-rvc",),
        required_backend=BackendKind.CUDA,
        backend_context={"gpu_vendor": "NVIDIA"},
    )
    transaction.core_layers = [cuda_layer]
    assert transaction.core_resolver_args == (
        "--extra-index-url",
        "https://download.pytorch.org/whl/cu128",
        "--index-strategy",
        "unsafe-best-match",
    )
    transaction.abort()

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


def test_backend_card_uses_the_shared_cuda_core_layer(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    spec = manager.core_layer_specs(BackendKind.CUDA, {"gpu_vendor": "NVIDIA"})[0]
    layer = manager.ensure_core_layer(spec, installer_factory=_factory(created), log=lambda _message: None)
    assert layer is not None
    cuda_library = layer.site_packages / "torch" / "lib" / "cudart64_12.dll"
    cuda_library.parent.mkdir(parents=True)
    cuda_library.write_bytes(b"cuda")

    with patch("core.runtime_environments.runtime_environments", return_value=manager):
        status = BackendInstallableComponent(BackendKind.CUDA).status({"gpu_vendor": "NVIDIA"})

    assert status.installed is True
    assert status.ready is True


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
    assert manager.runtime_paths(record) == (
        str(transaction.core_layers[0].site_packages),
        str(record.site_packages),
    )


def test_environment_commit_rejects_backend_distributions_inside_overlay(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    transaction = manager.begin(
        meta={"category": "asr", "item_id": "broken"},
        requested_specs=("silero-vad",),
        required_backend=BackendKind.CPU,
        backend_context={"gpu_vendor": "CPU"},
    )
    assert transaction.ensure_core_layers(
        _factory(created),
        log=lambda _message: None,
    )
    _write_dist(transaction.site_packages, "silero-vad", "6.0.0")
    _write_dist(transaction.site_packages, "torch", "2.7.1")

    with pytest.raises(RuntimeError, match="backend-owned distributions: torch"):
        transaction.commit()


def test_shared_core_precedes_overlays_in_runtime_and_validation_paths(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    transaction = manager.begin(
        meta={"category": "asr", "item_id": "google"},
        requested_specs=("silero-vad",),
        required_backend=BackendKind.CPU,
        backend_context={"gpu_vendor": "NVIDIA"},
    )
    assert transaction.ensure_core_layers(
        _factory(created),
        log=lambda _message: None,
    )
    _write_dist(transaction.site_packages, "silero-vad", "6.0.0")

    layer = transaction.core_layers[0]
    assert transaction.validation_paths == (
        str(layer.site_packages),
        str(transaction.site_packages),
    )

    record = transaction.commit()
    composition = manager.runtime_composition(
        selection={"asr": record.logical_id},
    )
    assert composition.paths == (
        str(layer.site_packages),
        str(record.site_packages),
    )


def test_overlay_packages_do_not_override_explicit_backend_contract(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    cuda_spec = manager.core_layer_specs(
        BackendKind.CUDA,
        {"gpu_vendor": "NVIDIA"},
    )[0]
    cuda_layer = manager.ensure_core_layer(
        cuda_spec,
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    assert cuda_layer is not None
    manager.promote_backend_profile((cuda_layer.layer_id,))

    transaction = manager.begin(
        meta={"category": "asr", "item_id": "cuda-with-onnxruntime"},
        requested_specs=("silero-vad", "onnxruntime"),
        required_backend=BackendKind.CUDA,
        backend_context={"gpu_vendor": "NVIDIA"},
    )
    assert transaction.ensure_core_layers(
        _factory(created),
        log=lambda _message: None,
    )
    _write_dist(transaction.site_packages, "silero-vad", "6.0.0")
    _write_dist(transaction.site_packages, "onnxruntime", "1.22.0")
    record = transaction.commit()

    composition = manager.runtime_composition(
        selection={"asr": record.logical_id},
    )
    assert record.packages["onnxruntime"] == "1.22.0"
    assert "onnxruntime" in record.probe_modules
    assert composition.core_layer_ids == (cuda_layer.layer_id,)
    assert composition.paths == (
        str(cuda_layer.site_packages),
        str(record.site_packages),
    )


def test_runtime_composition_bootstrap_probes_only_backend_imports(
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
    assert manager.runtime_composition().records == ()
    composition = manager.runtime_composition(
        selection={"tts": record.logical_id},
    )

    assert record.probe_modules == ("fish_speech_lib",)
    assert "fish_speech_lib" not in composition.probe_modules
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

    assert manager.remove_installed(record.logical_id, delete=False) is True
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


def test_rollback_preserves_a_concurrently_registered_environment(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    candidate = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("demo==1",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    candidate_record = candidate.commit()

    concurrent = manager.begin(
        meta={"category": "tts", "item_id": "voice-b"},
        requested_specs=("demo==1",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    concurrent_record = concurrent.commit()

    candidate.rollback_commit()

    assert manager.active(candidate_record.logical_id) is None
    assert manager.active(concurrent_record.logical_id) is not None


def test_recovers_ready_unregistered_overlay_without_accepting_retired_one(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "fish"},
        requested_specs=("fish-speech-lib==1.0.0",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    _write_dist(transaction.site_packages, "fish-speech-lib", "1.0.0")
    record = transaction.commit()

    assert manager.remove_installed(record.logical_id, delete=False) is True
    assert manager.recover_unregistered_overlays() == ()

    (record.root / ".retired").unlink()
    recovered = manager.recover_unregistered_overlays()

    assert recovered == (record,)
    assert manager.active(record.logical_id) is not None


def test_migrates_legacy_overlay_that_collapsed_plus_into_medium(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "medium+"},
        requested_specs=(),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    record = transaction.commit()
    legacy_id = "tts-medium"
    legacy_root = manager.overlay_root / legacy_id
    legacy_root.mkdir()
    os.replace(record.root, legacy_root / record.revision_id)

    registry = json.loads(manager.registry_path.read_text(encoding="utf-8"))
    entry = registry["environments"].pop(record.logical_id)
    registry["environments"][legacy_id] = entry
    manager.registry_path.write_text(json.dumps(registry), encoding="utf-8")

    assert manager.migrate_legacy_environment_ids() == (record.logical_id,)
    assert manager.active(record.logical_id) is not None
    assert (manager.overlay_root / record.logical_id / record.revision_id).is_dir()


def test_backend_profile_is_global_without_rewriting_installed_overlays(
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
    manager.promote_backend_profile((cpu_layer.layer_id,))

    cuda_tx = manager.begin(
        meta={"category": "backend", "item_id": "cuda"},
        requested_specs=(),
        required_backend=BackendKind.CUDA,
        backend_context={"gpu_vendor": "NVIDIA"},
    )
    assert cuda_tx.ensure_core_layers(_factory(created), log=lambda _message: None)
    cuda_layer = cuda_tx.core_layers[0]
    cuda_tx.commit()
    manager.promote_backend_profile((cuda_layer.layer_id,))

    selection = {"rag": cpu_record.logical_id}
    composition = manager.runtime_composition(selection=selection)
    assert cuda_layer.layer_id in composition.core_layer_ids
    assert cpu_layer.layer_id not in composition.core_layer_ids

    manager.promote_runtime_selection(selection, composition)
    installed = manager.active(cpu_record.logical_id)

    assert installed is not None
    assert installed.core_layer_ids == (cpu_layer.layer_id,)
    assert cuda_layer.root.exists()
    assert not cpu_layer.root.exists()



def test_selected_overlays_are_tried_against_one_global_backend_revision(
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
    candidate_record = candidate_tx.commit()
    manager.promote_backend_profile((new_layer.layer_id,))

    composition = manager.runtime_composition(
        selection={"tts": candidate_record.logical_id},
    )
    assert composition.core_layer_ids == (new_layer.layer_id,)
    assert str(new_layer.site_packages) in composition.paths
    assert str(old_layer.site_packages) not in composition.paths

    combined = manager.runtime_composition(
        selection={
            "tts": candidate_record.logical_id,
            "rag": old_record.logical_id,
        },
    )
    assert combined.core_layer_ids == (new_layer.layer_id,)
    assert str(candidate_record.site_packages) in combined.paths
    assert str(old_record.site_packages) in combined.paths
    assert str(old_layer.site_packages) not in combined.paths


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


def test_rag_snapshot_download_splits_oversized_process_timeout(monkeypatch) -> None:
    from managers.rag import install_spec

    process = MagicMock()
    process.returncode = 0
    process.communicate.side_effect = [
        subprocess.TimeoutExpired("snapshot_download", install_spec._SUBPROCESS_WAIT_SLICE_SEC),
        ("download complete\n", None),
    ]
    monkeypatch.setattr(install_spec.subprocess, "Popen", lambda *_args, **_kwargs: process)

    action = install_spec._snapshot_download_action(
        "owner/model",
        description="download",
        progress=50,
    )

    assert action.fn(ctx={"timeout_sec": 7_200_000.0})
    assert process.communicate.call_args_list[0].kwargs["timeout"] == install_spec._SUBPROCESS_WAIT_SLICE_SEC


def test_rag_snapshot_download_cleans_active_process_after_overall_timeout(monkeypatch) -> None:
    from managers.rag import install_spec

    process = MagicMock()
    process.returncode = None
    process.communicate.side_effect = [
        subprocess.TimeoutExpired("snapshot_download", 1.0),
        ("partial output\n", None),
    ]

    class _Installer:
        script_path = sys.executable

        def __init__(self) -> None:
            self.active = None

        def _set_active_process(self, active, _killer) -> None:
            self.active = active

        def _clear_active_process(self, active) -> None:
            if self.active is active:
                self.active = None

        @staticmethod
        def _terminate_process(active, _reason="") -> None:
            active.kill()

    installer = _Installer()
    monkeypatch.setattr(
        install_spec.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monotonic_values = iter((100.0, 100.5, 101.0))
    monkeypatch.setattr(install_spec.time, "monotonic", lambda: next(monotonic_values))

    action = install_spec._snapshot_download_action(
        "owner/model",
        description="download",
        progress=50,
    )

    assert not action.fn(pip_installer=installer, ctx={"timeout_sec": 1.0})
    assert installer.active is None
    process.kill.assert_called_once()
    assert process.communicate.call_args_list[1].kwargs == {}

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


def test_selected_overlays_are_composed_even_when_metadata_versions_differ(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")

    tts = manager.begin(
        meta={"category": "tts", "item_id": "voice"},
        requested_specs=("shared-demo==1.0",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    _write_dist(tts.site_packages, "shared-demo", "1.0")
    tts_record = tts.commit()

    asr = manager.begin(
        meta={"category": "asr", "item_id": "speech"},
        requested_specs=("shared-demo==2.0",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    _write_dist(asr.site_packages, "shared-demo", "2.0")
    asr_record = asr.commit()

    composition = manager.runtime_composition(
        selection={
            "tts": tts_record.logical_id,
            "asr": asr_record.logical_id,
        }
    )

    assert composition.records == (tts_record, asr_record)
    assert composition.paths[:2] == (
        str(tts_record.site_packages),
        str(asr_record.site_packages),
    )


def test_selected_overlay_keeps_previous_revision_until_runtime_switch(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []

    first_tx = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("voice-runtime==1.0.0",),
        required_backend=BackendKind.CPU,
        backend_context={"gpu_vendor": "CPU"},
    )
    assert first_tx.ensure_core_layers(_factory(created), log=lambda _message: None)
    _write_dist(first_tx.site_packages, "voice-runtime", "1.0.0")
    first = first_tx.commit()
    first_selection = manager.selection_with("tts", first)
    first_composition = manager.runtime_composition(selection=first_selection)
    manager.promote_runtime_selection(
        first_selection,
        first_composition,
        cleanup=False,
    )
    first_tx.finalize()

    second_tx = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("voice-runtime==2.0.0",),
        required_backend=BackendKind.CPU,
        backend_context={"gpu_vendor": "CPU"},
    )
    assert second_tx.ensure_core_layers(_factory(created), log=lambda _message: None)
    _write_dist(second_tx.site_packages, "voice-runtime", "2.0.0")
    second = second_tx.commit()
    second_tx.finalize()

    assert first.logical_id == second.logical_id
    assert first.revision_id != second.revision_id
    assert first.root.is_dir()
    assert second.root.is_dir()

    running_composition = manager.runtime_composition()
    assert running_composition.records == (first,)
    manager.cleanup_superseded_revisions(second.logical_id)
    assert first.root.is_dir()
    assert second.root.is_dir()

    second_selection = manager.selection_with("tts", second)
    second_composition = manager.runtime_composition(selection=second_selection)
    assert second_composition.records == (second,)
    manager.promote_runtime_selection(
        second_selection,
        second_composition,
        cleanup=False,
    )
    manager.cleanup_superseded_revisions(second.logical_id)

    assert not first.root.exists()
    assert second.root.is_dir()


def test_runtime_selection_supports_multiple_overlays_for_one_service(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")

    embeddings_tx = manager.begin(
        meta={"category": "rag", "item_id": "embeddings"},
        requested_specs=("transformers==4.45.2",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    _write_dist(embeddings_tx.site_packages, "transformers", "4.45.2")
    embeddings = embeddings_tx.commit()
    embeddings_tx.finalize()

    reranker_tx = manager.begin(
        meta={"category": "rag", "item_id": "reranker"},
        requested_specs=("sentencepiece==0.2.0",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    _write_dist(reranker_tx.site_packages, "sentencepiece", "0.2.0")
    reranker = reranker_tx.commit()
    reranker_tx.finalize()

    selection = {
        "rag:embeddings": embeddings.logical_id,
        "rag:reranker": reranker.logical_id,
    }
    composition = manager.runtime_composition(selection=selection)

    assert composition.records == (embeddings, reranker)
    assert composition.paths[:2] == (
        str(embeddings.site_packages),
        str(reranker.site_packages),
    )


def test_startup_cleanup_removes_unregistered_overlay_revisions(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")

    first_tx = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("voice-runtime==1.0.0",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    _write_dist(first_tx.site_packages, "voice-runtime", "1.0.0")
    first = first_tx.commit()

    second_tx = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("voice-runtime==2.0.0",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    _write_dist(second_tx.site_packages, "voice-runtime", "2.0.0")
    second = second_tx.commit()

    assert first.root.is_dir()
    assert second.root.is_dir()
    manager.cleanup_inactive_overlays()

    assert not first.root.exists()
    assert second.root.is_dir()


def test_core_cleanup_preserves_legacy_layers_until_profile_is_migrated(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=(),
        required_backend=BackendKind.CPU,
        backend_context={"gpu_vendor": "CPU"},
    )
    assert transaction.ensure_core_layers(_factory(created), log=lambda _message: None)
    layer = transaction.core_layers[0]
    transaction.commit()

    registry = manager.registry_snapshot()
    registry["backend_profile"] = {"core_layer_ids": []}
    manager.restore_registry(registry)
    manager.cleanup_unreferenced_core_layers()

    assert layer.root.is_dir()


def test_model_activation_can_replace_incompatible_preferred_backend(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []

    cpu_spec = CoreLayerSpec(
        group="torch-cpu",
        packages=("torch==2.7.1", "numpy==1.26.0"),
        capabilities=("torch.cpu", "torch.cpu@2.7.1"),
    )
    cuda_spec = CoreLayerSpec(
        group="torch-cu128",
        packages=("torch==2.7.1+cu128", "numpy==1.26.0"),
        capabilities=("torch.cpu", "torch.cuda", "torch.cuda@2.7.1+cu128"),
    )
    cpu_layer = manager.ensure_core_layer(
        cpu_spec,
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    cuda_layer = manager.ensure_core_layer(
        cuda_spec,
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    assert cpu_layer is not None and cuda_layer is not None
    manager.promote_backend_profile((cpu_layer.layer_id,))

    transaction = manager.begin(
        meta={"category": "tts", "item_id": "cuda-voice"},
        requested_specs=(),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    transaction.core_layers = [cuda_layer]
    record = transaction.commit()

    selection = manager.selection_with("tts", record)
    composition = manager.runtime_composition(selection=selection)

    assert composition.core_layer_ids == (cuda_layer.layer_id,)
    assert str(cuda_layer.site_packages) in composition.paths
    assert str(cpu_layer.site_packages) not in composition.paths


def test_cleanup_keeps_unpromoted_backend_candidate_for_installed_overlay(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []

    cpu_spec = CoreLayerSpec(
        group="torch-cpu",
        packages=("torch==2.7.1", "numpy==1.26.0"),
        capabilities=("torch.cpu", "torch.cpu@2.7.1"),
    )
    cuda_spec = CoreLayerSpec(
        group="torch-cu128",
        packages=("torch==2.7.1+cu128", "numpy==1.26.0"),
        capabilities=("torch.cpu", "torch.cuda", "torch.cuda@2.7.1+cu128"),
    )
    cpu_layer = manager.ensure_core_layer(
        cpu_spec,
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    cuda_layer = manager.ensure_core_layer(
        cuda_spec,
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    assert cpu_layer is not None and cuda_layer is not None
    manager.promote_backend_profile((cpu_layer.layer_id,))

    transaction = manager.begin(
        meta={"category": "tts", "item_id": "cuda-voice"},
        requested_specs=(),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    transaction.core_layers = [cuda_layer]
    transaction.commit()

    manager.cleanup_unreferenced_core_layers()

    assert cpu_layer.root.is_dir()
    assert cuda_layer.root.is_dir()


def test_component_context_uses_compatible_profile_after_original_layer_cleanup(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []

    cpu_spec = CoreLayerSpec(
        group="torch-cpu",
        packages=("torch==2.7.1", "numpy==1.26.0"),
        capabilities=("torch.cpu", "torch.cpu@2.7.1"),
    )
    cuda_spec = CoreLayerSpec(
        group="torch-cu128",
        packages=("torch==2.7.1+cu128", "numpy==1.26.0"),
        capabilities=("torch.cpu", "torch.cpu@2.7.1", "torch.cuda"),
    )
    cpu_layer = manager.ensure_core_layer(
        cpu_spec,
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    cuda_layer = manager.ensure_core_layer(
        cuda_spec,
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    assert cpu_layer is not None and cuda_layer is not None

    transaction = manager.begin(
        meta={"category": "rag", "item_id": "embeddings"},
        requested_specs=(),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    transaction.core_layers = [cpu_layer]
    record = transaction.commit()
    manager.promote_backend_profile((cuda_layer.layer_id,))
    manager.cleanup_unreferenced_core_layers()

    assert not cpu_layer.root.exists()
    context = manager.component_context(category="rag", item_id="embeddings")
    assert context["python_paths"] == [
        str(cuda_layer.site_packages),
        str(record.site_packages),
    ]


def test_startup_cleanup_preserves_selected_revision_after_reinstall(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")

    first_tx = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("voice-runtime==1.0.0",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    _write_dist(first_tx.site_packages, "voice-runtime", "1.0.0")
    first = first_tx.commit()
    first_selection = manager.selection_with("tts", first)
    manager.promote_runtime_selection(
        first_selection,
        manager.runtime_composition(selection=first_selection),
        cleanup=False,
    )

    second_tx = manager.begin(
        meta={"category": "tts", "item_id": "voice-a"},
        requested_specs=("voice-runtime==2.0.0",),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    _write_dist(second_tx.site_packages, "voice-runtime", "2.0.0")
    second = second_tx.commit()
    second_tx.finalize()

    manager.cleanup_inactive_overlays()

    assert first.root.is_dir()
    assert second.root.is_dir()
    assert manager.runtime_composition().records == (first,)


def test_explicit_backend_candidate_is_used_on_next_runtime_activation(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    cpu = manager.ensure_core_layer(
        CoreLayerSpec(
            group="torch-cpu",
            packages=("torch==2.7.1",),
            capabilities=("torch.cpu",),
        ),
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    cuda = manager.ensure_core_layer(
        CoreLayerSpec(
            group="torch-cu128",
            packages=("torch==2.7.1+cu128",),
            capabilities=("torch.cpu", "torch.cuda"),
        ),
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    assert cpu is not None and cuda is not None
    manager.promote_backend_profile((cpu.layer_id,))
    manager.register_backend_candidates((cuda.layer_id,))

    transaction = manager.begin(
        meta={"category": "tts", "item_id": "cpu-compatible"},
        requested_specs=(),
        required_backend=BackendKind.NONE,
        backend_context={},
    )
    transaction.core_layers = [cpu]
    record = transaction.commit()
    selection = manager.selection_with("tts", record)
    composition = manager.runtime_composition(selection=selection)

    assert composition.core_layer_ids == (cuda.layer_id,)

    manager.promote_runtime_selection(selection, composition, cleanup=False)
    registry = manager.registry_snapshot()
    assert registry["backend_profile"]["core_layer_ids"] == [cuda.layer_id]
    assert registry["backend_candidates"]["core_layer_ids"] == []


def test_core_cleanup_keeps_pending_backend_candidate_until_activation(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    cpu = manager.ensure_core_layer(
        CoreLayerSpec(
            group="torch-cpu",
            packages=("torch==2.7.1",),
            capabilities=("torch.cpu",),
        ),
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    cuda = manager.ensure_core_layer(
        CoreLayerSpec(
            group="torch-cu128",
            packages=("torch==2.7.1+cu128",),
            capabilities=("torch.cpu", "torch.cuda"),
        ),
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    assert cpu is not None and cuda is not None
    manager.promote_backend_profile((cpu.layer_id,))
    manager.register_backend_candidates((cuda.layer_id,))

    manager.cleanup_unreferenced_core_layers()

    assert cpu.root.is_dir()
    assert cuda.root.is_dir()


def test_backend_candidates_keep_torch_cuda_and_onnx_side_by_side(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    cuda = manager.ensure_core_layer(
        CoreLayerSpec(
            group="torch-cu128",
            packages=("torch==2.7.1+cu128",),
            capabilities=("torch.cpu", "torch.cuda"),
        ),
        installer_factory=_factory(created),
        log=lambda _message: None,
    )
    onnx = manager.ensure_core_layer(
        CoreLayerSpec(
            group="onnx-cpu",
            packages=("onnxruntime==1.22.0",),
            capabilities=("onnx.cpu",),
        ),
        installer_factory=_factory(created),
        log=lambda _message: None,
    )

    assert cuda is not None and onnx is not None
    manager.register_backend_candidates((cuda.layer_id, onnx.layer_id))
    manager.cleanup_unreferenced_core_layers()

    candidates = set(
        manager.registry_snapshot()["backend_candidates"]["core_layer_ids"]
    )
    assert candidates == {cuda.layer_id, onnx.layer_id}
    assert cuda.root.is_dir()
    assert onnx.root.is_dir()


def test_onnx_runtime_pins_numpy_and_keeps_torch_first_in_shared_paths(
    tmp_path: Path,
) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    specs = manager.core_layer_specs(
        BackendKind.ONNX,
        {"gpu_vendor": "NVIDIA"},
    )

    assert len(specs) == 2
    assert specs[0].group == "torch-cu128"
    assert specs[1].group == "onnx-dml"
    assert "onnx.dml" in specs[1].capabilities
    assert any(package.startswith("onnxruntime-directml==") for package in specs[1].packages)
    assert "numpy==1.26.0" in specs[1].packages

    created: list[_FakeInstaller] = []
    transaction = manager.begin(
        meta={"category": "tts", "item_id": "edge-onnx"},
        requested_specs=("tts-with-rvc-onnx",),
        required_backend=BackendKind.ONNX,
        backend_context={"gpu_vendor": "NVIDIA"},
    )
    assert transaction.ensure_core_layers(
        _factory(created),
        log=lambda _message: None,
    )
    _write_dist(transaction.site_packages, "tts-with-rvc-onnx", "1.0.0")
    record = transaction.commit()
    composition = manager.runtime_composition(
        selection={"tts": record.logical_id},
    )

    torch, onnx = transaction.core_layers
    assert onnx.packages["numpy"] == "1.26.0"
    assert onnx.owned_packages["numpy"] == "1.26.0"
    assert composition.paths[:2] == (
        str(torch.site_packages),
        str(onnx.site_packages),
    )


def test_materialized_backend_layer_is_registered_before_gc(tmp_path: Path) -> None:
    manager = RuntimeEnvironmentManager(tmp_path / "Lib")
    created: list[_FakeInstaller] = []
    layer = manager.ensure_core_layer(
        CoreLayerSpec(
            group="torch-cu128",
            packages=("torch==2.7.1+cu128",),
            capabilities=("torch.cpu", "torch.cuda"),
        ),
        installer_factory=_factory(created),
        log=lambda _message: None,
    )

    assert layer is not None
    registry = manager.registry_snapshot()
    assert layer.layer_id in registry["backend_candidates"]["core_layer_ids"]

    manager.cleanup_unreferenced_core_layers()

    assert layer.root.is_dir()
