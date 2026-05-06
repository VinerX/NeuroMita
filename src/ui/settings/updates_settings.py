"""Settings panel for Python/Unity updates."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QWidget,
    QVBoxLayout,
)

from main_logger import logger
from ui.gui_templates import create_section_header
from utils import getTranslationVariant as _


def setup_updates_settings_controls(self, parent):
    create_section_header(parent, _("Обновления", "Updates"))

    class _Dispatch(QObject):
        _go = pyqtSignal(object)

        def __init__(self):
            super().__init__()
            self._go.connect(lambda fn: fn())

        def schedule(self, fn):
            self._go.emit(fn)

    _dispatch = _Dispatch()

    def _persist_setting(key: str, value):
        if hasattr(self, "_save_setting"):
            self._save_setting(key, value)
            return
        try:
            self.settings.set(key, value)
            self.settings.save_settings()
        except Exception:
            logger.error(f"[updates_ui] Failed to persist setting {key!r}", exc_info=True)

    def _current_unity_dir() -> Path:
        base_dir = os.environ.get("NEUROMITA_BASE_DIR", "")
        unity_path = Path(base_dir).parent / "NeuroMita-Unity"
        unity_dir_setting = self.settings.get("UNITY_INSTALL_DIR", "")
        if unity_dir_setting:
            unity_path = Path(unity_dir_setting)
        return unity_path

    def _current_unity_version() -> str:
        try:
            ver_file = _current_unity_dir() / "_version.txt"
            if ver_file.exists():
                return ver_file.read_text(encoding="utf-8").strip() or "?"
        except Exception:
            logger.warning("[updates_ui] Failed to read Unity version", exc_info=True)
        return "?"

    def _find_unity_executable(unity_dir: Path) -> Path | None:
        if not unity_dir.exists() or not unity_dir.is_dir():
            return None

        exe_files = list(unity_dir.glob("*.exe"))
        if not exe_files:
            return None

        preferred_names = (
            "NeuroMita.exe",
            "NeuroMita-Unity.exe",
            "Unity.exe",
        )
        lower_map = {path.name.lower(): path for path in exe_files}
        for name in preferred_names:
            found = lower_map.get(name.lower())
            if found is not None:
                return found

        for path in exe_files:
            low = path.name.lower()
            if "neuromita" in low or "unity" in low:
                return path

        return exe_files[0]

    def _refresh_version_labels():
        try:
            from _version import __version__ as py_ver
        except Exception:
            py_ver = "?"
        lbl_py.setText(_("Python-часть: ", "Python part: ") + f"<b>{py_ver}</b>")
        lbl_unity.setText(_("Unity-часть: ", "Unity part: ") + f"<b>{_current_unity_version()}</b>")

    def _set_status(msg: str):
        logger.info(f"[updates_ui] {msg}")
        _dispatch.schedule(lambda: status_lbl.setText(msg))

    def _set_status_level(msg: str, level: str = "info"):
        log_fn = getattr(logger, level, logger.info)
        log_fn(f"[updates_ui] {msg}")
        _dispatch.schedule(lambda: status_lbl.setText(msg))

    def _update_progress(pct: int | None, text: str, busy: bool = False):
        def apply():
            progress_bar.setVisible(True)
            if busy or pct is None:
                progress_bar.setRange(0, 0)
            else:
                progress_bar.setRange(0, 100)
                progress_bar.setValue(max(0, min(100, pct)))
            status_lbl.setText(text)

        _dispatch.schedule(apply)

    def _hide_progress():
        _dispatch.schedule(lambda: progress_bar.setVisible(False))

    def _set_buttons_enabled(enabled: bool):
        _dispatch.schedule(lambda: btn_check.setEnabled(enabled))
        _dispatch.schedule(lambda: btn_install.setEnabled(enabled))

    def _render_update_info(py_info: dict | None, unity_info: dict | None):
        chunks: list[str] = []
        if py_info:
            chunks.append(_format_component_info(_("Python", "Python"), py_info))
        if unity_info:
            chunks.append(_format_component_info(_("Unity", "Unity"), unity_info))
        text = "\n\n".join(chunk for chunk in chunks if chunk).strip()
        if not text:
            text = _("Нет данных об обновлениях.", "No update information yet.")
        _dispatch.schedule(lambda: release_info.setPlainText(text))

    def _format_component_info(title: str, info: dict) -> str:
        if not info.get("ok"):
            err = info.get("error") or _("Неизвестная ошибка", "Unknown error")
            return f"{title}\n{_('Ошибка проверки', 'Check error')}: {err}"

        current_version = info.get("current_version") or "?"
        latest_version = info.get("latest_version") or "?"
        available = bool(info.get("available"))
        prerelease = bool(info.get("prerelease"))
        name = str(info.get("name") or "")
        published_at = str(info.get("published_at") or "")
        body = str(info.get("body") or "").strip()
        if len(body) > 1200:
            body = body[:1200].rstrip() + "\n..."

        lines = [
            title,
            f"{_('Текущая версия', 'Current version')}: {current_version}",
            f"{_('Последняя версия', 'Latest version')}: {latest_version}",
            f"{_('Доступно обновление', 'Update available')}: {(_('да', 'yes') if available else _('нет', 'no'))}",
        ]
        if prerelease:
            lines.append(_("Канал содержит prerelease.", "Channel contains prerelease."))
        if name:
            lines.append(f"{_('Заголовок релиза', 'Release title')}: {name}")
        if published_at:
            lines.append(f"{_('Дата публикации', 'Published at')}: {published_at}")
        if body:
            lines.extend(["", _("Что нового:", "What's new:"), body])
        return "\n".join(lines)

    def _on_progress(downloaded: int, total: int):
        if total > 0:
            pct = int(downloaded * 100 / total)
            mb_done = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            text = f"{mb_done:.1f} / {mb_total:.1f} MB"
            logger.info(f"[updates_ui] Download progress: {pct}% ({text})")
            _update_progress(pct, text)
        else:
            mb_done = downloaded / (1024 * 1024)
            text = f"{mb_done:.1f} MB"
            logger.info(f"[updates_ui] Download progress: {text}")
            _update_progress(None, text, busy=True)

    def _run_check_only():
        logger.info("[updates_ui] Check-only action started")
        _set_buttons_enabled(False)
        _update_progress(None, _("Проверяю релизы...", "Checking releases..."), busy=True)
        try:
            from updater import get_python_update_info, get_unity_update_info

            channel = self.settings.get("UPDATE_CHANNEL", "stable")
            base_dir = os.environ.get("NEUROMITA_BASE_DIR") or None
            unity_dir = self.settings.get("UNITY_INSTALL_DIR") or None

            logger.info(
                f"[updates_ui] Check-only params: channel={channel}, base_dir={base_dir}, unity_dir={unity_dir}"
            )

            py_info = get_python_update_info(base_dir=base_dir, channel=channel)
            unity_info = get_unity_update_info(base_dir=base_dir, unity_dir=unity_dir, channel=channel)
            _render_update_info(py_info, unity_info)

            if bool(py_info.get("available")) or bool(unity_info.get("available")):
                _set_status_level(_("Обновления найдены. Смотри информацию ниже.", "Updates found. See details below."), "notify")
            else:
                _set_status(_("Новых обновлений не найдено.", "No new updates found."))
        except Exception as e:
            logger.error("[updates_ui] Check-only action failed", exc_info=True)
            _set_status_level(f"{_('Ошибка проверки', 'Check error')}: {e}", "error")
        finally:
            _hide_progress()
            _set_buttons_enabled(True)

    def _run_install():
        logger.info("[updates_ui] Install action started")
        _set_buttons_enabled(False)
        _update_progress(None, _("Подготовка к установке...", "Preparing installation..."), busy=True)
        try:
            from updater import (
                check_for_unity_updates,
                check_for_updates,
                get_python_update_info,
                get_unity_update_info,
            )

            channel = self.settings.get("UPDATE_CHANNEL", "stable")
            tester_code = self.settings.get("TESTER_CODE") or None
            base_dir = os.environ.get("NEUROMITA_BASE_DIR") or None
            unity_dir = self.settings.get("UNITY_INSTALL_DIR") or None

            logger.info(
                f"[updates_ui] Install params: channel={channel}, base_dir={base_dir}, unity_dir={unity_dir}, "
                f"tester_code={'set' if tester_code else 'empty'}"
            )

            py_info = get_python_update_info(base_dir=base_dir, channel=channel)
            unity_info = get_unity_update_info(base_dir=base_dir, unity_dir=unity_dir, channel=channel)
            _render_update_info(py_info, unity_info)

            if not bool(py_info.get("available")) and not bool(unity_info.get("available")):
                _set_status(_("Новых обновлений не найдено.", "No new updates found."))
                return

            class _UiLogger:
                def info(self, msg):
                    _set_status(msg)

                def warning(self, msg):
                    _set_status_level(f"⚠ {msg}", "warning")

                def error(self, msg):
                    _set_status_level(f"✗ {msg}", "error")

                def success(self, msg):
                    _set_status_level(f"✓ {msg}", "success")

                def notify(self, msg):
                    _set_status_level(f"★ {msg}", "notify")

            ui_log = _UiLogger()

            if bool(py_info.get("available")):
                _set_status(_("Устанавливаю Python-обновление...", "Installing Python update..."))
                check_for_updates(
                    base_dir=base_dir,
                    logger=ui_log,
                    channel=channel,
                    tester_code=tester_code,
                    on_progress=_on_progress,
                    auto_update=True,
                )

            if bool(unity_info.get("available")):
                _set_status(_("Устанавливаю Unity-обновление...", "Installing Unity update..."))
                check_for_unity_updates(
                    base_dir=base_dir,
                    logger=ui_log,
                    unity_dir=unity_dir,
                    channel=channel,
                    tester_code=tester_code,
                    on_progress=_on_progress,
                    auto_update=True,
                )

            _refresh_version_labels()
        except SystemExit as e:
            logger.warning(f"[updates_ui] Install action requested process exit: code={getattr(e, 'code', None)}")
            _set_status_level(
                _("Python-обновление установлено. Перезапусти приложение.", "Python update installed. Restart the app."),
                "success",
            )
            _refresh_version_labels()
        except Exception as e:
            logger.error("[updates_ui] Install action failed", exc_info=True)
            _set_status_level(f"{_('Ошибка установки', 'Install error')}: {e}", "error")
        finally:
            _hide_progress()
            _set_buttons_enabled(True)

    def _launch_unity():
        unity_dir_text = unity_entry.text().strip()
        unity_dir = Path(unity_dir_text) if unity_dir_text else _current_unity_dir()
        logger.info(f"[updates_ui] Unity launch requested from {unity_dir}")
        try:
            exe_path = _find_unity_executable(unity_dir)
            if exe_path is None:
                _set_status_level(_("Не найден .exe в папке Unity.", "No .exe found in the Unity folder."), "warning")
                return

            os.startfile(str(exe_path))
            _set_status_level(_("Запускаю Unity...", "Launching Unity..."), "notify")
        except Exception as e:
            logger.error("[updates_ui] Failed to launch Unity", exc_info=True)
            _set_status_level(f"{_('Ошибка запуска Unity', 'Unity launch error')}: {e}", "error")

    # Current versions
    try:
        from _version import __version__ as py_ver
    except Exception:
        py_ver = "?"

    ver_widget = QWidget()
    ver_widget.setStyleSheet(
        "QWidget { background: transparent; border: none; }"
    )
    ver_layout = QVBoxLayout(ver_widget)
    ver_layout.setContentsMargins(10, 8, 10, 8)
    ver_layout.setSpacing(2)

    lbl_py = QLabel(_("Python-часть: ", "Python part: ") + f"<b>{py_ver}</b>")
    lbl_py.setStyleSheet("QLabel { background: transparent; border: none; color: #bca9bb; font-size: 11px; }")
    lbl_py.setTextFormat(Qt.TextFormat.RichText)
    ver_layout.addWidget(lbl_py)

    lbl_unity = QLabel(_("Unity-часть: ", "Unity part: ") + f"<b>{_current_unity_version()}</b>")
    lbl_unity.setStyleSheet("QLabel { background: transparent; border: none; color: #bca9bb; font-size: 11px; }")
    lbl_unity.setTextFormat(Qt.TextFormat.RichText)
    ver_layout.addWidget(lbl_unity)
    parent.addWidget(ver_widget)

    # Channel
    channel_row = QWidget()
    channel_row.setObjectName("UpdatesChannelRow")
    channel_row.setStyleSheet("QWidget#UpdatesChannelRow { background: transparent; }")
    channel_layout = QHBoxLayout(channel_row)
    channel_layout.setContentsMargins(0, 4, 0, 0)
    channel_layout.setSpacing(8)

    channel_lbl = QLabel(_("Канал обновлений:", "Update channel:"))
    channel_lbl.setStyleSheet("QLabel { color: #bca9bb; font-size: 12px; }")
    channel_layout.addWidget(channel_lbl)

    channel_combo = QComboBox()
    channel_combo.setStyleSheet("QComboBox { background: transparent; }")
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
        logger.info(f"[updates_ui] UPDATE_CHANNEL -> {text}")
        _persist_setting("UPDATE_CHANNEL", text)

    channel_combo.activated.connect(lambda _index: QTimer.singleShot(0, lambda: _save_channel(channel_combo.currentText())))
    channel_layout.addWidget(channel_combo)
    channel_layout.addStretch()
    parent.addWidget(channel_row)

    # Auto-update checkboxes
    chk_auto = QCheckBox(_("Авто-обновление Python при запуске", "Auto-update Python on startup"))
    chk_auto.setToolTip(_("AUTO_UPDATE=1 в features.env", "AUTO_UPDATE=1 in features.env"))
    chk_auto.setChecked(bool(self.settings.get("AUTO_UPDATE", self.settings.get("AUTO_UPDATE_CHECK", False))))

    def _save_auto(state):
        enabled = bool(state)
        logger.info(f"[updates_ui] AUTO_UPDATE -> {enabled}")
        _persist_setting("AUTO_UPDATE", enabled)
        _persist_setting("AUTO_UPDATE_CHECK", enabled)

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
        enabled = bool(state)
        logger.info(f"[updates_ui] AUTO_UPDATE_UNITY -> {enabled}")
        _persist_setting("AUTO_UPDATE_UNITY", enabled)

    chk_unity.stateChanged.connect(_save_unity_auto)
    parent.addWidget(chk_unity)

    # Tester code
    tester_row = QWidget()
    tester_row.setObjectName("UpdatesTesterRow")
    tester_row.setStyleSheet("QWidget#UpdatesTesterRow { background: transparent; }")
    tester_layout = QHBoxLayout(tester_row)
    tester_layout.setContentsMargins(0, 4, 0, 0)
    tester_layout.setSpacing(8)

    tester_lbl = QLabel(_("Код тестера:", "Tester code:"))
    tester_lbl.setStyleSheet("QLabel { color: #bca9bb; font-size: 12px; }")
    tester_lbl.setFixedWidth(100)
    tester_layout.addWidget(tester_lbl)

    tester_entry = QLineEdit()
    tester_entry.setStyleSheet("QLineEdit { background: transparent; }")
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
        logger.info("[updates_ui] TESTER_CODE updated")
        _persist_setting("TESTER_CODE", tester_entry.text())

    tester_entry.editingFinished.connect(_save_tester)
    tester_layout.addWidget(tester_entry)
    parent.addWidget(tester_row)

    # Unity install dir
    unity_row = QWidget()
    unity_row.setObjectName("UpdatesUnityRow")
    unity_row.setStyleSheet("QWidget#UpdatesUnityRow { background: transparent; }")
    unity_layout = QHBoxLayout(unity_row)
    unity_layout.setContentsMargins(0, 4, 0, 0)
    unity_layout.setSpacing(4)

    unity_lbl = QLabel(_("Папка Unity:", "Unity folder:"))
    unity_lbl.setStyleSheet("QLabel { color: #bca9bb; font-size: 12px; }")
    unity_lbl.setFixedWidth(100)
    unity_layout.addWidget(unity_lbl)

    unity_entry = QLineEdit()
    unity_entry.setStyleSheet("QLineEdit { background: transparent; }")
    unity_entry.setPlaceholderText(_("по умолчанию: ../NeuroMita-Unity", "default: ../NeuroMita-Unity"))
    unity_entry.setText(self.settings.get("UNITY_INSTALL_DIR", ""))
    unity_layout.addWidget(unity_entry)

    unity_browse = QPushButton("📁")
    unity_browse.setFixedWidth(36)
    unity_browse.setToolTip(_("Выбрать папку", "Browse folder"))

    def _browse_unity():
        directory = QFileDialog.getExistingDirectory(
            None,
            _("Выбрать папку Unity", "Select Unity folder"),
            unity_entry.text() or str(Path.home()),
        )
        if directory:
            logger.info(f"[updates_ui] UNITY_INSTALL_DIR -> {directory}")
            unity_entry.setText(directory)
            _persist_setting("UNITY_INSTALL_DIR", directory)
            _refresh_version_labels()

    unity_browse.clicked.connect(_browse_unity)
    unity_layout.addWidget(unity_browse)

    unity_launch = QPushButton(_("▶ Запуск", "▶ Launch"))
    unity_launch.setToolTip(_("Запустить Unity из выбранной папки", "Launch Unity from the selected folder"))
    unity_launch.clicked.connect(_launch_unity)
    unity_layout.addWidget(unity_launch)

    def _save_unity_dir():
        logger.info(f"[updates_ui] UNITY_INSTALL_DIR -> {unity_entry.text()}")
        _persist_setting("UNITY_INSTALL_DIR", unity_entry.text())
        _refresh_version_labels()

    unity_entry.editingFinished.connect(_save_unity_dir)
    parent.addWidget(unity_row)

    # Release info
    info_title = QLabel(_("Информация об обновлении", "Update information"))
    info_title.setStyleSheet("QLabel { color: #bca9bb; font-size: 12px; }")
    parent.addWidget(info_title)

    release_info = QTextEdit()
    release_info.setReadOnly(True)
    release_info.setMinimumHeight(180)
    release_info.setPlaceholderText(_("Сначала нажми «Проверить».", "Press 'Check' first."))
    parent.addWidget(release_info)

    # Progress + status
    progress_bar = QProgressBar()
    progress_bar.setRange(0, 100)
    progress_bar.setValue(0)
    progress_bar.setVisible(False)
    progress_bar.setStyleSheet(
        "QProgressBar { border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; background: rgba(16,13,25,0.96); height: 14px; text-align: center; color: #bca9bb; font-size: 10px; }"
        "QProgressBar::chunk { background: #db6596; border-radius: 3px; }"
    )
    parent.addWidget(progress_bar)

    status_lbl = QLabel("")
    status_lbl.setWordWrap(True)
    status_lbl.setStyleSheet("QLabel { color: #bca9bb; font-size: 11px; padding: 2px 0; }")
    parent.addWidget(status_lbl)

    # Action buttons
    buttons_row = QWidget()
    buttons_row.setObjectName("UpdatesButtonsRow")
    buttons_row.setStyleSheet("QWidget#UpdatesButtonsRow { background: transparent; }")
    buttons_layout = QHBoxLayout(buttons_row)
    buttons_layout.setContentsMargins(0, 0, 0, 0)
    buttons_layout.setSpacing(8)

    btn_check = QPushButton(_("Проверить обновления", "Check for updates"))
    btn_check.setStyleSheet(
        "QPushButton { background: #db6596; color: #ffffff; border: none; border-radius: 10px; padding: 7px 14px; font-weight: 600; }"
        "QPushButton:hover { background: #e26e9e; }"
        "QPushButton:disabled { background: #2b2230; color: #bca9bb; }"
    )

    btn_install = QPushButton(_("Установить обновления", "Install updates"))
    btn_install.setStyleSheet(
        "QPushButton { background: #db6596; color: #ffffff; border: none; border-radius: 10px; padding: 7px 14px; font-weight: 600; }"
        "QPushButton:hover { background: #e26e9e; }"
        "QPushButton:disabled { background: #2b2230; color: #bca9bb; }"
    )

    btn_check.clicked.connect(lambda: threading.Thread(target=_run_check_only, daemon=True).start())
    btn_install.clicked.connect(lambda: threading.Thread(target=_run_install, daemon=True).start())

    buttons_layout.addWidget(btn_check)
    buttons_layout.addWidget(btn_install)
    buttons_layout.addStretch()
    parent.addWidget(buttons_row)
