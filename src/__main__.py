from __future__ import annotations

import multiprocessing as mp
import os
import sys

os.environ.setdefault("QT_API", "pyqt6")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("UV_LINK_MODE", "copy")


def _consume_startup_mode(argv: list[str]) -> str:
    mode = str(os.environ.get("NEUROMITA_STARTUP_MODE", "full") or "full").strip().lower()
    remaining = [argv[0]]

    for arg in argv[1:]:
        low = str(arg or "").strip().lower()
        if low == "--gui-only":
            mode = "gui_only"
            continue
        if low.startswith("--startup-mode="):
            mode = low.split("=", 1)[1] or mode
            continue
        remaining.append(arg)

    argv[:] = remaining
    if mode in {"gui-only", "gui_only", "ui-only", "ui_only"}:
        return "gui_only"
    return "full"


def main() -> int:
    mp.freeze_support()

    from startup.runtime_bootstrap import initialize_runtime

    runtime = initialize_runtime(__file__)
    logger = runtime.logger
    QApplication = runtime.QApplication

    from controllers.main_controller import MainController
    from ui.windows.main_window import MainWindow

    logger.success("Функция main() запущена")
    startup_mode = _consume_startup_mode(sys.argv)
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
