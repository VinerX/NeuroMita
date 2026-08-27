# hoi4_server

import json, os, time, threading, queue, pathlib, sys
from datetime import datetime

from connetors.hoi4.hoi4_connector import run_console_cmd

# --- настройка ---------------------------------------------------------------
LOG_PATH = pathlib.Path(
    os.path.expandvars(
        r"%USERPROFILE%\Documents\Paradox Interactive\Hearts of Iron IV\logs\game.log"
    )
)

LINE_PREFIX = ("MITA_OUT")         # такой же как в моде
GAME_WINDOW_TITLE = "Hearts of Iron IV"

# -----------------------------------------------------------------------------


# ============ 1. «Хвостим» game.log ==========================================
class LogTailer(threading.Thread):
    def __init__(self, path: pathlib.Path, out_queue: queue.Queue, prefix: str):
        super().__init__(daemon=True)
        self.path, self.out_queue, self.prefix = path, out_queue, prefix

    def reopen_if_rotated(self, file_obj, last_inode):
        """
        В debug-режиме Clausewitz переоткрывает лог при alt+tab.
        Проверяем inode, перескакиваем на новый файл, если надо.
        """
        try:
            if os.stat(self.path).st_ino != last_inode:
                file_obj.close()
                return open(self.path, encoding="utf-8"), os.stat(self.path).st_ino
        except FileNotFoundError:
            pass
        return file_obj, last_inode

    def run(self):
        while not self.path.exists():
            print("Ожидаю появление game.log…")
            time.sleep(1)

        f = open(self.path, encoding="utf-8")
        f.seek(0, os.SEEK_END)                 # начинаем читать с конца
        inode = os.fstat(f.fileno()).st_ino

        print("[Tailer] запущен")
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.05)
                f, inode = self.reopen_if_rotated(f, inode)
                continue

            if self.prefix in line:
                print(f"Найден новый вызов! {line}")
                payload = line.split(self.prefix, 1)[1].strip()
                try:
                    data = json.loads(payload)
                    self.out_queue.put(data)  # кидаем в очередь «события от игры»
                    print("[Tailer] >", data)
                except json.JSONDecodeError:
                    print("JSON-ошибка в строке лога:", payload)


# ============ 2. Инжектор команд в консоль ===================================
import pyautogui, win32gui

class ConsoleInjector(threading.Thread):
    def __init__(self, in_queue: queue.Queue):
        super().__init__(daemon=True)
        self.in_queue = in_queue

    def focus_window(self):
        hwnd = win32gui.FindWindow(None, GAME_WINDOW_TITLE)
        if hwnd:
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.05)


    # Маппинг JSON-команд → куска клавиатуры
    def perform_command(self, cmd: dict):
        kind = cmd.get("cmd")
        if kind == "build_factory":
            state  = cmd.get("state", 1)
            count  = cmd.get("count", 1)
            tag    = cmd.get("tag",  "GER")

            run_console_cmd("set_global_flag mita_build_factory")
            run_console_cmd(f"set_global_variable mita_state = {state}")
            run_console_cmd(f"set_global_variable mita_count = {count}")
            run_console_cmd(f"event mitanet.999 {tag}")

        elif kind == "give_pp":
            amount = cmd.get("amount", 100)
            run_console_cmd(f"pp {amount}")

        # …добавляйте свои типы команд
        else:
            print("Неизвестная команда:", cmd)

    def run(self):
        print("[Injector] запущен")
        while True:
            cmd = self.in_queue.get()
            if cmd is None:
                break
            print("[Injector] <", cmd)
            self.perform_command(cmd)
            self.in_queue.task_done()


# ============ 3. Заглушка «нейронки» =========================================
def dummy_ai_logic(event: dict) -> dict | None:
    """
    Простая логика для тестов.
    Например, если увидели событие 'war', строим заводы,
    иначе ничего не делаем.
    """
    if event.get("type") == "heartbeat":
        # раз в 3 дня дарим себе 50 полит.власти
        return {"cmd": "give_pp", "amount": 50}

    if event.get("type") == "war":
        return {
            "cmd":   "build_factory",
            "state": 70,            # Берлин
            "count": 2,
            "tag":   event.get("actor_tag", "GER")
        }
    return None


# ============ 4. Склеиваем всё вместе ========================================
def main():
    tail_to_ai = queue.Queue()          # события из игры
    ai_to_game = queue.Queue()          # команды в игру

    tailer   = LogTailer(LOG_PATH, tail_to_ai, LINE_PREFIX)
    injector = ConsoleInjector(ai_to_game)

    tailer.start()
    injector.start()

    print("=== MITA Bridge запущен, ждём событий… ===")
    while True:
        evt = tail_to_ai.get()          # блокирует поток
        # здесь вы бы вызвали свою LLM-модель
        cmd = dummy_ai_logic(evt)
        if cmd:
            ai_to_game.put(cmd)

        tail_to_ai.task_done()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Выход.")
        sys.exit(0)