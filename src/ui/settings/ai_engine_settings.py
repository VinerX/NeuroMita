from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from localization.live import tr_set
from ui.gui_templates import SettingsBodyWidget, create_section_header
from ui.widgets.settings_sections import InnerCollapsibleSection
from utils import getTranslationVariant as _


def _format_bytes(value) -> str:
    try:
        size = max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return "—"


def _row(label: str, widget) -> SettingsBodyWidget:
    row = SettingsBodyWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(10)
    title = QLabel(label)
    title.setMinimumWidth(145)
    layout.addWidget(title, 0)
    layout.addWidget(widget, 1)
    return row


def setup_ai_engine_settings_controls(self, parent_layout, *, view_model) -> None:
    create_section_header(parent_layout, _("Управление AI Engine", "AI Engine management"))

    root = SettingsBodyWidget()
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    self.ai_hardware_label = QLabel("—")
    self.ai_hardware_label.setWordWrap(True)
    self.ai_hardware_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(_row(_("Видеокарта", "Graphics adapter"), self.ai_hardware_label))

    self.ai_driver_label = QLabel("—")
    self.ai_driver_label.setWordWrap(True)
    layout.addWidget(_row(_("Compute backend", "Compute backend"), self.ai_driver_label))

    hardware_refresh = tr_set(QPushButton(), "Обновить аппаратный профиль", "Refresh hardware profile")
    hardware_refresh.setObjectName("SecondaryButton")
    hardware_refresh.clicked.connect(lambda: view_model.refresh(hardware=True))
    layout.addWidget(hardware_refresh)

    create_section_header(layout, _("Режим AI workers", "AI worker mode"))
    mode_field = SettingsBodyWidget()
    mode_layout = QHBoxLayout(mode_field)
    mode_layout.setContentsMargins(0, 0, 0, 0)
    mode_layout.setSpacing(8)
    self.ai_engine_mode_combobox = QComboBox()
    self.ai_engine_mode_combobox.addItem(_("Shared — один worker", "Shared — one worker"), "shared")
    self.ai_engine_mode_combobox.addItem(_("Split — worker на контур", "Split — worker per domain"), "split")
    mode_layout.addWidget(self.ai_engine_mode_combobox, 1)
    self.ai_engine_mode_apply = tr_set(QPushButton(), "Применить", "Apply")
    self.ai_engine_mode_apply.setObjectName("SecondaryButton")
    mode_layout.addWidget(self.ai_engine_mode_apply, 0)
    layout.addWidget(_row(_("Топология", "Topology"), mode_field))

    self.ai_split_warning = tr_set(
        QLabel(),
        "Split запускает отдельный процесс для TTS, ASR, RAG и Beats. Изоляция выше, но каждый процесс может отдельно загрузить CUDA runtime и модели, поэтому потребление RAM/VRAM возрастает.",
        "Split starts a separate process for TTS, ASR, RAG and Beats. Isolation is stronger, but each process may load its own CUDA runtime and models, increasing RAM/VRAM usage.",
    )
    self.ai_split_warning.setWordWrap(True)
    self.ai_split_warning.setStyleSheet("color: #f0a64a;")
    layout.addWidget(self.ai_split_warning)

    self.ai_engine_status = QLabel("—")
    self.ai_engine_status.setWordWrap(True)
    layout.addWidget(self.ai_engine_status)

    open_hub = tr_set(QPushButton(), "Открыть AI Hub", "Open AI Hub")
    open_hub.setObjectName("SecondaryButton")
    open_hub.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    open_hub.clicked.connect(view_model.open_ai_hub)
    layout.addWidget(open_hub)

    maintenance = InnerCollapsibleSection(
        _("Обслуживание AI-пакетов", "AI package maintenance"),
        parent=self,
    )
    maintenance_hint = tr_set(
        QLabel(),
        "Удаляется только управляемая папка Lib/environment: backend layers, component overlays, registry и staging. Lib/core приложения не затрагивается. Перед удалением очередь установок и AI workers останавливаются.",
        "Only the managed Lib/environment folder is removed: backend layers, component overlays, registry and staging. Application Lib/core is not touched. The install queue and AI workers are stopped first.",
    )
    maintenance_hint.setWordWrap(True)
    maintenance.add_widget(maintenance_hint)

    self.ai_environment_path = QLabel("—")
    self.ai_environment_path.setWordWrap(True)
    self.ai_environment_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    maintenance.add_widget(self.ai_environment_path)

    self.ai_maintenance_status = QLabel("—")
    self.ai_maintenance_status.setWordWrap(True)
    maintenance.add_widget(self.ai_maintenance_status)

    self.ai_environment_reset = tr_set(
        QPushButton(),
        "Удалить все AI-окружения",
        "Delete all AI environments",
    )
    self.ai_environment_reset.setObjectName("DangerButton")
    maintenance.add_widget(self.ai_environment_reset)
    layout.addWidget(maintenance)

    parent_layout.addWidget(root)

    def selected_mode() -> str:
        return str(self.ai_engine_mode_combobox.currentData() or "shared")

    def update_warning() -> None:
        self.ai_split_warning.setVisible(selected_mode() == "split")

    self.ai_engine_mode_combobox.currentIndexChanged.connect(update_warning)
    self.ai_engine_mode_apply.clicked.connect(lambda: view_model.switch_mode(selected_mode()))

    def reset_environments() -> None:
        answer = QMessageBox.warning(
            self,
            _("Удаление AI-окружений", "Delete AI environments"),
            _(
                "Все AI backend layers и пакеты компонентов из Lib/environment будут удалены. Продолжить?",
                "All AI backend layers and component packages in Lib/environment will be deleted. Continue?",
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            view_model.reset_environments()

    self.ai_environment_reset.clicked.connect(reset_environments)

    def render(state) -> None:
        hardware = dict(state.hardware or {})
        primary = dict(hardware.get("primary") or {})
        vendor = str(hardware.get("vendor") or "CPU")
        name = str(primary.get("name") or _("Не обнаружена", "Not detected"))
        vendor_id = str(primary.get("vendor_id") or "—").upper()
        device_id = str(primary.get("device_id") or "—").upper()
        vram = _format_bytes(primary.get("dedicated_vram_bytes"))
        self.ai_hardware_label.setText(
            f"{name}\n{vendor} · PCI {vendor_id}:{device_id} · VRAM {vram}"
        )

        cuda = dict(hardware.get("cuda") or {})
        cuda_devices = list(cuda.get("devices") or [])
        if cuda.get("available"):
            capabilities = ", ".join(
                str(item.get("compute_capability") or "").upper()
                for item in cuda_devices
                if item.get("compute_capability")
            )
            driver = str(cuda.get("driver_version") or "—")
            self.ai_driver_label.setText(f"CUDA Driver {driver}" + (f" · {capabilities}" if capabilities else ""))
        elif vendor == "AMD":
            self.ai_driver_label.setText(_("AMD · ONNX/DirectML", "AMD · ONNX/DirectML"))
        else:
            self.ai_driver_label.setText(_("CPU / ONNX", "CPU / ONNX"))

        topology = dict(state.topology or {})
        mode = str(topology.get("mode") or "shared")
        index = self.ai_engine_mode_combobox.findData(mode)
        if index >= 0:
            self.ai_engine_mode_combobox.blockSignals(True)
            self.ai_engine_mode_combobox.setCurrentIndex(index)
            self.ai_engine_mode_combobox.blockSignals(False)
        update_warning()
        workers = dict(topology.get("workers") or {})
        alive = sum(1 for item in workers.values() if item.get("alive"))
        override = topology.get("override")
        status = _("Workers: ", "Workers: ") + f"{alive}/{len(workers)}"
        if override:
            status += f" · env override: {override}"
        self.ai_engine_status.setText(status)

        maintenance_state = dict(state.maintenance or {})
        path = str(maintenance_state.get("path") or "—")
        size = maintenance_state.get("size_bytes")
        self.ai_environment_path.setText(
            f"{path}" + (f"\n{_format_bytes(size)}" if size is not None else "")
        )
        message = str(maintenance_state.get("message") or "")
        error = str(maintenance_state.get("error") or state.error or "")
        self.ai_maintenance_status.setText(error or message or _("Готово", "Ready"))
        busy = bool(state.busy or maintenance_state.get("busy"))
        self.ai_environment_reset.setEnabled(not busy and bool(maintenance_state.get("path")))
        self.ai_engine_mode_apply.setEnabled(not busy and not bool(override) and bool(topology))
        hardware_refresh.setEnabled(not busy)

    view_model.state_changed.connect(render)
    render(view_model.state)
    view_model.refresh()
    QTimer.singleShot(1500, view_model.refresh)
