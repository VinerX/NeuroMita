from __future__ import annotations

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QDialog

from model_settings.service import ModelSettingsService
from model_settings.schema import SettingsSchema
from ui.settings.api_settings.dialogs.model_parameters_dialog import ModelParametersDialog
from utils import _


class PresetModelSettingsController(QObject):
    """Coordinate a preset's form and application service; no HTTP serialization."""

    def __init__(self, form, parent=None, *, service=None):
        super().__init__(parent)
        self.form = form
        self.service = service or ModelSettingsService()
        self.dialect = "openai_chat_completions"
        form.import_requested.connect(self.import_definition)
        form.export_requested.connect(self.export_definition)
        form.edit_requested.connect(self.edit_definition)

    def load(self, preset, dialect, settings=None):
        self.dialect = dialect
        document = self.service.for_preset(preset, dialect, settings)
        self._render(document)

    def _render(self, document):
        schema, normalized = self.service.resolve(document, self.dialect)
        self.form.load(schema, normalized)

    def restore(self, document, dialect=None):
        if dialect is not None:
            self.dialect = dialect
        self._render(document)

    def set_dialect(self, dialect, suggested=""):
        if dialect == self.dialect and not suggested:
            return
        document = self.form.document()
        if document is not None and dialect == self.dialect and document["schema_id"] == suggested:
            return
        self.dialect = dialect
        identifier = self.service.default_id(dialect, suggested)
        self._render(self.service.create(identifier))

    def import_definition(self):
        path, _filter = QFileDialog.getOpenFileName(self.form, _("Импорт JSON", "Import JSON"), "", "JSON (*.json)")
        if not path:
            return
        try:
            schema = self.service.import_definition(path, self.dialect)
            document = self.service.change_schema(self.form.document(), schema.data["id"], self.dialect)
            self._render(document)
            self.form.changed.emit()
        except (ValueError, OSError) as exc:
            self._error(exc)

    def export_definition(self):
        path, _filter = QFileDialog.getSaveFileName(self.form, _("Экспорт JSON", "Export JSON"), self.form.document()["schema_id"] + ".json", "JSON (*.json)")
        if path:
            try:
                self.service.export_definition(self.form.document(), self.dialect, path)
            except (ValueError, OSError) as exc:
                self._error(exc)

    def edit_definition(self):
        document = self.form.document()
        schema, _state = self.service.resolve(document, self.dialect)
        dialog = ModelParametersDialog(schema.data, self.form, validate_definition=self._validate_definition)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                document = self.service.customize(document, dialog.definition(), self.dialect)
                self._render(document)
                self.form.changed.emit()
                return
            except (ValueError, OSError) as exc:
                self._error(exc)

    def _validate_definition(self, data):
        schema = SettingsSchema.from_dict(data)
        self.service.check_dialect(schema, self.dialect)
        return schema.data

    def _error(self, exc):
        QMessageBox.warning(self.form, _("Ошибка описания настроек", "Settings definition error"), str(exc))
