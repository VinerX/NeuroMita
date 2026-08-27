#hoi4_connector.py

import ctypes
import time
import pyautogui
import win32clipboard
import win32gui
import win32con
import win32api
import win32process
import psutil

# ──────────────────────────────────────────────
# 1.  Поиск окна HoI4
# ──────────────────────────────────────────────
WINDOW_KEYWORD = "hearts of iron iv"      # искать без учёта регистра

def find_hoi4_hwnd():
    """
    Возвращает дескриптор первого видимого окна HoI4.
    Сначала ищем процесс hoi4.exe, затем все его окна.
    """
    target_pid = None
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] and "hoi4" in proc.info['name'].lower():
            target_pid = proc.info['pid']
            break

    if target_pid is None:
        return None

    hwnds = []
    def enum_cb(hwnd, _):
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == target_pid and win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).lower()
            if WINDOW_KEYWORD in title:
                hwnds.append(hwnd)

    win32gui.EnumWindows(enum_cb, None)
    return hwnds[0] if hwnds else None


def focus_hoi4() -> bool:
    hwnd = find_hoi4_hwnd()
    if not hwnd:
        print("⚠️  HoI4 окно не найдено")
        return False

    # разворачиваем, если свернуто
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.05)

    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.05)               # даём ОС переключить фокус
    return True


# ──────────────────────────────────────────────
# 2.  Открыть / закрыть консоль  (VK_OEM_3 = `~)
# ──────────────────────────────────────────────
VK_OEM_3   = 0xC0      # виртуальный код клавиши «` / ~ / §»
SCAN_GRAVE = 0x29      # физический scancode; пригодится для надёжности

def tap_console_key():
    # key down
    win32api.keybd_event(VK_OEM_3, SCAN_GRAVE, 0, 0)
    time.sleep(0.1)
    # key up
    win32api.keybd_event(VK_OEM_3, SCAN_GRAVE, win32con.KEYEVENTF_KEYUP, 0)


# ──────────────────────────────────────────────
# 3.  Выполнить одну консольную команду
# ──────────────────────────────────────────────
def run_console_cmd(cmd: str):
    if not focus_hoi4():
        return

    tap_console_key()               # открыть
    time.sleep(0.05)
    tap_backspace()
    tap_backspace()
    time.sleep(0.05)
    send_text(cmd)
    time.sleep(0.05)
    tap_enter_key()

    tap_console_key()               # закрыть


# ──────────────────────────────────────────────
# 4.  Пример высокоуровневой команды
# ──────────────────────────────────────────────
def send_build_factory(state_id: int, count: int, tag: str = "GER"):
    run_console_cmd("set_global_flag mita_build_factory")
    run_console_cmd(f"set_global_variable mita_state = {state_id}")
    run_console_cmd(f"set_global_variable mita_count = {count}")
    run_console_cmd(f"event mitanet.999 {tag}")



# ─────────── helper: нажать-отпустить любую клавишу ────────────
def tap_key(vk: int, scan: int | None = None, hold: float = 0.05):
    scan = scan or 0
    win32api.keybd_event(vk, scan, 0, 0)                     # down
    time.sleep(hold)
    win32api.keybd_event(vk, scan, win32con.KEYEVENTF_KEYUP, 0)  # up

# консольная клавиша `  (гравис)
VK_OEM_3, SCAN_GRAVE = 0xC0, 0x29
def tap_console_key():          # была раньше
    tap_key(VK_OEM_3, SCAN_GRAVE)

# клавиша Enter
VK_RETURN, SCAN_RETURN = 0x0D, 0x1C
def tap_enter_key():
    tap_key(VK_RETURN, SCAN_RETURN, hold=0.03)

# ────────── BackSpace ──────────
VK_BACK, SCAN_BACK = 0x08, 0x0E
def tap_backspace():
    tap_key(VK_BACK, SCAN_BACK, hold=0.02)
# ------------------------------------------------------------
# helpers для SendInput
# ------------------------------------------------------------
PUL = ctypes.POINTER(ctypes.c_ulong)

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk",      ctypes.c_ushort),
                ("wScan",    ctypes.c_ushort),
                ("dwFlags",  ctypes.c_ulong),
                ("time",     ctypes.c_ulong),
                ("dwExtraInfo", PUL)]

class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong),
                ("ii",   _INPUTunion)]

SendInput = ctypes.windll.user32.SendInput
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP   = 0x0002

def _send_unicode_char(ch: str, up: bool = False):
    """Посылает один символ (нажатие или отпускание)."""
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    ki = KEYBDINPUT(0, ord(ch), flags, 0, None)
    inp = INPUT(1, _INPUTunion(ki=ki))
    SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

# ------------------------------------------------------------
# собственно ввод строки
# ------------------------------------------------------------
def send_text(text: str, delay: float = 0.006):
    """
    Печатает text в текущее активное окно с помощью keybd_event +
    KEYEVENTF_UNICODE.  Работает без учёта раскладки.
    """
    for ch in text:
        # key DOWN
        win32api.keybd_event(
            0,                      # wVk   (виртуального кода нет)
            ord(ch),                # wScan ← именно сюда кладём Unicode-код
            KEYEVENTF_UNICODE,      # флаг UNICODE
            0
        )

        # key UP
        win32api.keybd_event(
            0,
            ord(ch),
            KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
            0
        )
        time.sleep(delay)
# ──────────────────────────────────────────────
# 5.  Тест
# ──────────────────────────────────────────────
if __name__ == "__main__":
    # пример: построить 3 завода в Берлине (state 70)
    send_build_factory(70, 3)