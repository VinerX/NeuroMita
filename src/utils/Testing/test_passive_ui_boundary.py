from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


_SRC_ROOT = Path(__file__).resolve().parents[2]
_UI_ROOT = _SRC_ROOT / "ui"
_COMPOSITION_EXEMPTIONS: set[Path] = set()
_FORBIDDEN_ROOTS = {
    "controllers",
    "managers",
    "handlers",
    "services",
    "game_connections",
    "updater",
}
_FORBIDDEN_MODULES = {
    "core.events",
    "core.services",
    "core.task_supervisor",
    "utils.pip_installer",
    "utils.archive_utils",
    "controllers.gui.composition_root",
    "controllers.gui.app_shell_controller",
    "controllers.gui.window_composition_controller",
    "controllers.gui.main_window_coordinator",
    "controllers.gui.presentation_hub",
}
_REMOVED_UI_INFRASTRUCTURE = {
    Path("async_bus.py"),
    Path("task_worker.py"),
    Path("pages/news_support.py"),
    Path("settings/updates_settings.py"),
    Path("settings/data_prefetch.py"),
    Path("settings/provider_options.py"),
    Path("settings/rag_memory_settings.py"),
    Path("settings/character_settings/logic.py"),
    Path("settings/microphone_settings/logic.py"),
    Path("settings/voiceover_settings/logic.py"),
    Path("settings/api_settings/logic.py"),
}


def _is_forbidden(module: str) -> bool:
    normalized = str(module or "").strip()
    if normalized in _FORBIDDEN_MODULES:
        return True
    root = normalized.split(".", 1)[0]
    return root in _FORBIDDEN_ROOTS


class PassiveUiBoundaryTests(unittest.TestCase):
    def test_application_views_do_not_import_backend_layers(self) -> None:
        violations: list[str] = []
        for path in sorted(_UI_ROOT.rglob("*.py")):
            relative = path.relative_to(_UI_ROOT)
            if relative in _COMPOSITION_EXEMPTIONS:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and _is_forbidden(node.module):
                    violations.append(f"{relative}:{node.lineno}: from {node.module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if _is_forbidden(alias.name):
                            violations.append(f"{relative}:{node.lineno}: import {alias.name}")
        self.assertEqual([], violations, "Passive UI boundary violations:\n" + "\n".join(violations))

    def test_application_logic_is_not_stored_under_ui(self) -> None:
        existing = [str(path) for path in sorted(_REMOVED_UI_INFRASTRUCTURE) if (_UI_ROOT / path).exists()]
        self.assertEqual([], existing, "Controller/infrastructure modules returned to ui/: " + ", ".join(existing))

    def test_views_do_not_reference_controller_modules_indirectly(self) -> None:
        violations: list[str] = []
        for path in sorted(_UI_ROOT.rglob("*.py")):
            relative = path.relative_to(_UI_ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if "controllers.gui" in node.value:
                        violations.append(f"{relative}:{node.lineno}: {node.value!r}")
        self.assertEqual([], violations, "Indirect controller references in ui/:\n" + "\n".join(violations))

    def test_api_settings_controllers_are_outside_ui(self) -> None:
        controller_dir = _UI_ROOT / "settings" / "api_settings" / "controllers"
        self.assertFalse(controller_dir.exists(), str(controller_dir))

    def test_views_do_not_reach_composition_backend_state(self) -> None:
        forbidden_attributes = {"event_bus", "main_controller", "backend_ready"}
        violations: list[str] = []
        for path in sorted(_UI_ROOT.rglob("*.py")):
            relative = path.relative_to(_UI_ROOT)
            if relative in _COMPOSITION_EXEMPTIONS:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
                    base = node.value
                    if (isinstance(base, ast.Attribute) and base.attr == "app") or (
                        isinstance(base, ast.Name) and base.id == "app"
                    ):
                        continue
                    violations.append(f"{relative}:{node.lineno}: .{node.attr}")
        self.assertEqual([], violations, "Views reach composition backend state:\n" + "\n".join(violations))

    def test_composition_root_is_outside_ui(self) -> None:
        self.assertFalse((_UI_ROOT / "composition_root.py").exists())
        self.assertTrue((_SRC_ROOT / "controllers" / "gui" / "composition_root.py").exists())

    def test_ui_topics_match_registered_backend_events(self) -> None:
        from core.events import Events
        from ui.presentation import UiTopic

        registered: set[str] = set()
        for group_name in dir(Events):
            if group_name.startswith("_"):
                continue
            group = getattr(Events, group_name)
            if not isinstance(group, type):
                continue
            for name in dir(group):
                if name.startswith("_"):
                    continue
                value = getattr(group, name)
                if isinstance(value, str):
                    registered.add(value)

        missing = sorted(topic.value for topic in UiTopic if topic.value not in registered)
        self.assertEqual([], missing)

    def test_detached_view_resolves_explicitly_injected_presentation(self) -> None:
        from ui.presentation import resolve_presentation

        presentation = object()
        detached_view = SimpleNamespace(presentation=presentation)

        self.assertIs(presentation, resolve_presentation(detached_view))


if __name__ == "__main__":
    unittest.main()
