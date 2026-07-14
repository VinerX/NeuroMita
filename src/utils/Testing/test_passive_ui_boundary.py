from __future__ import annotations

import ast
import unittest
from pathlib import Path


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
    Path("presentation.py"),
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
_GUI_HOST_NAMES = {"self", "gui", "view", "window"}
_ALLOWED_QT_HOST_ATTRIBUTES = {"style"}


def _module_gui_host_functions(tree: ast.Module):
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.args.args:
            continue
        host_name = node.args.args[0].arg
        if host_name in _GUI_HOST_NAMES:
            yield node, host_name


def _function_scope_nodes(function, host_name: str):
    stack = list(function.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, ast.ClassDef):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            arg_names = {
                item.arg
                for item in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            }
            if host_name in arg_names:
                continue
        stack.extend(ast.iter_child_nodes(node))


def _assigned_host_attributes(node, host_name: str) -> set[str]:
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = (node.target,)
    else:
        return set()
    return {
        target.attr
        for target in targets
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == host_name
    }


def _main_window_attribute_contract() -> set[str]:
    attributes = _main_window_method_contract()
    for relative, class_name in (
        (Path("windows/app_window_base.py"), "AppWindowBase"),
        (Path("windows/main_window.py"), "MainWindow"),
    ):
        path = _UI_ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        class_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        for node in ast.walk(class_node):
            attributes.update(_assigned_host_attributes(node, "self"))
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
                attributes.update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )

    roots = (_UI_ROOT, _SRC_ROOT / "controllers" / "gui")
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for function, host_name in _module_gui_host_functions(tree):
                for node in _function_scope_nodes(function, host_name):
                    attributes.update(_assigned_host_attributes(node, host_name))
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "setattr"
                        and len(node.args) >= 2
                        and isinstance(node.args[0], ast.Name)
                        and node.args[0].id == host_name
                        and isinstance(node.args[1], ast.Constant)
                        and isinstance(node.args[1].value, str)
                    ):
                        attributes.add(node.args[1].value)

    for path in sorted(_UI_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "widget_name"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    attributes.add(value.value)
    return attributes | _ALLOWED_QT_HOST_ATTRIBUTES


def _main_window_method_contract() -> set[str]:
    methods: set[str] = set()
    for relative, class_name in (
        (Path("windows/app_window_base.py"), "AppWindowBase"),
        (Path("windows/main_window.py"), "MainWindow"),
    ):
        path = _UI_ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        class_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        methods.update(
            node.name
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    return methods


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

    def test_views_do_not_use_presentation_service_locator(self) -> None:
        violations: list[str] = []
        for path in sorted(_UI_ROOT.rglob("*.py")):
            relative = path.relative_to(_UI_ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "presentation":
                    violations.append(f"{relative}:{node.lineno}: .presentation")
        self.assertEqual(
            [],
            violations,
            "Views use the presentation service locator:\n" + "\n".join(violations),
        )

    def test_gui_controllers_do_not_resolve_presentation_through_views(self) -> None:
        controllers_root = _SRC_ROOT / "controllers" / "gui"
        view_names = {"gui", "view", "window"}
        violations: list[str] = []

        for path in sorted(controllers_root.rglob("*.py")):
            relative = path.relative_to(controllers_root)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute) or node.attr != "presentation":
                    continue

                base = node.value
                direct_view = isinstance(base, ast.Name) and base.id in view_names
                stored_view = (
                    isinstance(base, ast.Attribute)
                    and isinstance(base.value, ast.Name)
                    and base.value.id == "self"
                    and base.attr in view_names
                )
                if direct_view or stored_view:
                    violations.append(f"{relative}:{node.lineno}: view.presentation")

            for function, host_name in _module_gui_host_functions(tree):
                for node in ast.walk(function):
                    if not isinstance(node, ast.Attribute) or node.attr != "presentation":
                        continue
                    if isinstance(node.value, ast.Name) and node.value.id == host_name:
                        violations.append(
                            f"{relative}:{node.lineno}: {host_name}.presentation"
                        )

        self.assertEqual(
            [],
            violations,
            "GUI controllers resolve the presentation hub through a View:\n"
            + "\n".join(violations),
        )

    def test_gui_view_settings_calls_match_qt_view_model_contract(self) -> None:
        binding_path = _UI_ROOT / "settings" / "settings_binding.py"
        binding_tree = ast.parse(
            binding_path.read_text(encoding="utf-8"),
            filename=str(binding_path),
        )
        view_model = next(
            node
            for node in binding_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "QtSettingsViewModel"
        )
        public_methods = {
            node.name
            for node in view_model.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }

        controllers_root = _SRC_ROOT / "controllers" / "gui"
        view_names = {"gui", "view", "window"}
        violations: list[str] = []
        for path in sorted(controllers_root.rglob("*.py")):
            relative = path.relative_to(controllers_root)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            scopes = [(tree, view_names)]
            scopes.extend(
                (function, {host_name})
                for function, host_name in _module_gui_host_functions(tree)
            )
            seen: set[tuple[int, str]] = set()
            for scope, host_names in scopes:
                for node in ast.walk(scope):
                    if not isinstance(node, ast.Attribute):
                        continue
                    settings_owner = node.value
                    if not (
                        isinstance(settings_owner, ast.Attribute)
                        and settings_owner.attr == "settings"
                        and isinstance(settings_owner.value, ast.Name)
                        and settings_owner.value.id in host_names
                    ):
                        continue
                    marker = (node.lineno, settings_owner.value.id)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    if node.attr not in public_methods:
                        violations.append(
                            f"{relative}:{node.lineno}: "
                            f"{settings_owner.value.id}.settings.{node.attr}"
                        )

        self.assertEqual(
            [],
            violations,
            "GUI controllers call methods absent from QtSettingsViewModel:\n"
            + "\n".join(violations),
        )

    def test_module_gui_host_method_calls_match_main_window_contract(self) -> None:
        controllers_root = _SRC_ROOT / "controllers" / "gui"
        public_methods = _main_window_method_contract()
        violations: list[str] = []

        for path in sorted(controllers_root.rglob("*.py")):
            relative = path.relative_to(controllers_root)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for function, host_name in _module_gui_host_functions(tree):
                for node in ast.walk(function):
                    if not isinstance(node, ast.Call):
                        continue
                    target = node.func
                    if not (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == host_name
                    ):
                        continue
                    if target.attr not in public_methods:
                        violations.append(
                            f"{relative}:{node.lineno}: {host_name}.{target.attr}()"
                        )

        self.assertEqual(
            [],
            violations,
            "Module-level GUI adapters call methods absent from MainWindow:\n"
            + "\n".join(violations),
        )

    def test_module_gui_host_attributes_are_declared(self) -> None:
        known_attributes = _main_window_attribute_contract()
        violations: list[str] = []

        for root in (_UI_ROOT, _SRC_ROOT / "controllers" / "gui"):
            for path in sorted(root.rglob("*.py")):
                relative = path.relative_to(_SRC_ROOT)
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for function, host_name in _module_gui_host_functions(tree):
                    for node in _function_scope_nodes(function, host_name):
                        if not (
                            isinstance(node, ast.Attribute)
                            and isinstance(node.value, ast.Name)
                            and node.value.id == host_name
                        ):
                            continue
                        if node.attr not in known_attributes:
                            violations.append(
                                f"{relative}:{node.lineno}: "
                                f"{function.name} -> {host_name}.{node.attr}"
                            )

        self.assertEqual(
            [],
            violations,
            "Module-level GUI adapters access undeclared MainWindow attributes:\n"
            + "\n".join(violations),
        )

    def test_views_do_not_store_concrete_composition_controllers(self) -> None:
        forbidden_attributes = {
            "presentation",
            "shell_controller",
            "window_controller",
            "page_coordinator",
            "main_controller",
        }
        violations: list[str] = []
        for path in sorted(_UI_ROOT.rglob("*.py")):
            relative = path.relative_to(_UI_ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
                    violations.append(f"{relative}:{node.lineno}: .{node.attr}")
        self.assertEqual(
            [],
            violations,
            "Views retain composition/controller objects:\n" + "\n".join(violations),
        )

    def test_views_do_not_construct_application_view_models(self) -> None:
        violations: list[str] = []
        for path in sorted(_UI_ROOT.rglob("*.py")):
            relative = path.relative_to(_UI_ROOT)
            if relative == Path("settings/settings_binding.py"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                name = (
                    function.id
                    if isinstance(function, ast.Name)
                    else function.attr
                    if isinstance(function, ast.Attribute)
                    else ""
                )
                if str(name).endswith("ViewModel"):
                    violations.append(f"{relative}:{node.lineno}: {name}()")
        self.assertEqual(
            [],
            violations,
            "Views construct application ViewModels instead of receiving them:\n"
            + "\n".join(violations),
        )

    def test_views_do_not_retain_main_window_as_gui_service_locator(self) -> None:
        violations: list[str] = []
        for path in sorted(_UI_ROOT.rglob("*.py")):
            relative = path.relative_to(_UI_ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute) or node.attr != "gui":
                    continue
                if isinstance(node.value, ast.Name) and node.value.id == "self":
                    violations.append(f"{relative}:{node.lineno}: self.gui")
        self.assertEqual(
            [],
            violations,
            "Views retain the main window as a mutable service locator:\n"
            + "\n".join(violations),
        )

    def test_stateful_pages_do_not_call_shell_business_methods(self) -> None:
        forbidden = {
            "switch_main_page",
            "show_settings_category",
            "open_release_page",
            "update_debug_info",
            "send_message",
            "load_chat_history",
            "clear_chat_display",
            "update_status_colors",
            "_show_guide",
        }
        roots = (_UI_ROOT / "pages", _UI_ROOT / "widgets" / "chat_panel.py")
        paths = list(roots[0].rglob("*.py")) + [roots[1]]
        violations: list[str] = []
        for path in sorted(paths):
            relative = path.relative_to(_UI_ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr not in forbidden:
                        continue
                    base = node.func.value
                    direct_host = isinstance(base, ast.Name) and base.id in {"gui", "window"}
                    self_gui = (
                        isinstance(base, ast.Attribute)
                        and isinstance(base.value, ast.Name)
                        and base.value.id == "self"
                        and base.attr == "gui"
                    )
                    if direct_host or self_gui:
                        violations.append(f"{relative}:{node.lineno}: {node.func.attr}()")
        self.assertEqual(
            [],
            violations,
            "Stateful Views call shell business methods instead of action ports:\n"
            + "\n".join(violations),
        )

    def test_shell_views_do_not_read_runtime_state_files(self) -> None:
        files = (
            Path("windows/app_window_base.py"),
            Path("pages/logs_page.py"),
        )
        forbidden_calls = {"open", "json.load"}
        violations: list[str] = []
        for relative in files:
            path = _UI_ROOT / relative
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if isinstance(function, ast.Name):
                    name = function.id
                elif isinstance(function, ast.Attribute):
                    if isinstance(function.value, ast.Name):
                        name = f"{function.value.id}.{function.attr}"
                    else:
                        name = function.attr
                else:
                    name = ""
                if name in forbidden_calls or name == "Path.open":
                    violations.append(f"{relative}:{node.lineno}: {name}()")
        self.assertEqual(
            [],
            violations,
            "Shell views read runtime files directly:\n" + "\n".join(violations),
        )

    def test_private_gui_self_calls_reference_declared_members(self) -> None:
        roots = (_UI_ROOT, _SRC_ROOT / "controllers" / "gui")
        declared: set[str] = set()
        calls: list[tuple[Path, int, str]] = []

        for root in roots:
            for path in sorted(root.rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        declared.add(node.name)
                    declared.update(_assigned_host_attributes(node, "self"))
                    if not isinstance(node, ast.Call):
                        continue
                    target = node.func
                    if not (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr.startswith("_")
                        and not target.attr.startswith("__")
                    ):
                        continue
                    calls.append((path, node.lineno, target.attr))

        violations = [
            f"{path.relative_to(_SRC_ROOT)}:{line}: self.{name}()"
            for path, line, name in calls
            if name not in declared
        ]
        self.assertEqual(
            [],
            violations,
            "GUI code calls private members that are never declared or assigned:\n"
            + "\n".join(violations),
        )

    def test_composition_root_is_outside_ui(self) -> None:
        self.assertFalse((_UI_ROOT / "composition_root.py").exists())
        self.assertTrue((_SRC_ROOT / "controllers" / "gui" / "composition_root.py").exists())

    def test_ui_topics_match_registered_backend_events(self) -> None:
        from core.events import Events
        from controllers.gui.presentation_contracts import UiTopic

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

if __name__ == "__main__":
    unittest.main()
