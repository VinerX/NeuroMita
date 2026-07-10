from __future__ import annotations

import multiprocessing as mp
import os
import sys
from dataclasses import dataclass

os.environ.setdefault("QT_API", "pyqt6")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
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

    from controllers.main_controller import MainController
    from ui.windows.main_window import MainWindow

    logger.success("Функция main() запущена")
    app = QApplication(sys.argv)
    logger.info("QApplication создан")

    from ui.wheel_guard import install_combobox_wheel_guard

    install_combobox_wheel_guard(app)

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "mycompany.myproduct.subproduct.version"
            )
        except Exception:
            pass

    logger.info("Создаю MainController...")
    controller = MainController(None, startup_mode=startup_mode)
    logger.info("MainController создан")

    try:
        from managers.finetune_collector import FineTuneCollector
        from managers.generation_input_collector import GenerationInputCollector

        FineTuneCollector.instance = FineTuneCollector()
        GenerationInputCollector.instance = GenerationInputCollector()
        logger.info("FineTuneCollector инициализирован")
    except Exception as exc:
        logger.warning(f"FineTuneCollector не инициализирован: {exc}")

    logger.info("Создаю MainWindow...")
    main_window = MainWindow(controller.settings)
    logger.info("MainWindow создан")
    controller.update_view(main_window)
    main_window.load_chat_history()

    try:
        from utils.win_titlebar import apply_dark_titlebar, install_dark_titlebar_sync

        install_dark_titlebar_sync(app, True)
        apply_dark_titlebar(main_window, True)
    except Exception:
        pass

    app.aboutToQuit.connect(controller.close_app)
    main_window.show()
    logger.info("Запускаю app.exec()...")
    return int(app.exec())


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

    from startup.runtime_bootstrap import initialize_runtime

    runtime = initialize_runtime(__file__, load_gui=options.mode != "headless")
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
