from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
        elif isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
    return result


class AIContourBoundaryTests(unittest.TestCase):
    def test_domain_workers_do_not_import_other_ai_domains(self) -> None:
        roots = {
            "asr": (
                (SRC / "handlers" / "asr_models", SRC / "handlers" / "ai_engine" / "services" / "asr_service.py"),
                ("handlers.voice_models", "managers.rag"),
            ),
            "tts": (
                (SRC / "handlers" / "voice_models", SRC / "handlers" / "ai_engine" / "services" / "tts_service.py"),
                ("handlers.asr_models", "managers.rag"),
            ),
            "rag": (
                (SRC / "managers" / "rag", SRC / "handlers" / "ai_engine" / "services" / "rag_service.py"),
                ("handlers.asr_models", "handlers.voice_models"),
            ),
        }
        violations: list[str] = []
        for domain, (targets, forbidden) in roots.items():
            files: list[Path] = []
            for target in targets:
                files.extend(target.rglob("*.py") if target.is_dir() else (target,))
            for path in files:
                for module in _imports(path):
                    if any(module == root or module.startswith(root + ".") for root in forbidden):
                        violations.append(f"{domain}: {path.relative_to(SRC)} -> {module}")
        self.assertEqual([], violations, "Cross-domain imports:\n" + "\n".join(violations))

    def test_gui_controllers_do_not_compute_installable_status(self) -> None:
        forbidden_calls = {"get_install_status", "check_requirements", "check_model_installed"}
        violations: list[str] = []
        for path in (SRC / "controllers" / "gui").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                else:
                    name = ""
                if name in forbidden_calls:
                    violations.append(f"{path.relative_to(SRC)}:{node.lineno}: {name}")
        self.assertEqual([], violations, "GUI computes installable state:\n" + "\n".join(violations))

    def test_auto_topology_is_shared(self) -> None:
        from controllers.ai_engine_controller import AIEngineController

        controller = AIEngineController.__new__(AIEngineController)
        with patch.dict(os.environ, {"NEUROMITA_AI_ENGINE_MODE": "auto"}, clear=False):
            self.assertEqual(controller._resolve_mode(), "shared")

    def test_split_composition_contains_only_its_domain_records(self) -> None:
        from controllers.ai_engine_controller import AIEngineController

        records = tuple(
            SimpleNamespace(category=category, logical_id=f"{category}:runtime")
            for category in ("tts", "asr", "rag", "beats")
        )

        class EnvironmentRegistry:
            def selected_records(self, *, selection=None):
                return records

            def runtime_composition(self, *, records):
                return SimpleNamespace(
                    paths=tuple(record.logical_id for record in records),
                    probe_modules=(),
                )

        controller = AIEngineController.__new__(AIEngineController)
        controller._environments = EnvironmentRegistry()

        for service in ("tts", "asr", "rag", "beats"):
            composition = controller._composition_for_service(service)
            self.assertEqual((f"{service}:runtime",), composition.paths)


if __name__ == "__main__":
    unittest.main()
