from __future__ import annotations

import ast
import unittest
from pathlib import Path

from ui.mvvm import FrozenList, FrozenMapping, immutable_payload, mutable_payload


_SRC_ROOT = Path(__file__).resolve().parents[2]
_UI_ROOT = _SRC_ROOT / "ui"
_PRESENTATION_CONTRACT = Path("presentation.py")
_SETTINGS_BINDING = Path("settings/settings_binding.py")


class IntentMvvmContractTests(unittest.TestCase):
    def test_immutable_payload_preserves_mapping_and_pair_list_shapes(self) -> None:
        mapping = immutable_payload({"first": 1, "second": [2, 3]})
        pairs = immutable_payload([("first", 1), ("second", 2)])
        original_tuple = ("tuple", [1, 2])
        frozen_tuple = immutable_payload(original_tuple)

        self.assertIsInstance(mapping, FrozenMapping)
        self.assertIsInstance(pairs, FrozenList)
        self.assertEqual(
            {"first": 1, "second": [2, 3]},
            mutable_payload(mapping),
        )
        self.assertEqual(
            [("first", 1), ("second", 2)],
            mutable_payload(pairs),
        )
        self.assertEqual(original_tuple, mutable_payload(frozen_tuple))

    def test_views_do_not_use_event_topics_or_async_runner(self) -> None:
        violations: list[str] = []
        allowed = {_PRESENTATION_CONTRACT, _SETTINGS_BINDING}
        forbidden_names = {"UiTopic", "run_ui_async", "dispatch_ui"}

        for path in sorted(_UI_ROOT.rglob("*.py")):
            relative = path.relative_to(_UI_ROOT)
            if relative in allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id in forbidden_names:
                    violations.append(f"{relative}:{node.lineno}: {node.id}")
                elif isinstance(node, ast.Attribute):
                    if node.attr in {"events", "tasks", "event_bus"}:
                        violations.append(f"{relative}:{node.lineno}: .{node.attr}")

        self.assertEqual(
            [],
            violations,
            "Views bypass intent-driven presentation:\n" + "\n".join(violations),
        )

    def test_state_dataclasses_are_frozen(self) -> None:
        violations: list[str] = []
        for path in sorted(_UI_ROOT.rglob("*presentation.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if not isinstance(node, ast.ClassDef) or not node.name.endswith("State"):
                    continue
                dataclass_decorator = next(
                    (
                        decorator
                        for decorator in node.decorator_list
                        if (
                            isinstance(decorator, ast.Call)
                            and isinstance(decorator.func, ast.Name)
                            and decorator.func.id == "dataclass"
                        )
                    ),
                    None,
                )
                if dataclass_decorator is None:
                    violations.append(f"{path.relative_to(_UI_ROOT)}:{node.lineno}: no dataclass")
                    continue
                keywords = {
                    keyword.arg: keyword.value
                    for keyword in dataclass_decorator.keywords
                    if keyword.arg
                }
                frozen = keywords.get("frozen")
                if not isinstance(frozen, ast.Constant) or frozen.value is not True:
                    violations.append(f"{path.relative_to(_UI_ROOT)}:{node.lineno}: not frozen")

        self.assertEqual(
            [],
            violations,
            "Mutable presentation states:\n" + "\n".join(violations),
        )

    def test_settings_widgets_use_the_shared_binding_bridge(self) -> None:
        source = (_UI_ROOT / "gui_templates.py").read_text(encoding="utf-8")
        self.assertIn("_bind_setting_two_way", source)
        self.assertIn("binding.bind_two_way", source)

    def test_gui_controllers_do_not_poke_private_view_state(self) -> None:
        """Храповик миграции controllers/gui на MVVM.

        Обращения вида `gui._attr` / `setattr(gui, "_attr", ...)` — это старый
        стиль «состояние в виджетах». Новым файлам он запрещён полностью;
        для ещё не мигрированных зафиксирован текущий счётчик нарушений —
        уменьшать можно, расти нельзя. Домигрировал файл — убери его из списка.
        """
        allowed_counts = {
            "character_settings_logic.py": 187,
        }
        controllers_root = _SRC_ROOT / "controllers" / "gui"
        actual_counts: dict[str, int] = {}

        for path in sorted(controllers_root.rglob("*.py")):
            relative = str(path.relative_to(controllers_root)).replace("\\", "/")
            count = 0
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "gui"
                    and node.attr.startswith("_")
                ):
                    count += 1
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in ("setattr", "getattr")
                    and node.args
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id == "gui"
                    and len(node.args) > 1
                    and isinstance(node.args[1], ast.Constant)
                    and str(node.args[1].value).startswith("_")
                ):
                    count += 1
            if count:
                actual_counts[relative] = count

        problems: list[str] = []
        for relative, count in actual_counts.items():
            budget = allowed_counts.get(relative)
            if budget is None:
                problems.append(
                    f"{relative}: {count} обращений к приватному состоянию gui — "
                    "новый код обязан хранить состояние во view model/хабе"
                )
            elif count > budget:
                problems.append(
                    f"{relative}: нарушений стало {count} (бюджет {budget}) — "
                    "уменьшать можно, расти нельзя"
                )
        for relative, budget in allowed_counts.items():
            actual = actual_counts.get(relative, 0)
            if actual < budget:
                problems.append(
                    f"{relative}: нарушений осталось {actual} (бюджет {budget}) — "
                    "затяни храповик: обнови бюджет в allowed_counts"
                )

        self.assertEqual([], problems, "\n".join(problems))

    def test_stateful_views_do_not_own_refresh_generations(self) -> None:
        files = (
            Path("windows/ai_hub/dialog.py"),
            Path("windows/asr_glossary_view.py"),
            Path("windows/voice_model_view.py"),
        )
        forbidden = (
            "_refresh_ticket",
            "_settings_ticket",
            "_deps_refresh_ticket",
            "on_install_progress(",
            "on_install_finished(",
            "on_install_failed(",
        )
        violations: list[str] = []
        for relative in files:
            source = (_UI_ROOT / relative).read_text(encoding="utf-8")
            for token in forbidden:
                if token in source:
                    violations.append(f"{relative}: {token}")

        self.assertEqual(
            [],
            violations,
            "Stateful views own asynchronous refresh/install state:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()