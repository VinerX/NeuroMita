from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any, Optional

from PyQt6.QtCore import QObject, pyqtSignal, Qt, QEvent
from PyQt6.QtWidgets import QDialog, QWidget

from main_logger import logger


DialogFactory = Callable[[QWidget, dict], QDialog]
OnReadyCallback = Callable[[QDialog, dict], None]


@dataclass(frozen=True)
class DialogSpec:
    factory: DialogFactory
    singleton: bool = True
    hide_on_close: bool = True
    modal: bool = False
    on_ready: Optional[OnReadyCallback] = None


class _HideOnCloseFilter(QObject):
    def __init__(self, dialog: QDialog):
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._dialog and event.type() == QEvent.Type.Close:
            try:
                self._dialog.hide()
                event.ignore()
                return True
            except Exception:
                return False
        return False


class WindowManager(QObject):
    """
    Менеджер окон (диалогов), живущий в UI-потоке.
    Потокобезопасный API: show_dialog/close_dialog можно вызывать из любых потоков.

    NEW: show_dialog_blocking() — модальный блокирующий показ диалога с возвратом результата.
    """

    _request_show = pyqtSignal(str, object)            # window_id, payload(dict)
    _request_close = pyqtSignal(str, bool)             # window_id, destroy
    _request_close_all = pyqtSignal(bool)              # destroy
    _request_show_blocking = pyqtSignal(str, object, object)  # window_id, payload(dict), holder(dict)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._parent = parent

        self._specs: dict[str, DialogSpec] = {}
        self._dialogs: dict[str, QDialog] = {}
        self._filters: dict[str, _HideOnCloseFilter] = {}

        self._request_show.connect(self._on_request_show, type=Qt.ConnectionType.QueuedConnection)
        self._request_close.connect(self._on_request_close, type=Qt.ConnectionType.QueuedConnection)
        self._request_close_all.connect(self._on_request_close_all, type=Qt.ConnectionType.QueuedConnection)

        # Blocking: caller thread waits until this slot returns.
        self._request_show_blocking.connect(self._on_request_show_blocking, type=Qt.ConnectionType.BlockingQueuedConnection)

    def register_dialog(
        self,
        window_id: str,
        factory: DialogFactory,
        *,
        singleton: bool = True,
        hide_on_close: bool = True,
        modal: bool = False,
        on_ready: Optional[OnReadyCallback] = None,
    ) -> None:
        self._specs[window_id] = DialogSpec(
            factory=factory,
            singleton=singleton,
            hide_on_close=hide_on_close,
            modal=modal,
            on_ready=on_ready,
        )

    def set_dialog_on_ready(self, window_id: str, on_ready: Optional[OnReadyCallback]) -> None:
        spec = self._specs.get(window_id)
        if not spec:
            logger.error(f"WindowManager.set_dialog_on_ready: неизвестный window_id='{window_id}'")
            return
        self._specs[window_id] = DialogSpec(
            factory=spec.factory,
            singleton=spec.singleton,
            hide_on_close=spec.hide_on_close,
            modal=spec.modal,
            on_ready=on_ready,
        )

    def show_dialog(self, window_id: str, payload: Optional[dict] = None) -> None:
        self._request_show.emit(window_id, payload or {})

    def show_dialog_blocking(self, window_id: str, payload: Optional[dict] = None) -> dict:
        holder: dict = {}
        self._request_show_blocking.emit(window_id, payload or {}, holder)
        return holder

    def close_dialog(self, window_id: str, *, destroy: bool = False) -> None:
        self._request_close.emit(window_id, destroy)

    def close_all(self, *, destroy: bool = False) -> None:
        self._request_close_all.emit(destroy)

    def get_dialog(self, window_id: str) -> Optional[QDialog]:
        dlg = self._dialogs.get(window_id)
        if not dlg:
            return None
        try:
            dlg.isVisible()
            return dlg
        except Exception:
            return None

    def _get_or_create_dialog(self, window_id: str, payload: dict, spec: DialogSpec) -> Optional[QDialog]:
        dialog: Optional[QDialog] = None
        if spec.singleton:
            dialog = self.get_dialog(window_id)

        if dialog is None:
            try:
                dialog = spec.factory(self._parent, payload)
            except Exception as e:
                logger.error(f"WindowManager: ошибка factory для '{window_id}': {e}", exc_info=True)
                err_cb = payload.get("error_callback")
                if callable(err_cb):
                    try:
                        err_cb(str(e))
                    except Exception:
                        pass
                return None

            if spec.singleton:
                self._dialogs[window_id] = dialog

            if spec.hide_on_close:
                try:
                    f = _HideOnCloseFilter(dialog)
                    dialog.installEventFilter(f)
                    self._filters[window_id] = f
                except Exception:
                    pass

        return dialog

    def _on_request_show(self, window_id: str, payload_obj: object) -> None:
        payload = payload_obj if isinstance(payload_obj, dict) else {}

        spec = self._specs.get(window_id)
        if not spec:
            logger.error(f"WindowManager: неизвестный window_id='{window_id}'")
            err_cb = payload.get("error_callback")
            if callable(err_cb):
                try:
                    err_cb(f"Unknown window_id: {window_id}")
                except Exception:
                    pass
            return

        dialog = self._get_or_create_dialog(window_id, payload, spec)
        if dialog is None:
            return

        try:
            modal = bool(payload.get("modal", spec.modal))
            dialog.setModal(modal)

            if callable(spec.on_ready):
                spec.on_ready(dialog, payload)

            on_ready = payload.get("on_ready") or payload.get("callback")
            if callable(on_ready):
                on_ready(dialog)

            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception as e:
            logger.error(f"WindowManager: ошибка show '{window_id}': {e}", exc_info=True)
            err_cb = payload.get("error_callback")
            if callable(err_cb):
                try:
                    err_cb(str(e))
                except Exception:
                    pass

    def _on_request_show_blocking(self, window_id: str, payload_obj: object, holder_obj: object) -> None:
        payload = payload_obj if isinstance(payload_obj, dict) else {}
        holder = holder_obj if isinstance(holder_obj, dict) else {}

        spec = self._specs.get(window_id)
        if not spec:
            logger.error(f"WindowManager: неизвестный window_id='{window_id}' (blocking)")
            holder["error"] = f"Unknown window_id: {window_id}"
            return

        dialog = self._get_or_create_dialog(window_id, payload, spec)
        if dialog is None:
            holder["error"] = "Failed to create dialog"
            return

        # Important: hide-on-close filter breaks exec() if it ignores Close.
        f = self._filters.get(window_id)
        if f:
            try:
                dialog.removeEventFilter(f)
            except Exception:
                pass

        try:
            dialog.setModal(True)

            if callable(spec.on_ready):
                spec.on_ready(dialog, payload)

            on_ready = payload.get("on_ready") or payload.get("callback")
            if callable(on_ready):
                on_ready(dialog)

            holder["dialog"] = dialog
            dialog.exec()

            if hasattr(dialog, "get_choice"):
                try:
                    holder["choice"] = dialog.get_choice()
                except Exception:
                    pass

            holder["done"] = True

        except Exception as e:
            logger.error(f"WindowManager: ошибка show_blocking '{window_id}': {e}", exc_info=True)
            holder["error"] = str(e)

        finally:
            if f:
                try:
                    dialog.installEventFilter(f)
                except Exception:
                    pass

            if not spec.singleton:
                try:
                    dialog.hide()
                    dialog.deleteLater()
                except Exception:
                    pass

    def _on_request_close(self, window_id: str, destroy: bool) -> None:
        dialog = self.get_dialog(window_id)
        if not dialog:
            self._dialogs.pop(window_id, None)
            self._filters.pop(window_id, None)
            return

        try:
            if destroy:
                dialog.hide()
                dialog.deleteLater()
                self._dialogs.pop(window_id, None)
                self._filters.pop(window_id, None)
            else:
                dialog.hide()
        except Exception:
            self._dialogs.pop(window_id, None)
            self._filters.pop(window_id, None)

    def _on_request_close_all(self, destroy: bool) -> None:
        for window_id in list(self._dialogs.keys()):
            self._on_request_close(window_id, destroy)