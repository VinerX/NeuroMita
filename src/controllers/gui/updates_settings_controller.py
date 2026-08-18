"""Settings panel for Python/Unity updates."""
from __future__ import annotations

import os
from controllers.gui.async_runner import run_async
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QWidget,
    QVBoxLayout,
)

from core.unity_installation import (
    find_unity_executable as find_installed_unity_executable,
    unity_install_dir,
)
from main_logger import logger
from services.update_contour import target_for_contour
from ui.gui_templates import create_section_header
from ui.widgets.tr_combobox import TRQComboBox
from utils import getTranslationVariant as _
from localization.live import tr_set


def setup_updates_settings_controls(
    self,
    parent,
    *,
    pending_restart_version: Callable[[], str],
    set_pending_restart_version: Callable[[str | None], None],
):
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
        try:
            save_setting = getattr(self, "_save_setting", None)
            if callable(save_setting):
                save_setting(key, value)
                return

            settings = getattr(self, "settings", None)
            setter = getattr(settings, "set", None)
            if not callable(setter):
                raise RuntimeError("Settings write port is unavailable")
            setter(key, value)
        except Exception:
            logger.error(f"[updates_ui] Failed to persist setting {key!r}", exc_info=True)

    def _current_update_target():
        return target_for_contour(self.settings.get("UPDATE_CONTOUR", "release"))

    def _current_unity_dir() -> Path:
        configured = str(self.settings.get("UNITY_INSTALL_DIR", "") or "").strip() or None
        return unity_install_dir(configured)

    def _current_unity_version() -> str:
        try:
            ver_file = _current_unity_dir() / "_version.txt"
            if ver_file.exists():
                return ver_file.read_text(encoding="utf-8").strip() or "?"
        except Exception:
            logger.warning("[updates_ui] Failed to read Unity version", exc_info=True)
        return "?"

    def _pending_python_restart_version() -> str:
        return str(pending_restart_version() or "").strip()

    def _has_pending_python_restart() -> bool:
        return bool(_pending_python_restart_version())

    def _mark_python_restart_required(version: str | None) -> None:
        set_pending_restart_version(version)
        sidebar = getattr(self, "shell_sidebar", None)
        if sidebar is not None and hasattr(sidebar, "refresh_version_label"):
            try:
                sidebar.refresh_version_label()
            except Exception:
                logger.warning("[updates_ui] Failed to refresh sidebar version label", exc_info=True)

    def _find_unity_executable(unity_dir: Path) -> Path | None:
        return find_installed_unity_executable(unity_dir)

    def _refresh_version_labels():
        py_ver = _pending_python_restart_version()
        if not py_ver:
            try:
                from _version import __version__ as py_ver
            except Exception:
                py_ver = "?"
        py_suffix = _(" • нужен перезапуск", " • restart required") if _has_pending_python_restart() else ""
        lbl_py.setText(_("Python-часть: ", "Python part: ") + f"<b>{py_ver}</b>{py_suffix}")
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
        if title == _("Python", "Python") and _has_pending_python_restart():
            current_version = _pending_python_restart_version() or current_version
            available = False
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

            target = _current_update_target()
            channel = target.channel
            base_dir = os.environ.get("NEUROMITA_BASE_DIR") or None
            unity_dir = self.settings.get("UNITY_INSTALL_DIR") or None

            logger.info(
                f"[updates_ui] Check-only params: contour={target.contour}, repo={target.repo}, "
                f"channel={channel}, base_dir={base_dir}, unity_dir={unity_dir}"
            )

            py_info = get_python_update_info(base_dir=base_dir, channel=channel)
            unity_info = get_unity_update_info(base_dir=base_dir, unity_dir=unity_dir, channel=channel)
            if _has_pending_python_restart():
                py_info = dict(py_info or {})
                py_info["current_version"] = _pending_python_restart_version() or py_info.get("current_version") or "?"
                py_info["available"] = False
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

    def _prompt_restart():
        # Вызывается на UI-потоке после успешной установки Python-обновления.
        from utils.app_restart import restart_app

        box = QMessageBox(btn_install)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Обновление установлено", "Update installed"))
        box.setText(_(
            "Python-обновление установлено.\n\n"
            "Перезапустить приложение сейчас, чтобы применить его?\n"
            "(До перезапуска программа работает на старой версии.)",
            "The Python update has been installed.\n\n"
            "Restart the app now to apply it?\n"
            "(Until you restart, the app keeps running the old version.)",
        ))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        if box.exec() == QMessageBox.StandardButton.Yes:
            restart_app()
        else:
            _set_status_level(
                _("Обновление применится при следующем запуске.",
                  "The update will be applied on the next start."),
                "notify",
            )

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

            target = _current_update_target()
            channel = target.channel
            tester_code = self.settings.get("TESTER_CODE") or None
            base_dir = os.environ.get("NEUROMITA_BASE_DIR") or None
            unity_dir = self.settings.get("UNITY_INSTALL_DIR") or None

            logger.info(
                f"[updates_ui] Install params: contour={target.contour}, repo={target.repo}, "
                f"channel={channel}, base_dir={base_dir}, unity_dir={unity_dir}, "
                f"tester_code={'set' if tester_code else 'empty'}"
            )

            py_info = get_python_update_info(base_dir=base_dir, channel=channel)
            unity_info = get_unity_update_info(base_dir=base_dir, unity_dir=unity_dir, channel=channel)
            if _has_pending_python_restart():
                py_info = dict(py_info or {})
                py_info["current_version"] = _pending_python_restart_version() or py_info.get("current_version") or "?"
                py_info["available"] = False
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

            py_applied = False
            python_pending_restart = False
            pending_python_version = str(py_info.get("latest_version") or "").strip()
            if bool(py_info.get("available")):
                _set_status(_("Устанавливаю Python-обновление...", "Installing Python update..."))
                python_result = check_for_updates(
                    base_dir=base_dir,
                    logger=ui_log,
                    channel=channel,
                    tester_code=tester_code,
                    on_progress=_on_progress,
                    auto_update=True,
                    restart_on_success=False,
                    update_mode=(self.settings.get("UPDATE_MODE", "diff") or "diff"),
                    preserve_prompts=bool(self.settings.get("UPDATE_PRESERVE_PROMPTS", True)),
                )
                if not python_result.ok:
                    raise RuntimeError(python_result.error or "Python update failed")
                py_applied = bool(python_result)
                python_pending_restart = bool(python_result.restart_required)

            if bool(unity_info.get("available")) and not python_pending_restart:
                _set_status(_("Устанавливаю Unity-обновление...", "Installing Unity update..."))
                unity_result = check_for_unity_updates(
                    base_dir=base_dir,
                    logger=ui_log,
                    unity_dir=unity_dir,
                    channel=channel,
                    tester_code=tester_code,
                    on_progress=_on_progress,
                    auto_update=True,
                )
                if not unity_result.ok:
                    raise RuntimeError(unity_result.error or "Unity update failed")

            _refresh_version_labels()

            if py_applied:
                _dispatch.schedule(lambda ver=pending_python_version: _mark_python_restart_required(ver))
                _dispatch.schedule(_refresh_version_labels)
                # Python-часть заменена на диске — предлагаем управляемый
                # перезапуск (диалог показываем на UI-потоке).
                _dispatch.schedule(_prompt_restart)
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

    def _ensure_tester_code() -> bool:
        if _current_update_target().contour != "test":
            return True
        current = tester_entry.text().strip()
        if current:
            return True

        code, ok = QInputDialog.getText(
            btn_install,
            _("Код тестера", "Tester code"),
            _(
                "Введите код тестера для установки релизных архивов.",
                "Enter the tester code required to install release archives.",
            ),
            QLineEdit.EchoMode.Password,
            "",
        )
        if not ok:
            _set_status_level(
                _("Установка отменена: код тестера не введён.", "Installation cancelled: tester code was not entered."),
                "warning",
            )
            return False

        code = str(code or "").strip()
        if not code:
            _set_status_level(
                _("Установка отменена: код тестера пустой.", "Installation cancelled: tester code is empty."),
                "warning",
            )
            return False

        tester_entry.setText(code)
        _save_tester()
        return True

    # Current versions
    py_ver = _pending_python_restart_version()
    if not py_ver:
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
    _refresh_version_labels()

    # Живая смена языка: строки версий ставятся через setText с f-строкой (номер
    # версии), поэтому не в реестре tr_set — переустанавливаем по сигналу.
    if not getattr(self, "_updates_version_lang_hook_bound", False):
        self._updates_version_lang_hook_bound = True
        try:
            from localization.live import language_changed_signal

            def _relabel_versions(*_a):
                try:
                    _refresh_version_labels()
                except RuntimeError:
                    pass  # виджеты уже удалены — игнорируем

            language_changed_signal().connect(_relabel_versions)
        except Exception:
            pass

    # Update contour (read-only; the contour is the single source of truth)
    target = _current_update_target()
    readonly_value_style = (
        "QLabel { background-color: rgba(16,13,25,0.76); "
        "border: 1px solid rgba(255,255,255,0.05); border-radius: 10px; "
        "color: #f3edf6; padding: 7px 10px; }"
    )
    combo_style = (
        "QComboBox { background-color: rgba(16,13,25,0.76); border: 1px solid rgba(255,255,255,0.05); border-radius: 10px; "
        "color: #f3edf6; padding: 7px 10px; }"
        "QComboBox:focus { border: 1px solid rgba(183, 75, 125,0.24); }"
        "QComboBox::drop-down { border: none; width: 26px; }"
        "QComboBox QAbstractItemView { background-color: rgba(15,16,31,0.96); border: 1px solid rgba(183, 75, 125,0.24); color: #f3edf6; selection-background-color: rgba(183, 75, 125,0.30); }"
    )

    contour_row = QWidget()
    contour_row.setObjectName("UpdatesContourRow")
    contour_row.setStyleSheet("QWidget#UpdatesContourRow { background: transparent; }")
    contour_layout = QHBoxLayout(contour_row)
    contour_layout.setContentsMargins(0, 4, 0, 0)
    contour_layout.setSpacing(8)
    contour_lbl = tr_set(QLabel(), "Контур обновлений:", "Update contour:")
    contour_lbl.setStyleSheet("QLabel { color: #bca9bb; font-size: 12px; }")
    contour_lbl.setFixedWidth(120)
    contour_layout.addWidget(contour_lbl)
    contour_value = tr_set(
        QLabel(),
        "Тестовый" if target.contour == "test" else "Стабильный",
        "Test" if target.contour == "test" else "Stable",
    )
    contour_value.setStyleSheet(readonly_value_style)
    contour_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    contour_layout.addWidget(contour_value)
    contour_layout.addStretch()
    parent.addWidget(contour_row)

    repo_row = QWidget()
    repo_row.setObjectName("UpdatesRepoRow")
    repo_row.setStyleSheet("QWidget#UpdatesRepoRow { background: transparent; }")
    repo_layout = QHBoxLayout(repo_row)
    repo_layout.setContentsMargins(0, 4, 0, 0)
    repo_layout.setSpacing(8)
    repo_lbl = tr_set(QLabel(), "Репозиторий:", "Repository:")
    repo_lbl.setStyleSheet("QLabel { color: #bca9bb; font-size: 12px; }")
    repo_lbl.setFixedWidth(120)
    repo_layout.addWidget(repo_lbl)
    repo_value = QLabel(target.repo)
    repo_value.setStyleSheet(readonly_value_style)
    repo_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    repo_layout.addWidget(repo_value)
    repo_layout.addStretch()
    parent.addWidget(repo_row)

    # Update mode (diff / full)
    mode_row = QWidget()
    mode_row.setObjectName("UpdatesModeRow")
    mode_row.setStyleSheet("QWidget#UpdatesModeRow { background: transparent; }")
    mode_layout = QHBoxLayout(mode_row)
    mode_layout.setContentsMargins(0, 4, 0, 0)
    mode_layout.setSpacing(8)

    mode_lbl = tr_set(QLabel(), "Режим установки:", "Install mode:")
    mode_lbl.setStyleSheet("QLabel { color: #bca9bb; font-size: 12px; }")
    mode_layout.addWidget(mode_lbl)

    mode_combo = TRQComboBox()
    mode_combo.setStyleSheet(combo_style)
    # data: "diff"/"full"; подписи переводятся вживую.
    mode_combo.add_tr_item("Дифф (только изменённые файлы)", "Diff (changed files only)", value="diff")
    mode_combo.add_tr_item("Полная перезапись", "Full replace", value="full")
    current_mode = (self.settings.get("UPDATE_MODE", "diff") or "diff").lower()
    mode_combo.set_current_value(current_mode)
    tr_set(mode_combo, "Дифф - переписываются только изменённые файлы, встроенный питон с\n"
            "зависимостями и локальные файлы не трогаются (быстро, без переустановки).\n"
            "Полная - папка очищается и релиз раскладывается заново.",
            "Diff - only changed files are rewritten; the embedded Python with its\n"
            "dependencies and local files are left intact (fast, no reinstall).\n"
            "Full - the folder is wiped and the release is laid out from scratch.", "setToolTip")

    def _save_mode():
        value = mode_combo.currentData() or "diff"
        if value == (self.settings.get("UPDATE_MODE", "diff") or "diff").lower():
            return
        logger.info(f"[updates_ui] UPDATE_MODE -> {value}")
        _persist_setting("UPDATE_MODE", value)

    mode_combo.activated.connect(lambda _index: QTimer.singleShot(0, _save_mode))
    mode_layout.addWidget(mode_combo)
    mode_layout.addStretch()
    parent.addWidget(mode_row)

    # Preserve local prompts on update
    chk_keep_prompts = tr_set(QCheckBox(), "Не перезаписывать мои промпты", "Keep my prompts")
    tr_set(chk_keep_prompts, "Файлы в папке Prompts, которые уже есть локально, не будут заменены\n"
            "версией из релиза. Новые промпты из релиза всё равно добавятся.",
            "Files in the Prompts folder that already exist locally won't be\n"
            "replaced by the release version. New release prompts are still added.", "setToolTip")
    chk_keep_prompts.setChecked(bool(self.settings.get("UPDATE_PRESERVE_PROMPTS", True)))

    def _save_keep_prompts(state):
        enabled = bool(state)
        logger.info(f"[updates_ui] UPDATE_PRESERVE_PROMPTS -> {enabled}")
        _persist_setting("UPDATE_PRESERVE_PROMPTS", enabled)

    chk_keep_prompts.stateChanged.connect(_save_keep_prompts)
    parent.addWidget(chk_keep_prompts)

    # Background update check (notify only, no auto-apply)
    chk_check_startup = tr_set(QCheckBox(), "Проверять обновления при запуске", "Check for updates on startup")
    tr_set(chk_check_startup, "Фоновая проверка наличия обновлений и показ плашки на главном экране.\n"
            "Ничего не скачивает и не устанавливает само.",
            "Background check for updates and a banner on the home screen.\n"
            "Does not download or install anything by itself.", "setToolTip")
    chk_check_startup.setChecked(bool(self.settings.get("UPDATE_CHECK_ON_STARTUP", True)))

    def _save_check_startup(state):
        enabled = bool(state)
        logger.info(f"[updates_ui] UPDATE_CHECK_ON_STARTUP -> {enabled}")
        _persist_setting("UPDATE_CHECK_ON_STARTUP", enabled)

    chk_check_startup.stateChanged.connect(_save_check_startup)
    parent.addWidget(chk_check_startup)

    # Auto-update checkboxes
    chk_auto = tr_set(QCheckBox(), "Авто-обновление Python при запуске", "Auto-update Python on startup")
    tr_set(chk_auto, "AUTO_UPDATE=1 в features.env", "AUTO_UPDATE=1 in features.env", "setToolTip")
    chk_auto.setChecked(bool(self.settings.get("AUTO_UPDATE", self.settings.get("AUTO_UPDATE_CHECK", False))))

    def _save_auto(state):
        enabled = bool(state)
        logger.info(f"[updates_ui] AUTO_UPDATE -> {enabled}")
        _persist_setting("AUTO_UPDATE", enabled)
        _persist_setting("AUTO_UPDATE_CHECK", enabled)

    chk_auto.stateChanged.connect(_save_auto)
    parent.addWidget(chk_auto)

    chk_unity = tr_set(QCheckBox(), "Авто-обновление Unity при запуске", "Auto-update Unity on startup")
    tr_set(chk_unity, "Скачивает Unity-часть мода если вышла новая версия",
            "Downloads Unity part of the mod when a new version is released", "setToolTip")
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

    tester_lbl = tr_set(QLabel(), "Код тестера:", "Tester code:")
    tester_lbl.setStyleSheet("QLabel { color: #bca9bb; font-size: 12px; }")
    tester_lbl.setFixedWidth(100)
    tester_layout.addWidget(tester_lbl)

    tester_entry = QLineEdit()
    tester_entry.setStyleSheet(
        "QLineEdit { background-color: rgba(16,13,25,0.76); border: 1px solid rgba(255,255,255,0.05); border-radius: 10px; "
        "color: #f3edf6; padding: 7px 10px; }"
        "QLineEdit:focus { border: 1px solid rgba(183, 75, 125,0.24); }"
    )
    tester_entry.setEchoMode(QLineEdit.EchoMode.Password)
    tr_set(tester_entry, "пароль для тестовых архивов", "password for test archives", "setPlaceholderText")
    tester_entry.setText(self.settings.get("TESTER_CODE", ""))
    tr_set(tester_entry, "Пароль для распаковки зашифрованных тестовых архивов.",
            "Password to unpack encrypted tester archives.", "setToolTip")

    def _save_tester():
        logger.info("[updates_ui] TESTER_CODE updated")
        _persist_setting("TESTER_CODE", tester_entry.text())

    tester_entry.editingFinished.connect(_save_tester)
    tester_layout.addWidget(tester_entry)
    tester_row.setVisible(target.contour == "test")
    parent.addWidget(tester_row)

    self._tester_code_entry = tester_entry

    # Unity install dir
    unity_row = QWidget()
    unity_row.setObjectName("UpdatesUnityRow")
    unity_row.setStyleSheet("QWidget#UpdatesUnityRow { background: transparent; }")
    unity_layout = QHBoxLayout(unity_row)
    unity_layout.setContentsMargins(0, 4, 0, 0)
    unity_layout.setSpacing(4)

    unity_lbl = tr_set(QLabel(), "Папка Unity:", "Unity folder:")
    unity_lbl.setStyleSheet("QLabel { color: #bca9bb; font-size: 12px; }")
    unity_lbl.setFixedWidth(100)
    unity_layout.addWidget(unity_lbl)

    unity_entry = QLineEdit()
    unity_entry.setStyleSheet(
        "QLineEdit { background-color: rgba(16,13,25,0.76); border: 1px solid rgba(255,255,255,0.05); border-radius: 10px; "
        "color: #f3edf6; padding: 7px 10px; }"
        "QLineEdit:focus { border: 1px solid rgba(183, 75, 125,0.24); }"
    )
    tr_set(unity_entry, "по умолчанию: NeuroMita-Unity", "default: NeuroMita-Unity", "setPlaceholderText")
    unity_entry.setText(self.settings.get("UNITY_INSTALL_DIR", ""))
    unity_layout.addWidget(unity_entry)

    unity_browse = QPushButton("📁")
    unity_browse.setFixedWidth(36)
    tr_set(unity_browse, "Выбрать папку", "Browse folder", "setToolTip")

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

    unity_launch = tr_set(QPushButton(), "▶ Запуск", "▶ Launch")
    tr_set(unity_launch, "Запустить Unity из выбранной папки", "Launch Unity from the selected folder", "setToolTip")
    unity_launch.clicked.connect(_launch_unity)
    unity_layout.addWidget(unity_launch)

    def _save_unity_dir():
        logger.info(f"[updates_ui] UNITY_INSTALL_DIR -> {unity_entry.text()}")
        _persist_setting("UNITY_INSTALL_DIR", unity_entry.text())
        _refresh_version_labels()

    unity_entry.editingFinished.connect(_save_unity_dir)
    parent.addWidget(unity_row)

    # Action buttons (подняты НАД описанием обновления)
    buttons_row = QWidget()
    buttons_row.setObjectName("UpdatesButtonsRow")
    buttons_row.setStyleSheet("QWidget#UpdatesButtonsRow { background: transparent; }")
    buttons_layout = QHBoxLayout(buttons_row)
    buttons_layout.setContentsMargins(0, 0, 0, 0)
    buttons_layout.setSpacing(8)

    btn_check = tr_set(QPushButton(), "Проверить обновления", "Check for updates")
    btn_check.setStyleSheet(
        "QPushButton { background: #b74b7d; color: #ffffff; border: none; border-radius: 10px; padding: 7px 14px; font-weight: 600; }"
        "QPushButton:hover { background: #c04c80; }"
        "QPushButton:disabled { background: #2b2230; color: #bca9bb; }"
    )

    btn_install = tr_set(QPushButton(), "Установить обновления", "Install updates")
    btn_install.setStyleSheet(
        "QPushButton { background: #b74b7d; color: #ffffff; border: none; border-radius: 10px; padding: 7px 14px; font-weight: 600; }"
        "QPushButton:hover { background: #c04c80; }"
        "QPushButton:disabled { background: #2b2230; color: #bca9bb; }"
    )

    def _confirm_and_install():
        if not _ensure_tester_code():
            return
        # Предупреждаем про перезапись промптов, если их сохранение выключено.
        keep_prompts = bool(self.settings.get("UPDATE_PRESERVE_PROMPTS", True))
        box = QMessageBox(btn_install)
        box.setIcon(QMessageBox.Icon.Warning if not keep_prompts else QMessageBox.Icon.Question)
        box.setWindowTitle(_("Обновление", "Update"))
        if keep_prompts:
            text = _(
                "Обновление установит новую версию игры.\n\n"
                "Сохранение промптов включено: ваши локальные файлы в папке "
                "Prompts заменены не будут (новые промпты из релиза добавятся).\n\n"
                "Продолжить установку обновления?",
                "The update will install the new game version.\n\n"
                "Keeping prompts is enabled: your local files in the Prompts "
                "folder won't be replaced (new release prompts are still added).\n\n"
                "Continue installing the update?",
            )
        else:
            text = _(
                "Обновление перезапишет файлы игры в этой папке.\n\n"
                "Сохранение промптов выключено — ваши правки в папке Prompts "
                "могут быть заменены версией из релиза. Сделайте копию важных "
                "промптов перед продолжением.\n\nПродолжить установку обновления?",
                "The update will overwrite the game files in this folder.\n\n"
                "Keeping prompts is disabled - your edits in the Prompts folder "
                "may be replaced with the release version. Back up important "
                "prompts before continuing.\n\nContinue installing the update?",
            )
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() == QMessageBox.StandardButton.Yes:
            run_async(self, _run_install, name="settings-update-install")

    btn_check.clicked.connect(
        lambda: run_async(self, _run_check_only, name="settings-update-check")
    )
    btn_install.clicked.connect(_confirm_and_install)

    buttons_layout.addWidget(btn_check)
    buttons_layout.addWidget(btn_install)
    buttons_layout.addStretch()
    parent.addWidget(buttons_row)

    # Progress + status (под кнопками)
    progress_bar = QProgressBar()
    progress_bar.setRange(0, 100)
    progress_bar.setValue(0)
    progress_bar.setVisible(False)
    progress_bar.setStyleSheet(
        "QProgressBar { border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; background: rgba(16,13,25,0.96); height: 14px; text-align: center; color: #bca9bb; font-size: 10px; }"
        "QProgressBar::chunk { background: #b74b7d; border-radius: 3px; }"
    )
    parent.addWidget(progress_bar)

    status_lbl = QLabel("")
    status_lbl.setWordWrap(True)
    status_lbl.setStyleSheet("QLabel { color: #bca9bb; font-size: 11px; padding: 2px 0; }")
    parent.addWidget(status_lbl)

    # Release info (описание обновы — под кнопками и статусом)
    info_title = tr_set(QLabel(), "Информация об обновлении", "Update information")
    info_title.setStyleSheet("QLabel { color: #bca9bb; font-size: 12px; }")
    parent.addWidget(info_title)

    release_info = QTextEdit()
    release_info.setReadOnly(True)
    release_info.setMinimumHeight(180)
    tr_set(release_info, "Сначала нажми «Проверить».", "Press 'Check' first.", "setPlaceholderText")
    release_info.setStyleSheet(
        "QTextEdit { background-color: rgba(16,13,25,0.76); border: 1px solid rgba(255,255,255,0.05); border-radius: 10px; "
        "color: #f3edf6; padding: 7px 10px; }"
    )
    parent.addWidget(release_info)
