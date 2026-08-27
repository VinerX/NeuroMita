from __future__ import annotations

from pathlib import Path
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


def _ffmpeg_path() -> Path:
    # Matches SystemController's startup check: ffmpeg.exe in the working dir
    # (the game root). resolve() so the path is stable regardless of cwd churn.
    return Path("ffmpeg.exe").resolve()


class FFmpegInstallableComponent:
    """Surfaces the bundled-on-demand FFmpeg binary in the AI Hub.

    FFmpeg is still auto-installed silently on startup (SystemController); this
    component just makes it visible/manageable under «Зависимости» — status,
    (re)install for repair, and uninstall — through the same pipeline as every
    other component."""

    category = ComponentCategory.DEPENDENCY
    legacy_kind = "deps"

    def __init__(self) -> None:
        self.item_id = "ffmpeg"
        self.id = make_component_id(self.category, self.item_id)

    def metadata(self) -> ComponentMetadata:
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title="FFmpeg",
            description=_(
                "Утилита обработки аудио/видео. Нужна для локальной озвучки (RVC) "
                "и работы с медиа. Скачивается автоматически.",
                "Audio/video processing tool. Needed for local voiceover (RVC) and "
                "media handling. Downloaded automatically.",
            ),
            backend=BackendKind.NONE,
            legacy_kind=self.legacy_kind,
            tags=("system", "ffmpeg"),
            size="~120 MB",
        )

    def status(self, ctx: dict[str, Any] | None = None) -> ComponentStatus:
        exists = _ffmpeg_path().exists()
        return ComponentStatus(
            id=self.id,
            code=ComponentStatusCode.INSTALLED if exists else ComponentStatusCode.NOT_INSTALLED,
            installed=exists,
            ready=exists,
            message=_("FFmpeg установлен.", "FFmpeg is installed.")
            if exists
            else _("FFmpeg не установлен.", "FFmpeg is not installed."),
            backend=BackendKind.NONE,
        )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        run_ctx = dict(ctx or {})
        clean = bool(run_ctx.get("clean"))
        path = _ffmpeg_path()

        if path.exists() and not clean:
            return InstallPlan(
                actions=[],
                already_installed=True,
                already_installed_status="Already installed",
            )

        def _install(**kwargs) -> bool:
            from utils.ffmpeg_installer import install_ffmpeg

            cb = kwargs.get("callbacks")
            # Clean reinstall: drop the existing (possibly corrupt) binary so it
            # is fetched again instead of skipped by install_ffmpeg's own check.
            if clean and path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
            # Pass the install-log sink so the real failure reason (network
            # reset, bad zip, ...) surfaces in the window, not just "failed".
            log = cb.log if cb is not None else None
            ok = bool(install_ffmpeg(target_directory=".", log=log))
            if not ok and cb is not None:
                try:
                    cb.log("FFmpeg download/extract failed.")
                except Exception:
                    pass
            return ok

        return InstallPlan(
            actions=[
                InstallAction(
                    type="call",
                    description=_("Загрузка FFmpeg...", "Downloading FFmpeg..."),
                    progress=20,
                    fn=_install,
                )
            ],
            ok_status="Done",
        )

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        path = _ffmpeg_path()
        if not path.exists():
            return noop_plan("FFmpeg is not installed.")

        def _remove(**_kwargs) -> bool:
            try:
                path.unlink()
            except OSError:
                return False
            return True

        return InstallPlan(
            actions=[
                InstallAction(
                    type="call",
                    description=_("Удаление FFmpeg...", "Removing FFmpeg..."),
                    progress=50,
                    fn=_remove,
                )
            ],
            ok_status="Done",
        )

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


def create_ffmpeg_installable_components() -> list[FFmpegInstallableComponent]:
    return [FFmpegInstallableComponent()]
