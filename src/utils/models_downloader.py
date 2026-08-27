# import os
# import requests
# import re
# import tempfile
# import py7zr
# import time
# import shutil
# from urllib.parse import urlparse, unquote
# import tkinter as tk
# from tkinter import ttk, messagebox
# import threading
# import traceback

# from SettingsManager import SettingsManager


# def getTranslationVariant(ru_str, en_str=""):
#     lang = SettingsManager.get("LANGUAGE", "RU")
#     if en_str and lang == "EN":
#         return en_str
#     return ru_str

# _ = getTranslationVariant

# class OperationCancelledError(Exception):
#     pass

# class ModelsDownloader:
#     DEFAULT_LIST_URL = "https://pixeldrain.com/l/YQgQ8MsG#item=3"

#     def __init__(self, target_dir=".", list_url=None):
#         self.list_url = list_url if list_url else self.DEFAULT_LIST_URL
#         self.target_dir = os.path.abspath(target_dir)
#         self.expected_filename = "Models.7z"
#         self._download_window = None
#         self._status_var = None
#         self._progress_bar = None
#         self._cancel_requested = False
#         self._download_thread = None
#         self._result_status = None

#     def _check_cancel_internal(self):
#         if self._cancel_requested:
#             raise OperationCancelledError(_("Операция отменена пользователем.", "Operation cancelled by user."))

#     def _request_cancel_internal(self):
#         if not self._cancel_requested:
#             self._cancel_requested = True
#             if self._status_var:
#                 self._update_status_gui(_("Отмена...", "Cancelling..."))
#             if self._download_window:
#                 for widget in self._download_window.winfo_children():
#                     if isinstance(widget, tk.Button) and _("Отменить", "Cancel") in widget.cget("text"):
#                         self._download_window.after(0, lambda w=widget: w.config(state=tk.DISABLED))

#     def _update_status_gui(self, message):
#         if self._download_window and self._status_var and self._download_window.winfo_exists():
#             self._download_window.after(0, lambda: self._status_var.set(message))

#     def _update_progress_gui(self, downloaded, total):
#         if self._download_window and self._progress_bar and self._download_window.winfo_exists():
#             def update_bar():
#                 if not self._progress_bar or not self._progress_bar.winfo_exists(): return
#                 if total > 0:
#                     percent = int(downloaded / total * 100)
#                     if self._progress_bar['mode'] == 'indeterminate':
#                         self._progress_bar.stop()
#                         self._progress_bar.config(mode='determinate', maximum=100)
#                     self._progress_bar.config(value=percent)
#                 else:
#                     if self._progress_bar['mode'] == 'determinate':
#                         self._progress_bar.config(mode='indeterminate', maximum=100)
#                         self._progress_bar.start(10)

#             self._download_window.after(0, update_bar)

#     def _close_download_window(self, delay_ms=1500):
#         if self._download_window and self._download_window.winfo_exists():
#             self._download_window.after(delay_ms, self._download_window.destroy)
#         self._download_window = None
#         self._status_var = None
#         self._progress_bar = None

#     def _get_pixeldrain_file_info(self):
#         self._update_status_gui(_("Анализ URL...", "Parsing URL..."))
#         self._check_cancel_internal()
#         parsed_url = urlparse(self.list_url)
#         path_parts = parsed_url.path.strip('/').split('/')
#         if len(path_parts) < 2 or path_parts[0] != 'l':
#             raise ValueError(_("Неверный URL списка Pixeldrain.", "Invalid Pixeldrain list URL."))
#         list_id = path_parts[1]
#         item_index = 0
#         if parsed_url.fragment:
#             match = re.search(r'item=(\d+)', parsed_url.fragment)
#             if match:
#                 item_number = int(match.group(1))
#                 if item_number > 0:
#                     item_index = item_number
#                 else:
#                     raise ValueError(_("Неверный номер элемента в URL (должен быть > 0).", "Invalid item number in URL (must be > 0)."))

#         api_url = f"https://pixeldrain.com/api/list/{list_id}"
#         self._update_status_gui(_("Запрос информации о файле...", "Requesting file info..."))
#         self._check_cancel_internal()
#         try:
#             response = requests.get(api_url, timeout=20)
#             response.raise_for_status()
#             list_data = response.json()
#         except requests.exceptions.Timeout:
#             raise ConnectionError(_("Тайм-аут при запросе информации о файле.", "Timeout requesting file info."))
#         except requests.exceptions.RequestException as e:
#             raise ConnectionError(f"{_('Ошибка сети при запросе информации', 'Network error requesting info')}: {e}")

