from __future__ import annotations

import ast
import unittest
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2]
_UI_ROOT = _SRC_ROOT / "ui"
_CONTROLLERS_ROOT = _SRC_ROOT / "controllers"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise AssertionError(f"{class_name}.{method_name} not found")


class GuideWindowManagerTests(unittest.TestCase):
    def test_guide_dialog_is_a_qdialog_host_for_guide_widget(self) -> None:
        path = _UI_ROOT / "windows" / "guide_dialog.py"
        tree = _parse(path)
        guide_class = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "GuideDialog"
        )
        base_names = {
            base.id for base in guide_class.bases if isinstance(base, ast.Name)
        }
        self.assertIn("QDialog", base_names)

        init = next(
            node for node in guide_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        constructed = {
            node.func.id
            for node in ast.walk(init)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("GuideWidget", constructed)

    def test_window_manager_registers_guide_as_singleton_top_level_dialog(self) -> None:
        path = _CONTROLLERS_ROOT / "gui" / "window_composition_controller.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn(
            '"guide": (self._factory_guide, True, True, False, self._on_guide_ready)',
            text,
        )
        self.assertIn("def _factory_guide", text)
        self.assertIn("def _on_guide_ready", text)

    def test_app_window_opens_guide_only_through_window_manager(self) -> None:
        path = _UI_ROOT / "windows" / "app_window_base.py"
        method = _method(_parse(path), "AppWindowBase", "_show_guide")

        calls = [
            node for node in ast.walk(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "show_dialog"
        ]
        self.assertEqual(1, len(calls))
        self.assertTrue(
            calls[0].args
            and isinstance(calls[0].args[0], ast.Constant)
            and calls[0].args[0].value == "guide"
        )
        self.assertFalse(
            any(
                isinstance(node, ast.Attribute) and node.attr == "overlay"
                for node in ast.walk(method)
            ),
            "Guide path must not fall back to the in-window overlay",
        )

    def test_dark_titlebar_filter_does_not_recreate_hwnd_on_winidchange(self) -> None:
        path = _SRC_ROOT / "utils" / "win_titlebar.py"
        text = path.read_text(encoding="utf-8")
        filter_block = text[text.index("class _DarkTitlebarFilter"):]
        self.assertIn("QEvent.Type.Show", filter_block)
        self.assertNotIn("QEvent.Type.WinIdChange", filter_block)


if __name__ == "__main__":
    unittest.main()
