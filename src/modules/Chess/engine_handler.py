# File: Modules/Chess/engine_handler.py
import chess
import chess.engine
import requests
import gzip
import shutil
import os
import platform
import zipfile
import tarfile
import stat # для chmod
import queue # Для межпроцессного взаимодействия
import time

from core.task_supervisor import task_supervisor

from .board_logic import PureBoardLogic # Используем относительный импорт

LC0_VERSION = "v0.31.2" 
LC0_CPU_BACKEND = "cpu-dnnl"
LC0_FALLBACK_URL_WINDOWS = f"https://github.com/LeelaChessZero/lc0/releases/download/{LC0_VERSION}/lc0-{LC0_VERSION}-windows-{LC0_CPU_BACKEND}.zip"
LC0_FALLBACK_URL_LINUX = f"https://github.com/LeelaChessZero/lc0/releases/download/{LC0_VERSION}/lc0-{LC0_VERSION}-linux-x86_64-{LC0_CPU_BACKEND}.tar.gz"
LC0_FALLBACK_URL_MACOS = f"https://github.com/LeelaChessZero/lc0/releases/download/{LC0_VERSION}/lc0-{LC0_VERSION}-macos-x86_64-{LC0_CPU_BACKEND}.tar.gz"
LC0_DIR_BASE = "lc0_engine_files" 
LC0_EXE_NAME_WINDOWS = "lc0.exe"
LC0_EXE_NAME_LINUX_MACOS = "lc0"
ENGINE_THINK_TIME_DEFAULT = 0.01 
MAIA_ELO = 1500 
LC0_EXECUTABLE_PATH_GLOBAL = None

def ensure_lc0_dir():
    os.makedirs(LC0_DIR_BASE, exist_ok=True)

