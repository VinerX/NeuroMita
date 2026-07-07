from __future__ import annotations

import importlib.util
from typing import Any

from core.backends import BackendKind
from core.install_types import InstallAction, InstallPlan
from core.installables import (
    ComponentCategory,
    ComponentMetadata,
    ComponentStatus,
    ComponentStatusCode,
    make_component_id,
)
from core.installables.helpers import noop_plan
from utils import getTranslationVariant as _


_PACKAGE = "opencv-python"
_IMPORT_NAME = "cv2"


def _cv2_installed() -> bool:
    # find_spec, а не import: cv2 тяжёлый, а для статуса достаточно факта наличия.
    try:
        return importlib.util.find_spec(_IMPORT_NAME) is not None
    except Exception:
        return False


class OpenCVInstallableComponent:
    """OpenCV (cv2) для камеры — захват кадров и перечисление устройств.

    Раньше cv2 ставился «скрытно» лишь при первом запуске захвата
    (camera_handler), а перечисление камер в настройках падало с warning-ом,
    пока пакет не появится (курица-и-яйцо). Здесь он становится обычным
    управляемым компонентом «Зависимости» в AI Hub — статус, установка,
    удаление — по тому же пайплайну, что и ffmpeg."""

    category = ComponentCategory.DEPENDENCY
    legacy_kind = "deps"

    def __init__(self) -> None:
        self.item_id = "opencv"
        self.id = make_component_id(self.category, self.item_id)

    def metadata(self) -> ComponentMetadata:
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title="OpenCV",
            description=_(
                "Библиотека компьютерного зрения (cv2). Нужна для работы камеры — "
                "захвата кадров и выбора устройства в настройках.",
                "Computer-vision library (cv2). Needed for the camera — frame "
                "capture and device selection in settings.",
            ),
            backend=BackendKind.NONE,
            legacy_kind=self.legacy_kind,
            tags=("system", "camera", "opencv"),
            size="~40 MB",
        )

    def status(self, ctx: dict[str, Any] | None = None) -> ComponentStatus:
        installed = _cv2_installed()
        return ComponentStatus(
            id=self.id,
            code=ComponentStatusCode.INSTALLED if installed else ComponentStatusCode.NOT_INSTALLED,
            installed=installed,
            ready=installed,
            message=_("OpenCV установлен.", "OpenCV is installed.")
            if installed
            else _("OpenCV не установлен.", "OpenCV is not installed."),
            backend=BackendKind.NONE,
        )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        clean = bool((ctx or {}).get("clean"))
        if _cv2_installed() and not clean:
            return InstallPlan(
                actions=[],
                already_installed=True,
                already_installed_status=_("Already installed", "Already installed"),
            )
        return InstallPlan(
            actions=[
                InstallAction(
                    type="pip",
                    description=_("Установка OpenCV...", "Installing OpenCV..."),
                    progress=40,
                    packages=[_PACKAGE],
                )
            ],
            ok_status=_("Done", "Done"),
        )

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        if not _cv2_installed():
            return noop_plan(_("OpenCV is not installed.", "OpenCV is not installed."))

        def _uninstall(*, pip_installer=None, callbacks=None, **_kwargs) -> bool:
            if pip_installer is None:
                return True
            try:
                # include_dependencies=False: сносим только opencv-python, не задевая
                # numpy и прочее, общее с torch/RAG.
                return bool(pip_installer.uninstall_packages(
                    [_PACKAGE],
                    _("Удаление OpenCV...", "Removing OpenCV..."),
                    include_dependencies=False,
                ))
            except Exception as exc:
                if callbacks is not None:
                    try:
                        callbacks.log(str(exc))
                    except Exception:
                        pass
                return False

        return InstallPlan(
            actions=[
                InstallAction(
                    type="call",
                    description=_("Удаление OpenCV...", "Removing OpenCV..."),
                    progress=50,
                    fn=_uninstall,
                )
            ],
            ok_status=_("Done", "Done"),
        )

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


def create_opencv_installable_components() -> list[OpenCVInstallableComponent]:
    return [OpenCVInstallableComponent()]
