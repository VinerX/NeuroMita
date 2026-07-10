from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "run.py"


def _load_launcher():
    name = f"neuromita_run_test_{id(object())}"
    spec = importlib.util.spec_from_file_location(name, LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_is_bound_to_the_interpreter_that_started_it() -> None:
    launcher = _load_launcher()
    assert launcher.PYTHON == Path(sys.executable)


def test_launcher_uv_is_isolated_from_embedded_python_scripts() -> None:
    launcher = _load_launcher()
    assert launcher.UV_TARGET == launcher.ROOT / ".bootstrap" / "uv"
    assert launcher.UV_EXE.parent == launcher.UV_TARGET / "bin"
    assert launcher.UV_EXE.parent != launcher.PYTHON.parent / "Scripts"


def test_uv_requirements_install_targets_embedded_python_explicitly(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example-package\n", encoding="utf-8")
    python = tmp_path / "embedded" / "python.exe"
    target = python.parent / "Lib" / "site-packages"
    uv = tmp_path / ".bootstrap" / "uv" / "bin" / "uv.exe"
    commands: list[list[str]] = []

    monkeypatch.setattr(launcher, "PYTHON", python)
    monkeypatch.setattr(launcher, "PYTHON_SITE_PACKAGES", target)
    monkeypatch.setattr(launcher, "REQ_FILE", requirements)
    monkeypatch.setattr(launcher, "UV_EXE", uv)
    monkeypatch.setattr(launcher, "ensure_uv", lambda: True)
    monkeypatch.setattr(launcher, "run", lambda cmd, **_kwargs: commands.append(list(cmd)) or 0)

    assert launcher.install_requirements() is True
    command = commands[0]
    assert command[:3] == [str(uv), "pip", "install"]
    assert command[command.index("--python") + 1] == str(python)
    assert command[command.index("--target") + 1] == str(target)


def test_pip_fallback_targets_embedded_site_packages(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example-package\n", encoding="utf-8")
    python = tmp_path / "embedded" / "python.exe"
    target = python.parent / "Lib" / "site-packages"
    commands: list[list[str]] = []

    monkeypatch.setattr(launcher, "PYTHON", python)
    monkeypatch.setattr(launcher, "PYTHON_SITE_PACKAGES", target)
    monkeypatch.setattr(launcher, "REQ_FILE", requirements)
    monkeypatch.setattr(launcher, "ensure_uv", lambda: False)
    monkeypatch.setattr(launcher, "ensure_pip", lambda: None)
    monkeypatch.setattr(launcher, "run", lambda cmd, **_kwargs: commands.append(list(cmd)) or 0)

    assert launcher.install_requirements() is True
    command = commands[0]
    assert command[:5] == [str(python), "-m", "pip", "--isolated", "install"]
    assert command[command.index("--target") + 1] == str(target)


def test_uv_bootstrap_installs_only_into_private_target(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher()
    target = tmp_path / ".bootstrap" / "uv"
    executable = target / "bin" / "uv.exe"
    commands: list[list[str]] = []

    monkeypatch.setattr(launcher, "UV_TARGET", target)
    monkeypatch.setattr(launcher, "UV_EXE", executable)
    monkeypatch.setattr(launcher, "PYTHON", tmp_path / "embedded" / "python.exe")
    monkeypatch.setattr(launcher, "ensure_pip", lambda: None)
    monkeypatch.setattr(launcher, "run_quiet", lambda cmd, **_kwargs: executable.is_file())

    def fake_run(cmd, **_kwargs):
        commands.append(list(cmd))
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(b"")
        return 0

    monkeypatch.setattr(launcher, "run", fake_run)

    assert launcher.ensure_uv() is True
    command = commands[0]
    assert command[command.index("--target") + 1] == str(target)
    assert str(launcher.PYTHON.parent / "Scripts") not in " ".join(command)
