import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import socket
import json
import base64
import os


class SocketClientTester(tk.Tk):
    """
    GUI-клиент для тестирования ChatServer с функцией периодической автоотправки.
    """

    def __init__(self):
        super().__init__()
        self.title("Game Client Emulator")
        self.geometry("900x750")

        # Счетчик для автоматического увеличения ID сообщения
        self.message_id_counter = 1
        # Списки для хранения путей и base64-строк изображений
        self.image_paths = []
        self.image_base64_list = []

        # Для управления циклом автоотправки
        self.auto_send_job_id = None
        self.is_auto_sending = False

        # Создаем основной фрейм
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Создаем виджеты
        self.create_widgets(main_frame)
        self.set_default_values()

    def create_widgets(self, parent):
        """Создает и размещает все виджеты в окне."""
        # --- Левая колонка: Ввод данных ---
        input_frame = ttk.Labelframe(parent, text="Message Parameters", padding="10")
        input_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        # ... (все поля с entry_host до text_hierarchy остаются без изменений) ...
        # --- Секция подключения ---
        ttk.Label(input_frame, text="Host:").grid(row=0, column=0, sticky="w", pady=2)
        self.entry_host = ttk.Entry(input_frame, width=20)
        self.entry_host.grid(row=0, column=1, sticky="ew")

        ttk.Label(input_frame, text="Port:").grid(row=1, column=0, sticky="w", pady=2)
        self.entry_port = ttk.Entry(input_frame, width=20)
        self.entry_port.grid(row=1, column=1, sticky="ew")

        # --- Основные параметры сообщения ---
        ttk.Label(input_frame, text="ID:").grid(row=2, column=0, sticky="w", pady=2)
        self.entry_id = ttk.Entry(input_frame)
        self.entry_id.grid(row=2, column=1, sticky="ew")

        ttk.Label(input_frame, text="Type:").grid(row=3, column=0, sticky="w", pady=2)
        self.entry_type = ttk.Entry(input_frame)
        self.entry_type.grid(row=3, column=1, sticky="ew")

        ttk.Label(input_frame, text="Character:").grid(row=4, column=0, sticky="w", pady=2)
        self.entry_character = ttk.Entry(input_frame)
        self.entry_character.grid(row=4, column=1, sticky="ew")

        ttk.Label(input_frame, text="Input (for manual send):").grid(row=5, column=0, sticky="w", pady=2)
        self.entry_input = ttk.Entry(input_frame)
        self.entry_input.grid(row=5, column=1, sticky="ew")

        ttk.Label(input_frame, text="System Message:").grid(row=6, column=0, sticky="w", pady=2)
        self.entry_system_message = ttk.Entry(input_frame)
        self.entry_system_message.grid(row=6, column=1, sticky="ew")

        ttk.Label(input_frame, text="System Info:").grid(row=7, column=0, sticky="w", pady=2)
        self.entry_system_info = ttk.Entry(input_frame)
        self.entry_system_info.grid(row=7, column=1, sticky="ew")

        # --- Дополнительные параметры ---
        ttk.Label(input_frame, text="Distance:").grid(row=8, column=0, sticky="w", pady=2)
        self.entry_distance = ttk.Entry(input_frame)
        self.entry_distance.grid(row=8, column=1, sticky="ew")

        ttk.Label(input_frame, text="Player Room:").grid(row=9, column=0, sticky="w", pady=2)
        self.entry_room_player = ttk.Entry(input_frame)
        self.entry_room_player.grid(row=9, column=1, sticky="ew")

        ttk.Label(input_frame, text="Mita Room:").grid(row=10, column=0, sticky="w", pady=2)
        self.entry_room_mita = ttk.Entry(input_frame)
        self.entry_room_mita.grid(row=10, column=1, sticky="ew")

        ttk.Label(input_frame, text="Current Info:").grid(row=11, column=0, sticky="w", pady=2)
        self.entry_current_info = ttk.Entry(input_frame)
        self.entry_current_info.grid(row=11, column=1, sticky="ew")

        self.dialog_active_var = tk.BooleanVar()
        self.check_dialog_active = ttk.Checkbutton(input_frame, text="Dialog Active", variable=self.dialog_active_var)
        self.check_dialog_active.grid(row=12, column=0, columnspan=2, sticky="w", pady=5)

        ttk.Label(input_frame, text="Near Objects (hierarchy, one per line):").grid(row=13, column=0, columnspan=2,
                                                                                    sticky="w", pady=2)
        self.text_hierarchy = tk.Text(input_frame, height=3, width=30)
        self.text_hierarchy.grid(row=14, column=0, columnspan=2, sticky="ew")

        # --- НОВАЯ СЕКЦИЯ: Автоотправка ---
        auto_send_frame = ttk.Labelframe(input_frame, text="Auto-Send 'waiting' message", padding="5")
        auto_send_frame.grid(row=15, column=0, columnspan=2, pady=10, sticky="ew")

        self.auto_send_var = tk.BooleanVar(value=False)
        self.check_auto_send = ttk.Checkbutton(
            auto_send_frame, text="Enable Auto-Send", variable=self.auto_send_var, command=self.toggle_auto_send
        )
        self.check_auto_send.grid(row=0, column=0, sticky="w")

        ttk.Label(auto_send_frame, text="Interval (ms):").grid(row=0, column=1, sticky="e", padx=(10, 2))
        self.entry_interval = ttk.Entry(auto_send_frame, width=8)
        self.entry_interval.grid(row=0, column=2, sticky="e")
        self.entry_interval.insert(0, "500")

        # --- Изображения ---
        image_frame = ttk.Frame(input_frame)
        image_frame.grid(row=16, column=0, columnspan=2, pady=5, sticky="ew")
        self.btn_add_image = ttk.Button(image_frame, text="Add Image", command=self.add_image)
        self.btn_add_image.pack(side=tk.LEFT, padx=5)
        self.btn_clear_images = ttk.Button(image_frame, text="Clear Images", command=self.clear_images)
        self.btn_clear_images.pack(side=tk.LEFT)
        self.lbl_images = ttk.Label(input_frame, text="Images: None", wraplength=300)
        self.lbl_images.grid(row=17, column=0, columnspan=2, sticky="w")

        # --- Кнопка отправки ---
        self.btn_send = ttk.Button(input_frame, text="Send Manual Message", command=self.send_manual_message)
        self.btn_send.grid(row=18, column=0, columnspan=2, pady=15, sticky="ew")

        input_frame.columnconfigure(1, weight=1)

        # --- Правая колонка: Логи ---
        log_frame = ttk.Frame(parent, padding="10")
        log_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")

        request_log_frame = ttk.Labelframe(log_frame, text="Sent JSON", padding="5")
        request_log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.text_request = tk.Text(request_log_frame, height=15, width=50, wrap=tk.WORD, bg="#f0f0f0")
        self.text_request.pack(fill=tk.BOTH, expand=True)

        response_log_frame = ttk.Labelframe(log_frame, text="Received JSON", padding="5")
        response_log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.text_response = tk.Text(response_log_frame, height=15, width=50, wrap=tk.WORD, bg="#e0f7e0")
        self.text_response.pack(fill=tk.BOTH, expand=True)

        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=2)
        parent.rowconfigure(0, weight=1)

    def set_default_values(self):
        # ... (метод без изменений) ...
        self.entry_host.insert(0, "127.0.0.1")
        self.entry_port.insert(0, "12345")
        self.entry_id.insert(0, str(self.message_id_counter))
        self.entry_type.insert(0, "user")
        self.entry_character.insert(0, "Player")
        self.entry_input.insert(0, "Привет, Мита!")  # Изменено для наглядности
        self.entry_system_message.insert(0, "-")
        self.entry_system_info.insert(0, "-")
        self.entry_distance.insert(0, "2.5")
        self.entry_room_player.insert(0, "1")
        self.entry_room_mita.insert(0, "1")
        self.entry_current_info.insert(0, "Солнечный день, мы находимся в лесу.")
        self.text_hierarchy.insert(tk.END, "Дерево\nПень\nТропинка")
        self.dialog_active_var.set(True)

    def add_image(self):
        # ... (метод без изменений) ...
        filepath = filedialog.askopenfilename(title="Select an image", filetypes=(
        ("PNG files", "*.png"), ("JPEG files", "*.jpg"), ("All files", "*.*")))
        if not filepath: return
        try:
            with open(filepath, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                self.image_paths.append(os.path.basename(filepath))
                self.image_base64_list.append(encoded_string)
                self.lbl_images.config(text=f"Images: {', '.join(self.image_paths)}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not read or encode image:\n{e}")

    def clear_images(self):
        # ... (метод без изменений) ...
        self.image_paths = []
        self.image_base64_list = []
        self.lbl_images.config(text="Images: None")

    def toggle_auto_send(self):
        """Включает или выключает цикл автоматической отправки."""
        self.is_auto_sending = self.auto_send_var.get()

        if self.is_auto_sending:
            self.btn_send.config(state=tk.DISABLED)
            self.run_auto_send_loop()
        else:
            if self.auto_send_job_id:
                self.after_cancel(self.auto_send_job_id)
                self.auto_send_job_id = None
            self.btn_send.config(state=tk.NORMAL)

    def run_auto_send_loop(self):
        """Выполняет один шаг цикла автоотправки и планирует следующий."""
        if not self.is_auto_sending:
            return

        # Выполняем отправку
        self.execute_send_logic(is_auto_send=True)

        # Планируем следующий запуск
        try:
            interval = int(self.entry_interval.get())
        except ValueError:
            interval = 500  # Значение по умолчанию в случае ошибки ввода

        self.auto_send_job_id = self.after(interval, self.run_auto_send_loop)

    def send_manual_message(self):
        """Инициирует отправку сообщения вручную."""
        self.execute_send_logic(is_auto_send=False)

    def execute_send_logic(self, is_auto_send):
        """Основная логика сборки и отправки сообщения."""
        # 1. Сбор данных из полей GUI
        try:
            message_input = "waiting" if is_auto_send else self.entry_input.get()

            payload = {
                "id": int(self.entry_id.get()), "type": self.entry_type.get(), "character": self.entry_character.get(),
                "input": message_input,
                "dataToSentSystem": self.entry_system_message.get(), "systemInfo": self.entry_system_info.get(),
                "distance": self.entry_distance.get().replace(",", "."),
                "roomPlayer": int(self.entry_room_player.get()),
                "roomMita": int(self.entry_room_mita.get()),
                "hierarchy": [line for line in self.text_hierarchy.get("1.0", tk.END).strip().split('\n') if line],
                "currentInfo": self.entry_current_info.get(), "dialog_active": self.dialog_active_var.get(),
                # Изображения отправляем только вручную, чтобы не нагружать сеть
                "image_base64_list": self.image_base64_list if not is_auto_send else []
            }
        except ValueError as e:
            if not is_auto_send: messagebox.showerror("Input Error", f"Invalid number format: {e}")
            return

        # 2. Отображение отправляемого JSON
        self.text_request.delete("1.0", tk.END)
        self.text_request.insert(tk.END, json.dumps(payload, indent=4))
        self.text_response.delete("1.0", tk.END)

        # 3. Отправка данных через сокет
        host = self.entry_host.get()
        port = int(self.entry_port.get())
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            client_socket.connect((host, port))
            message_bytes = json.dumps(payload).encode('utf-8')
            client_socket.sendall(message_bytes)

            response_bytes = b""
            while True:
                chunk = client_socket.recv(4096)
                if not chunk: break
                response_bytes += chunk
            response_str = response_bytes.decode('utf-8')

            try:
                response_json = json.loads(response_str)
                self.text_response.insert(tk.END, json.dumps(response_json, indent=4, ensure_ascii=False))
            except json.JSONDecodeError:
                self.text_response.insert(tk.END, f"Error: Could not decode JSON.\n\nRaw response:\n{response_str}")

            # Увеличиваем ID для следующего сообщения
            self.message_id_counter += 1
            self.entry_id.delete(0, tk.END)
            self.entry_id.insert(0, str(self.message_id_counter))

            # Очищаем изображения только после ручной отправки
            if not is_auto_send:
                self.clear_images()

        except socket.error as e:
            error_message = f"Socket Error: {e}"
            self.text_response.insert(tk.END, error_message + "\n")
            if not is_auto_send:  # Показываем всплывающее окно только при ручной отправке
                messagebox.showerror("Connection Error", error_message)
            # Если произошла ошибка, останавливаем автоотправку, чтобы не спамить лог
            if self.is_auto_sending:
                self.auto_send_var.set(False)
                self.toggle_auto_send()

        finally:
            client_socket.close()


if __name__ == "__main__":
    app = SocketClientTester()
    app.mainloop()