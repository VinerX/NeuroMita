from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtWidgets import QApplication, QLabel

from controllers.gui.protocol_pipeline_gui_controller import (
    ProtocolPipelineGuiController,
)
from handlers.llm_providers.message_transforms import get_transform_catalog
from ui.dialogs.message_processing_dialog import MessageProcessingDialog

_APP = None


@pytest.fixture
def dialog():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    widget = MessageProcessingDialog()
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()


def payload(current=None):
    catalog = get_transform_catalog()
    result = {
        "transform_catalog": catalog,
        "available_ids": [entry["id"] for entry in catalog],
        "base_transforms": [{"id": "merge_system_messages"}],
    }
    if current is not None:
        result["current_transforms"] = current
    return result


def test_empty_override_survives_reopening(dialog):
    dialog.apply_payload(payload([]))
    assert dialog.transforms() == []
    assert not dialog.empty_label.isHidden()
    assert dialog.list.isHidden()
    assert dialog.reset_button.isEnabled()
    assert not dialog.apply_button.isEnabled()
    dialog._on_reset()
    assert dialog.transforms() == [{"id": "merge_system_messages"}]
    assert dialog.apply_button.isEnabled()


def test_reorder_remove_reset_preserve_params_without_mutating_source(dialog):
    source = payload(
        [
            {"id": "merge_system_messages"},
            {
                "id": "ensure_last_message_user",
                "params": {"fallback_user_text": "continue"},
            },
        ]
    )
    dialog.apply_payload(source)
    dialog.list.setCurrentRow(1)
    assert not dialog.down_button.isEnabled()
    dialog._move(-1)
    assert dialog.list.currentRow() == 0
    assert not dialog.up_button.isEnabled()
    assert dialog.transforms()[0]["params"]["fallback_user_text"] == "continue"
    exported = dialog.transforms()
    exported[0]["params"]["fallback_user_text"] = "changed"
    assert dialog.transforms()[0]["params"]["fallback_user_text"] == "continue"
    assert source["current_transforms"][0]["id"] == "merge_system_messages"
    dialog._on_remove()
    assert dialog.transforms() == source["base_transforms"]
    dialog._on_reset()
    assert not dialog.reset_button.isEnabled()


def test_labels_are_readable_and_combo_uses_stable_ids(dialog):
    dialog.apply_payload(payload())
    assert dialog.combo.findData("merge_system_messages") == -1
    card = dialog.list.itemWidget(dialog.list.item(0))
    title = card.findChild(QLabel, "ProcessingTitle").text()
    assert "merge_system_messages" not in title
    assert card.findChild(QLabel, "ProcessingDescription").text()
    chosen = dialog.combo.currentData()
    dialog._on_add()
    assert dialog.transforms()[-1]["id"] == chosen
    assert dialog.combo.findData(chosen) == -1
    assert dialog.apply_button.isEnabled()


def test_window_manager_applies_only_on_accept_and_refreshes_callback(dialog):
    controller = ProtocolPipelineGuiController.__new__(ProtocolPipelineGuiController)
    manager = Mock()
    controller.view = SimpleNamespace(window_manager=manager)
    controller._ensure_registered()
    registration = manager.register_dialog.call_args.kwargs
    first, second = Mock(), Mock()
    registration["on_ready"](dialog, dict(payload(), on_apply=first))
    dialog.reject()
    first.assert_not_called()
    registration["on_ready"](dialog, dict(payload([]), on_apply=second))
    controller._apply(dialog)
    first.assert_not_called()
    second.assert_called_once_with([])
    created = registration["factory"](None, dict(payload(), on_apply=first))
    created.reject()
    first.assert_not_called()
    created._on_remove()
    created.accept()
    first.assert_called_once_with([])
    created.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_live_language_change_keeps_selection_and_parameters(dialog, monkeypatch):
    import localization
    from localization.live import language_changed_signal, refresh_all

    monkeypatch.setattr(localization, "_current_language", lambda: "RU")
    dialog.apply_payload(payload())
    selected = dialog.combo.currentData()
    original = dialog.transforms()
    monkeypatch.setattr(localization, "_current_language", lambda: "EN")
    refresh_all()
    language_changed_signal().emit("EN")
    assert dialog.windowTitle() == "Message processing"
    assert dialog.combo.currentData() == selected
    assert dialog.transforms() == original
    card = dialog.list.itemWidget(dialog.list.item(0))
    assert card.findChild(QLabel, "ProcessingTitle").text() == "Merge system messages"
    assert "Processing order" in dialog.count_label.text()


def test_help_follows_candidate_and_existing_step_without_changing_pipeline(dialog):
    dialog.apply_payload(payload())
    original = dialog.transforms()
    index = dialog.combo.findData("system_to_user_prefix")
    dialog.combo.setCurrentIndex(index)
    assert dialog.help_text.toPlainText()
    candidate_help = dialog.help_text.toPlainText()
    assert dialog.combo.itemData(index, Qt.ItemDataRole.ToolTipRole)
    dialog.combo.highlighted.emit(dialog.combo.findData("normalize_system_messages"))
    assert dialog.help_text.toPlainText() != candidate_help
    dialog.list.currentRowChanged.emit(0)
    assert dialog.help_text.toPlainText() != candidate_help
    assert dialog.transforms() == original


def test_detailed_help_retranslates_without_changing_candidate(dialog, monkeypatch):
    import localization
    from localization.live import refresh_all, language_changed_signal

    monkeypatch.setattr(localization, "_current_language", lambda: "RU")
    dialog.apply_payload(payload([]))
    dialog.combo.setCurrentIndex(dialog.combo.findData("normalize_system_messages"))
    original = dialog.help_text.toPlainText()
    tooltip = dialog.combo.itemData(dialog.combo.currentIndex(), Qt.ItemDataRole.ToolTipRole)
    monkeypatch.setattr(localization, "_current_language", lambda: "EN")
    refresh_all()
    language_changed_signal().emit("EN")
    assert dialog.help_text.toPlainText() != original
    assert dialog.combo.itemData(dialog.combo.currentIndex(), Qt.ItemDataRole.ToolTipRole) != tooltip
    assert dialog.combo.currentData() == "normalize_system_messages"
    assert dialog.transforms() == []