#         if not list_data.get('success'):
#             raise ConnectionError(f"{_('Ошибка API Pixeldrain', 'Pixeldrain API error')}: {list_data.get('message', _('Нет сообщения об ошибке', 'No error message'))}")

#         files = list_data.get('files')
#         if not files:
#              raise ValueError(_("Список файлов пуст.", "File list is empty."))
#         if item_index >= len(files):
#             raise ValueError(_("Указанный номер элемента ({num}) превышает количество файлов ({count}) в списке.",
#                                "Specified item number ({num}) exceeds file count ({count}) in the list.").format(num=item_index + 1, count=len(files)))

#         file_info = files[item_index]
#         file_id = file_info.get('id')
#         file_name = file_info.get('name')

#         if not file_id or not file_name:
#              raise ValueError(_("Не найден ID или имя файла в ответе API.", "Missing file ID or name in API response."))

#         self.expected_filename = file_name
#         self._update_status_gui(_("Найден файл:", "File found:") + f" {self.expected_filename}")
#         return file_id, self.expected_filename

#     def _download_file(self, url, destination_archive_path):
#         self._update_status_gui(_("Скачивание:", "Downloading:") + f" {os.path.basename(destination_archive_path)}")
#         downloaded_size = 0
#         chunk_size = 8192 * 4
#         last_update_time = time.time()

#         try:
#             # Убедимся, что директория существует
#             os.makedirs(os.path.dirname(destination_archive_path), exist_ok=True)
            
#             with requests.get(url, stream=True, timeout=(15, 90)) as r:
#                 r.raise_for_status()
#                 total_size = int(r.headers.get('content-length', 0))
#                 self._update_progress_gui(0, total_size)

#                 with open(destination_archive_path, 'wb') as f:
#                     for chunk in r.iter_content(chunk_size=chunk_size):
#                         self._check_cancel_internal()
#                         if chunk:
#                             f.write(chunk)
#                             downloaded_size += len(chunk)
#                             current_time = time.time()
#                             if current_time - last_update_time > 0.3 or downloaded_size == total_size:
#                                 self._update_progress_gui(downloaded_size, total_size)
#                                 size_mb = downloaded_size / (1024 * 1024)
#                                 if total_size > 0:
#                                     total_mb_str = f"{total_size / (1024 * 1024):.1f} MB"
#                                     percent_str = f"({(downloaded_size / total_size * 100):.0f}%)"
#                                 else:
#                                     total_mb_str = "?? MB"
#                                     percent_str = ""
#                                 self._update_status_gui(f"{_('Скачано', 'Downloaded')}: {size_mb:.1f} / {total_mb_str} {percent_str}")
#                                 last_update_time = current_time

#             self._update_status_gui(_("Скачивание завершено.", "Download complete."))
#             return destination_archive_path

#         except OperationCancelledError:
#             # Если операция была отменена, удаляем частично скачанный файл
#             if os.path.exists(destination_archive_path):
#                 try: os.remove(destination_archive_path)
#                 except OSError: pass
#             raise
#         except Exception as e:
#             # Если возникла ошибка, удаляем частично скачанный файл
#             if os.path.exists(destination_archive_path):
#                 try: os.remove(destination_archive_path)
#                 except OSError: pass
#             if isinstance(e, requests.exceptions.RequestException):
#                 raise ConnectionError(f"{_('Ошибка сети при скачивании', 'Network error during download')}: {e}")
#             else:
#                 raise IOError(f"{_('Ошибка при скачивании или записи файла', 'Error downloading or writing file')}: {e}")

#     def _extract_7z(self, archive_path):
#         archive_filename = os.path.basename(archive_path)
#         self._update_status_gui(_("Распаковка:", "Extracting:") + f" {archive_filename}")

#         if self._progress_bar:
#              self._update_progress_gui(0, -1)

#         try:
#             os.makedirs(self.target_dir, exist_ok=True)
#             self._check_cancel_internal()

#             with py7zr.SevenZipFile(archive_path, mode='r') as z:
#                 z.extractall(path=self.target_dir)
#             self._check_cancel_internal()

#             self._update_status_gui(_("Распаковка завершена.", "Extraction complete."))
#             self._result_status = True
#             return True

