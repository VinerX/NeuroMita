"""Settings panel - Updates section.

Provides channel selection, tester code, Unity install path, and
a "Check now" button that runs update checks in a background thread.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QWidget,
    QVBoxLayout,
)

from ui.gui_templates import create_section_header
from utils import getTranslationVariant as _


def setup_updates_settings_controls(self, parent):
    create_section_header(parent, _("Обновления", "Updates"))

    def _persist_setting(key: str, value):
        if hasattr(self, "_save_setting"):
            self._save_setting(key, value)
            return
        try:
            self.settings.set(key, value)
            self.settings.save_settings()
        except Exception:
            pass

    # Current versions
    try:
        from _version import __version__ as py_ver
    except Exception:
        py_ver = "?"

    unity_ver = "?"
    try:
        base_dir = os.environ.get("NEUROMITA_BASE_DIR", "")
        unity_path = Path(base_dir).parent / "NeuroMita-Unity"
        unity_dir_setting = self.settings.get("UNITY_INSTALL_DIR", "")
        if unity_dir_setting:
            unity_path = Path(unity_dir_setting)
        ver_file = unity_path / "_version.txt"
        if ver_file.exists():
            unity_ver = ver_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    ver_widget = QWidget()
    ver_widget.setStyleSheet(
        "QWidget { background: #1e1e2e; border: 1px solid #3a3a5c; border-radius: 6px; }"
    )
    ver_layout = QVBoxLayout(ver_widget)
    ver_layout.setContentsMargins(10, 8, 10, 8)
    ver_layout.setSpacing(2)

    lbl_py = QLabel(_("Python-часть: ", "Python part: ") + f"<b>{py_ver}</b>")
    lbl_py.setStyleSheet(
        "QLabel { background: transparent; border: none; color: #b0b0d0; font-size: 11px; }"
    )
    lbl_py.setTextFormat(Qt.TextFormat.RichText)
    ver_layout.addWidget(lbl_py)

    lbl_unity = QLabel(_("Unity-часть: ", "Unity part: ") + f"<b>{unity_ver}</b>")
    lbl_unity.setStyleSheet(
        "QLabel { background: transparent; border: none; color: #b0b0d0; font-size: 11px; }"
    )
    lbl_unity.setTextFormat(Qt.TextFormat.RichText)
    ver_layout.addWidget(lbl_unity)

    parent.addWidget(ver_widget)

    # Channel
    channel_row = QWidget()
    channel_layout = QHBoxLayout(channel_row)
    channel_layout.setContentsMargins(0, 4, 0, 0)
    channel_layout.setSpacing(8)

    channel_lbl = QLabel(_("Канал обновлений:", "Update channel:"))
    channel_lbl.setStyleSheet("QLabel { color: #c0c0d8; font-size: 12px; }")
    channel_layout.addWidget(channel_lbl)

    channel_combo = QComboBox()
    channel_combo.addItems(["stable", "beta"])
    current_channel = self.settings.get("UPDATE_CHANNEL", "stable")
    idx = channel_combo.findText(current_channel)
    if idx >= 0:
        channel_combo.setCurrentIndex(idx)
    channel_combo.setToolTip(
        _(
            "stable - официальные релизы.\n"
            "beta - включая пре-релизы.",
            "stable - official releases.\n"
            "beta - including pre-releases.",
        )
    )

    def _save_channel(text: str):
        if text == self.settings.get("UPDATE_CHANNEL", "stable"):
            return
        _persist_setting("UPDATE_CHANNEL", text)

    def _on_channel_activated(_index: int):
        selected = channel_combo.currentText()
        QTimer.singleShot(0, lambda: _save_channel(selected))

    channel_combo.activated.connect(_on_channel_activated)
    channel_layout.addWidget(channel_combo)
    channel_layout.addStretch()
    parent.addWidget(channel_row)

    # Auto-update checkboxes
    chk_auto = QCheckBox(_("Авто-обновление Python при запуске", "Auto-update Python on startup"))
    chk_auto.setToolTip(_("AUTO_UPDATE=1 в features.env", "AUTO_UPDATE=1 in features.env"))
    chk_auto.setChecked(bool(self.settings.get("AUTO_UPDATE_CHECK", False)))

    def _save_auto(state):
        _persist_setting("AUTO_UPDATE_CHECK", bool(state))

    chk_auto.stateChanged.connect(_save_auto)
    parent.addWidget(chk_auto)

    chk_unity = QCheckBox(_("Авто-обновление Unity при запуске", "Auto-update Unity on startup"))
    chk_unity.setToolTip(
        _(
            "Скачивает Unity-часть мода если вышла новая версия",
            "Downloads Unity part of the mod when a new version is released",
        )
    )
    chk_unity.setChecked(bool(self.settings.get("AUTO_UPDATE_UNITY", False)))

    def _save_unity_auto(state):
        _persist_setting("AUTO_UPDATE_UNITY", bool(state))

    chk_unity.stateChanged.connect(_save_unity_auto)
    parent.addWidget(chk_unity)

    # Tester code
    tester_row = QWidget()
    tester_layout = QHBoxLayout(tester_row)
    tester_layout.setContentsMargins(0, 4, 0, 0)
    tester_layout.setSpacing(8)

    tester_lbl = QLabel(_("Код тестера:", "Tester code:"))
    tester_lbl.setStyleSheet("QLabel { color: #c0c0d8; font-size: 12px; }")
    tester_lbl.setFixedWidth(100)
    tester_layout.addWidget(tester_lbl)

    tester_entry = QLineEdit()
    tester_entry.setEchoMode(QLineEdit.EchoMode.Password)
    tester_entry.setPlaceholderText(_("пароль для тестовых архивов", "password for test archives"))
    tester_entry.setText(self.settings.get("TESTER_CODE", ""))
    tester_entry.setToolTip(
        _(
            "Пароль для распаковки зашифрованных тестовых архивов.",
            "Password to unpack encrypted tester archives.",
        )
    )

    def _save_tester():
        _persist_setting("TESTER_CODE", tester_entry.text())

    tester_entry.editingFinished.connect(_save_tester)
    tester_layout.addWidget(tester_entry)
    parent.addWidget(tester_row)

    # Unity install dir
    unity_row = QWidget()
    unity_layout = QHBoxLayout(unity_row)
    unity_layout.setContentsMargins(0, 4, 0, 0)
    unity_layout.setSpacing(4)

    unity_lbl = QLabel(_("Папка Unity:", "Unity folder:"))
    unity_lbl.setStyleSheet("QLabel { color: #c0c0d8; font-size: 12px; }")
    unity_lbl.setFixedWidth(100)
    unity_layout.addWidget(unity_lbl)

    unity_entry = QLineEdit()
    unity_entry.setPlaceholderText(_("по умолчанию: ../NeuroMita-Unity", "default: ../NeuroMita-Unity"))
    unity_entry.setText(self.settings.get("UNITY_INSTALL_DIR", ""))
    unity_layout.addWidget(unity_entry)

    unity_browse = QPushButton("...")
    unity_browse.setFixedWidth(32)
    unity_browse.setToolTip(_("Выбрать папку", "Browse folder"))

    def _browse_unity():
        directory = QFileDialog.getExistingDirectory(
            None,
            _("Выбрать папку Unity", "Select Unity folder"),
            unity_entry.text() or str(Path.home()),
        )
        if directory:
            unity_entry.setText(directory)
            _persist_setting("UNITY_INSTALL_DIR", directory)

    unity_browse.clicked.connect(_browse_unity)
    unity_layout.addWidget(unity_browse)

    def _save_unity_dir():
        _persist_setting("UNITY_INSTALL_DIR", unity_entry.text())

    unity_entry.editingFinished.connect(_save_unity_dir)
    parent.addWidget(unity_row)

    # Progress + status
    progress_bar = QProgressBar()
    progress_bar.setRange(0, 100)
    progress_bar.setValue(0)
    progress_bar.setVisible(False)
    progress_bar.setStyleSheet(
        "QProgressBar { border: 1px solid #3a3a5c; border-radius: 4px; background: #1a1a2e; height: 14px; text-align: center; color: #c0c0d8; font-size: 10px; }"
        "QProgressBar::chunk { background: #6060c0; border-radius: 3px; }"
    )
    parent.addWidget(progress_bar)

    status_lbl = QLabel("")
    status_lbl.setWordWrap(True)
    status_lbl.setStyleSheet("QLabel { color: #a0a0c0; font-size: 11px; padding: 2px 0; }")
    parent.addWidget(status_lbl)

    # Check now button
    btn_check = QPushButton(_("Проверить обновления", "Check for updates"))
    btn_check.setStyleSheet(
        "QPushButton { background: #3a3a7c; color: #e0e0ff; border: none; border-radius: 5px; padding: 6px 12px; font-size: 12px; }"
        "QPushButton:hover { background: #4a4a9c; }"
        "QPushButton:disabled { background: #2a2a4c; color: #606080; }"
    )

    def _on_progress(downloaded: int, total: int):
        if total > 0:
            pct = int(downloaded * 100 / total)
            mb_done = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            QTimer.singleShot(0, lambda: _update_progress(pct, f"{mb_done:.1f} / {mb_total:.1f} MB"))
        else:
            mb_done = downloaded / (1024 * 1024)
            QTimer.singleShot(0, lambda: _update_progress(-1, f"{mb_done:.1f} MB"))

    def _update_progress(pct: int, text: str):
        progress_bar.setVisible(True)
        if pct >= 0:
            progress_bar.setRange(0, 100)
            progress_bar.setValue(pct)
        else:
            progress_bar.setRange(0, 0)
        status_lbl.setText(text)

    def _set_status(msg: str):
        QTimer.singleShot(0, lambda: status_lbl.setText(msg))

    def _run_check():
        try:
            from updater import check_for_updates, check_for_unity_updates
        except ImportError as e:
            QTimer.singleShot(0, lambda: status_lbl.setText(f"Import error: {e}"))
            QTimer.singleShot(0, lambda: btn_check.setEnabled(True))
            return

        ch = self.settings.get("UPDATE_CHANNEL", "stable")
        tc = self.settings.get("TESTER_CODE") or None
        bd = os.environ.get("NEUROMITA_BASE_DIR") or None
        ud = self.settings.get("UNITY_INSTALL_DIR") or None

        class _UiLogger:
            def info(self, msg):
                _set_status(msg)

            def warning(self, msg):
                _set_status(f"⚠ {msg}")

            def error(self, msg):
                _set_status(f"✗ {msg}")

            def success(self, msg):
                _set_status(f"✓ {msg}")

            def notify(self, msg):
                _set_status(f"★ {msg}")

        ui_log = _UiLogger()

        try:
            check_for_updates(
                base_dir=bd,
                logger=ui_log,
                channel=ch,
                tester_code=tc,
                on_progress=_on_progress,
            )
        except SystemExit:
            raise
        except Exception as e:
            _set_status(f"Python update error: {e}")

        try:
            check_for_unity_updates(
                base_dir=bd,
                logger=ui_log,
                unity_dir=ud,
                channel=ch,
                tester_code=tc,
                on_progress=_on_progress,
            )
        except Exception as e:
            _set_status(f"Unity update error: {e}")

        QTimer.singleShot(0, lambda: progress_bar.setVisible(False))
        QTimer.singleShot(0, lambda: btn_check.setEnabled(True))

    def _on_check_clicked():
        btn_check.setEnabled(False)
        progress_bar.setValue(0)
        progress_bar.setVisible(True)
        status_lbl.setText(_("Проверяю...", "Checking ..."))
        thread = threading.Thread(target=_run_check, daemon=True)
        thread.start()

    btn_check.clicked.connect(_on_check_clicked)
    parent.addWidget(btn_check)
