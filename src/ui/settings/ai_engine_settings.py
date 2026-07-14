from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from localization.live import tr_set
from ui.gui_templates import SettingsBodyWidget, create_section_header
from ui.widgets.settings_sections import InnerCollapsibleSection
from utils import getTranslationVariant as _

try:
    import qtawesome as qta
except Exception:
    qta = None


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


def _set_icon(widget, name: str, *, color: str = "#f2b6d8", size: int = 18) -> None:
    if qta is None:
        return
    try:
        widget.setIcon(qta.icon(name, color=color))
        widget.setIconSize(QSize(size, size))
        if hasattr(widget, "setFixedSize"):
            widget.setFixedSize(max(30, size + 14), max(30, size + 14))
    except Exception:
        pass


def _card_icon(name: str) -> QLabel:
    label = QLabel()
    label.setObjectName("AIEngineCardIcon")
    label.setFixedSize(44, 44)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if qta is not None:
        try:
            label.setPixmap(qta.icon(name, color="#f2b6d8").pixmap(21, 21))
        except Exception:
            pass
    return label


def _chip(text: str, variant: str = "default", tooltip: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName(
        {
            "cuda": "AIEngineChipCuda",
            "onnx": "AIEngineChipOnnx",
            "gpu": "AIEngineChipGpu",
            "warning": "AIEngineChipWarning",
            "success": "AIEngineChipSuccess",
        }.get(variant, "AIEngineChip")
    )
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    if tooltip:
        label.setToolTip(tooltip)
    return label


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def setup_ai_engine_settings_controls(self, parent_layout, *, view_model) -> None:
    create_section_header(parent_layout, _("Управление AI Engine", "AI Engine management"))

    root = SettingsBodyWidget()
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)

    hardware_card = QFrame()
    hardware_card.setObjectName("AIEngineHardwarePanel")
    hardware_card.setMinimumHeight(116)
    hardware_layout = QHBoxLayout(hardware_card)
    hardware_layout.setContentsMargins(20, 20, 16, 20)
    hardware_layout.setSpacing(16)
    hardware_layout.addWidget(_card_icon("fa6s.display"), 0, Qt.AlignmentFlag.AlignTop)

    hardware_content = QVBoxLayout()
    hardware_content.setContentsMargins(0, 0, 0, 0)
    hardware_content.setSpacing(8)
    hardware_title = tr_set(
        QLabel(),
        "Устройство и ускорение",
        "Device and acceleration",
    )
    hardware_title.setObjectName("AIEngineCardTitle")
    hardware_content.addWidget(hardware_title)

    hardware_subtitle = tr_set(
        QLabel(),
        "Видеокарта и backend, доступные установленным AI-моделям.",
        "Graphics adapter and backend available to installed AI models.",
    )
    hardware_subtitle.setObjectName("AIEngineCardSubtitle")
    hardware_content.addWidget(hardware_subtitle)

    self.ai_hardware_loading = QWidget()
    loading_layout = QHBoxLayout(self.ai_hardware_loading)
    loading_layout.setContentsMargins(0, 0, 0, 0)
    loading_layout.setSpacing(7)
    self.ai_hardware_spinner = QPushButton()
    self.ai_hardware_spinner.setObjectName("AIEngineLoadingSpinner")
    self.ai_hardware_spinner.setEnabled(False)
    self.ai_hardware_spinner.setFixedSize(20, 20)
    if qta is not None:
        try:
            self._ai_hardware_spin = qta.Spin(self.ai_hardware_spinner)
            self.ai_hardware_spinner.setIcon(
                qta.icon(
                    "fa6s.spinner",
                    color="#f2b6d8",
                    animation=self._ai_hardware_spin,
                )
            )
        except Exception:
            pass
    loading_text = tr_set(
        QLabel(),
        "Определяем видеокарту и доступное ускорение…",
        "Detecting graphics adapter and available acceleration…",
    )
    loading_text.setObjectName("AIEngineLoadingText")
    loading_layout.addWidget(self.ai_hardware_spinner, 0)
    loading_layout.addWidget(loading_text, 1)
    hardware_content.addWidget(self.ai_hardware_loading)

    self.ai_hardware_info = QWidget()
    self.ai_hardware_info.setObjectName("AIEngineHardwareInfo")
    info_layout = QHBoxLayout(self.ai_hardware_info)
    info_layout.setContentsMargins(0, 0, 0, 0)
    info_layout.setSpacing(8)
    self.ai_hardware_name = QLabel("—")
    self.ai_hardware_name.setObjectName("AIEngineHardwareName")
    self.ai_hardware_name.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
    )
    info_layout.addWidget(self.ai_hardware_name, 0, Qt.AlignmentFlag.AlignVCenter)
    self.ai_hardware_chips = QHBoxLayout()
    self.ai_hardware_chips.setContentsMargins(0, 0, 0, 0)
    self.ai_hardware_chips.setSpacing(6)
    info_layout.addLayout(self.ai_hardware_chips)
    info_layout.addStretch(1)
    hardware_content.addWidget(self.ai_hardware_info)
    hardware_layout.addLayout(hardware_content, 1)

    hardware_refresh = QPushButton()
    hardware_refresh.setObjectName("AIEngineIconButton")
    hardware_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
    hardware_refresh.setToolTip(_("Обновить аппаратный профиль", "Refresh hardware profile"))
    _set_icon(hardware_refresh, "fa6s.rotate", size=15)
    hardware_refresh.clicked.connect(lambda: view_model.refresh_hardware(force=True))
    hardware_layout.addWidget(hardware_refresh, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(hardware_card)

    hub_card = QFrame()
    hub_card.setObjectName("AIEngineHubPanel")
    hub_card.setMinimumHeight(128)
    hub_layout = QHBoxLayout(hub_card)
    hub_layout.setContentsMargins(20, 20, 20, 20)
    hub_layout.setSpacing(16)
    hub_layout.addWidget(_card_icon("fa6s.cubes"), 0, Qt.AlignmentFlag.AlignTop)
    hub_text = QVBoxLayout()
    hub_text.setContentsMargins(0, 0, 0, 0)
    hub_text.setSpacing(8)
    hub_title = tr_set(QLabel(), "Модели и компоненты", "Models and components")
    hub_title.setObjectName("AIEngineCardTitle")
    hub_subtitle = tr_set(
        QLabel(),
        "Установка и удаление моделей TTS, ASR, RAG и их зависимостей.",
        "Install and remove TTS, ASR and RAG models with their dependencies.",
    )
    hub_subtitle.setObjectName("AIEngineCardSubtitle")
    hub_subtitle.setWordWrap(True)
    hub_text.addWidget(hub_title)
    hub_text.addWidget(hub_subtitle)

    self.ai_backend_notice = QFrame()
    self.ai_backend_notice.setObjectName("AIEngineBackendNotice")
    self.ai_backend_notice.setVisible(False)
    backend_notice_layout = QHBoxLayout(self.ai_backend_notice)
    backend_notice_layout.setContentsMargins(10, 8, 10, 8)
    backend_notice_layout.setSpacing(8)
    self.ai_backend_notice_icon = QLabel()
    self.ai_backend_notice_icon.setFixedSize(18, 18)
    self.ai_backend_notice_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    backend_notice_layout.addWidget(self.ai_backend_notice_icon, 0)
    self.ai_backend_notice_text = QLabel()
    self.ai_backend_notice_text.setObjectName("AIEngineBackendNoticeText")
    self.ai_backend_notice_text.setWordWrap(True)
    backend_notice_layout.addWidget(self.ai_backend_notice_text, 1)
    hub_text.addWidget(self.ai_backend_notice)

    hub_actions = QHBoxLayout()
    hub_actions.setContentsMargins(0, 3, 0, 0)
    open_hub = tr_set(QPushButton(), "Открыть AI Hub", "Open AI Hub")
    open_hub.setObjectName("SettingsHeaderPrimaryButton")
    open_hub.setCursor(Qt.CursorShape.PointingHandCursor)
    if qta is not None:
        try:
            open_hub.setIcon(qta.icon("fa6s.arrow-up-right-from-square", color="#ffffff"))
        except Exception:
            pass
    open_hub.clicked.connect(view_model.open_ai_hub)
    hub_actions.addWidget(open_hub, 0)
    hub_actions.addStretch(1)
    hub_text.addLayout(hub_actions)
    hub_layout.addLayout(hub_text, 1)
    layout.addWidget(hub_card)

    mode_card = QFrame()
    mode_card.setObjectName("AIEngineModePanel")
    mode_card.setMinimumHeight(178)
    mode_card_layout = QHBoxLayout(mode_card)
    mode_card_layout.setContentsMargins(20, 20, 20, 20)
    mode_card_layout.setSpacing(16)
    mode_card_layout.addWidget(
        _card_icon("fa6s.diagram-project"),
        0,
        Qt.AlignmentFlag.AlignTop,
    )

    mode_layout = QVBoxLayout()
    mode_layout.setContentsMargins(0, 0, 0, 0)
    mode_layout.setSpacing(12)

    mode_header = QHBoxLayout()
    mode_header.setSpacing(12)
    mode_title = tr_set(QLabel(), "Режим процессов", "Process mode")
    mode_title.setObjectName("AIEngineCardTitle")
    mode_header.addWidget(mode_title, 1)
    self.ai_engine_status = _chip(_("Запуск…", "Starting…"), "warning")
    mode_header.addWidget(self.ai_engine_status, 0, Qt.AlignmentFlag.AlignVCenter)
    mode_layout.addLayout(mode_header)

    mode_subtitle = tr_set(
        QLabel(),
        "Как AI-контуры распределяются между процессами приложения.",
        "How AI domains are distributed between application processes.",
    )
    mode_subtitle.setObjectName("AIEngineCardSubtitle")
    mode_layout.addWidget(mode_subtitle)

    selector_row = QHBoxLayout()
    selector_row.setContentsMargins(0, 0, 0, 0)
    selector_row.setSpacing(8)
    self.ai_engine_mode_combobox = QComboBox()
    self.ai_engine_mode_combobox.addItem(
        _(
            "Общий процесс (shared)",
            "Shared process (shared)",
        ),
        "shared",
    )
    self.ai_engine_mode_combobox.addItem(
        _(
            "Изолированные процессы (split)",
            "Isolated processes (split)",
        ),
        "split",
    )
    selector_row.addWidget(self.ai_engine_mode_combobox, 1)
    self.ai_engine_mode_apply = tr_set(QPushButton(), "Применено", "Applied")
    self.ai_engine_mode_apply.setObjectName("AIEngineApplyButton")
    self.ai_engine_mode_apply.setMinimumWidth(128)
    selector_row.addWidget(self.ai_engine_mode_apply, 0)
    mode_layout.addLayout(selector_row)

    self.ai_mode_description = QLabel()
    self.ai_mode_description.setObjectName("AIEngineModeDescription")
    self.ai_mode_description.setWordWrap(True)
    mode_layout.addWidget(self.ai_mode_description)

    self.ai_split_warning = QLabel()
    self.ai_split_warning.setObjectName("AIEngineModeWarning")
    self.ai_split_warning.setWordWrap(True)
    mode_layout.addWidget(self.ai_split_warning)
    mode_card_layout.addLayout(mode_layout, 1)
    layout.addWidget(mode_card)

    maintenance = InnerCollapsibleSection(
        _("Обслуживание AI-пакетов", "AI package maintenance"),
        parent=self,
    )
    maintenance_hint = tr_set(
        QLabel(),
        "Полный сброс установленных AI-зависимостей. Основное окружение приложения Lib/core не затрагивается.",
        "Fully reset installed AI dependencies. The main application environment in Lib/core is not touched.",
    )
    maintenance_hint.setObjectName("AIEngineMaintenanceHint")
    maintenance_hint.setWordWrap(True)
    maintenance.add_widget(maintenance_hint)

    self.ai_environment_path = QLabel("—")
    self.ai_environment_path.setObjectName("AIEngineEnvironmentPath")
    self.ai_environment_path.setWordWrap(True)
    self.ai_environment_path.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse
    )
    maintenance.add_widget(self.ai_environment_path)

    self.ai_maintenance_status = QLabel("—")
    self.ai_maintenance_status.setObjectName("AIEngineMaintenanceStatus")
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

    applied_mode = {"value": "", "rendered": ""}
    latest_state = {"value": view_model.state}

    def selected_mode() -> str:
        return str(self.ai_engine_mode_combobox.currentData() or "shared")

    def update_mode_copy() -> None:
        split = selected_mode() == "split"
        self.ai_mode_description.setText(
            _(
                "TTS, ASR, RAG и Beats работают в одном процессе и используют общий CUDA context. Это режим с минимальным расходом VRAM.",
                "TTS, ASR, RAG and Beats run in one process and share one CUDA context. This mode uses the least VRAM.",
            )
            if not split
            else ""
        )
        self.ai_split_warning.setText(
            _(
                "TTS, ASR, RAG и Beats получают отдельные процессы: падения и конфликты зависимостей изолированы. При этом создаётся несколько CUDA contexts, поэтому расход RAM и VRAM выше.",
                "TTS, ASR, RAG and Beats get separate processes, isolating crashes and dependency conflicts. This creates multiple CUDA contexts, so RAM and VRAM usage is higher.",
            )
        )
        self.ai_mode_description.setVisible(not split)
        self.ai_split_warning.setVisible(split)

    def update_apply_button() -> None:
        state = latest_state["value"]
        topology = dict(state.topology or {})
        override = topology.get("override")
        dirty = bool(applied_mode["value"]) and selected_mode() != applied_mode["value"]
        applying = bool(state.busy and dirty)
        enabled = bool(dirty and not state.busy and topology and not override)
        self.ai_engine_mode_apply.setEnabled(enabled)
        self.ai_engine_mode_apply.setProperty("dirty", dirty)
        if not applied_mode["value"]:
            button_text = (
                _("Недоступно", "Unavailable")
                if state.topology_error
                else _("Загрузка…", "Loading…")
            )
        elif applying:
            button_text = _("Применение…", "Applying…")
        elif dirty:
            button_text = _("Применить", "Apply")
        else:
            button_text = _("Применено", "Applied")
        self.ai_engine_mode_apply.setText(button_text)
        self.ai_engine_mode_apply.setToolTip(
            _(
                "Режим зафиксирован переменной окружения NEUROMITA_AI_ENGINE_MODE.",
                "The mode is locked by the NEUROMITA_AI_ENGINE_MODE environment variable.",
            )
            if override
            else ""
        )
        style = self.ai_engine_mode_apply.style()
        if style is not None:
            style.unpolish(self.ai_engine_mode_apply)
            style.polish(self.ai_engine_mode_apply)
        self.ai_engine_mode_apply.update()

    def on_mode_selected() -> None:
        update_mode_copy()
        update_apply_button()

    self.ai_engine_mode_combobox.currentIndexChanged.connect(on_mode_selected)
    self.ai_engine_mode_apply.clicked.connect(
        lambda: view_model.switch_mode(selected_mode())
    )

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

    def render_hardware(state) -> None:
        hardware = dict(state.hardware or {})
        primary = dict(hardware.get("primary") or {})
        loading = bool(
            state.hardware_loading
            or (not hardware and not state.hardware_error)
        )
        self.ai_hardware_loading.setVisible(loading)
        self.ai_hardware_info.setVisible(not loading)
        if loading:
            return

        vendor = str(hardware.get("vendor") or "CPU").upper()
        name = str(
            primary.get("name")
            or (
                _("Не удалось определить видеокарту", "Could not detect graphics adapter")
                if state.hardware_error
                else _("Видеокарта не обнаружена", "No graphics adapter detected")
            )
        )
        vendor_id = str(primary.get("vendor_id") or "—").upper()
        device_id = str(primary.get("device_id") or "—").upper()
        vram = _format_bytes(primary.get("dedicated_vram_bytes"))
        cuda = dict(hardware.get("cuda") or {})
        cuda_devices = list(cuda.get("devices") or [])
        driver = str(cuda.get("driver_version") or "—")
        capabilities = ", ".join(
            str(item.get("compute_capability") or "").upper()
            for item in cuda_devices
            if item.get("compute_capability")
        )
        tooltip = f"PCI {vendor_id}:{device_id}"
        if cuda.get("available"):
            tooltip += f"\nCUDA Driver {driver}"
            if capabilities:
                tooltip += f" · {capabilities}"
        self.ai_hardware_name.setText(name)
        self.ai_hardware_name.setToolTip(tooltip)
        hardware_card.setToolTip(tooltip)

        _clear_layout(self.ai_hardware_chips)
        if state.hardware_error:
            self.ai_hardware_chips.addWidget(
                _chip(_("Ошибка проверки", "Detection failed"), "warning")
            )
            hardware_card.setToolTip(state.hardware_error)
        elif vendor == "NVIDIA":
            self.ai_hardware_chips.addWidget(_chip("NVIDIA", "gpu"))
            if cuda.get("available"):
                self.ai_hardware_chips.addWidget(
                    _chip("CUDA", "cuda", f"CUDA Driver {driver}")
                )
            else:
                self.ai_hardware_chips.addWidget(
                    _chip(_("CUDA недоступна", "CUDA unavailable"), "warning")
                )
        elif vendor == "AMD":
            self.ai_hardware_chips.addWidget(_chip("AMD", "gpu"))
            self.ai_hardware_chips.addWidget(_chip("ONNX", "onnx"))
            self.ai_hardware_chips.addWidget(_chip("DirectML"))
        elif vendor == "INTEL":
            self.ai_hardware_chips.addWidget(_chip("INTEL", "gpu"))
            self.ai_hardware_chips.addWidget(_chip("ONNX", "onnx"))
        else:
            self.ai_hardware_chips.addWidget(_chip("CPU"))
            self.ai_hardware_chips.addWidget(_chip("ONNX", "onnx"))
        if primary.get("dedicated_vram_bytes"):
            self.ai_hardware_chips.addWidget(_chip(f"VRAM {vram}"))
        if capabilities:
            self.ai_hardware_chips.addWidget(_chip(capabilities))

    def render_topology(state) -> None:
        topology = dict(state.topology or {})
        mode = str(topology.get("mode") or "")
        if mode and mode != applied_mode["rendered"]:
            applied_mode["value"] = mode
            applied_mode["rendered"] = mode
            index = self.ai_engine_mode_combobox.findData(mode)
            if index >= 0:
                self.ai_engine_mode_combobox.blockSignals(True)
                self.ai_engine_mode_combobox.setCurrentIndex(index)
                self.ai_engine_mode_combobox.blockSignals(False)
            update_mode_copy()

        workers = dict(topology.get("workers") or {})
        alive = sum(1 for item in workers.values() if item.get("alive"))
        total = len(workers)
        ready = bool(total and alive == total)
        if state.topology_error and not topology:
            status = _("AI Engine недоступен", "AI Engine unavailable")
        elif state.topology_loading and not topology:
            status = _("AI Engine запускается…", "AI Engine is starting…")
        elif not total:
            status = _("Процессы не запущены", "Processes are not running")
        elif mode == "shared" and ready:
            status = _("Процесс работает", "Process is running")
        else:
            status = _(
                "Процессы: {alive} из {total}",
                "Processes: {alive} of {total}",
            ).format(alive=alive, total=total)
        self.ai_engine_status.setText(status)
        self.ai_engine_status.setObjectName(
            "AIEngineChipSuccess" if ready else "AIEngineChipWarning"
        )
        style = self.ai_engine_status.style()
        if style is not None:
            style.unpolish(self.ai_engine_status)
            style.polish(self.ai_engine_status)
        update_apply_button()

    def render_backends(state) -> None:
        ready: dict[str, str] = {}
        for row in state.backends or ():
            metadata = row.get("metadata") if isinstance(row, dict) else None
            status = row.get("status") if isinstance(row, dict) else None
            if not isinstance(metadata, dict) or not isinstance(status, dict):
                continue
            if status.get("ready"):
                item_id = str(metadata.get("item_id") or "").strip().lower()
                if item_id:
                    ready[item_id] = str(metadata.get("title") or item_id.upper())

        if "cuda" in ready:
            ready.pop("cpu", None)
        installed = [ready[item] for item in ("cuda", "cpu", "onnx") if item in ready]
        multiple = len(installed) > 1
        self.ai_backend_notice.setVisible(multiple)
        if not multiple:
            return

        shared = str((state.topology or {}).get("mode") or "shared") == "shared"
        severity = "warning" if shared else "info"
        self.ai_backend_notice.setProperty("severity", severity)
        backend_names = " + ".join(installed)
        self.ai_backend_notice_text.setText(
            _(
                "Установлены {backends}. В режиме shared выбранные модели загружаются в один процесс, поэтому возможны конфликты нативных библиотек. При ошибках совместимости используйте split.",
                "Installed: {backends}. In shared mode, selected models load into one process, so native-library conflicts are possible. Use split if compatibility errors occur.",
            ).format(backends=backend_names)
            if shared
            else _(
                "Установлены {backends}. Режим split позволяет изолировать их по AI-контурам.",
                "Installed: {backends}. Split mode can isolate them by AI domain.",
            ).format(backends=backend_names)
        )
        if qta is not None:
            try:
                self.ai_backend_notice_icon.setPixmap(
                    qta.icon(
                        "fa6s.triangle-exclamation" if shared else "fa6s.circle-info",
                        color="#f0a64a" if shared else "#9cc3ff",
                    ).pixmap(15, 15)
                )
            except Exception:
                pass
        style = self.ai_backend_notice.style()
        if style is not None:
            style.unpolish(self.ai_backend_notice)
            style.polish(self.ai_backend_notice)
        self.ai_backend_notice.update()

    def render_maintenance(state) -> None:
        maintenance_state = dict(state.maintenance or {})
        path = str(maintenance_state.get("path") or "—")
        size = maintenance_state.get("size_bytes")
        if state.maintenance_loading and not maintenance_state:
            self.ai_environment_path.setText(
                _("Подсчитываем размер AI-окружений…", "Calculating AI environment size…")
            )
        else:
            self.ai_environment_path.setText(
                f"{path}" + (f"\n{_format_bytes(size)}" if size is not None else "")
            )
        message = str(maintenance_state.get("message") or "")
        error = str(
            maintenance_state.get("error")
            or state.maintenance_error
            or ""
        )
        self.ai_maintenance_status.setText(
            error or message or _("Готово", "Ready")
        )
        busy = bool(state.busy or maintenance_state.get("busy"))
        self.ai_environment_reset.setEnabled(
            not busy and bool(maintenance_state.get("path"))
        )

    def render(state) -> None:
        latest_state["value"] = state
        render_hardware(state)
        render_topology(state)
        render_backends(state)
        render_maintenance(state)
        hardware_refresh.setEnabled(not state.hardware_loading and not state.busy)

    view_model.state_changed.connect(render)
    render(view_model.state)
    update_mode_copy()
    QTimer.singleShot(0, view_model.refresh)