#         except OperationCancelledError:
#             self._result_status = False
#             raise
#         except Exception as e:
#             self._result_status = False
#             print(f"Extraction Error: {e}")
#             traceback.print_exc()
#             raise RuntimeError(f"{_('Ошибка распаковки', 'Extraction error')}: {e}")
#         finally:
#             if self._progress_bar:
#                  if self._download_window and self._download_window.winfo_exists():
#                      self._download_window.after(0, lambda: self._progress_bar.stop() if self._progress_bar else None)

#     def _run_download_logic(self):
#         downloaded_archive_path = None

#         try:
#             file_id, file_name = self._get_pixeldrain_file_info()
#             download_url = f"https://pixeldrain.com/api/file/{file_id}"
            
#             # Download directly to the folder where the target directory is
#             parent_dir = os.path.dirname(self.target_dir)
#             archive_path = os.path.join(parent_dir, file_name)

#             downloaded_archive_path = self._download_file(download_url, archive_path)
#             self._check_cancel_internal()

#             self._extract_7z(downloaded_archive_path)
            
#             # Optionally remove the archive after extraction
#             if os.path.exists(downloaded_archive_path):
#                 try:
#                     os.remove(downloaded_archive_path)
#                 except OSError as e:
#                     print(f"Warning: Failed to remove archive {downloaded_archive_path}: {e}")

#             self._update_status_gui(_("Готово!", "Done!"))
#             self._result_status = True
#             self._close_download_window(delay_ms=1000)

#         except OperationCancelledError as e:
#             self._update_status_gui(str(e))
#             self._result_status = False
#             self._close_download_window()
#         except Exception as e:
#             error_message = str(e)
#             self._update_status_gui(f"{_('Ошибка', 'Error')}: {error_message}")
#             self._result_status = False
#             print(f"Download Error: {e}")
#             traceback.print_exc()
#             self._close_download_window(delay_ms=3000)

#     def are_models_installed(self):
#         return os.path.exists(os.path.join(self.target_dir, "Models")) and os.path.isdir(os.path.join(self.target_dir, "Models")) and len(os.listdir(os.path.join(self.target_dir, "Models"))) > 0

#     def download_models_if_needed(self, parent_window):
#         if self.are_models_installed():
#             print("Models already installed.")
#             return True

#         if self._download_window and self._download_window.winfo_exists():
#              print("Download window already open.")
#              self._download_window.lift()
#              self._download_window.focus_force()
#              parent_window.wait_window(self._download_window)
#              return self._result_status or False

#         if self._download_thread and self._download_thread.is_alive():
#             print("Download thread is already running.")
#             messagebox.showwarning(_("Загрузка", "Download"),
#                                    _("Процесс загрузки уже запущен в фоновом режиме.",
#                                      "A download process is already running in the background."),
#                                    parent=parent_window)
#             return False

#         self._cancel_requested = False
#         self._result_status = None

#         self._download_window = tk.Toplevel(parent_window)
#         self._download_window.title(_("Загрузка моделей", "Downloading Models"))
#         self._download_window.geometry("450x200")
#         self._download_window.configure(bg="#3a3a3a")
#         self._download_window.resizable(False, False)
#         self._download_window.transient(parent_window)
#         self._download_window.grab_set()
#         self._download_window.protocol("WM_DELETE_WINDOW", self._request_cancel_internal)

#         self._status_var = tk.StringVar(value=_("Подготовка...", "Preparing..."))
#         status_label = tk.Label(self._download_window, textvariable=self._status_var,
#                                 font=("Arial", 11), bg="#3a3a3a", fg="#ffffff",
#                                 wraplength=430, justify=tk.CENTER)
#         status_label.pack(pady=(20, 10), fill=tk.X, padx=10)

#         self._progress_bar = ttk.Progressbar(self._download_window, orient="horizontal",
#                                              length=400, mode="indeterminate")
#         self._progress_bar.pack(pady=10, padx=20)
#         self._progress_bar.start(10)

#         cancel_button = tk.Button(self._download_window, text=_("Отменить", "Cancel"),
#                                   command=self._request_cancel_internal, bg="#ff6347", fg="#ffffff",
#                                   activebackground="#e55337", activeforeground="#ffffff",
#                                   relief=tk.FLAT, bd=0, padx=10, pady=5, font=("Arial", 10))
#         cancel_button.pack(pady=(15, 20))

#         self._download_thread = threading.Thread(target=self._run_download_logic, daemon=True)
#         self._download_thread.start()

#         parent_window.wait_window(self._download_window)

#         final_result = self._result_status if self._result_status is not None else False

#         self._download_window = None
#         self._status_var = None
#         self._progress_bar = None
#         self._download_thread = None

#         return final_result
    