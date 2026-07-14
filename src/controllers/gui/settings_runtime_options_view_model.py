from __future__ import annotations

from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from main_logger import logger
from ui.settings.runtime_options_presentation import (
    CameraDeviceSelected,
    LoadCameraOptions,
    LoadProviderOptions,
    SettingsRuntimeOptionsState,
)
from utils import getTranslationVariant as _


class SettingsRuntimeOptionsViewModel(IntentViewModel[SettingsRuntimeOptionsState]):
    def __init__(self, *, providers, settings, parent=None) -> None:
        super().__init__(
            SettingsRuntimeOptionsState(
                provider_options=tuple(providers.current() or ()),
            ),
            parent,
        )
        self._providers = providers
        self._settings = settings

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, LoadProviderOptions):
            self.load_providers()
            return
        if isinstance(intent, LoadCameraOptions):
            self.load_cameras()
            return
        if isinstance(intent, CameraDeviceSelected):
            self.select_camera(intent.value)

    def load_providers(self) -> None:
        self.update_state(providers_loading=True, error=None)
        self.run_coalesced(
            "settings-provider-options",
            lambda: tuple(self._providers.load() or ()),
            lambda options: self.update_state(
                provider_options=tuple(options),
                providers_loading=False,
                provider_revision=self.state.provider_revision + 1,
                error=None,
            ),
            lambda error: self.update_state(
                providers_loading=False,
                error=str(error),
            ),
        )

    def load_cameras(self) -> None:
        self.update_state(cameras_loading=True, error=None)
        self.run_coalesced(
            "settings-camera-options",
            self._enumerate_cameras,
            lambda options: self.update_state(
                camera_options=tuple(options),
                cameras_loading=False,
                camera_revision=self.state.camera_revision + 1,
                error=None,
            ),
            lambda error: self.update_state(
                camera_options=(
                    _("Камеры недоступны", "Cameras unavailable"),
                ),
                cameras_loading=False,
                error=str(error),
                camera_revision=self.state.camera_revision + 1,
            ),
        )

    def select_camera(self, value: str) -> None:
        text = str(value or "").strip()
        if not text.startswith("Camera "):
            return
        try:
            index = int(text.rsplit(" ", 1)[-1])
        except (TypeError, ValueError):
            return
        self._settings.set("CAMERA_INDEX", index)
        logger.info(f"[screen_capture] Selected camera index: {index}")

    @staticmethod
    def _enumerate_cameras() -> tuple[str, ...]:
        try:
            import cv2
        except ImportError:
            logger.info(
                "[screen_capture] OpenCV (cv2) is not installed; camera enumeration is unavailable."
            )
            return (_("OpenCV не установлен (см. AI Hub)", "OpenCV not installed (see AI Hub)"),)

        cameras: list[str] = []
        capture_backend = getattr(cv2, "CAP_DSHOW", 0)
        for index in range(5):
            capture = cv2.VideoCapture(index, capture_backend)
            try:
                if capture.isOpened():
                    cameras.append(f"Camera {index}")
            finally:
                capture.release()
        return tuple(cameras or (_("Камер не найдено", "No cameras found"),))
