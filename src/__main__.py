from __future__ import annotations

import multiprocessing as mp
import os
import sys
from dataclasses import dataclass

from startup.startup_profiler import startup_trace

startup_trace.claim_owner()
startup_trace.mark("entry.module_loaded")

os.environ.setdefault("QT_API", "pyqt6")
os.environ.setdefault("UV_LINK_MODE", "copy")


@dataclass(frozen=True)
class StartupOptions:
    mode: str = "full"
    headless_run_seconds: float = 0.0
    headless_status_interval: float = 60.0


def _parse_float(value: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return max(minimum, float(default))


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "full").strip().lower()
    if normalized in {"gui-only", "gui_only", "ui-only", "ui_only"}:
        return "gui_only"
    if normalized in {"headless", "server", "server-only", "server_only", "no-gui", "no_gui"}:
        return "headless"
    return "full"


def _consume_startup_options(argv: list[str]) -> StartupOptions:
    mode = _normalize_mode(os.environ.get("NEUROMITA_STARTUP_MODE", "full"))
    run_seconds = _parse_float(os.environ.get("NEUROMITA_HEADLESS_RUN_SECONDS", "0"), 0.0)
    status_interval = _parse_float(
        os.environ.get("NEUROMITA_HEADLESS_STATUS_INTERVAL", "60"),
        60.0,
    )
    remaining = [argv[0]]

    for arg in argv[1:]:
        raw = str(arg or "").strip()
        low = raw.lower()
        if low == "--gui-only":
            mode = "gui_only"
            continue
        if low in {"--headless", "--server", "--server-only", "--no-gui"}:
            mode = "headless"
            continue
        if low.startswith("--startup-mode="):
            mode = _normalize_mode(raw.split("=", 1)[1])
            continue
        if low.startswith("--headless-run-seconds=") or low.startswith("--run-seconds="):
            run_seconds = _parse_float(raw.split("=", 1)[1], run_seconds)
            continue
        if low.startswith("--headless-status-interval="):
            status_interval = _parse_float(raw.split("=", 1)[1], status_interval)
            continue
        if low.startswith("--server-host="):
            os.environ["NEUROMITA_SERVER_HOST"] = raw.split("=", 1)[1].strip()
            continue
        if low.startswith("--server-port="):
            os.environ["NEUROMITA_SERVER_PORT"] = raw.split("=", 1)[1].strip()
            continue
        remaining.append(arg)

    argv[:] = remaining
    return StartupOptions(
        mode=mode,
        headless_run_seconds=run_seconds,
        headless_status_interval=status_interval,
    )


