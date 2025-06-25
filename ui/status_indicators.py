import tkinter as tk
from utils import _


def create_status_indicators(gui, parent):
    """Создает индикаторы статуса в родительском виджете."""
    status_frame = tk.Frame(parent, bg="#2c2c2c")
    status_frame.pack(fill=tk.X, padx=10, pady=5)

    # Стиль для чекбоксов
    style = {"bg": "#2c2c2c", "fg": "#ffffff", "selectcolor": "#2c2c2c", "activebackground": "#2c2c2c",
             "activeforeground": "#ffffff", "font": ("Arial", 10)}

    # Индикатор подключения к игре
    gui.game_status_checkbox = tk.Checkbutton(
        status_frame, text=_('Игра', 'Game'), variable=gui.game_connected_checkbox_var,
        state=tk.DISABLED, **style
    )
    gui.game_status_checkbox.pack(side=tk.LEFT, padx=5)

    # Индикатор подключения к Телеграм (TG)
    gui.silero_status_checkbox = tk.Checkbutton(
        status_frame, text=_('Телеграм', 'Telegram'), variable=gui.silero_connected,
        state=tk.DISABLED, **style
    )
    gui.silero_status_checkbox.pack(side=tk.LEFT, padx=5)

    # Индикатор распознавания речи
    gui.mic_status_checkbox = tk.Checkbutton(
        status_frame, text=_('Распознавание', 'Recognition'), variable=gui.mic_recognition_active,
        state=tk.DISABLED, **style
    )
    gui.mic_status_checkbox.pack(side=tk.LEFT, padx=5)

    # Индикатор захвата экрана
    gui.screen_capture_status_checkbox = tk.Checkbutton(
        status_frame, text=_('Захват экрана', 'Screen'), variable=gui.screen_capture_active,
        state=tk.DISABLED, **style
    )
    gui.screen_capture_status_checkbox.pack(side=tk.LEFT, padx=5)

    # Индикатор захвата камеры
    gui.camera_capture_status_checkbox = tk.Checkbutton(
        status_frame, text=_('Камера', 'Camera'), variable=gui.camera_capture_active,
        state=tk.DISABLED, **style
    )
    gui.camera_capture_status_checkbox.pack(side=tk.LEFT, padx=5)

    # Первоначальное обновление цветов
    gui.update_status_colors()