# ui/status_indicators.py
import tkinter as tk
from utils import getTranslationVariant as _

def create_status_indicators(self, parent):
    # Создаем фрейм для индикаторов
    status_frame = tk.Frame(parent, bg="#2c2c2c")
    status_frame.pack(fill=tk.X, pady=3)

    # Переменные статуса
    self.game_connected_checkbox_var = tk.BooleanVar(value=False)  # Статус подключения к игре
    self.silero_connected = tk.BooleanVar(value=False)  # Статус подключения к Silero

    # Галки для подключения
    self.game_status_checkbox = tk.Checkbutton(
        status_frame,
        text=_("Подключение к игре", "Connection to game"),
        variable=self.game_connected_checkbox_var,
        state="disabled",
        bg="#2c2c2c",
        fg="#ffffff",
        selectcolor="#2c2c2c"
    )
    self.game_status_checkbox.pack(side=tk.LEFT, padx=5, pady=4)

    self.silero_status_checkbox = tk.Checkbutton(
        status_frame,
        text=_("Подключение Telegram", "Connection Telegram"),
        variable=self.silero_connected,
        state="disabled",
        bg="#2c2c2c",
        fg="#ffffff",
        selectcolor="#2c2c2c"
    )
    self.silero_status_checkbox.pack(side=tk.LEFT, padx=5, pady=4)