def _run_gui(runtime, startup_mode: str) -> int:
    logger = runtime.logger
    QApplication = runtime.QApplication
    if QApplication is None:
        raise RuntimeError("GUI runtime was not initialized")

    startup_trace.mark("gui.host.start")
    logger.success("Функция main() запущена")
    with startup_trace.phase("gui.qapplication_create"):
        app = QApplication(sys.argv)
    logger.info("QApplication создан")
    from controllers.gui.qt_dispatch import install_qt_dispatcher
    from controllers.gui.qt_logging import install_qt_message_logging

    install_qt_message_logging(logger)

    install_qt_dispatcher(app)

    from ui.wheel_guard import install_combobox_wheel_guard

    install_combobox_wheel_guard(app)

    try:
        from ui.app_icon import application_icon, set_app_user_model_id

        # Закрепляем идентичность в панели задач ДО создания окон, иначе после
        # перезапуска detached-процессом иконка наследуется от python.exe.
        set_app_user_model_id()
        app.setWindowIcon(application_icon())
    except Exception:
        pass

    with startup_trace.phase("gui.shell_services_create"):
        from controllers.settings_controller import SettingsController
        from core.app_paths import settings_path
        from core.services import services
        from services.character_registry import SettingsOnlyCharacterRegistry
        from services.contracts import (
            AppVarsService,
            ASRSettingsService,
            CharacterRegistry,
            GameLinkService,
            LoopService,
            SettingsService,
            InstallableCatalogService,
            HardwareInventoryService,
        )
        from services.game_link_service import DisconnectedGameLinkService
        from services.loop_service import NoLoopService
        from services.settings_service import DefaultAppVarsService

        shell_settings_controller = SettingsController(
            str(settings_path("settings.json", create_parent=True))
        )
        shell_settings_service = services().get(SettingsService)
        if not services().is_registered(ASRSettingsService):
            from services.asr_settings_service import ensure_asr_settings_service

            ensure_asr_settings_service()
        if not services().is_registered(HardwareInventoryService):
            from services.hardware_inventory_service import WindowsHardwareInventoryService

            services().register(
                HardwareInventoryService,
                WindowsHardwareInventoryService(),
            )
        if not services().is_registered(InstallableCatalogService):
            from services.installable_catalog_service import DefaultInstallableCatalogService

            services().register(
                InstallableCatalogService,
                DefaultInstallableCatalogService(shell_settings_service),
            )
        shell_game_link = DisconnectedGameLinkService()
        services().register(GameLinkService, shell_game_link, replace=True)
        services().register(LoopService, NoLoopService(), replace=True)
        services().register(
            CharacterRegistry,
            SettingsOnlyCharacterRegistry(shell_settings_service),
            replace=True,
        )
        services().register(
            AppVarsService,
            DefaultAppVarsService(shell_settings_service, shell_game_link),
            replace=True,
        )

    with startup_trace.phase("gui.window_import"):
        from controllers.gui.composition_root import GuiCompositionRoot

    logger.info("Создаю GUI composition root...")
    with startup_trace.phase("gui.window_create"):
        gui_root = GuiCompositionRoot(shell_settings_controller)
        main_window = gui_root.window
    logger.info("GUI composition root создан")

    main_window.show()
    startup_trace.mark("gui.window_shown")
    app.processEvents()
    startup_trace.mark("gui.first_paint")
    startup_trace.write()

    from PyQt6.QtCore import QTimer
    from startup.gui_backend_loader import GuiBackendLoader

    def on_backend_ready(controller) -> None:
        try:
            with startup_trace.phase("gui.controller_attach"):
                gui_root.attach_backend(controller)
            QTimer.singleShot(0, main_window.load_chat_history)
            startup_trace.mark("gui.backend_attached")
            startup_trace.write()
            home_page = getattr(main_window, "home_page", None)
            if home_page is not None:
                home_page.refresh_status_cards()
        except Exception as exc:
            logger.error(f"Failed to attach GUI backend: {exc}", exc_info=True)
            try:
                controller.close_app()
            except Exception:
                pass
            on_backend_failed(exc)

    def on_backend_failed(error: BaseException) -> None:
        message = f"Backend startup failed: {type(error).__name__}: {error}"
        logger.error(message)
        gui_root.backend_failed(error)

    backend_loader = GuiBackendLoader(
        runtime=runtime,
        startup_mode=startup_mode,
        settings_controller=shell_settings_controller,
        on_ready=on_backend_ready,
        on_failed=on_backend_failed,
        parent=app,
    )
    main_window.backend_loader = backend_loader
    app.aboutToQuit.connect(backend_loader.request_shutdown)
    app.aboutToQuit.connect(gui_root.close)

    def close_shell_catalog() -> None:
        try:
            catalog = services().get_optional(InstallableCatalogService)
            if catalog is not None:
                catalog.close()
        except Exception:
            pass

    app.aboutToQuit.connect(close_shell_catalog)

    try:
        from utils.win_titlebar import apply_dark_titlebar, install_dark_titlebar_sync

        install_dark_titlebar_sync(app)
        apply_dark_titlebar(main_window)
    except Exception:
        pass

    QTimer.singleShot(0, main_window.activate_current_main_page)
    QTimer.singleShot(0, backend_loader.start)
    startup_trace.mark("gui.ready_for_event_loop")
    startup_trace.write()
    logger.info("Запускаю app.exec()...")
    result = int(app.exec())
    backend_loader.request_shutdown()
    if not backend_loader.wait(timeout=5.0):
        logger.warning("GUI backend startup thread did not stop within 5 seconds")
    if result < 0:
        logger.critical(
            "Qt event loop terminated with an invalid negative exit code: %d",
            result,
        )
        return 1
    return result


def _run_headless(runtime, options: StartupOptions) -> int:
    from startup.headless_runtime import HeadlessOptions, HeadlessRuntimeHost

    host = HeadlessRuntimeHost(
        runtime,
        HeadlessOptions(
            run_seconds=options.headless_run_seconds,
            status_interval=options.headless_status_interval,
        ),
    )
    return host.run()


def main() -> int:
    mp.freeze_support()
    options = _consume_startup_options(sys.argv)
    startup_trace.configure(mode=options.mode)
    startup_trace.mark("entry.options_parsed", mode=options.mode)

    from startup.runtime_bootstrap import initialize_runtime

    runtime = initialize_runtime(
        __file__,
        load_gui=options.mode != "headless",
        defer_backend_bootstrap=options.mode != "headless",
    )
    startup_trace.mark("entry.runtime_initialized")
    if options.mode == "headless":
        return _run_headless(runtime, options)
    return _run_gui(runtime, options.mode)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        try:
            from main_logger import logger

            logger.error("Ошибка в main()", exc_info=True)
        except Exception:
            pass
        raise
