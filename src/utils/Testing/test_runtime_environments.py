from __future__ import annotations

import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from core.backends import BackendKind
from core.runtime_environments import RuntimeEnvironmentManager


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
            module = self.target / name.replace("-", "_")
            module.mkdir(exist_ok=True)
            (module / "__init__.py").write_text("", encoding="utf-8")
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

    assert manager.core_root == (tmp_path / "Lib" / "core").resolve()
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
    # Transitive packages are not globally owned by the core layer and may be
    # overridden by an overlay compatibility profile.
    assert list(transaction.site_packages.glob("sympy-*.dist-info"))

    record = transaction.commit({"source": "test"})
    assert manager.active(transaction.logical_id) == record
    assert record.site_packages.is_dir()
    assert not transaction.staging_root.exists()
    assert manager.runtime_paths(record)[0] == str(record.site_packages)


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