def download_file(url, dest_path, desc=""):
    print(f"CONSOLE (engine_handler download_file): Скачивание {desc} ({url})...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, stream=True, timeout=60, headers=headers, allow_redirects=True)
        response.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
        print(f"CONSOLE (engine_handler download_file): {desc} УСПЕШНО СКАЧАН: {dest_path}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"CONSOLE (engine_handler download_file): ОШИБКА скачивания {desc}: {e}", exc_info=True)
        return False

def extract_archive(archive_path, dest_dir, executable_name_in_archive):
    print(f"CONSOLE (engine_handler extract_archive): Распаковка {archive_path} в {dest_dir}...")
    main_exe_path = None
    extracted_something = False
    try:
        if archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                base_archive_dir = ""
                files_to_extract = []
                for member_info in zip_ref.infolist():
                    if member_info.filename.endswith(executable_name_in_archive):
                        if os.path.dirname(member_info.filename): base_archive_dir = os.path.dirname(member_info.filename) + "/"
                        break
                for member_info in zip_ref.infolist():
                    if member_info.is_dir(): continue
                    if member_info.filename.startswith(base_archive_dir):
                        target_filename = member_info.filename[len(base_archive_dir):]
                        if not target_filename: continue
                        files_to_extract.append((member_info, target_filename))
                if not files_to_extract: print(f"CONSOLE (engine_handler extract_archive): Не найдено файлов для извлечения (включая {executable_name_in_archive}) в {archive_path}"); return None
                for member_info, target_filename in files_to_extract:
                    target_path = os.path.join(dest_dir, target_filename)
                    if os.path.dirname(target_filename): os.makedirs(os.path.join(dest_dir, os.path.dirname(target_filename)), exist_ok=True)
                    with zip_ref.open(member_info) as source, open(target_path, "wb") as target: shutil.copyfileobj(source, target)
                    extracted_something = True
                    if os.path.basename(target_filename) == executable_name_in_archive: main_exe_path = target_path
        elif archive_path.endswith(".tar.gz"):
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                base_archive_dir = ""
                members_to_extract_info = []
                temp_members = tar_ref.getmembers()
                for member_info in temp_members:
                    if member_info.name.endswith(executable_name_in_archive) and member_info.isfile():
                        if os.path.dirname(member_info.name): base_archive_dir = os.path.dirname(member_info.name) + "/"
                        break
                for member_info in temp_members:
                    if not member_info.isfile(): continue
                    if member_info.name.startswith(base_archive_dir):
                        target_filename = member_info.name[len(base_archive_dir):]
                        if not target_filename: continue
                        members_to_extract_info.append((member_info, target_filename))
                if not members_to_extract_info: print(f"CONSOLE (engine_handler extract_archive): Не найдено файлов для извлечения (включая {executable_name_in_archive}) в {archive_path}"); return None
                for member_info, target_filename in members_to_extract_info:
                    target_path = os.path.join(dest_dir, target_filename)
                    if os.path.dirname(target_filename): os.makedirs(os.path.join(dest_dir, os.path.dirname(target_filename)), exist_ok=True)
                    try:
                        with tar_ref.extractfile(member_info) as source, open(target_path, "wb") as target: shutil.copyfileobj(source, target)
                        extracted_something = True
                        if os.path.basename(target_filename) == executable_name_in_archive: main_exe_path = target_path
                    except Exception as e_extract_file: print(f"CONSOLE (engine_handler extract_archive): Ошибка при извлечении файла {member_info.name}: {e_extract_file}", exc_info=True)
        else: print(f"CONSOLE (engine_handler extract_archive): Неподдерживаемый формат архива: {archive_path}"); return None

        if main_exe_path and os.path.exists(main_exe_path): print(f"CONSOLE (engine_handler extract_archive): Архив УСПЕШНО РАСПАКОВАН, Lc0 основной файл: {main_exe_path}"); return main_exe_path
        elif extracted_something:
            potential_main_exe = os.path.join(dest_dir, executable_name_in_archive)
            if os.path.exists(potential_main_exe): print(f"CONSOLE (engine_handler extract_archive): Найден {executable_name_in_archive} в {dest_dir} после распаковки (не через main_exe_path)."); return potential_main_exe
            print(f"CONSOLE (engine_handler extract_archive): Извлечены некоторые файлы, но '{executable_name_in_archive}' не идентифицирован как main_exe_path. Проверьте {dest_dir}"); return None
        else: print(f"CONSOLE (engine_handler extract_archive): ОШИБКА: Не удалось найти '{executable_name_in_archive}' или другие файлы в архиве '{archive_path}'."); return None
    except Exception as e: print(f"CONSOLE (engine_handler extract_archive): КРИТИЧЕСКАЯ ОШИБКА распаковки {archive_path}: {e}", exc_info=True); return None
    finally:
        if os.path.exists(archive_path):
            try: os.remove(archive_path)
            except Exception as e_del: print(f"CONSOLE (engine_handler extract_archive): Не удалось удалить временный архив {archive_path}: {e_del}")

def setup_lc0():
    global LC0_EXECUTABLE_PATH_GLOBAL
    print("CONSOLE (engine_handler setup_lc0): Начало настройки Lc0.")
    ensure_lc0_dir() 
    system = platform.system()
    lc0_exe_name = LC0_EXE_NAME_WINDOWS if system == "Windows" else LC0_EXE_NAME_LINUX_MACOS
    potential_lc0_path = os.path.join(LC0_DIR_BASE, lc0_exe_name)
    print(f"CONSOLE (engine_handler setup_lc0): Потенциальный путь к Lc0: {potential_lc0_path}")

    if os.path.exists(potential_lc0_path):
        print(f"CONSOLE (engine_handler setup_lc0): Lc0 файл НАЙДЕН по пути {potential_lc0_path}.")
        if system == "Windows" or os.access(potential_lc0_path, os.X_OK): # На Windows os.X_OK не всегда надежен для исполняемости, но достаточен для проверки существования и базового доступа
            LC0_EXECUTABLE_PATH_GLOBAL = potential_lc0_path
            print(f"CONSOLE (engine_handler setup_lc0): Lc0 ГОТОВ К ИСПОЛЬЗОВАНИЮ: {LC0_EXECUTABLE_PATH_GLOBAL}")
            return True
        else: # Для Linux/MacOS, если X_OK ложно
            print(f"CONSOLE (engine_handler setup_lc0): Lc0 файл НАЙДЕН, но НЕ ИСПОЛНЯЕМЫЙ (os.X_OK=False) на {system}. Попытка chmod...")
            try:
                st = os.stat(potential_lc0_path)
                os.chmod(potential_lc0_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                if os.access(potential_lc0_path, os.X_OK):
                    LC0_EXECUTABLE_PATH_GLOBAL = potential_lc0_path
                    print(f"CONSOLE (engine_handler setup_lc0): Chmod УСПЕШЕН. Lc0 ГОТОВ К ИСПОЛЬЗОВАНИЮ: {LC0_EXECUTABLE_PATH_GLOBAL}")
                    return True
                else:
                    print(f"CONSOLE (engine_handler setup_lc0): ОШИБКА: Chmod НЕ ПОМОГ. Lc0 НЕ ИСПОЛНЯЕМЫЙ.")
                    return False
            except Exception as e_chmod_existing:
                print(f"CONSOLE (engine_handler setup_lc0): ОШИБКА chmod для существующего Lc0: {e_chmod_existing}", exc_info=True)
                return False
    else:
        print(f"CONSOLE (engine_handler setup_lc0): Lc0 файл НЕ НАЙДЕН в '{LC0_DIR_BASE}'. Попытка скачивания...")
        lc0_url = None
        if system == "Windows": lc0_url = LC0_FALLBACK_URL_WINDOWS
        elif system == "Linux": lc0_url = LC0_FALLBACK_URL_LINUX
        elif system == "Darwin": lc0_url = LC0_FALLBACK_URL_MACOS

        if lc0_url:
            archive_filename = os.path.join(LC0_DIR_BASE, os.path.basename(lc0_url))
            if download_file(lc0_url, archive_filename, "Lc0 архив"):
                extracted_path = extract_archive(archive_filename, LC0_DIR_BASE, lc0_exe_name)
                if extracted_path:
                    LC0_EXECUTABLE_PATH_GLOBAL = extracted_path
                    print(f"CONSOLE (engine_handler setup_lc0): Lc0 извлечен в: {LC0_EXECUTABLE_PATH_GLOBAL}")
                    if system != "Windows":
                        if not os.path.exists(LC0_EXECUTABLE_PATH_GLOBAL):
                             print(f"CONSOLE (engine_handler setup_lc0): КРИТИЧЕСКАЯ ОШИБКА: Lc0 извлечен, но путь {LC0_EXECUTABLE_PATH_GLOBAL} не существует!")
                             return False
                        print(f"CONSOLE (engine_handler setup_lc0): Установка прав на исполнение для {LC0_EXECUTABLE_PATH_GLOBAL} на {system}...")
                        try:
                            st = os.stat(LC0_EXECUTABLE_PATH_GLOBAL)
                            os.chmod(LC0_EXECUTABLE_PATH_GLOBAL, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
                            if os.access(LC0_EXECUTABLE_PATH_GLOBAL, os.X_OK):
                                 print(f"CONSOLE (engine_handler setup_lc0): Права на исполнение УСПЕШНО УСТАНОВЛЕНЫ для {LC0_EXECUTABLE_PATH_GLOBAL}")
                            else: # Эта ветка не должна достигаться, если chmod успешен, но для полноты
                                 print(f"CONSOLE (engine_handler setup_lc0): ВНИМАНИЕ: Права на исполнение НЕ УДАЛОСЬ УСТАНОВИТЬ (os.X_OK=False) для {LC0_EXECUTABLE_PATH_GLOBAL} после chmod.")
                                 # Тем не менее, возвращаем True, т.к. файл извлечен. Проблемы с правами могут быть специфичны для окружения.
                        except Exception as e_chmod:
                            print(f"CONSOLE (engine_handler setup_lc0): ОШИБКА: Не удалось установить права на исполнение для Lc0: {e_chmod}", exc_info=True)
                            # Возвращаем True, так как файл извлечен, но с предупреждением о правах.
                    print(f"CONSOLE (engine_handler setup_lc0): Lc0 скачан и настроен: {LC0_EXECUTABLE_PATH_GLOBAL}")
                    return True
                else:
                    print(f"CONSOLE (engine_handler setup_lc0): ОШИБКА: Не удалось распаковать Lc0 из скачанного архива '{archive_filename}'.")
                    return False
            else: # download_file вернул False
                 print(f"CONSOLE (engine_handler setup_lc0): ОШИБКА: Не удалось скачать Lc0 архив с {lc0_url}.")
                 return False
        else:
            print(f"CONSOLE (engine_handler setup_lc0): ОШИБКА: Автоматическое скачивание Lc0 для {system} не настроено или URL не определен.")
            return False
    print(f"CONSOLE (engine_handler setup_lc0): ЗАВЕРШЕНИЕ setup_lc0 с НЕУДАЧЕЙ (непредвиденный путь кода).") # Должно быть недостижимо
    return False

def setup_maia_weights(maia_elo: int):
    print(f"CONSOLE (engine_handler setup_maia_weights): Начало настройки весов Maia ELO {maia_elo}.")
    ensure_lc0_dir()
    maia_weights_url = f"https://github.com/CSSLab/maia-chess/releases/download/v1.0/maia-{maia_elo}.pb.gz"
    maia_weights_gz_filename = os.path.join(LC0_DIR_BASE, f"maia-{maia_elo}.pb.gz")
    maia_weights_pb_filename = os.path.join(LC0_DIR_BASE, f"maia-{maia_elo}.pb")
    print(f"CONSOLE (engine_handler setup_maia_weights): Путь к файлу весов .pb: {maia_weights_pb_filename}")

    if os.path.exists(maia_weights_pb_filename):
        print(f"CONSOLE (engine_handler setup_maia_weights): Веса Maia ELO {maia_elo} УЖЕ СУЩЕСТВУЮТ: {maia_weights_pb_filename}")
        return maia_weights_pb_filename

    print(f"CONSOLE (engine_handler setup_maia_weights): Веса Maia ELO {maia_elo} не найдены. Попытка скачивания с {maia_weights_url}...")
    if download_file(maia_weights_url, maia_weights_gz_filename, f"Maia ELO {maia_elo} weights (gz)"):
        print(f"CONSOLE (engine_handler setup_maia_weights): Распаковка {maia_weights_gz_filename} в {maia_weights_pb_filename}...")
        try:
            with gzip.open(maia_weights_gz_filename, 'rb') as f_in:
                with open(maia_weights_pb_filename, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            print(f"CONSOLE (engine_handler setup_maia_weights): Веса Maia ELO {maia_elo} УСПЕШНО РАСПАКОВАНЫ: {maia_weights_pb_filename}")
            if os.path.exists(maia_weights_gz_filename): 
                try: os.remove(maia_weights_gz_filename)
                except Exception as e_del_gz: print(f"CONSOLE (engine_handler setup_maia_weights): Не удалось удалить временный .gz файл: {e_del_gz}")
            return maia_weights_pb_filename
        except Exception as e:
            print(f"CONSOLE (engine_handler setup_maia_weights): ОШИБКА распаковки весов Maia ELO {maia_elo} из {maia_weights_gz_filename}: {e}", exc_info=True)
            if os.path.exists(maia_weights_gz_filename): 
                try: os.remove(maia_weights_gz_filename)
                except Exception as e_del_gz_fail: print(f"CONSOLE (engine_handler setup_maia_weights): Не удалось удалить .gz файл после ошибки распаковки: {e_del_gz_fail}")
            if os.path.exists(maia_weights_pb_filename): 
                try: os.remove(maia_weights_pb_filename)
                except Exception as e_del_pb_fail: print(f"CONSOLE (engine_handler setup_maia_weights): Не удалось удалить частично созданный .pb файл: {e_del_pb_fail}")
            return None
    else: # download_file вернул False
        print(f"CONSOLE (engine_handler setup_maia_weights): ОШИБКА скачивания весов Maia ELO {maia_elo} с URL: {maia_weights_url}")
        return None

class ChessGameController:
    def __init__(self, initial_elo: int, player_is_white_gui: bool,
                 state_q: queue.Queue, status_update_cb_gui, board_update_cb_gui, game_over_cb_gui,
                 is_auto: bool = False, is_cheat: bool = False):
        self.board_logic = PureBoardLogic()
        self.engine = None
        self.current_maia_elo = initial_elo
        self.current_maia_weights_path = None
        self.player_is_white_in_gui = player_is_white_gui
        self.engine_is_thinking = False
        self.is_engine_enabled_for_moves = True
        self.state_queue = state_q
        self.status_update_cb_gui = status_update_cb_gui
        self.board_update_cb_gui = board_update_cb_gui
        self.game_over_cb_gui = game_over_cb_gui
        self.think_time = ENGINE_THINK_TIME_DEFAULT
        self.is_auto = is_auto    # True = Maia ходит сама, False = LLM выбирает ходы
        self.is_cheat = is_cheat  # True = разрешены чит-команды
        self._send_status_to_gui_if_possible(f"Контроллер инициализирован. ELO: {self.current_maia_elo}")

    def _send_status_to_gui_if_possible(self, message: str):
        if self.status_update_cb_gui:
            self.status_update_cb_gui(message)

    def initialize_dependencies_and_engine(self):
        self._send_status_to_gui_if_possible("Настройка зависимостей Lc0...")
        print("CONSOLE (ChessGameController initialize_dependencies_and_engine): Начало настройки Lc0.")
        if not LC0_EXECUTABLE_PATH_GLOBAL: 
            if not setup_lc0():
                msg = "КРИТИЧЕСКАЯ ОШИБКА: Не удалось настроить Lc0. Проверьте консоль."
                self._send_status_to_gui_if_possible(msg)
                print(f"CONSOLE (ChessGameController initialize_dependencies_and_engine): ОШИБКА - setup_lc0() вернул False.")
                self._send_state_to_main_process(error="Lc0 setup failed", critical_process_failure=True)
                return False
        print("CONSOLE (ChessGameController initialize_dependencies_and_engine): Lc0 настроен/найден.")
        
        self._send_status_to_gui_if_possible(f"Настройка весов Maia ELO {self.current_maia_elo}...")
        print(f"CONSOLE (ChessGameController initialize_dependencies_and_engine): Начало настройки весов Maia ELO {self.current_maia_elo}.")
        self.current_maia_weights_path = setup_maia_weights(self.current_maia_elo)
        if not self.current_maia_weights_path:
            msg = f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось настроить веса Maia ELO {self.current_maia_elo}."
            self._send_status_to_gui_if_possible(msg)
            print(f"CONSOLE (ChessGameController initialize_dependencies_and_engine): ОШИБКА - setup_maia_weights({self.current_maia_elo}) вернул None.")
            self._send_state_to_main_process(error=f"Maia {self.current_maia_elo} weights setup failed", critical_process_failure=True)
            return False
        print(f"CONSOLE (ChessGameController initialize_dependencies_and_engine): Веса Maia ELO {self.current_maia_elo} настроены: {self.current_maia_weights_path}")

        print("CONSOLE (ChessGameController initialize_dependencies_and_engine): Запуск внутреннего процесса движка...")
        return self._start_engine_process_internal()

    def _start_engine_process_internal(self):
        print("CONSOLE (engine_handler _start_engine_process_internal): Начало запуска процесса движка.")
        if self.engine: self.shutdown_engine_process()

        if not LC0_EXECUTABLE_PATH_GLOBAL or not os.path.exists(LC0_EXECUTABLE_PATH_GLOBAL):
            msg = "КРИТИЧЕСКАЯ ОШИБКА: Lc0 не найден для запуска процесса."
            self._send_status_to_gui_if_possible(msg)
            print(f"CONSOLE (engine_handler _start_engine_process_internal): ОШИБКА - Lc0 путь не существует или не установлен: {LC0_EXECUTABLE_PATH_GLOBAL}")
            self._send_state_to_main_process(error="Lc0 executable not found for engine start", critical_process_failure=True)
            return False
        if not self.current_maia_weights_path or not os.path.exists(self.current_maia_weights_path):
            msg = f"КРИТИЧЕСКАЯ ОШИБКА: Веса Maia ELO {self.current_maia_elo} не найдены для запуска."
            self._send_status_to_gui_if_possible(msg)
            print(f"CONSOLE (engine_handler _start_engine_process_internal): ОШИБКА - Путь к весам Maia не существует: {self.current_maia_weights_path}")
            self._send_state_to_main_process(error=f"Maia {self.current_maia_elo} weights not found for engine start", critical_process_failure=True)
            return False
        try:
            self._send_status_to_gui_if_possible(f"Запуск движка Maia ELO {self.current_maia_elo} с Lc0: {LC0_EXECUTABLE_PATH_GLOBAL} и весами: {self.current_maia_weights_path}")
            print(f"CONSOLE (engine_handler _start_engine_process_internal): Команда запуска Lc0: '{LC0_EXECUTABLE_PATH_GLOBAL}'")
            print(f"CONSOLE (engine_handler _start_engine_process_internal): Абсолютный путь к файлу весов для Lc0: '{os.path.abspath(self.current_maia_weights_path)}'")
            
            if platform.system() != "Windows" and not os.access(LC0_EXECUTABLE_PATH_GLOBAL, os.X_OK):
                print(f"CONSOLE (engine_handler _start_engine_process_internal): ВНИМАНИЕ! Lc0 файл '{LC0_EXECUTABLE_PATH_GLOBAL}' не исполняемый (os.X_OK=False) на {platform.system()} ПЕРЕД popen_uci.")

            self.engine = chess.engine.SimpleEngine.popen_uci(LC0_EXECUTABLE_PATH_GLOBAL)
            print(f"CONSOLE (engine_handler _start_engine_process_internal): chess.engine.SimpleEngine.popen_uci УСПЕШНО выполнен.")
            
            time.sleep(0.5) 
            
            self.engine.configure({"WeightsFile": os.path.abspath(self.current_maia_weights_path)})
            print(f"CONSOLE (engine_handler _start_engine_process_internal): engine.configure УСПЕШНО выполнен.")
            
            try:
                self.engine.ping()
                print(f"CONSOLE (engine_handler _start_engine_process_internal): Движок успешно ответил на ping.")
            except chess.engine.EngineTerminatedError:
                print(f"CONSOLE (engine_handler _start_engine_process_internal): ОШИБКА: Движок завершился сразу после configure или во время ping.")
                self.engine = None 
                raise 
            except Exception as e_ping:
                 print(f"CONSOLE (engine_handler _start_engine_process_internal): ОШИБКА: Движок не ответил на ping: {e_ping}", exc_info=True)

            self._send_status_to_gui_if_possible(f"Движок Maia ELO {self.current_maia_elo} запущен.")
            print(f"CONSOLE (engine_handler _start_engine_process_internal): Движок Maia ELO {self.current_maia_elo} УСПЕШНО запущен и настроен.")
            return True
        except Exception as e:
            msg = f"КРИТИЧЕСКАЯ ОШИБКА запуска движка: {e}. Проверьте консоль."
            self._send_status_to_gui_if_possible(msg)
            print(f"CONSOLE (engine_handler _start_engine_process_internal): ОШИБКА запуска/конфигурации движка Lc0 ('{LC0_EXECUTABLE_PATH_GLOBAL}'): {e}", exc_info=True)
            if self.engine: 
                try: self.engine.quit()
                except: pass
            self.engine = None
            self._send_state_to_main_process(error=f"Engine start/configure failed: {str(e)}", critical_process_failure=True)
            return False

    def new_game(self, fen=None, player_is_white_gui_override=None):
        print(f"CONSOLE (ChessGameController new_game): Начало новой игры. FEN: {fen}, Override white: {player_is_white_gui_override}")
        self.board_logic.reset_board(fen)
        if player_is_white_gui_override is not None:
            self.player_is_white_in_gui = player_is_white_gui_override
        
        self.engine_is_thinking = False
        
        current_turn_color = "Белые" if self.board_logic.get_turn() == chess.WHITE else "Черные"
        player_color_str = "белыми" if self.player_is_white_in_gui else "черными"
        
        self._send_status_to_gui_if_possible(f"Новая игра. Игрок в GUI {player_color_str}. Ход {current_turn_color}.")
        if self.board_update_cb_gui: self.board_update_cb_gui()
        
        self._send_state_to_main_process(last_move_san="Новая игра")
        
        if self.is_auto and self._is_controlled_side_turn():
            self._make_engine_move_sync()
        print(f"CONSOLE (ChessGameController new_game): Состояние отправлено. auto={self.is_auto}, cheat={self.is_cheat}.")


    def _is_controlled_side_turn(self):
        board_turn_is_white = self.board_logic.get_turn() == chess.WHITE
        return board_turn_is_white != self.player_is_white_in_gui

    def _make_engine_move_sync(self):
        """Авто-ход движка (для auto/cheat режимов). Синхронно, без потоков."""
        if self.engine_is_thinking or not self.engine:
            return
        if not self._is_controlled_side_turn():
            return
        self.engine_is_thinking = True
        self._send_status_to_gui_if_possible(f"Maia (ELO {self.current_maia_elo}) думает...")
        try:
            result = self.engine.play(self.board_logic.board, chess.engine.Limit(time=self.think_time))
            if result.move:
                uci = result.move.uci()
                san = self.board_logic.board.san(result.move)
                success, msg, _ = self.board_logic.make_move(uci)
                if success:
                    self._send_status_to_gui_if_possible(f"Maia: {san}")
                    if self.board_update_cb_gui: self.board_update_cb_gui()
                    if not self._check_and_handle_game_over(moved_by="Maia", san_move=san):
                        self._send_state_to_main_process()
                else:
                    self._send_status_to_gui_if_possible(f"Maia: ошибка хода {uci}")
            else:
                self._send_status_to_gui_if_possible("Maia не смогла сделать ход.")
        except Exception as e:
            self._send_status_to_gui_if_possible(f"Ошибка Maia: {e}")
        finally:
            self.engine_is_thinking = False

    def handle_player_move_from_gui(self, uci_move_str):
        print(f"CONSOLE (ChessGameController handle_player_move_from_gui): UCI: '{uci_move_str}'")
        if self.engine_is_thinking:
            self._send_status_to_gui_if_possible("Движок думает, подождите.")
            return False
        
        if self._is_controlled_side_turn(): 
             self._send_status_to_gui_if_possible("Сейчас не ваш ход (ожидается ход LLM/Maia).")
             return False

        success, message, san_move = self.board_logic.make_move(uci_move_str)
        if success:
            self._send_status_to_gui_if_possible(f"Игрок GUI: {san_move}")
            if self.board_update_cb_gui: self.board_update_cb_gui()
            
            if self._check_and_handle_game_over(moved_by="Игрок GUI", san_move=san_move):
                return True

            self._send_state_to_main_process()

            if self.is_auto and not self.board_logic.is_game_over()[0]:
                self._make_engine_move_sync()
            print(f"CONSOLE (ChessGameController handle_player_move_from_gui): auto={self.is_auto}")
            return True
        else:
            self._send_status_to_gui_if_possible(f"Игрок GUI: {message} (ход {uci_move_str})")
            return False

    def force_llm_or_engine_move(self, uci_move_str, is_llm_decision=True):
        source_str = "LLM" if is_llm_decision else "Движок (команда)"
        print(f"CONSOLE (ChessGameController force_llm_or_engine_move): UCI: '{uci_move_str}', Источник: '{source_str}'")

        if self.engine_is_thinking and is_llm_decision: 
            self._send_status_to_gui_if_possible(f"{source_str}: Движок был занят, ход {uci_move_str} может быть неактуален. Применяем.")
        
        # Если LLM командует ход, мы его делаем, даже если формально не ее очередь.
        # Это позволяет LLM "жульничать" или исправлять ошибки, если это предусмотрено ее логикой.
        if not self._is_controlled_side_turn() and is_llm_decision:
            self._send_status_to_gui_if_possible(f"Предупреждение: {source_str} пытается сделать ход {uci_move_str} не в свою очередь. Применяем принудительно.")
        elif not self._is_controlled_side_turn() and not is_llm_decision: # Движок (не LLM) пытается ходить не в свою очередь - это ошибка
            msg = f"Критическая ошибка: {source_str} пытается сделать ход {uci_move_str} не в свою очередь."
            self._send_status_to_gui_if_possible(msg)
            self._send_state_to_main_process(error=msg, error_move=uci_move_str)
            return False

        
        self._send_status_to_gui_if_possible(f"Ход от {source_str}: {uci_move_str}...")
        success, message, san_move = self.board_logic.make_move(uci_move_str)
        if success:
            self._send_status_to_gui_if_possible(f"{source_str}: {san_move}")
            if self.board_update_cb_gui: self.board_update_cb_gui()
            if self._check_and_handle_game_over(moved_by=source_str, san_move=san_move):
                return True
            self._send_state_to_main_process() # Отправляем состояние после хода ИИ
            # Не делаем автоматический ход игрока GUI, ждем его реакции
            return True
        else:
            self._send_status_to_gui_if_possible(f"{source_str}: {message} (ход {uci_move_str})")
            self._send_state_to_main_process(error_move=uci_move_str, error_message=message)
            return False

    def request_engine_move_auto(self): # Вызывается, когда LLM присылает <RequestBestChessMove!>
        print("CONSOLE (ChessGameController request_engine_move_auto): Запрос хода у движка (по команде LLM).")
        if not self.engine:
            print("CONSOLE (ChessGameController request_engine_move_auto): Отмена - движок не инициализирован.")
            self._send_status_to_gui_if_possible("Ошибка: движок Maia не инициализирован для хода.")
            self._send_state_to_main_process(error="Maia engine not initialized for best move request.")
            return
        if self.engine_is_thinking:
            print("CONSOLE (ChessGameController request_engine_move_auto): Отмена - движок уже думает.")
            self._send_status_to_gui_if_possible("Движок Maia уже думает.")
            # Состояние не меняем, LLM получит его позже или уже имеет.
            return

        if not self._is_controlled_side_turn():
            msg = "LLM запросил ход Maia, но сейчас не очередь ИИ."
            print(f"CONSOLE (ChessGameController request_engine_move_auto): Отмена - {msg}")
            self._send_status_to_gui_if_possible(msg)
            self._send_state_to_main_process(error=msg)
            return

        self.engine_is_thinking = True
        self._send_status_to_gui_if_possible(f"Maia (ELO {self.current_maia_elo}) думает (по запросу LLM)...")
        current_board_fen_for_engine = self.board_logic.get_fen()

        def _think():
            engine_san_move = "N/A"
            engine_uci_move = None
            error_during_think = None
            try:
                print(f"CONSOLE (ChessGameController _think): Поток _think запущен. FEN: {current_board_fen_for_engine}")
                thread_board = chess.Board(current_board_fen_for_engine) 
                if not self.engine: 
                    print("CONSOLE (ChessGameController _think): ОШИБКА - self.engine is None в потоке _think.")
                    error_during_think = "Engine became None in thinking thread"
                    return # Выход из _think

                result = self.engine.play(thread_board, chess.engine.Limit(time=self.think_time))
                if result.move:
                    engine_uci_move = result.move.uci()
                    engine_san_move = thread_board.san(result.move)
                    print(f"CONSOLE (ChessGameController _think): Движок предложил ход: {engine_san_move} (UCI: {engine_uci_move})")
                    
                    # Этот ход будет применен к основной доске из основного потока GUI (или контроллера)
                    # после того как _think завершится, чтобы избежать проблем с многопоточностью tkinter
                    # Вместо этого, мы просто сигнализируем, что ход найден.
                    # Применение хода произойдет в finally блоке, если не было ошибок
                else:
                    self._send_status_to_gui_if_possible("Maia не смогла сделать ход (result.move is None).")
                    print("CONSOLE (ChessGameController _think): Maia не смогла сделать ход (result.move is None).")
                    error_during_think = "Maia could not make a move (result.move is None)"

            except chess.engine.EngineTerminatedError as ete:
                self._send_status_to_gui_if_possible("Критическая ошибка: Движок неожиданно завершил работу.")
                print(f"CONSOLE (ChessGameController _think): ОШИБКА - Движок Lc0 завершил работу: {ete}", exc_info=True)
                self.engine = None 
                error_during_think = f"Engine terminated during thinking: {str(ete)}"
            except Exception as e:
                self._send_status_to_gui_if_possible(f"Ошибка во время хода движка: {e}. Проверьте консоль.")
                print(f"CONSOLE (ChessGameController _think): ОШИБКА во время хода движка: {e}", exc_info=True)
                error_during_think = f"Engine thinking error: {str(e)}"
            finally:
                self.engine_is_thinking = False # Сбрасываем флаг в любом случае
                print(f"CONSOLE (ChessGameController _think): Поток _think завершен. SAN движка: {engine_san_move}, UCI: {engine_uci_move}, Ошибка: {error_during_think}")

                if error_during_think:
                    self._send_status_to_gui_if_possible(f"Maia: Ошибка при обдумывании хода: {error_during_think}")
                    self._send_state_to_main_process(error=error_during_think)
                    if self.board_update_cb_gui: self.board_update_cb_gui() # Обновить доску на случай, если статус изменился
                elif engine_uci_move:
                    # Применяем ход здесь, так как _think завершен
                    success_apply, msg_apply, _ = self.board_logic.make_move(engine_uci_move)
                    if success_apply:
                         self._send_status_to_gui_if_possible(f"Maia: {engine_san_move}")
                         if self.board_update_cb_gui: self.board_update_cb_gui()
                         if not self._check_and_handle_game_over(moved_by="Maia", san_move=engine_san_move):
                             self._send_state_to_main_process() # Отправляем состояние после успешного хода Maia
                    else:
                         error_msg_apply = f"Maia: ОШИБКА применения собственного хода {engine_uci_move} ({msg_apply})"
                         self._send_status_to_gui_if_possible(error_msg_apply)
                         print(f"CONSOLE (ChessGameController _think finally): КРИТИЧЕСКАЯ ОШИБКА: {error_msg_apply}")
                         self._send_state_to_main_process(error=error_msg_apply, error_move=engine_uci_move)
                         if self.board_update_cb_gui: self.board_update_cb_gui()
                else: # No error, but no move either (should have been caught by error_during_think)
                    no_move_msg = "Maia не вернула ход после обдумывания."
                    self._send_status_to_gui_if_possible(no_move_msg)
                    self._send_state_to_main_process(error=no_move_msg)
                    if self.board_update_cb_gui: self.board_update_cb_gui()


        task_supervisor().start_thread(
            self,
            "chess-engine-think",
            _think,
            replace=True,
        )

    def _check_and_handle_game_over(self, moved_by="", san_move="", error_during_move=None):
        is_over, outcome_message = self.board_logic.is_game_over()
        final_outcome_message = outcome_message
        
        # Эта логика немного изменилась, error_during_move теперь обрабатывается в вызывающих функциях
        # или в _send_state_to_main_process
        if error_during_move and not is_over : 
            final_outcome_message = f"{outcome_message} (Ошибка во время хода {moved_by}: {error_during_move})"
            print(f"CONSOLE (ChessGameController _check_and_handle_game_over): Ошибка во время хода '{moved_by}': {error_during_move}. Формально игра не окончена, но сообщаем об ошибке.")
            # Состояние с ошибкой уже должно быть отправлено вызывающей функцией или будет отправлено
            # не считаем это концом игры здесь, если is_over == False
            # return False # Игра формально не окончена

        if is_over:
            print(f"CONSOLE (ChessGameController _check_and_handle_game_over): Игра окончена: {final_outcome_message}")
            if self.game_over_cb_gui: self.game_over_cb_gui(final_outcome_message)
            else: self._send_status_to_gui_if_possible(final_outcome_message)
            self._send_state_to_main_process() 
        return is_over
            
    def _send_state_to_main_process(self, error=None, error_move=None, error_message=None, game_resigned=False, game_stopped_by_llm=False, critical_process_failure=False, last_move_san=None):
        if not self.state_queue:
            print("CONSOLE (ChessGameController _send_state_to_main_process): ОШИБКА - state_queue не инициализирована.")
            return

        game_over, outcome_msg_board = self.board_logic.is_game_over()
        
        current_last_move_san = last_move_san
        if current_last_move_san is None and self.board_logic.board.move_stack:
            last_move_obj = self.board_logic.board.peek()
            # Нужна копия доски ДО последнего хода, чтобы получить SAN корректно
            temp_board_for_san = self.board_logic.board.copy()
            temp_board_for_san.pop() # Убираем последний ход, чтобы получить его SAN
            try: 
                current_last_move_san = temp_board_for_san.san(last_move_obj)
            except Exception: # Если SAN не получается (например, ход был нелегальным или доска в странном состоянии)
                current_last_move_san = last_move_obj.uci()


        state_data = {
            "fen": self.board_logic.get_fen(),
            "board_ascii": self.board_logic.ascii_board(),
            "turn": "white" if self.board_logic.get_turn() == chess.WHITE else "black",
            "legal_moves_uci": self.board_logic.get_legal_moves_uci() if not (game_over or game_resigned or game_stopped_by_llm or critical_process_failure) else [],
            "legal_moves_short": self.board_logic.get_legal_moves_uci_short(10) if not (game_over or game_resigned or game_stopped_by_llm or critical_process_failure) else [],
            "is_game_over": game_over or game_resigned or game_stopped_by_llm or critical_process_failure,
            "outcome_message": outcome_msg_board,
            "player_is_white_in_gui": self.player_is_white_in_gui,
            "current_elo": self.current_maia_elo,
            "is_auto": self.is_auto,
            "is_cheat": self.is_cheat,
            "last_move_san": current_last_move_san if current_last_move_san else "N/A",
            "timestamp": time.time()
        }
        if error: state_data["error"] = str(error)
        if error_move: state_data["error_move"] = error_move
        if error_message: state_data["error_message_for_move"] = error_message
        if game_resigned: state_data["game_resigned_by_llm"] = True; state_data["outcome_message"] = "LLM (Maia) сдался."
        if game_stopped_by_llm: state_data["game_stopped_by_llm"] = True; state_data["outcome_message"] = "Игра остановлена LLM."
        if critical_process_failure: state_data["critical_process_failure"] = True; state_data["outcome_message"] = f"Критический сбой процесса GUI: {error if error else 'Неизвестная ошибка'}"


        try:
            self.state_queue.put(state_data)
            print(f"CONSOLE (ChessGameController _send_state_to_main_process): Состояние отправлено. FEN: {state_data['fen'][:20]}..., Turn: {state_data['turn']}, GameOver: {state_data['is_game_over']}, Outcome: {state_data['outcome_message']}, Error: {state_data.get('error')}, LastSAN: {state_data.get('last_move_san')}")
        except Exception as e:
            print(f"CONSOLE (ChessGameController _send_state_to_main_process): ОШИБКА отправки состояния в state_queue: {e}", exc_info=True)

    def shutdown_engine_process(self):
        print("CONSOLE (ChessGameController shutdown_engine_process): Запрос на остановку движка.")
        task_supervisor().cancel_owner(self, timeout=1.0)
        if self.engine:
            print("CONSOLE (ChessGameController shutdown_engine_process): Движок существует, вызываем quit().")
            try:
                self.engine.quit()
                print("CONSOLE (ChessGameController shutdown_engine_process): engine.quit() УСПЕШНО вызван.")
            except chess.engine.EngineTerminatedError:
                print("CONSOLE (ChessGameController shutdown_engine_process): Движок уже был завершен (EngineTerminatedError).")
            except Exception as e:
                print(f"CONSOLE (ChessGameController shutdown_engine_process): ОШИБКА при engine.quit(): {e}", exc_info=True)
            finally:
                self.engine = None
                print("CONSOLE (ChessGameController shutdown_engine_process): self.engine установлен в None.")
        else:
            print("CONSOLE (ChessGameController shutdown_engine_process): Движок уже был None, нечего останавливать.")

    def get_current_board_object_for_gui(self): return self.board_logic.get_board_for_display()
    def get_player_color_is_white_for_gui(self): return self.player_is_white_in_gui
    def get_board_logic_for_gui(self): return self.board_logic

    def process_command(self, command_data: dict):
        action = command_data.get("action")
        print(f"CONSOLE (ChessGameController process_command): Получена команда: {action}, Данные: {command_data}")

        if self.board_logic.is_game_over()[0] and action not in ["get_state", "stop", "resign", "stop_gui_process"]: # stop_gui_process добавлено из chess_board.py
            self._send_status_to_gui_if_possible(f"Игра уже окончена. Команда '{action}' не будет выполнена.")
            self._send_state_to_main_process() # Отправить актуальное состояние (что игра окончена)
            return

        if action == "engine_move": # LLM хочет, чтобы Maia сделала лучший ход
            self.is_engine_enabled_for_moves = True # Убедимся, что Maia может ходить
            self.request_engine_move_auto() # Эта функция уже проверяет _is_controlled_side_turn()
        elif action == "force_engine_move": # LLM хочет сделать конкретный ход
            move_uci = command_data.get("move")
            if move_uci:
                # self.is_engine_enabled_for_moves = False # Не обязательно, т.к. это не "автономный" ход Maia
                self.force_llm_or_engine_move(move_uci, is_llm_decision=True)
            else:
                msg = "LLM прислал команду force_engine_move без хода."
                self._send_status_to_gui_if_possible(msg)
                self._send_state_to_main_process(error=msg)
        elif action == "change_elo":
            new_elo = command_data.get("elo")
            if isinstance(new_elo, int): self.change_engine_elo(new_elo)
            else:
                msg = f"Некорректный ELO для смены: {new_elo}"
                self._send_status_to_gui_if_possible(msg)
                self._send_state_to_main_process(error=msg)
        elif action == "resign":
            msg = "Игра завершена: LLM (Maia) сдался."
            self._send_status_to_gui_if_possible(msg)
            if self.game_over_cb_gui: self.game_over_cb_gui(msg)
            # self.shutdown_engine_process() # Движок может понадобиться для анализа, если GUI не закрывается сразу
            self._send_state_to_main_process(game_resigned=True)
            # GUI должен сам решить, закрывать ли движок при выходе
        elif action == "stop": 
            msg = "Игра остановлена по команде LLM."
            self._send_status_to_gui_if_possible(msg)
            # self.shutdown_engine_process()
            self._send_state_to_main_process(game_stopped_by_llm=True)
        elif action == "get_state":
            self._send_state_to_main_process()
        elif action == "cheat_move":
            move_uci = command_data.get("move")
            if move_uci:
                success, msg, san = self.board_logic.force_move(move_uci)
                self._send_status_to_gui_if_possible(f"Чит: {msg}")
                if self.board_update_cb_gui: self.board_update_cb_gui()
                if not self._check_and_handle_game_over(moved_by="Чит", san_move=san or move_uci):
                    self._send_state_to_main_process()
            else:
                self._send_state_to_main_process(error="cheat_move без хода")
        elif action == "cheat_spawn":
            square = command_data.get("square")
            piece = command_data.get("piece")
            if square and piece:
                success, msg, _ = self.board_logic.spawn_piece(square, piece)
                self._send_status_to_gui_if_possible(f"Чит: {msg}")
                if self.board_update_cb_gui: self.board_update_cb_gui()
                self._send_state_to_main_process()
            else:
                self._send_state_to_main_process(error="cheat_spawn: нужны square и piece")
        elif action == "cheat_remove":
            square = command_data.get("square")
            if square:
                success, msg, _ = self.board_logic.remove_piece(square)
                self._send_status_to_gui_if_possible(f"Чит: {msg}")
                if self.board_update_cb_gui: self.board_update_cb_gui()
                self._send_state_to_main_process()
            else:
                self._send_state_to_main_process(error="cheat_remove: нужен square")
        elif action == "switch_auto":
            enable = command_data.get("enable", True)
            old = self.is_auto
            self.is_auto = bool(enable)
            msg = f"Авто-режим: {'ВКЛ' if self.is_auto else 'ВЫКЛ'}."
            self._send_status_to_gui_if_possible(msg)
            if self.is_auto and not old and self._is_controlled_side_turn() and not self.board_logic.is_game_over()[0]:
                self._make_engine_move_sync()
            else:
                self._send_state_to_main_process()
        elif action == "switch_cheat":
            self.is_cheat = bool(command_data.get("enable", True))
            msg = f"Чит-режим: {'ВКЛ' if self.is_cheat else 'ВЫКЛ'}."
            self._send_status_to_gui_if_possible(msg)
            self._send_state_to_main_process()
        # stop_gui_process обрабатывается в цикле run_chess_gui_process
        else:
            msg = f"Неизвестная команда от LLM: {action}"
            self._send_status_to_gui_if_possible(msg)
            self._send_state_to_main_process(error=msg)

    def change_engine_elo(self, new_elo: int):
        self._send_status_to_gui_if_possible(f"Попытка сменить ELO на {new_elo}...")
        print(f"CONSOLE (ChessGameController change_engine_elo): Смена ELO на {new_elo}. Текущий: {self.current_maia_elo}")
        if self.current_maia_elo == new_elo and self.engine:
            self._send_status_to_gui_if_possible(f"ELO уже установлен на {new_elo}.")
            self._send_state_to_main_process() 
            return

        old_elo_for_fallback = self.current_maia_elo # Сохраняем старый ELO на случай ошибки
        self.current_maia_elo = new_elo 
        
        self._send_status_to_gui_if_possible(f"Настройка весов для нового ELO {new_elo}...")
        new_weights_path = setup_maia_weights(self.current_maia_elo)
        if not new_weights_path:
            msg = f"ОШИБКА: Не удалось настроить веса для ELO {new_elo}. Возврат к ELO {old_elo_for_fallback}."
            self._send_status_to_gui_if_possible(msg)
            self.current_maia_elo = old_elo_for_fallback # Возвращаем старый ELO
            # Попытка перенастроить старые веса не нужна, т.к. движок еще не перезапускался с новым ELO
            self._send_state_to_main_process(error=msg) 
            return

        self.current_maia_weights_path = new_weights_path 
        
        self._send_status_to_gui_if_possible(f"Перезапуск движка с новым ELO {new_elo}...")
        if not self._start_engine_process_internal(): 
            msg = f"ОШИБКА: Не удалось перезапустить движок с ELO {new_elo}. Возврат к ELO {old_elo_for_fallback} (если возможно)."
            self._send_status_to_gui_if_possible(msg)
            self.current_maia_elo = old_elo_for_fallback # Пытаемся вернуть старый ELO
            self.current_maia_weights_path = setup_maia_weights(self.current_maia_elo) # Пытаемся получить старые веса
            if not self.current_maia_weights_path or not self._start_engine_process_internal():
                 critical_msg = "КРИТИЧЕСКАЯ ОШИБКА: Не удалось вернуться к предыдущему ELO после сбоя смены."
                 self._send_status_to_gui_if_possible(critical_msg)
                 self._send_state_to_main_process(error=critical_msg, critical_process_failure=True)
            else:
                 self._send_state_to_main_process(error=msg + " Восстановлен предыдущий ELO.")
            return
        else:
            self._send_status_to_gui_if_possible(f"ELO успешно изменен на {new_elo}. Движок перезапущен.")
            # После смены ELO, если это ход ИИ, LLM должна решить, что делать.
            # Поэтому просто отправляем состояние.
            self._send_state_to_main_process()
            # Не вызываем request_engine_move_auto() здесь автоматически.
            # if self.is_engine_enabled_for_moves and self._is_controlled_side_turn() and not self.board_logic.is_game_over()[0]:
            #     self.request_engine_move_auto()
            # else:
            #     self._send_state_to_main_process()